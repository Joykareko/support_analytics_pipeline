-- One row per customer contact, whichever way it reached us.
-- A contact is an agent ticket, or a chatbot conversation. When the bot hands a chat to an
-- agent, the bot conversation and the agent ticket are the SAME contact, so they are joined
-- rather than counted twice.
WITH bot AS (
    SELECT
        b.bot_conversation_id AS contact_id,
        b.customer_id,
        b.started_at          AS contact_at,
        'chat'                AS channel,
        b.contact_reason,
        b.product_area,
        CASE b.outcome WHEN 'resolved_by_bot' THEN 'Bot resolved'
                       WHEN 'handed_to_agent' THEN 'Bot to agent'
                       ELSE 'Bot abandoned' END AS path,
        t.handle_minutes,
        t.agent_id,
        t.csat
    FROM stg_bot_conversations b
    LEFT JOIN stg_tickets t
      ON t.via_bot_handoff
     AND t.customer_id = b.customer_id
     AND t.created_at BETWEEN b.started_at AND b.started_at + INTERVAL 10 MINUTE
),
agent AS (
    SELECT ticket_id, customer_id, created_at, channel, contact_reason, product_area,
           'Agent' AS path, handle_minutes, agent_id, csat
    FROM stg_tickets
    WHERE NOT via_bot_handoff
),
contacts AS (
    SELECT * FROM bot
    UNION ALL
    SELECT * FROM agent
)
SELECT
    c.*,
    CAST(c.contact_at AS DATE)                       AS contact_date,
    CAST(date_trunc('week', c.contact_at) AS DATE)   AS contact_week,
    CAST(date_trunc('month', c.contact_at) AS DATE)  AS contact_month,
    COALESCE(c.handle_minutes * a.hourly_cost_eur / 60, 0)
        + CASE WHEN c.path LIKE 'Bot%' THEN 0.25 ELSE 0 END AS cost_eur,
    -- Repeat contact: the same customer contacting about the same reason within 7 days
    LAG(c.contact_at) OVER w >= c.contact_at - INTERVAL 7 DAY  AS is_repeat_7d,
    CASE WHEN c.contact_at > TIMESTAMP '2026-09-23 23:59:59' THEN NULL   -- not enough days to know
         ELSE COALESCE(LEAD(c.contact_at) OVER w <= c.contact_at + INTERVAL 7 DAY, FALSE)
    END AS followed_by_repeat_7d
FROM contacts c
LEFT JOIN stg_agents a USING (agent_id)
WINDOW w AS (PARTITION BY c.customer_id, c.contact_reason ORDER BY c.contact_at);
