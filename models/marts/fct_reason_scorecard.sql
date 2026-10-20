-- Scorecard per contact reason: volume, first contact resolution, handle time, CSAT and cost.
-- First contact resolution (FCR) = share of contacts with no repeat about the same reason within 7 days.
SELECT contact_reason,
       COUNT(*) AS contacts,
       AVG((NOT followed_by_repeat_7d)::INT) AS fcr_rate,
       AVG(COALESCE(is_repeat_7d, FALSE)::INT) AS repeat_share,
       AVG(handle_minutes) AS avg_handle_minutes,
       AVG((csat >= 4)::INT) AS csat_rate,
       COUNT(csat) AS csat_responses,
       SUM(cost_eur) / COUNT(*) AS cost_per_contact_eur,
       SUM(cost_eur) AS total_cost_eur
FROM int_contacts
GROUP BY 1
ORDER BY contacts DESC;
