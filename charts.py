"""Generate the 4 dashboard charts (matplotlib, dpi=150) from data/ + outputs/.
Run after analysis.py:  python3 charts.py"""
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

claims = pd.read_csv("data/claims.csv", parse_dates=["claim_date"], dtype={"procedure_code": str})
flagged = pd.read_csv("outputs/flagged_claims.csv", parse_dates=["claim_date"])
ranking = pd.read_csv("outputs/provider_risk_ranking.csv")
COLORS = {"duplicate": "#c0392b", "upcoding_suspect": "#e67e22", "provider_outlier": "#8e44ad",
          "excessive_units": "#2980b9", "weekend_billing": "#27ae60"}

# 1) Flagged paid $ by flag type (a claim can carry several flags, so types overlap)
types, amounts = [], []
for t in COLORS:
    m = flagged.flag_types.str.contains(t)
    types.append(t.replace("_", " ").title())
    amounts.append(flagged.loc[m, "paid_amount"].sum())
fig, ax = plt.subplots(figsize=(8, 4.2))
bars = ax.barh(types[::-1], amounts[::-1], color=[COLORS[t] for t in
               ["weekend_billing", "excessive_units", "provider_outlier", "upcoding_suspect", "duplicate"]])
for b, v in zip(bars, amounts[::-1]):
    ax.text(v + 1500, b.get_y() + b.get_height() / 2, f"${v:,.0f}", va="center", fontsize=9)
ax.set_xlabel("Paid $ on flagged claims (types overlap)")
ax.set_title("Estimated Recovery Exposure by FWA Flag Type")
plt.tight_layout(); plt.savefig("images/flagged_amount_by_type.png", dpi=150); plt.close()

# 2) Provider risk: avg billed per claim vs upcoding rate, sized by claims, colored by tier
fig, ax = plt.subplots(figsize=(8, 4.6))
tier_color = {"High": "#c0392b", "Medium": "#e67e22", "Low": "#95a5a6"}
for tier, sub in ranking.groupby("risk_tier"):
    ax.scatter(sub.avg_billed_per_claim, sub.upcoding_rate * 100, s=sub.claims * 2.2,
               c=tier_color[tier], alpha=0.65, label=f"{tier} risk")
top = ranking.iloc[0]
ax.annotate(f"Top: {top.provider_id} (score {top.risk_score})",
            (top.avg_billed_per_claim, top.upcoding_rate * 100),
            xytext=(12, 10), textcoords="offset points", fontsize=9, fontweight="bold")
ax.set_xlabel("Average billed $ per claim"); ax.set_ylabel("Upcoding rate % (high-complexity share)")
ax.set_title("Provider Risk Outliers — Billing Level vs Upcoding Rate"); ax.legend()
plt.tight_layout(); plt.savefig("images/provider_risk_outliers.png", dpi=150); plt.close()

# 3) Monthly trend: flagged paid vs total paid
claims["month"] = claims.claim_date.dt.to_period("M").astype(str)
flagged["month"] = flagged.claim_date.dt.to_period("M").astype(str)
monthly = claims.groupby("month").paid_amount.sum().rename("total")
mflag = flagged.groupby("month").paid_amount.sum().rename("flagged")
df = pd.concat([monthly, mflag], axis=1).fillna(0)
fig, ax = plt.subplots(figsize=(8, 4.2))
ax.bar(df.index, df.total, color="#bdc3c7", label="Total paid")
ax.bar(df.index, df.flagged, color="#c0392b", label="Flagged paid (recovery exposure)")
ax.set_ylabel("Paid $"); ax.set_title("Monthly Flagged Paid $ vs Total Paid $ — 2025")
ax.tick_params(axis="x", rotation=45); ax.legend()
plt.tight_layout(); plt.savefig("images/monthly_flagged_trend.png", dpi=150); plt.close()

# 4) Billed vs paid by procedure code
g = claims.groupby("procedure_code")[["billed_amount", "paid_amount"]].sum().sort_values("billed_amount", ascending=True)
fig, ax = plt.subplots(figsize=(8, 5))
y = range(len(g))
ax.barh([i + 0.2 for i in y], g.billed_amount, height=0.4, color="#7f8c8d", label="Billed")
ax.barh([i - 0.2 for i in y], g.paid_amount, height=0.4, color="#2980b9", label="Paid")
ax.set_yticks(list(y)); ax.set_yticklabels(g.index)
ax.set_xlabel("Total $ in 2025"); ax.set_title("Billed vs Paid by Procedure Code"); ax.legend()
plt.tight_layout(); plt.savefig("images/billed_vs_paid_by_procedure.png", dpi=150); plt.close()
print("4 charts written to images/")
