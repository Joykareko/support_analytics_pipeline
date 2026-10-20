-- Help centre self-service: how many article sessions were followed by a contact within 24 hours.
SELECT CAST(date_trunc('month', date) AS DATE) AS month,
       article_topic,
       SUM(sessions) AS sessions,
       SUM(sessions_followed_by_contact) AS followed_by_contact,
       SUM(sessions_followed_by_contact)::DOUBLE / SUM(sessions) AS contact_after_reading_rate
FROM stg_help_centre
GROUP BY 1, 2
ORDER BY 1, 2;
