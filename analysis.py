"""
Turn the metric tables into findings: charts, a volume forecast with a capacity estimate,
and a weekly support performance pack.

    python analysis.py          (run after run_pipeline.py)

Outputs:
    docs/*.png                                 charts used in the README
    reports/weekly_support_pack_<week>.md      the weekly pack for ops managers
    reports/findings.md                        headline numbers for the README
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DOCS, REPORTS = ROOT / "docs", ROOT / "reports"
con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
q = lambda sql: con.execute(sql).df()

# Palette (validated reference palette): slot 1 blue, slot 2 orange; neutrals for context
BLUE, ORANGE, MUTED, GRID, INK, INK2, SURFACE = "#2a78d6", "#eb6834", "#898781", "#ebeae6", "#0b0b0b", "#52514e", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "font.size": 10, "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "lines.linewidth": 2,
})


def finish(fig, ax, name: str, subtitle: str) -> None:
    ax.set_title(ax.get_title(loc="left"), loc="left", pad=26)
    ax.text(0, 1.025, subtitle, transform=ax.transAxes, color=INK2, fontsize=9.5, va="bottom")
    fig.tight_layout()
    fig.savefig(DOCS / name, dpi=150)
    plt.close(fig)


def pct(x: float, dp: int = 0) -> str:
    return f"{x * 100:.{dp}f}%"


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    F = {}   # headline findings

    # ---------- 1. Daily contact rate with events ----------
    d = q("SELECT * FROM fct_daily_pulse ORDER BY date")
    d["date"] = pd.to_datetime(d["date"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(d["date"], d["contacts_per_1k_orders"].rolling(7, center=True, min_periods=1).mean(),
            color=MUTED, linewidth=1.5, label="7 day average")
    ax.plot(d["date"], d["contacts_per_1k_orders"], color=BLUE, linewidth=1.2, alpha=0.9, label="Daily")
    spikes = d[d["is_spike"]]
    ax.scatter(spikes["date"], spikes["contacts_per_1k_orders"], s=40, color=ORANGE, zorder=3,
               edgecolor=SURFACE, linewidth=1.5, label="Flagged spike")
    for day, text, y in [("2026-02-02", "Help article rewritten", 32.5), ("2026-03-02", "Chatbot launched", 29.5)]:
        ax.axvline(pd.Timestamp(day), color=MUTED, linestyle=(0, (3, 3)), linewidth=1)
        ax.text(pd.Timestamp(day), y, " " + text, color=INK2, fontsize=8.5, va="top")
    top = spikes.iloc[spikes["contacts_per_1k_orders"].argmax()]
    ax.annotate("Payment provider outage\n12 to 14 May", (top["date"], top["contacts_per_1k_orders"]),
                xytext=(25, -10), textcoords="offset points", fontsize=8.5, color=INK, va="top",
                arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.8))
    ax.set_ylim(0, 34)
    ax.set_ylabel("Contacts per 1,000 orders")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(frameon=False, loc="lower left", ncol=3, fontsize=9)
    ax.set_title("Daily contact rate")
    finish(fig, ax, "contact_rate_daily.png",
           "Normalised by orders, so growth in sales does not look like growth in problems. Only the outage days were flagged.")
    normal = d[(d["date"] < "2026-05-01") & (d["date"] >= "2026-04-01")]
    out = d[d["is_spike"]]
    F["outage_rate"] = out["contacts_per_1k_orders"].mean()
    F["outage_trailing"] = out["trailing_28d_rate"].mean()
    F["outage_backlog"] = int(out["open_tickets_end_of_day"].max())
    F["normal_backlog"] = int(normal["open_tickets_end_of_day"].median())
    F["outage_sla"] = out["sla_met_rate"].mean()
    F["normal_sla"] = normal["sla_met_rate"].mean()
    F["outage_csat"] = out["csat_rate"].mean()
    F["normal_csat"] = normal["csat_rate"].mean()
    F["spike_days"] = len(out)

    # ---------- 2. Bot deflection: claimed vs true ----------
    b = q("""SELECT intent, SUM(bot_conversations) AS conv,
                    SUM(claimed_resolved)::DOUBLE / SUM(bot_conversations) AS claimed,
                    SUM(truly_resolved)::DOUBLE / SUM(conversations_measurable) AS true_rate
             FROM fct_bot_deflection GROUP BY 1 ORDER BY claimed - true_rate""")
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    y = np.arange(len(b))
    ax.hlines(y, b["true_rate"], b["claimed"], color=GRID, linewidth=6, zorder=1)
    ax.scatter(b["claimed"], y, s=90, color=MUTED, zorder=2, edgecolor=SURFACE, linewidth=2, label="Claimed by the bot")
    ax.scatter(b["true_rate"], y, s=90, color=BLUE, zorder=3, edgecolor=SURFACE, linewidth=2,
               label="True (no repeat contact within 7 days)")
    for i, r in b.iterrows():
        ax.text(r["true_rate"] - 0.012, i, pct(r["true_rate"]), ha="right", va="center", fontsize=9, color=INK)
        ax.text(r["claimed"] + 0.012, i, pct(r["claimed"]), ha="left", va="center", fontsize=9, color=INK2)
    ax.set_yticks(y, b["intent"])
    ax.set_xlim(0, 0.6)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", visible=False)
    ax.set_ylim(-0.6, len(b) - 0.4)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=9)
    ax.set_title("Chatbot resolution: claimed vs true")
    finish(fig, ax, "bot_deflection.png", "Share of bot conversations resolved, Mar to Sep 2026.")
    tot = q("""SELECT SUM(bot_conversations) c, SUM(claimed_resolved)::DOUBLE/SUM(bot_conversations) cl,
                      SUM(truly_resolved)::DOUBLE/SUM(conversations_measurable) tr FROM fct_bot_deflection""").iloc[0]
    F["bot_conv"], F["bot_claimed"], F["bot_true"] = int(tot["c"]), tot["cl"], tot["tr"]
    ref = b.set_index("intent").loc["Refund request"]
    F["refund_claimed"], F["refund_true"] = ref["claimed"], ref["true_rate"]
    kc = b.set_index("intent").loc["Key activation"]
    F["key_claimed"], F["key_true"] = kc["claimed"], kc["true_rate"]

    # ---------- 3. Seller disputes growing ----------
    w = q("SELECT * FROM fct_reason_weekly ORDER BY week")
    w["week"] = pd.to_datetime(w["week"])
    s = w[w["contact_reason"] == "Seller dispute"]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(s["week"], s["contacts_per_1k_orders"], color=BLUE)
    base = s[(s["week"] >= "2026-04-01") & (s["week"] < "2026-06-01")]["contacts_per_1k_orders"].mean()
    last = s.tail(4)["contacts_per_1k_orders"].mean()
    ax.axhline(base, color=MUTED, linestyle=(0, (3, 3)), linewidth=1)
    ax.text(pd.Timestamp("2026-04-01"), base - 0.17, f"Apr to May average: {base:.2f}", color=INK2, fontsize=8.5)
    ax.annotate(f"Last 4 weeks: {last:.2f} (+{last / base - 1:.0%})", (s["week"].iloc[-1], s["contacts_per_1k_orders"].iloc[-1]),
                xytext=(-160, 12), textcoords="offset points", fontsize=9, color=INK)
    ax.set_ylim(0, s["contacts_per_1k_orders"].max() * 1.25)
    ax.set_ylabel("Contacts per 1,000 orders")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_title("Seller disputes are growing faster than orders")
    finish(fig, ax, "seller_disputes.png", "Weekly seller dispute contacts per 1,000 orders.")
    F["seller_base"], F["seller_last"] = base, last
    sc = q("SELECT * FROM fct_reason_scorecard").set_index("contact_reason")
    F["seller_cost"], F["seller_csat"] = sc.loc["Seller dispute", "cost_per_contact_eur"], sc.loc["Seller dispute", "csat_rate"]
    F["avg_cost"] = (sc["total_cost_eur"].sum() / sc["contacts"].sum())

    # ---------- 4. Help article ----------
    h = q("SELECT * FROM fct_help_centre WHERE article_topic = 'Key activation' ORDER BY month")
    k = w[w["contact_reason"] == "Key activation"]
    F["key_read_before"] = h[h["month"] < "2026-02-01"]["contact_after_reading_rate"].mean()
    F["key_read_after"] = h[h["month"] >= "2026-02-01"]["contact_after_reading_rate"].mean()
    F["key_rate_before"] = k[(k["week"] < "2026-02-02")]["contacts_per_1k_orders"].mean()
    F["key_rate_after"] = k[(k["week"] >= "2026-02-02") & (k["week"] < "2026-03-02")]["contacts_per_1k_orders"].mean()
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(k["week"], k["contacts_per_1k_orders"], color=BLUE)
    ax.axvline(pd.Timestamp("2026-02-02"), color=MUTED, linestyle=(0, (3, 3)), linewidth=1)
    ax.text(pd.Timestamp("2026-02-02"), k["contacts_per_1k_orders"].max() * 1.12, " Article rewritten",
            color=INK2, fontsize=8.5, va="top")
    ax.set_ylim(0, k["contacts_per_1k_orders"].max() * 1.15)
    ax.set_ylabel("Contacts per 1,000 orders")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_title("Key activation contacts fell after the help article was rewritten")
    finish(fig, ax, "key_activation.png",
           f"Readers who still contacted support fell from {pct(F['key_read_before'])} to {pct(F['key_read_after'])}.")

    # ---------- 5. Tagging audit ----------
    t = q("SELECT * FROM fct_tagging_audit ORDER BY month")
    t["month"] = pd.to_datetime(t["month"])
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    for cohort, color in [("Existing agents", BLUE), ("Joined Jul 2026", ORANGE)]:
        c = t[t["agent_cohort"] == cohort]
        ax.plot(c["month"], c["untagged_rate"], color=color, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=cohort)
        ax.text(c["month"].iloc[-1] + pd.Timedelta(days=6), c["untagged_rate"].iloc[-1],
                f"{cohort}: {pct(c['untagged_rate'].iloc[-1])}", va="center", fontsize=9, color=INK)
    ax.set_ylim(0, 0.4)
    ax.set_xlim(t["month"].min() - pd.Timedelta(days=10), t["month"].max() + pd.Timedelta(days=95))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax.set_title("Untagged tickets by agent cohort")
    finish(fig, ax, "tagging_audit.png", "Share of tickets with no usable contact tag.")
    mc = q("SELECT * FROM fct_monthly_cost ORDER BY month")
    pre, post = mc[mc["month"] < "2026-03-01"], mc[mc["month"] >= "2026-03-01"]
    F["cpc_pre"] = pre["cost_eur"].sum() / pre["contacts"].sum()
    F["cpc_post"] = post["cost_eur"].sum() / post["contacts"].sum()
    F["rate_pre"] = 1000 * pre["contacts"].sum() / pre["orders"].sum()
    F["rate_post"] = 1000 * post["contacts"].sum() / post["orders"].sum()
    F["untag_existing"] = t[t["agent_cohort"] == "Existing agents"]["untagged_rate"].tail(3).mean()
    F["untag_new"] = t[t["agent_cohort"] == "Joined Jul 2026"]["untagged_rate"].mean()

    # ---------- 6. Forecast and capacity ----------
    wk = q("""SELECT contact_week AS week, COUNT(*) FILTER (WHERE path IN ('Agent','Bot to agent')) AS agent_contacts,
                     AVG(handle_minutes) AS aht
              FROM int_contacts GROUP BY 1 ORDER BY 1""")
    wo = q("SELECT CAST(date_trunc('week', date) AS DATE) AS week, SUM(orders) AS orders, COUNT(*) n FROM stg_orders GROUP BY 1")
    wk = wk.merge(wo, on="week")
    wk = wk[wk["n"] == 7].reset_index(drop=True)
    wk["rate"] = 1000 * wk["agent_contacts"] / wk["orders"]
    # Forecast = planned orders x trailing 4 week agent contact rate. Baseline = last week's volume.
    wk["forecast"] = wk["orders"] * wk["rate"].shift(1).rolling(4).mean() / 1000
    wk["naive"] = wk["agent_contacts"].shift(1)
    test = wk.dropna(subset=["forecast", "naive"])
    test = test[~test["week"].astype(str).isin(["2026-05-11"])]  # outage week is not forecastable
    mape = lambda f: (abs(test[f] - test["agent_contacts"]) / test["agent_contacts"]).mean()
    F["mape_model"], F["mape_naive"] = mape("forecast"), mape("naive")
    wk["week"] = pd.to_datetime(wk["week"])
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(wk["week"], wk["agent_contacts"], color=BLUE, label="Actual agent contacts")
    ax.plot(wk["week"], wk["forecast"], color=ORANGE, linewidth=1.5, linestyle=(0, (4, 2)), label="Forecast")
    ax.set_ylim(0, wk["agent_contacts"].max() * 1.15)
    ax.set_ylabel("Agent contacts per week")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.set_title("Weekly agent volume: forecast vs actual")
    finish(fig, ax, "forecast.png",
           f"Planned orders x recent contact rate. Average error {pct(F['mape_model'], 1)} vs {pct(F['mape_naive'], 1)} for 'same as last week'.")
    # Capacity for the next week: assume orders grow 2% and occupancy of 75%, 35 productive hours per agent
    last4 = wk.tail(4)
    next_orders = last4["orders"].mean() * 1.02
    next_contacts = next_orders * last4["rate"].mean() / 1000
    hours = next_contacts * last4["aht"].mean() / 60 / 0.75
    F.update(next_contacts=next_contacts, next_hours=hours, next_fte=hours / 35)

    # ---------- weekly packs ----------
    for week in ["2026-05-11", "2026-09-21"]:
        write_weekly_pack(pd.Timestamp(week))
    write_findings(F)
    print(pd.Series(F).round(3).to_string())


def write_weekly_pack(week: pd.Timestamp) -> None:
    prev = week - pd.Timedelta(days=7)
    end = week + pd.Timedelta(days=6)
    p = q(f"SELECT * FROM fct_daily_pulse WHERE date BETWEEN DATE '{prev.date()}' AND DATE '{end.date()}'")
    p["date"] = pd.to_datetime(p["date"])
    cur, pre = p[p["date"] >= week], p[p["date"] < week]

    def summary(x):
        return {"contacts": x["contacts"].sum(), "orders": x["orders"].sum(),
                "rate": 1000 * x["contacts"].sum() / x["orders"].sum(),
                "sla": (x["sla_met_rate"]).mean(), "csat": (x["csat_rate"] * x["csat_responses"]).sum() / x["csat_responses"].sum(),
                "backlog": int(x["open_tickets_end_of_day"].iloc[-1])}
    c, r = summary(cur), summary(pre)
    reasons = q(f"""SELECT contact_reason, contacts, contacts_per_1k_orders, trailing_8w_rate, is_spike
                    FROM fct_reason_weekly WHERE week = DATE '{week.date()}' ORDER BY contacts DESC""")
    gap = q(f"""SELECT contact_reason,
                       AVG((path = 'Bot resolved')::INT) - AVG((path = 'Bot resolved' AND NOT followed_by_repeat_7d)::INT) AS g
                FROM int_contacts WHERE path LIKE 'Bot%' AND contact_week = DATE '{week.date()}'
                  AND followed_by_repeat_7d IS NOT NULL GROUP BY 1 ORDER BY g DESC LIMIT 1""")
    bot = q(f"""SELECT COUNT(*) conv,
                       AVG((path = 'Bot resolved')::INT) claimed,
                       AVG((path = 'Bot resolved' AND NOT followed_by_repeat_7d)::INT) FILTER (WHERE followed_by_repeat_7d IS NOT NULL) true_rate
                FROM int_contacts WHERE path LIKE 'Bot%' AND contact_week = DATE '{week.date()}'""").iloc[0]
    tag = q(f"""SELECT AVG((reason_source = 'subject rules')::INT) u FROM stg_tickets
                WHERE CAST(date_trunc('week', created_at) AS DATE) = DATE '{week.date()}'""").iloc[0, 0]

    def chg(a, b, as_pct=False):
        if as_pct:
            return f"{(a - b) * 100:+.1f} pts"
        return f"{a / b - 1:+.0%}"

    lines = [f"# Weekly support pack: week of {week:%d %b %Y}", "",
             "_Generated by `analysis.py` from the metric tables. Synthetic data._", "",
             "## Headline", ""]
    alerts = []
    spikes = reasons[reasons["is_spike"]]
    for _, s in spikes.iterrows():
        alerts.append(f"**{s['contact_reason']} contacts spiked** to {s['contacts_per_1k_orders']:.1f} per 1,000 orders, "
                      f"{s['contacts_per_1k_orders'] / s['trailing_8w_rate']:.1f}x the 8 week average "
                      f"({s['contacts']:,} contacts). Check with Payments whether a provider or checkout issue is open.")
    if c["sla"] < 0.90:
        alerts.append(f"**First response SLA fell to {pct(c['sla'])}**, below the 90% target. Consider moving Tier 2 agents to the queue until the backlog clears.")
    if c["backlog"] > 1.3 * r["backlog"]:
        alerts.append(f"**Backlog grew to {c['backlog']:,} open tickets** from {r['backlog']:,} a week earlier.")
    growth = q(f"""WITH r AS (
                      SELECT contact_reason,
                             -- medians, so a one-off spike does not look like a trend
                             MEDIAN(contacts_per_1k_orders) FILTER (WHERE week > DATE '{week.date()}' - INTERVAL 56 DAY) AS recent,
                             MEDIAN(contacts_per_1k_orders) FILTER (WHERE week <= DATE '{week.date()}' - INTERVAL 56 DAY) AS before
                      FROM fct_reason_weekly
                      WHERE week <= DATE '{week.date()}' AND week > DATE '{week.date()}' - INTERVAL 112 DAY
                      GROUP BY 1)
                   SELECT * FROM r WHERE recent > 1.2 * before AND contact_reason <> 'Unclassified'""")
    for _, g in growth.iterrows():
        alerts.append(f"**{g['contact_reason']} is a growing issue:** {g['recent']:.2f} contacts per 1,000 orders over the last "
                      f"8 weeks (median) vs {g['before']:.2f} in the 8 weeks before ({g['recent'] / g['before'] - 1:+.0%}). "
                      "Share the top examples with the team that owns it.")
    if tag > 0.12:
        alerts.append(f"**{pct(tag)} of tickets were untagged.** Most come from agents who joined in July; a 15 minute tagging refresher would fix most of it.")
    if not alerts:
        alerts.append("No spikes this week. Volume moved in line with orders.")
    lines += [f"- {a}" for a in alerts] + ["", "## Key numbers", "",
              "| Metric | This week | Last week | Change |", "| --- | --- | --- | --- |",
              f"| Contacts | {c['contacts']:,} | {r['contacts']:,} | {chg(c['contacts'], r['contacts'])} |",
              f"| Orders | {c['orders']:,.0f} | {r['orders']:,.0f} | {chg(c['orders'], r['orders'])} |",
              f"| Contacts per 1,000 orders | {c['rate']:.1f} | {r['rate']:.1f} | {chg(c['rate'], r['rate'])} |",
              f"| First response within SLA | {pct(c['sla'])} | {pct(r['sla'])} | {chg(c['sla'], r['sla'], True)} |",
              f"| CSAT (share rating 4 or 5) | {pct(c['csat'])} | {pct(r['csat'])} | {chg(c['csat'], r['csat'], True)} |",
              f"| Open tickets at week end | {c['backlog']:,} | {r['backlog']:,} | {chg(c['backlog'], r['backlog'])} |",
              "", "## Contact drivers", "",
              "| Reason | Contacts | Per 1,000 orders | vs 8 week average |", "| --- | --- | --- | --- |"]
    for _, s in reasons.iterrows():
        vs = round(s["contacts_per_1k_orders"] / s["trailing_8w_rate"] - 1, 2) + 0.0 if s["trailing_8w_rate"] else 0.0
        lines.append(f"| {s['contact_reason']} | {s['contacts']:,} | {s['contacts_per_1k_orders']:.2f} | {vs:+.0%} |")
    if bot["conv"] > 0:
        lines += ["", "## Chatbot", "",
                  f"{int(bot['conv']):,} bot conversations. The bot marked {pct(bot['claimed'])} resolved, but only "
                  f"{pct(bot['true_rate'])} were truly resolved (no repeat contact within 7 days). "
                  f"The biggest gap is in {gap.iloc[0, 0].lower()} chats, where customers the bot 'resolved' came back."]
    (REPORTS / f"weekly_support_pack_{week.date()}.md").write_text("\n".join(lines) + "\n")


def write_findings(F: dict) -> None:
    text = f"""# Headline findings (synthetic data, Oct 2025 to Sep 2026)

1. Payment provider outage: contacts hit {F['outage_rate']:.1f} per 1,000 orders against a normal {F['outage_trailing']:.1f}. First response SLA fell from {pct(F['normal_sla'])} to {pct(F['outage_sla'])}, CSAT from {pct(F['normal_csat'])} to {pct(F['outage_csat'])}, and the backlog peaked at {F['outage_backlog']:,} open tickets against a normal {F['normal_backlog']:,}. The daily alert flagged exactly the {F['spike_days']} outage days and nothing else all year.
2. Chatbot: across {F['bot_conv']:,} conversations the bot claimed {pct(F['bot_claimed'])} resolved, but only {pct(F['bot_true'])} were truly resolved. For refunds the gap is {pct(F['refund_claimed'])} claimed vs {pct(F['refund_true'])} true; for key activation it is small ({pct(F['key_claimed'])} vs {pct(F['key_true'])}). Cost per contact fell from EUR {F['cpc_pre']:.2f} to EUR {F['cpc_post']:.2f} after launch, but contacts per 1,000 orders did not fall ({F['rate_pre']:.1f} before, {F['rate_post']:.1f} after), because many "resolved" customers came back.
3. Help article: after the key activation article was rewritten, readers who still contacted support fell from {pct(F['key_read_before'])} to {pct(F['key_read_after'])}, and key activation contacts fell from {F['key_rate_before']:.2f} to {F['key_rate_after']:.2f} per 1,000 orders.
4. Seller disputes: up from {F['seller_base']:.2f} to {F['seller_last']:.2f} per 1,000 orders (+{F['seller_last'] / F['seller_base'] - 1:.0%}). They are the most expensive contact (EUR {F['seller_cost']:.2f} each vs EUR {F['avg_cost']:.2f} average) with the lowest CSAT ({pct(F['seller_csat'])}).
5. Tagging: {pct(F['untag_new'])} of tickets from agents who joined in July are untagged, against {pct(F['untag_existing'])} for existing agents.
6. Forecast: planned orders x recent contact rate gives a {pct(F['mape_model'], 1)} average weekly error, against {pct(F['mape_naive'], 1)} for "same as last week". Next week needs about {F['next_contacts']:,.0f} agent contacts, {F['next_hours']:,.0f} agent hours, or {F['next_fte']:.0f} full time agents.
"""
    (REPORTS / "findings.md").write_text(text)


if __name__ == "__main__":
    main()
