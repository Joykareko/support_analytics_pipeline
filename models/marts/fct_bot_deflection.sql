-- Claimed vs true chatbot deflection by month and intent.
-- Claimed: the bot marked the chat resolved. True: resolved AND the customer did not
-- come back about the same reason within 7 days.
SELECT contact_month AS month,
       contact_reason AS intent,
       COUNT(*) AS bot_conversations,
       COUNT(*) FILTER (WHERE path = 'Bot resolved') AS claimed_resolved,
       COUNT(*) FILTER (WHERE path = 'Bot resolved' AND NOT followed_by_repeat_7d) AS truly_resolved,
       COUNT(*) FILTER (WHERE followed_by_repeat_7d IS NOT NULL) AS conversations_measurable
FROM int_contacts
WHERE path LIKE 'Bot%'
GROUP BY 1, 2
ORDER BY 1, 2;
