-- Monthly cost per contact and per 1,000 orders.
WITH m AS (
    SELECT contact_month AS month, COUNT(*) AS contacts, SUM(cost_eur) AS cost_eur,
           COUNT(*) FILTER (WHERE path LIKE 'Bot%') AS bot_contacts
    FROM int_contacts GROUP BY 1
),
o AS (SELECT CAST(date_trunc('month', date) AS DATE) AS month, SUM(orders) AS orders FROM stg_orders GROUP BY 1)
SELECT m.month, o.orders, m.contacts, m.bot_contacts, m.cost_eur,
       m.cost_eur / m.contacts AS cost_per_contact_eur,
       1000.0 * m.contacts / o.orders AS contacts_per_1k_orders,
       1000.0 * m.cost_eur / o.orders AS cost_per_1k_orders_eur
FROM m JOIN o USING (month)
ORDER BY 1;
