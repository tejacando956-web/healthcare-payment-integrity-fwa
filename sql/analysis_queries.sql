-- Payment Integrity Analytics: Claims Fraud, Waste & Abuse (FWA) Detection
-- Standard SQL (BigQuery / Snowflake dialect; STDDEV and window functions are portable).
-- Tables: claims(claim_id, patient_id, provider_id, procedure_code, units,
--              billed_amount, paid_amount, claim_date, status), providers(provider_id, specialty, region)
-- Each query mirrors one rule in analysis.py.

-- Q1. DUPLICATE BILLING: identical patient/provider/procedure/date/amount billed 2+ times
SELECT patient_id, provider_id, procedure_code, claim_date, billed_amount, COUNT(*) AS copies,
       SUM(paid_amount) AS paid_on_all_copies
FROM claims
GROUP BY patient_id, provider_id, procedure_code, claim_date, billed_amount
HAVING COUNT(*) > 1
ORDER BY paid_on_all_copies DESC;

-- Q2. DUPLICATE CLAIM ROWS: every copy after the first (the recoverable ones)
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id, provider_id, procedure_code,
                               claim_date, billed_amount ORDER BY claim_id) AS copy_rank
  FROM claims) t
WHERE copy_rank > 1;

-- Q3. PROVIDER BILLING PROFILE: volume, avg billed per claim and per patient
SELECT provider_id, COUNT(*) AS claims, COUNT(DISTINCT patient_id) AS patients,
       SUM(billed_amount) AS total_billed, SUM(paid_amount) AS total_paid,
       AVG(billed_amount) AS avg_billed_per_claim,
       SUM(billed_amount) / COUNT(DISTINCT patient_id) AS avg_billed_per_patient
FROM claims GROUP BY provider_id ORDER BY avg_billed_per_claim DESC;

-- Q4. SPECIALTY-RELATIVE OUTLIERS: z-score of avg billed per claim WITHIN specialty
WITH prov AS (
  SELECT c.provider_id, p.specialty, AVG(c.billed_amount) AS avg_billed
  FROM claims c JOIN providers p USING (provider_id) GROUP BY c.provider_id, p.specialty)
SELECT *, (avg_billed - AVG(avg_billed) OVER (PARTITION BY specialty))
          / STDDEV(avg_billed) OVER (PARTITION BY specialty) AS z_score
FROM prov WHERE (avg_billed - AVG(avg_billed) OVER (PARTITION BY specialty))
          / STDDEV(avg_billed) OVER (PARTITION BY specialty) > 2.0
ORDER BY z_score DESC;

-- Q5. PROVIDER PERCENTILE RANKS: NTILE quartile of avg billed per claim within specialty
WITH prov AS (
  SELECT c.provider_id, p.specialty, AVG(c.billed_amount) AS avg_billed
  FROM claims c JOIN providers p USING (provider_id) GROUP BY c.provider_id, p.specialty)
SELECT *, NTILE(4) OVER (PARTITION BY specialty ORDER BY avg_billed) AS billed_quartile
FROM prov ORDER BY specialty, billed_quartile DESC;

-- Q6. UPCODING RATE BY PROVIDER: high-complexity share of E&M + Psychotherapy volume
SELECT provider_id,
       SUM(CASE WHEN procedure_code IN ('99215','90837') THEN 1 ELSE 0 END) AS high_complexity,
       COUNT(*) AS family_claims,
       100.0 * SUM(CASE WHEN procedure_code IN ('99215','90837') THEN 1 ELSE 0 END) / COUNT(*) AS upcoding_rate_pct
FROM claims
WHERE procedure_code IN ('99212','99213','99214','99215','90832','90834','90837')
GROUP BY provider_id
HAVING COUNT(*) >= 15 AND upcoding_rate_pct >= 30
ORDER BY upcoding_rate_pct DESC;

-- Q7. EXCESSIVE UNITS: therapy codes billed above the typical 4-unit session
SELECT claim_id, patient_id, provider_id, procedure_code, units, billed_amount, paid_amount, claim_date
FROM claims
WHERE procedure_code IN ('97110','97530') AND units >= 6
ORDER BY units DESC, billed_amount DESC;

-- Q8. WEEKEND BILLING SPIKE: providers whose weekend share is far above peers
SELECT provider_id, COUNT(*) AS claims,
       100.0 * SUM(CASE WHEN EXTRACT(DAYOFWEEK FROM claim_date) IN (1, 7) THEN 1 ELSE 0 END) / COUNT(*) AS weekend_pct
FROM claims GROUP BY provider_id
HAVING COUNT(*) >= 25 AND weekend_pct >= 35
ORDER BY weekend_pct DESC;

-- Q9. BILLED VS PAID BY PROCEDURE: where billed dollars leak between charge and payment
SELECT procedure_code, COUNT(*) AS claims, SUM(billed_amount) AS billed, SUM(paid_amount) AS paid,
       100.0 * SUM(paid_amount) / SUM(billed_amount) AS paid_ratio_pct
FROM claims GROUP BY procedure_code ORDER BY billed DESC;

-- Q10. MONTHLY FLAGGED EXPOSURE TREND: paid $ on duplicate claims per month
SELECT SUBSTR(CAST(claim_date AS STRING), 1, 7) AS month, COUNT(*) AS duplicate_claims,
       SUM(paid_amount) AS duplicate_paid
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY patient_id, provider_id, procedure_code,
                                   claim_date, billed_amount ORDER BY claim_id) AS copy_rank
      FROM claims) t
WHERE copy_rank > 1
GROUP BY month ORDER BY month;
