"""
Clean the raw helpdesk, chatbot, order and help centre exports.

Every fix is written to a cleaning log, so nothing changes silently.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

# Agents type contact tags in many ways. Map every variant to one contact reason.
TAG_MAP = {
    "key activation": "Key activation", "activation key": "Key activation",
    "payment failed": "Payment failed", "payment issue": "Payment failed",
    "refund": "Refund request", "refund request": "Refund request", "refund req": "Refund request",
    "not delivered": "Order not delivered", "order not delivered": "Order not delivered",
    "delivery issue": "Order not delivered", "nd": "Order not delivered",
    "account access": "Account access", "login": "Account access", "2fa": "Account access",
    "seller dispute": "Seller dispute", "seller issue": "Seller dispute",
    "wallet": "Wallet balance", "wallet balance": "Wallet balance",
    "general": "General question", "question": "General question", "general question": "General question",
}

# When a ticket has no usable tag, classify it from its subject line.
# Order matters: delivery phrases mention "key" and "code", so they are checked first.
SUBJECT_RULES = [
    ("Order not delivered", r"where is my|still pending|didn.t receive|delayed|no email with"),
    ("Seller dispute", r"seller"),
    ("Wallet balance", r"wallet|top up"),
    ("Refund request", r"refund|money back|cancel"),
    ("Payment failed", r"payment|declined|charged|checkout|paid but"),
    ("Key activation", r"key|code|activat|redeem|region"),
    ("Account access", r"log ?in|2fa|password|locked"),
    ("General question", r"question|how does|do you sell"),
]

PRODUCT_AREA = {
    "Key activation": "Keys", "Payment failed": "Payments", "Refund request": "Refunds",
    "Order not delivered": "Delivery", "Account access": "Account", "Seller dispute": "Marketplace",
    "Wallet balance": "Payments", "General question": "Other", "Unclassified": "Unclassified",
}


def normalise_tag(tag: str) -> str | None:
    if not isinstance(tag, str):
        return None
    key = re.sub(r"[-_]+", " ", tag).strip().lower()
    return TAG_MAP.get(key)


def classify_subject(subject: str) -> str:
    s = str(subject).lower()
    for reason, pattern in SUBJECT_RULES:
        if re.search(pattern, s):
            return reason
    return "Unclassified"


def parse_timestamp(value) -> pd.Timestamp:
    """Handle the three formats in the helpdesk export: ISO, DD/MM/YYYY HH:MM and epoch milliseconds."""
    if pd.isna(value) or value == "":
        return pd.NaT
    v = str(value)
    if v.isdigit():
        return pd.to_datetime(int(v), unit="ms")
    if "/" in v:
        return pd.to_datetime(v, format="%d/%m/%Y %H:%M")
    return pd.to_datetime(v.replace("Z", ""), format="%Y-%m-%dT%H:%M:%S")


def clean_tickets(raw: pd.DataFrame, log: list) -> pd.DataFrame:
    t = raw.copy()
    n = len(t)
    t = t.drop_duplicates()
    log.append(("tickets", "Duplicate rows from overlapping exports", n - len(t), "Removed"))

    fmt_counts = {
        "epoch ms": t["created_at"].astype(str).str.fullmatch(r"\d+").sum(),
        "DD/MM/YYYY": t["created_at"].astype(str).str.contains("/").sum(),
    }
    t["created_at"] = t["created_at"].map(parse_timestamp)
    t["first_response_at"] = t["first_response_at"].map(parse_timestamp)
    t["resolved_at"] = t["resolved_at"].map(parse_timestamp)
    log.append(("tickets", "Created time in three formats (ISO, DD/MM/YYYY, epoch ms)",
                int(sum(fmt_counts.values())), "Parsed to one timestamp type"))

    bad = t["resolved_at"] < t["created_at"]
    t.loc[bad, "resolved_at"] = pd.NaT
    t["clock_error"] = bad
    log.append(("tickets", "Resolved before it was created (clock error)", int(bad.sum()),
                "Resolution time removed and flagged"))

    csat = t["csat"].fillna("").astype(str).str.strip().replace({"N/A": ""})
    t["csat"] = pd.to_numeric(csat, errors="coerce").round().astype("Int64")
    log.append(("tickets", "CSAT stored as text ('4.0', 'N/A', blank)", int((csat != "").sum()),
                "Converted to whole numbers 1 to 5; blanks mean no survey response"))

    t["reason_from_tag"] = t["tag"].map(normalise_tag)
    variants = t.loc[t["reason_from_tag"].notna(), "tag"].nunique()
    log.append(("tickets", f"{variants} different tag spellings for 8 contact reasons",
                int(t["reason_from_tag"].notna().sum()), "Mapped to standard contact reasons"))

    missing = t["reason_from_tag"].isna()
    t["reason_from_subject"] = t["subject"].map(classify_subject)
    t["contact_reason"] = t["reason_from_tag"].fillna(t["reason_from_subject"])
    t["reason_source"] = missing.map({True: "subject rules", False: "agent tag"})
    log.append(("tickets", "Untagged or tagged 'other'", int(missing.sum()),
                "Classified from the subject line with keyword rules"))
    still = (t["contact_reason"] == "Unclassified").sum()
    log.append(("tickets", "Untagged with a vague subject ('Help', 'Hi')", int(still),
                "Left as Unclassified and flagged for agent review"))

    t["product_area"] = t["contact_reason"].map(PRODUCT_AREA)
    t["via_bot_handoff"] = t["via_bot_handoff"].astype(str).str.lower().eq("true")
    return t


def clean_bot(raw: pd.DataFrame, log: list) -> pd.DataFrame:
    b = raw.copy()
    b["started_at"] = pd.to_datetime(b["started_at"], utc=True).dt.tz_localize(None)
    b = b.rename(columns={"detected_intent": "contact_reason"})
    b["product_area"] = b["contact_reason"].map(PRODUCT_AREA)
    log.append(("bot_conversations", "Chatbot conversations", len(b), "Loaded; intent used as contact reason"))
    return b


def clean_all(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    log: list = []
    tickets = clean_tickets(raw["tickets"], log)
    bot = clean_bot(raw["bot_conversations"], log)
    orders = raw["orders"].assign(date=lambda d: pd.to_datetime(d["date"]))
    help_centre = raw["help_centre"].assign(date=lambda d: pd.to_datetime(d["date"]))
    agents = raw["agents"].assign(start_date=lambda d: pd.to_datetime(d["start_date"]))
    cleaning_log = pd.DataFrame(log, columns=["table", "issue", "rows_affected", "action"])
    return ({"tickets": tickets, "bot_conversations": bot, "orders": orders,
             "help_centre": help_centre, "agents": agents}, cleaning_log)


def load_raw() -> dict[str, pd.DataFrame]:
    return {
        "tickets": pd.read_csv(RAW / "helpdesk_tickets.csv", dtype={"csat": str, "created_at": str,
                                                                    "resolved_at": str, "tag": str}),
        "bot_conversations": pd.read_json(RAW / "bot_conversations.json", dtype={"started_at": str}),
        "orders": pd.read_csv(RAW / "orders_daily.csv"),
        "help_centre": pd.read_csv(RAW / "help_centre_sessions.csv"),
        "agents": pd.read_csv(RAW / "agents.csv"),
    }
