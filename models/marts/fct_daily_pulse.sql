-- Daily operations pulse: volume, contact rate, backlog, first response SLA and CSAT.
-- A day is flagged when contacts per 1,000 orders run 40% above the trailing 28 day average.
WITH days AS (
    SELECT o.date, o.orders FROM stg_orders o
),
contacts AS (
    SELECT contact_date AS date, COUNT(*) AS contacts,
           COUNT(*) FILTER (WHERE path IN ('Agent', 'Bot to agent')) AS agent_contacts
    FROM int_contacts GROUP BY 1
),
tickets AS (
    SELECT CAST(created_at AS DATE) AS date,
           AVG(CASE WHEN channel = 'chat'
                    THEN (first_response_at <= created_at + INTERVAL 5 MINUTE)::INT
                    ELSE (first_response_at <= created_at + INTERVAL 24 HOUR)::INT END) AS sla_met_rate,
           AVG((csat >= 4)::INT) AS csat_rate,
           COUNT(csat) AS csat_responses
    FROM stg_tickets GROUP BY 1
),
backlog AS (
    SELECT d.date,
           COUNT(t.ticket_id) AS open_tickets_end_of_day
    FROM days d
    LEFT JOIN stg_tickets t
      ON CAST(t.created_at AS DATE) <= d.date
     AND (t.resolved_at IS NULL OR CAST(t.resolved_at AS DATE) > d.date)
     AND t.created_at >= d.date - INTERVAL 30 DAY
    GROUP BY 1
),
joined AS (
    SELECT d.date, d.orders, c.contacts, c.agent_contacts,
           1000.0 * c.contacts / d.orders AS contacts_per_1k_orders,
           b.open_tickets_end_of_day, t.sla_met_rate, t.csat_rate, t.csat_responses
    FROM days d
    JOIN contacts c USING (date)
    JOIN tickets t USING (date)
    JOIN backlog b USING (date)
)
SELECT *,
       AVG(contacts_per_1k_orders) OVER (ORDER BY date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS trailing_28d_rate,
       COALESCE(contacts_per_1k_orders > 1.4 *
           AVG(contacts_per_1k_orders) OVER (ORDER BY date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING), FALSE) AS is_spike
FROM joined
ORDER BY date;
