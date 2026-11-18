"""
Payment Integrity FWA detection - RULE-BASED analysis (no hidden flag column is read).

Detection rules (thresholds are explicit constants a payment-integrity analyst would tune):
  R1 Duplicate billing   : same patient + provider + procedure + date + billed amount billed 2+ times
  R2 Upcoding            : provider's high-complexity share of E&M / Psychotherapy volume >= threshold
                           (peer mean + 1.5 SD, floor 30%) with >= 15 family claims -> their high-code claims flagged
  R3 Provider outlier    : z-score of avg billed per claim OR per patient > 2.0 -> their claims billed
                           above 1.3x the procedure median flagged
  R4 Excessive units     : therapy codes (97110/97530) billed with >= 6 units (typical max 4)
  R5 Weekend billing     : provider weekend claim share >= 35% with >= 25 claims -> their weekend claims flagged

Outputs: outputs/kpi_summary.csv, outputs/insights.md,
         outputs/flagged_claims.csv, outputs/provider_risk_ranking.csv
Run: python3 analysis.py   (after generate_data.py)
"""
import numpy as np
import pandas as pd

Z_THRESHOLD, UPCODING_FLOOR, EXCESSIVE_UNITS = 2.0, 0.30, 6
WEEKEND_SHARE_MIN, WEEKEND_MIN_CLAIMS, UPCODING_MIN_FAMILY = 0.35, 25, 15
FAMILIES = {"E&M": ({"99212", "99213", "99214", "99215"}, "99215"),
            "Psych": ({"90832", "90834", "90837"}, "90837")}
UNIT_CODES = {"97110", "97530"}

claims = pd.read_csv("data/claims.csv", parse_dates=["claim_date"], dtype={"procedure_code": str})
providers = pd.read_csv("data/providers.csv")
claims["is_weekend"] = claims.claim_date.dt.dayofweek >= 5
claims["month"] = claims.claim_date.dt.to_period("M").astype(str)
proc_median = claims.groupby("procedure_code").billed_amount.median()

flags = {cid: [] for cid in claims.claim_id}

# R1 duplicates: every copy after the first is a duplicate billing
dup_key = ["patient_id", "provider_id", "procedure_code", "claim_date", "billed_amount"]
claims["_dup_rank"] = claims.groupby(dup_key).cumcount()
dup_ids = claims.loc[claims._dup_rank > 0, "claim_id"]
for cid in dup_ids:
    flags[cid].append("duplicate")

# R4 excessive units
for cid in claims.loc[claims.procedure_code.isin(UNIT_CODES) & (claims.units >= EXCESSIVE_UNITS), "claim_id"]:
    flags[cid].append("excessive_units")

# Provider-level aggregates (drive R2, R3, R5 and the risk ranking)
def family_stats(df):
    fam = df[df.procedure_code.isin(FAMILIES["E&M"][0] | FAMILIES["Psych"][0])]
    high = fam[fam.procedure_code.isin({FAMILIES["E&M"][1], FAMILIES["Psych"][1]})]
    return pd.Series({"family_claims": len(fam), "upcoding_rate": len(high) / len(fam) if len(fam) else 0.0})

prov = claims.groupby("provider_id").agg(
    claims=("claim_id", "count"), patients=("patient_id", "nunique"),
    total_billed=("billed_amount", "sum"), total_paid=("paid_amount", "sum"),
    avg_billed_per_claim=("billed_amount", "mean"),
    weekend_claims=("is_weekend", "sum")).reset_index()
prov["avg_billed_per_patient"] = prov.total_billed / prov.patients
prov["weekend_share"] = prov.weekend_claims / prov.claims
prov = prov.merge(claims.groupby("provider_id").apply(family_stats).reset_index(), on="provider_id")
prov = prov.merge(providers[["provider_id", "specialty", "region"]], on="provider_id", how="left")
for col in ["avg_billed_per_claim", "avg_billed_per_patient"]:
    # z-scores WITHIN specialty: a radiologist is compared with radiologists, not with primary care
    g = prov.groupby("specialty")[col]
    prov[f"z_{col}"] = (prov[col] - g.transform("mean")) / g.transform(lambda s: s.std(ddof=0))
up_thresh = max(UPCODING_FLOOR, prov.upcoding_rate.mean() + 1.5 * prov.upcoding_rate.std(ddof=0))
prov["is_outlier"] = (prov.z_avg_billed_per_claim > Z_THRESHOLD) | (prov.z_avg_billed_per_patient > Z_THRESHOLD)
prov["is_upcoder"] = (prov.family_claims >= UPCODING_MIN_FAMILY) & (prov.upcoding_rate >= up_thresh)
prov["is_weekend"] = (prov.weekend_share >= WEEKEND_SHARE_MIN) & (prov.claims >= WEEKEND_MIN_CLAIMS)

by_prov = claims.set_index("provider_id")
# R2 upcoding: high-complexity claims of flagged providers
for pid in prov.loc[prov.is_upcoder, "provider_id"]:
    for cid in by_prov.loc[[pid]].query("procedure_code in ['99215','90837']").claim_id:
        flags[cid].append("upcoding_suspect")
# R3 outliers: flagged providers' claims priced above 1.3x procedure median
for pid in prov.loc[prov.is_outlier, "provider_id"]:
    sub = by_prov.loc[[pid]]
    for cid in sub[sub.billed_amount > sub.procedure_code.map(proc_median) * 1.3].claim_id:
        flags[cid].append("provider_outlier")
# R5 weekend billing
for pid in prov.loc[prov.is_weekend, "provider_id"]:
    for cid in by_prov.loc[[pid]].query("is_weekend").claim_id:
        flags[cid].append("weekend_billing")

claims["flag_types"] = claims.claim_id.map(lambda c: ";".join(flags[c]))
flagged = claims[claims.flag_types != ""].copy()
flagged["primary_flag"] = flagged.flag_types.str.split(";").str[0]
flagged_out = flagged[["claim_id", "patient_id", "provider_id", "procedure_code", "units",
                       "billed_amount", "paid_amount", "claim_date", "status",
                       "flag_types", "primary_flag"]]
flagged_out.to_csv("outputs/flagged_claims.csv", index=False)

# Provider risk ranking: transparent composite score (0-100)
flag_by_prov = flagged.groupby("provider_id").agg(
    flagged_claims=("claim_id", "count"), flagged_paid=("paid_amount", "sum")).reset_index()
prov = prov.merge(flag_by_prov, on="provider_id", how="left").fillna({"flagged_claims": 0, "flagged_paid": 0.0})
prov["flagged_share"] = prov.flagged_claims / prov.claims
prov["risk_score"] = (12 * prov.z_avg_billed_per_claim.clip(lower=0)
                      + 45 * prov.upcoding_rate + 25 * prov.weekend_share
                      + 40 * prov.flagged_share
                      + 12 * prov.is_upcoder + 12 * prov.is_outlier
                      + 8 * prov.is_weekend).clip(upper=100).round(1)
prov["risk_tier"] = pd.cut(prov.risk_score, [-1, 25, 50, 101], labels=["Low", "Medium", "High"])
ranking = prov.sort_values("risk_score", ascending=False)
ranking[["provider_id", "specialty", "region", "claims", "patients", "total_billed", "total_paid",
         "avg_billed_per_claim", "avg_billed_per_patient", "z_avg_billed_per_claim",
         "upcoding_rate", "weekend_share", "flagged_claims", "flagged_paid",
         "risk_score", "risk_tier"]].to_csv("outputs/provider_risk_ranking.csv", index=False)

def paid_of(flag):
    return flagged.loc[flagged.flag_types.str.contains(flag), "paid_amount"].sum()

top = ranking.iloc[0]
kpi = pd.DataFrame({"kpi": [
    "total_claims", "total_billed_usd", "total_paid_usd", "flagged_claims", "flagged_pct",
    "estimated_recovery_exposure_usd", "duplicate_claims", "duplicate_paid_usd",
    "excessive_units_claims", "upcoding_suspect_claims", "upcoding_suspect_rate_pct",
    "weekend_flagged_claims", "provider_outlier_claims", "high_risk_providers",
    "top_outlier_provider", "top_provider_risk_score", "top_provider_avg_billed_per_claim",
    "specialty_peer_avg_billed_per_claim"],
    "value": [len(claims), round(claims.billed_amount.sum(), 2), round(claims.paid_amount.sum(), 2),
              len(flagged), round(100 * len(flagged) / len(claims), 2),
              round(flagged.paid_amount.sum(), 2), int((claims._dup_rank > 0).sum()),
              round(claims.loc[claims._dup_rank > 0, "paid_amount"].sum(), 2),
              int(flagged.flag_types.str.contains("excessive_units").sum()),
              int(flagged.flag_types.str.contains("upcoding_suspect").sum()),
              round(100 * int(flagged.flag_types.str.contains("upcoding_suspect").sum()) / len(claims), 2),
              int(flagged.flag_types.str.contains("weekend_billing").sum()),
              int(flagged.flag_types.str.contains("provider_outlier").sum()),
              int((ranking.risk_tier == "High").sum()),
              top.provider_id, top.risk_score, round(top.avg_billed_per_claim, 2),
              round(prov.loc[prov.specialty == top.specialty, "avg_billed_per_claim"].median(), 2)]})
kpi.to_csv("outputs/kpi_summary.csv", index=False)

top3 = ranking.head(3)
by_type = {t: (int(flagged.flag_types.str.contains(t).sum()), round(paid_of(t), 2))
           for t in ["duplicate", "upcoding_suspect", "provider_outlier", "excessive_units", "weekend_billing"]}
with open("outputs/insights.md", "w") as f:
    f.write("# Insights — Payment Integrity Analytics: Claims Fraud, Waste & Abuse Detection\n\n")
    f.write("> Portfolio project — synthetic data only, no PHI. Detection is 100% rule-based (see analysis.py).\n\n")
    f.write("## Headline KPIs\n")
    for _, r in kpi.iterrows():
        f.write(f"- **{r.kpi}**: {r.value}\n")
    f.write("\n## Findings\n")
    f.write(f"- **{len(flagged)} of {len(claims)} claims ({100*len(flagged)/len(claims):.1f}%) tripped at least one FWA rule**, "
            f"putting **${flagged.paid_amount.sum():,.0f} of paid dollars** into review as estimated recovery exposure.\n")
    f.write(f"- **Duplicate billing is the cleanest recovery**: {int((claims._dup_rank>0).sum())} duplicate copies worth "
            f"${claims.loc[claims._dup_rank>0,'paid_amount'].sum():,.0f} paid — same patient, provider, procedure, date and amount.\n")
    for t, (n, amt) in by_type.items():
        f.write(f"- Flag type `{t}`: {n} claims, ${amt:,.0f} paid.\n")
    f.write(f"- **Top risk provider {top.provider_id}** ({top.specialty}, {top.region}) scores {top.risk_score}/100 — "
            f"avg billed per claim ${top.avg_billed_per_claim:,.0f} vs a specialty peer median of "
            f"${prov.loc[prov.specialty == top.specialty, 'avg_billed_per_claim'].median():,.0f}.\n")
    f.write("- Next three riskiest providers: " + ", ".join(
        f"{r.provider_id} ({r.risk_score})" for r in top3.iloc[1:].itertuples()) + ".\n")
    f.write("- Upcoding suspects concentrate in high-complexity codes 99215/90837 billed by a small set of providers "
            f"at >= {up_thresh:.0%} of their E&M/Psych volume vs a peer mean of {prov.upcoding_rate.mean():.0%}.\n")
    f.write("\n## How a payment-integrity team would use this\n"
            "1. Send duplicate + excessive-unit flags to auto-review (highest precision, fastest recovery).\n"
            "2. Route High-tier providers to pre-payment review and medical-record requests before alleging anything —\n"
            "   statistical outliers are leads for investigation, not proof of fraud.\n"
            "3. Feed confirmed outcomes back to recalibrate thresholds (z > 2.0, upcoding floor 30%, weekend 35%).\n")
print(kpi.to_string(index=False))
assert len(flagged) > 100 and 5 < 100 * len(flagged) / len(claims) < 40
print(f"\nFlagged: {len(flagged)} claims | exposure ${flagged.paid_amount.sum():,.0f} | top provider {top.provider_id} ({top.risk_score})")
