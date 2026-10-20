"""
Generate one year of synthetic customer support data for a fictional digital games
marketplace (game keys, gift cards and in-game currency sold by many sellers).

The exports are deliberately messy, the way real helpdesk and warehouse exports are:
mixed timestamp formats, inconsistent and missing contact tags, duplicate rows from
overlapping exports, CSAT stored as text, and a few clock errors.

Four real-world stories are built into the data for the analysis to find:
  1. A payment provider outage (12 to 14 May 2026) that floods support with payment contacts.
  2. A rewritten key activation help article (2 Feb 2026) that genuinely prevents contacts.
  3. A chatbot launched on 2 Mar 2026. It "resolves" many chats, but refund customers it
     resolves often come back within a week, so its claimed deflection overstates reality.
  4. Seller disputes growing steadily from June 2026, faster than orders.

    python scripts/generate_sample_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(7)
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
START, END = pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30")
DAYS = pd.date_range(START, END, freq="D")

OUTAGE = (pd.Timestamp("2026-05-12"), pd.Timestamp("2026-05-14"))
ARTICLE_REWRITE = pd.Timestamp("2026-02-02")
BOT_LAUNCH = pd.Timestamp("2026-03-02")
SELLER_GROWTH_START = pd.Timestamp("2026-06-01")
NEW_AGENT_COHORT = pd.Timestamp("2026-07-01")

# reason: (contacts per 1,000 orders, product area, mean handle minutes)
REASONS = {
    "Key activation": (4.0, "Keys", 8),
    "Payment failed": (2.4, "Payments", 12),
    "Refund request": (3.0, "Refunds", 10),
    "Order not delivered": (2.0, "Delivery", 9),
    "Account access": (1.5, "Account", 14),
    "Seller dispute": (1.0, "Marketplace", 22),
    "Wallet balance": (0.8, "Payments", 9),
    "General question": (0.7, "Other", 6),
}
BOT_ELIGIBLE = {"Key activation", "Refund request", "Order not delivered", "Account access"}
# Chance that a customer whose chat the bot "resolved" comes back within 7 days
BOT_FALSE_RESOLVE = {"Key activation": 0.10, "Refund request": 0.55,
                     "Order not delivered": 0.30, "Account access": 0.20}
AGENT_REPEAT = {"Key activation": 0.07, "Payment failed": 0.12, "Refund request": 0.10,
                "Order not delivered": 0.11, "Account access": 0.09, "Seller dispute": 0.18,
                "Wallet balance": 0.08, "General question": 0.04}

# Messy tag spellings agents actually use
TAG_VARIANTS = {
    "Key activation": ["key activation", "Key-Activation", "activation_key", "KEY ACTIVATION", "key_activation"],
    "Payment failed": ["payment failed", "Payment-Failed", "payment_issue", "PAYMENT FAILED"],
    "Refund request": ["refund", "Refund request", "refund_req", "REFUND"],
    "Order not delivered": ["not delivered", "order_not_delivered", "Delivery issue", "ND"],
    "Account access": ["account access", "login", "2fa", "Account-Access"],
    "Seller dispute": ["seller dispute", "seller_issue", "Seller Dispute"],
    "Wallet balance": ["wallet", "wallet balance", "Wallet_Balance"],
    "General question": ["general", "question", "General question"],
}
SUBJECTS = {
    "Key activation": ["Key not working", "Activation code invalid", "The key says already used",
                       "Can't redeem my code on Steam", "Region locked key?", "Code doesn't activate"],
    "Payment failed": ["Payment failed but money taken", "Card declined", "Charged twice",
                       "Payment error at checkout", "Paid but no order"],
    "Refund request": ["I want a refund", "Refund please", "Requesting my money back",
                       "Wrong game bought, refund?", "Cancel my order and refund"],
    "Order not delivered": ["Where is my key", "Order still pending", "Didn't receive my order",
                            "Order delayed", "No email with my code"],
    "Account access": ["Can't log in", "Lost my 2FA", "Password reset not arriving", "Account locked"],
    "Seller dispute": ["Seller sent wrong key", "Problem with seller", "Seller not responding",
                       "Report a seller"],
    "Wallet balance": ["Wallet balance missing", "Top up not showing", "Wallet funds gone"],
    "General question": ["Question about a game", "How does this work", "Do you sell gift cards",
                         "Question about pricing"],
}
# Some customers write subjects that say nothing about the problem
VAGUE_SUBJECTS = ["Help", "Urgent!!", "Problem with my order", "Hi", "Please help", "Issue", "Order #"]
CHANNEL_P = {"chat": 0.6, "email": 0.35, "web_form": 0.05}
FIRST_RESPONSE_MIN = {"chat": 2.5, "email": 420, "web_form": 600}  # typical, in minutes


def daily_orders() -> pd.Series:
    t = np.arange(len(DAYS))
    base = 11_000 * (1 + 0.35 * t / len(DAYS))            # 35% growth over the year
    weekday = np.where(DAYS.dayofweek >= 5, 1.18, 0.94)
    season = np.ones(len(DAYS))
    for a, b, lift in [("2025-11-27", "2025-12-01", 1.9),   # Black Friday
                       ("2025-12-18", "2026-01-03", 1.45),  # holidays
                       ("2026-06-25", "2026-07-09", 1.35)]: # summer sale
        season[(DAYS >= a) & (DAYS <= b)] = lift
    noise = RNG.normal(1, 0.04, len(DAYS))
    return pd.Series((base * weekday * season * noise).round().astype(int), index=DAYS)


def contact_rate(reason: str, day: pd.Timestamp) -> float:
    rate = REASONS[reason][0]
    if reason == "Key activation" and day >= ARTICLE_REWRITE:
        rate *= 0.68                                       # better help article
    if reason == "Payment failed" and OUTAGE[0] <= day <= OUTAGE[1]:
        rate *= 7.0                                        # provider outage
    if reason == "Seller dispute" and day >= SELLER_GROWTH_START:
        rate *= 1 + 0.65 * (day - SELLER_GROWTH_START).days / 121
    return rate


def pick_channel() -> str:
    return RNG.choice(list(CHANNEL_P), p=list(CHANNEL_P.values()))


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    orders = daily_orders()
    agents = [f"A{n:03d}" for n in range(1, 41)]
    new_agents = [f"A{n:03d}" for n in range(41, 49)]
    customers = np.arange(100_000, 400_000)

    tickets, bot_convs = [], []
    tid, bid = 1, 1

    def make_ticket(cust, reason, ts, channel, from_bot=False, outage=False):
        nonlocal tid
        mean_frt = FIRST_RESPONSE_MIN[channel] * (6 if outage and channel != "chat" else 1)
        frt = RNG.exponential(mean_frt)
        handle = max(1.5, RNG.lognormal(np.log(REASONS[reason][2]), 0.45))
        resolve_hours = (frt / 60) + RNG.exponential(3 if channel == "chat" else 20)
        day = ts.normalize()
        pool = agents + (new_agents if day >= NEW_AGENT_COHORT else [])
        agent = RNG.choice(pool)
        untag_p = 0.30 if agent in new_agents else 0.09
        tag = "" if RNG.random() < untag_p else RNG.choice(TAG_VARIANTS[reason])
        if tag == "" and RNG.random() < 0.4:
            tag = "other"
        tickets.append({
            "ticket_id": f"T{tid:07d}", "customer_id": int(cust), "created_at": ts,
            "channel": channel, "tag": tag,
            "subject": RNG.choice(VAGUE_SUBJECTS) if RNG.random() < 0.07 else RNG.choice(SUBJECTS[reason]),
            "true_reason": reason, "agent_id": agent, "via_bot_handoff": from_bot,
            "first_response_at": ts + pd.Timedelta(minutes=float(frt)),
            "resolved_at": ts + pd.Timedelta(hours=float(resolve_hours)),
            "handle_minutes": round(handle, 1),
        })
        tid += 1
        return tickets[-1]

    for day in DAYS:
        n_orders = orders[day]
        for reason in REASONS:
            n = RNG.poisson(n_orders / 1000 * contact_rate(reason, day))
            outage = reason == "Payment failed" and OUTAGE[0] <= day <= OUTAGE[1]
            for _ in range(n):
                cust = RNG.choice(customers)
                ts = day + pd.Timedelta(seconds=int(RNG.integers(0, 86_400)))
                channel = pick_channel()
                # contact chain: first contact, plus possible repeat contacts within 7 days
                for attempt in range(3):
                    if channel == "chat" and reason in BOT_ELIGIBLE and ts >= BOT_LAUNCH:
                        r = RNG.random()
                        outcome = ("resolved_by_bot" if r < 0.46 else
                                   "handed_to_agent" if r < 0.88 else "abandoned")
                        bot_convs.append({"bot_conversation_id": f"B{bid:07d}", "customer_id": int(cust),
                                          "started_at": ts, "detected_intent": reason,
                                          "outcome": outcome, "true_reason": reason})
                        bid += 1
                        if outcome == "handed_to_agent":
                            t = make_ticket(cust, reason, ts + pd.Timedelta(minutes=3), "chat", True, outage)
                            back = RNG.random() < AGENT_REPEAT[reason]
                        elif outcome == "resolved_by_bot":
                            back = RNG.random() < BOT_FALSE_RESOLVE[reason]
                        else:
                            back = RNG.random() < 0.5
                    else:
                        make_ticket(cust, reason, ts, channel, False, outage)
                        back = RNG.random() < AGENT_REPEAT[reason] * (2.2 if outage else 1)
                    if not back:
                        break
                    ts = ts + pd.Timedelta(hours=float(RNG.uniform(6, 160)))
                    channel = pick_channel()
                    if ts > END + pd.Timedelta(days=1):
                        break

    t = pd.DataFrame(tickets)
    b = pd.DataFrame(bot_convs)

    # CSAT survey: ~25% respond; repeat contacts and slow responses score lower
    t = t.sort_values("created_at").reset_index(drop=True)
    t["prior_7d"] = (t.groupby(["customer_id", "true_reason"])["created_at"]
                       .diff().dt.total_seconds().lt(7 * 86400))
    wait_h = (t["first_response_at"] - t["created_at"]).dt.total_seconds() / 3600
    in_outage = (t["true_reason"] == "Payment failed") & t["created_at"].between(OUTAGE[0], OUTAGE[1] + pd.Timedelta(days=1))
    base = (4.3 - 1.2 * t["prior_7d"] - 1.0 * (wait_h > 24) - 0.8 * in_outage
            - 0.4 * (t["true_reason"] == "Seller dispute"))
    score = np.clip(np.round(base + RNG.normal(0, 0.9, len(t))), 1, 5).astype(int)
    responded = RNG.random(len(t)) < 0.25
    t["csat"] = np.where(responded, score.astype(str), "")
    fmt = RNG.random(len(t))
    t.loc[responded & (fmt < 0.2), "csat"] = t["csat"] + ".0"
    t.loc[~responded & (fmt < 0.1), "csat"] = "N/A"

    # Messy timestamps: ISO, European text format, epoch milliseconds
    def messy(ts: pd.Series) -> pd.Series:
        r = RNG.random(len(ts))
        iso = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        eu = ts.dt.strftime("%d/%m/%Y %H:%M")
        ep = (ts.astype("int64") // 10**6).astype(str)
        return pd.Series(np.where(r < 0.7, iso, np.where(r < 0.9, eu, ep)), index=ts.index)

    out = t.copy()
    out["created_at"] = messy(out["created_at"])
    out["first_response_at"] = out["first_response_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["resolved_at"] = t["resolved_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # A few clock errors: resolved before created
    bad = RNG.choice(len(out), 40, replace=False)
    out.loc[bad, "resolved_at"] = (t.loc[bad, "created_at"] - pd.Timedelta(hours=2)).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Tickets still open at export time have no resolved_at
    out.loc[t["created_at"] > END - pd.Timedelta(hours=10), "resolved_at"] = ""
    # Overlapping export windows duplicate some rows
    dups = out.sample(frac=0.012, random_state=3)
    out = pd.concat([out, dups]).sample(frac=1, random_state=5)
    out.drop(columns=["true_reason", "prior_7d"]).to_csv(RAW / "helpdesk_tickets.csv", index=False)
    # The true reason is kept separately so the tagging audit can be checked against it
    t[["ticket_id", "true_reason"]].to_csv(RAW / "_answer_key_true_reasons.csv", index=False)

    b["started_at"] = b["started_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    b.drop(columns=["true_reason"]).to_json(RAW / "bot_conversations.json", orient="records", indent=0)

    pd.DataFrame({"date": DAYS.strftime("%Y-%m-%d"), "orders": orders.values}).to_csv(RAW / "orders_daily.csv", index=False)

    # Help centre: sessions per article topic and how many contacted support within 24h
    hc = []
    for day in DAYS:
        for topic, views_per_k, follow in [("Key activation", 30, 0.22), ("Refunds", 18, 0.30),
                                           ("Payments", 12, 0.25), ("Delivery", 14, 0.20),
                                           ("Account", 10, 0.28)]:
            sessions = RNG.poisson(orders[day] / 1000 * views_per_k)
            if topic == "Key activation" and day >= ARTICLE_REWRITE:
                sessions = int(sessions * 1.25)
                follow = 0.09
            hc.append({"date": day.strftime("%Y-%m-%d"), "article_topic": topic, "sessions": sessions,
                       "sessions_followed_by_contact": RNG.binomial(sessions, follow)})
    pd.DataFrame(hc).to_csv(RAW / "help_centre_sessions.csv", index=False)

    ag = pd.DataFrame({"agent_id": agents + new_agents,
                       "team": ["Tier 1"] * 30 + ["Tier 2"] * 10 + ["Tier 1"] * 8,
                       "start_date": ["2024-03-01"] * 40 + ["2026-07-01"] * 8,
                       "hourly_cost_eur": [16.0] * 30 + [21.0] * 10 + [16.0] * 8})
    ag.to_csv(RAW / "agents.csv", index=False)

    print(f"orders: {orders.sum():,} | tickets: {len(t):,} (+{len(dups)} duplicate rows) | "
          f"bot conversations: {len(b):,}")


if __name__ == "__main__":
    main()
