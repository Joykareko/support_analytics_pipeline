-- Weekly contacts per 1,000 orders by contact reason, with a spike flag.
-- Normalising by orders separates "more customers" from "more problems".
WITH weekly_orders AS (
    SELECT CAST(date_trunc('week', date) AS DATE) AS week, SUM(orders) AS orders, COUNT(*) AS days
    FROM stg_orders GROUP BY 1
),
weekly AS (
    SELECT contact_week AS week, contact_reason, COUNT(*) AS contacts
    FROM int_contacts GROUP BY 1, 2
)
SELECT w.week, w.contact_reason, w.contacts, o.orders,
       1000.0 * w.contacts / o.orders AS contacts_per_1k_orders,
       AVG(1000.0 * w.contacts / o.orders) OVER r AS trailing_8w_rate,
       COALESCE(1000.0 * w.contacts / o.orders > 1.5 * AVG(1000.0 * w.contacts / o.orders) OVER r
                AND w.contacts >= 30, FALSE) AS is_spike
FROM weekly w
JOIN weekly_orders o USING (week)
WHERE o.days = 7                                  -- skip partial first and last weeks
WINDOW r AS (PARTITION BY w.contact_reason ORDER BY w.week ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING)
ORDER BY w.week, w.contact_reason;
