"""
Data quality checks that run after cleaning and before any report is built.

Each check returns PASS, WARN or FAIL. A FAIL stops the pipeline, so the weekly
support pack is never built on broken data.
"""
from __future__ import annotations

import duckdb
import pandas as pd


def run_checks(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    checks = [
        ("Every ticket has a unique ID",
         "SELECT COUNT(*) - COUNT(DISTINCT ticket_id) FROM stg_tickets", "FAIL"),
        ("Every ticket has a valid created time",
         "SELECT COUNT(*) FROM stg_tickets WHERE created_at IS NULL", "FAIL"),
        ("No contacts dated outside the reporting year",
         """SELECT (SELECT COUNT(*) FROM stg_tickets WHERE created_at >= TIMESTAMP '2026-10-02')
                 + (SELECT COUNT(*) FROM stg_bot_conversations WHERE started_at >= TIMESTAMP '2026-10-02')""",
         "FAIL"),
        ("Every ticket is assigned to a known agent",
         """SELECT COUNT(*) FROM stg_tickets t LEFT JOIN stg_agents a USING (agent_id)
            WHERE a.agent_id IS NULL""", "FAIL"),
        ("Orders recorded for every day",
         """SELECT 365 - COUNT(DISTINCT date) FROM stg_orders""", "FAIL"),
        ("CSAT scores between 1 and 5",
         "SELECT COUNT(*) FROM stg_tickets WHERE csat NOT BETWEEN 1 AND 5", "FAIL"),
        ("Tickets with a clock error (resolved before created)",
         "SELECT COUNT(*) FROM stg_tickets WHERE clock_error", "WARN"),
        ("Tickets still unclassified after the subject rules",
         "SELECT COUNT(*) FROM stg_tickets WHERE contact_reason = 'Unclassified'", "WARN"),
    ]
    rows = []
    for name, sql, severity in checks:
        failing = con.execute(sql).fetchone()[0]
        rows.append({"check": name, "failing_rows": int(failing),
                     "status": "PASS" if failing == 0 else severity})
    return pd.DataFrame(rows)
