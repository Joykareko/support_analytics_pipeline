-- Tagging audit: how many tickets agents left untagged, by month and agent cohort.
-- Untagged tickets weaken every contact driver report, so this is tracked like any other KPI.
SELECT CAST(date_trunc('month', t.created_at) AS DATE) AS month,
       CASE WHEN a.start_date >= DATE '2026-07-01' THEN 'Joined Jul 2026' ELSE 'Existing agents' END AS agent_cohort,
       COUNT(*) AS tickets,
       AVG((t.reason_source = 'subject rules')::INT) AS untagged_rate,
       AVG((t.contact_reason = 'Unclassified')::INT) AS unclassified_rate
FROM stg_tickets t
JOIN stg_agents a USING (agent_id)
GROUP BY 1, 2
ORDER BY 1, 2;
