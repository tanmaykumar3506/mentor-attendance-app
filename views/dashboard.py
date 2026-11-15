"""Dashboard: KPIs, action queue, today's board, alerts, trends and lead view."""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import config as cfg
from src import logic, ui


def _compliance(day: pd.DataFrame) -> float | None:
    w = day[day["expected"] == "Working"]
    return float((w["status"] == "Present").mean() * 100) if len(w) else None


def render(ctx: dict) -> None:
    att, exc, as_of = ctx["att"], ctx["exc"], ctx["as_of"]
    ui.page_header("Attendance Dashboard", f"Control room view for {as_of:%A, %d %B %Y} - end-of-day review")

    day = att[att["date"] == as_of]
    if (day["expected"] == "Holiday").all():
        st.info("This day is a holiday. No attendance is expected.")
        return

    working = day[day["expected"] == "Working"]
    n_exp = len(working)
    present = int((working["status"] == "Present").sum())
    incomplete = int((working["status"] == "Incomplete").sum())
    absent = int((working["status"] == "Absent").sum())
    miss_in = int((working["issue"] == cfg.ISSUE_CHECKIN).sum())
    miss_out = int((working["issue"] == cfg.ISSUE_CHECKOUT).sum())
    leave = int((day["expected"] == "Leave").sum())
    late = int(working["late"].sum())
    pct = present / n_exp * 100 if n_exp else 0

    prev_dates = sorted(d for d in att.loc[att["expected"] == "Working", "date"].unique() if d < as_of.to_datetime64())
    prev = _compliance(att[att["date"] == prev_dates[-1]]) if prev_dates else None
    delta = f" ({pct - prev:+.0f} pts vs previous day)" if prev is not None else ""

    ui.kpi_row([
        ("Expected today", n_exp, f"of {len(day)} mentors", "#2563EB"),
        ("Present", present, f"{pct:.0f}% fully punched{delta}", cfg.STATUS_COLORS["Present"]),
        ("Incomplete", incomplete, f"{miss_in} no check-in / {miss_out} no check-out", cfg.STATUS_COLORS["Incomplete"]),
        ("Absent", absent, "no punches, no leave", cfg.STATUS_COLORS["Absent"]),
        ("On leave", leave, "approved in roster", cfg.STATUS_COLORS["Leave"]),
        ("Late check-ins", late, f"after {cfg.CHECKIN_TARGET} + {cfg.CHECKIN_GRACE_MIN} min", "#64748B"),
    ])
    st.write("")

    open_n = int(exc["status"].isin(cfg.NEEDS_ACTION_STATUSES).sum())
    overdue = int((exc["sla"] == "Overdue").sum())
    l3 = int((exc["level"] == 3).sum())
    recent = exc[(exc["date"] > as_of - pd.Timedelta(days=30)) & exc["close_hours"].notna()]
    med = f"{recent['close_hours'].median():.1f} h" if len(recent) else "-"
    ui.kpi_row([
        ("Open exceptions", open_n, "need action", "#F59E0B"),
        ("Overdue", overdue, "past next-morning deadline", "#DC2626"),
        ("Escalated to L3", l3, "program manager", "#7C3AED"),
        ("Median time to close", med, "last 30 days (detected to closed)", "#0EA5E9"),
    ])

    # ------------------------------------------------------------ follow-up progress
    today_exc = exc[exc["date"] == as_of]
    if len(today_exc):
        st.write("")
        contacted = int((today_exc["contacted_at"] != "").sum())
        closed = int(today_exc["status"].isin(cfg.CLOSED_STATUSES).sum())
        n = len(today_exc)
        st.markdown(f"**Follow-up progress for today's {n} exception(s)**")
        p1, p2 = st.columns(2)
        p1.progress(contacted / n, text=f"Mentor contacted: {contacted} of {n}")
        p2.progress(closed / n, text=f"Closed with reason and proof: {closed} of {n}")

    # --------------------------------------------------------------- action queue
    st.subheader("Action queue")
    queue = logic.action_queue(exc)
    if queue.empty:
        st.success("Nothing needs action. Every exception is closed.")
    else:
        st.caption("Everything that needs a person right now, most urgent first. Update status on the Exceptions & Alerts page.")
        styled = ui.style_map(ui.style_map(queue.style, ui.level_css, subset=["Level"]), ui.sla_css, subset=["SLA"])
        st.dataframe(styled, hide_index=True, **ui.WIDE, height=min(40 + 35 * len(queue), 330))

    # ---------------------------------------------------------- board + alerts
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Today's attendance board")
        board = working[["mentor_id", "mentor_name", "track", "check_in", "check_out", "status", "issue", "final_status"]].copy()
        board["flags"] = [
            ", ".join(x for x in [("Late" if l else ""), ("Early leave" if e else "")] if x)
            for l, e in zip(working["late"], working["early_leave"])
        ]
        board.columns = ["ID", "Mentor", "Track", "Check-in", "Check-out", "Status", "Issue", "After follow-up", "Flags"]
        leave_rows = day[day["expected"] == "Leave"]
        if len(leave_rows):
            extra = pd.DataFrame({
                "ID": leave_rows["mentor_id"], "Mentor": leave_rows["mentor_name"], "Track": leave_rows["track"],
                "Check-in": "", "Check-out": "", "Status": "Leave", "Issue": "", "After follow-up": "Leave", "Flags": "",
            })
            board = pd.concat([board, extra], ignore_index=True)
        order = {"Absent": 0, "Incomplete": 1, "Present": 2, "Leave": 3}
        board = board.sort_values(by="Status", key=lambda s: s.map(order), kind="stable")
        st.dataframe(
            ui.style_status(board, ["Status", "After follow-up"]),
            hide_index=True, **ui.WIDE, height=min(40 + 35 * len(board), 760),
        )
    with right:
        st.subheader("Alerts")
        alerts = logic.build_alerts(att, exc, as_of)
        if not alerts:
            st.success("No open alerts. All clear.")
        for a in alerts[:6]:
            ui.alert(a["severity"], a["title"], a["detail"])
        if len(alerts) > 6:
            st.caption(f"+ {len(alerts) - 6} more on the Exceptions & Alerts page")
        with st.expander("Daily summary (copy and send to manager)"):
            st.code(logic.daily_summary_text(att, exc, as_of), language=None)

    st.divider()

    # ------------------------------------------------------------------- trends
    window = att[(att["date"] <= as_of) & (att["date"] > as_of - pd.Timedelta(days=21)) & (att["expected"] != "Holiday")]
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.subheader("Daily attendance (last 3 weeks)")
        trend = window.groupby(["date", "status"]).size().reset_index(name="mentors")
        domain = ["Present", "Incomplete", "Absent", "Leave"]
        chart = (
            alt.Chart(trend).mark_bar().encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
                y=alt.Y("mentors:Q", title="Mentors"),
                color=alt.Color("status:N", title=None,
                                scale=alt.Scale(domain=domain, range=[cfg.STATUS_COLORS[s] for s in domain]),
                                legend=alt.Legend(orient="bottom")),
                tooltip=[alt.Tooltip("date:T", format="%d %b"), "status:N", "mentors:Q"],
            ).properties(height=280)
        )
        st.altair_chart(chart, **ui.WIDE)
    with c2:
        st.subheader("Punch compliance vs target")
        w = window[window["expected"] == "Working"]
        g = w.groupby("date")
        comp = pd.DataFrame({
            "Biometric record": g["status"].apply(lambda s: (s == "Present").mean() * 100),
            "After follow-up": g["final_status"].apply(lambda s: s.str.startswith("Present").mean() * 100),
        }).reset_index().melt("date", var_name="series", value_name="pct")
        base = alt.Chart(comp).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")))
        lines = base.mark_line(point=True).encode(
            y=alt.Y("pct:Q", title="% of working mentors", scale=alt.Scale(domain=[60, 100])),
            color=alt.Color("series:N", title=None,
                            scale=alt.Scale(domain=["Biometric record", "After follow-up"], range=["#F59E0B", "#16A34A"]),
                            legend=alt.Legend(orient="bottom")),
            tooltip=[alt.Tooltip("date:T", format="%d %b"), "series:N", alt.Tooltip("pct:Q", format=".0f")],
        )
        target = alt.Chart(pd.DataFrame({"t": [cfg.COMPLIANCE_TARGET]})).mark_rule(strokeDash=[5, 4], color="#64748B").encode(y="t:Q")
        st.altair_chart((lines + target).properties(height=280), **ui.WIDE)
        st.caption(f"Dashed line = {cfg.COMPLIANCE_TARGET}% target. The gap between the lines is what follow-up recovers.")

    c3, c4 = st.columns([3, 2], gap="large")
    with c3:
        st.subheader("Who misses most (last 30 days)")
        e30 = exc[exc["date"] > as_of - pd.Timedelta(days=30)]
        if e30.empty:
            st.caption("No exceptions in the last 30 days.")
        else:
            top = e30.groupby(["mentor_name", "exception_type"]).size().reset_index(name="count")
            totals = top.groupby("mentor_name")["count"].sum().nlargest(8).index.tolist()
            top = top[top["mentor_name"].isin(totals)]
            types = [cfg.ISSUE_CHECKIN, cfg.ISSUE_CHECKOUT, cfg.ISSUE_ABSENT]
            chart2 = (
                alt.Chart(top).mark_bar().encode(
                    y=alt.Y("mentor_name:N", sort=totals, title=None),
                    x=alt.X("count:Q", title="Exceptions"),
                    color=alt.Color("exception_type:N", title=None,
                                    scale=alt.Scale(domain=types, range=["#F59E0B", "#FB923C", "#DC2626"]),
                                    legend=alt.Legend(orient="bottom")),
                    tooltip=["mentor_name", "exception_type", "count"],
                ).properties(height=300)
            )
            st.altair_chart(chart2, **ui.WIDE)
    with c4:
        st.subheader("Lead view (last 14 days)")
        w14 = att[(att["date"] <= as_of) & (att["date"] > as_of - pd.Timedelta(days=14)) & (att["expected"] == "Working")]
        lead = w14.groupby("lead").agg(
            Mentors=("mentor_id", "nunique"),
            Compliance=("status", lambda s: round((s == "Present").mean() * 100, 1)),
            Misses=("issue", lambda s: int((s != "").sum())),
        ).reset_index().rename(columns={"lead": "Lead"})
        open_by_lead = exc[exc["status"].isin(cfg.NEEDS_ACTION_STATUSES)].groupby("lead").size()
        lead["Open"] = lead["Lead"].map(open_by_lead).fillna(0).astype(int)
        lead["Compliance"] = lead["Compliance"].map(lambda v: f"{v:.1f}%")
        st.dataframe(lead, hide_index=True, **ui.WIDE)
        st.caption("Compliance = fully punched days / working days. Open = exceptions waiting on action.")
