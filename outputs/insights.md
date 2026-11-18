# Insights — Payment Integrity Analytics: Claims Fraud, Waste & Abuse Detection

> Portfolio project — synthetic data only, no PHI. Detection is 100% rule-based (see analysis.py).

## Headline KPIs
- **total_claims**: 2767
- **total_billed_usd**: 710777.76
- **total_paid_usd**: 443611.4
- **flagged_claims**: 454
- **flagged_pct**: 16.41
- **estimated_recovery_exposure_usd**: 113431.95
- **duplicate_claims**: 45
- **duplicate_paid_usd**: 10370.23
- **excessive_units_claims**: 60
- **upcoding_suspect_claims**: 125
- **upcoding_suspect_rate_pct**: 4.52
- **weekend_flagged_claims**: 71
- **provider_outlier_claims**: 184
- **high_risk_providers**: 10
- **top_outlier_provider**: PR012
- **top_provider_risk_score**: 100.0
- **top_provider_avg_billed_per_claim**: 222.97
- **specialty_peer_avg_billed_per_claim**: 94.2

## Findings
- **454 of 2767 claims (16.4%) tripped at least one FWA rule**, putting **$113,432 of paid dollars** into review as estimated recovery exposure.
- **Duplicate billing is the cleanest recovery**: 45 duplicate copies worth $10,370 paid — same patient, provider, procedure, date and amount.
- Flag type `duplicate`: 45 claims, $10,370 paid.
- Flag type `upcoding_suspect`: 125 claims, $22,120 paid.
- Flag type `provider_outlier`: 184 claims, $67,786 paid.
- Flag type `excessive_units`: 60 claims, $20,039 paid.
- Flag type `weekend_billing`: 71 claims, $5,870 paid.
- **Top risk provider PR012** (Primary Care, Northeast) scores 100.0/100 — avg billed per claim $223 vs a specialty peer median of $94.
- Next three riskiest providers: PR041 (100.0), PR029 (100.0).
- Upcoding suspects concentrate in high-complexity codes 99215/90837 billed by a small set of providers at >= 42% of their E&M/Psych volume vs a peer mean of 12%.

## How a payment-integrity team would use this
1. Send duplicate + excessive-unit flags to auto-review (highest precision, fastest recovery).
2. Route High-tier providers to pre-payment review and medical-record requests before alleging anything —
   statistical outliers are leads for investigation, not proof of fraud.
3. Feed confirmed outcomes back to recalibrate thresholds (z > 2.0, upcoding floor 30%, weekend 35%).
