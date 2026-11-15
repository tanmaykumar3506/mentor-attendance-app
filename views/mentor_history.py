"""Mentor-wise attendance history."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import config as cfg
from src import logic, ui


def render(ctx: dict) -> None:
    att, exc, mentors, as_of = ctx["att"], ctx["exc"], ctx["mentors"], ctx["as_of"]
    ui.page_header("Mentor History", "Attendance pattern, exceptions and punch times for one mentor")

    c1, c2 = st.columns([2, 2])
    options = mentors["mentor_id"] + " - " + mentors["mentor_name"]
    choice = c1.selectbox("Mentor", options.tolist(), key="hist_mentor")
    span = c2.radio("Period", ["Last 7 days", "Last 14 days", "Last 30 days", "All data"], index=2, horizontal=True, key="hist_span")
    mid = choice.split(" - ")[0]
    m = mentors[mentors["mentor_id"] == mid].iloc[0]

    d = att[(att["mentor_id"] == mid) & (att["date"] <= as_of)]
    days = {"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}.get(span)
    if days:
        d = d[d["date"] > as_of - pd.Timedelta(days=days)]

    st.caption(f"{m['track']} - Lead: {m['lead']} - Shift {m['shift']} - Contact {m['phone']}")
    work = d[d["expected"] == "Working"]
    n = len(work)
    present = int((work["status"] == "Present").sum())
    ui.kpi_row([
        ("Punch compliance", f"{present / n * 100:.0f}%" if n else "-", f"{present} of {n} working days", cfg.STATUS_COLORS["Present"]),
        ("Missing check-in", int((work["issue"] == cfg.ISSUE_CHECKIN).sum()), "days", cfg.STATUS_COLORS["Incomplete"]),
        ("Missing check-out", int((work["issue"] == cfg.ISSUE_CHECKOUT).sum()), "days", "#FB923C"),
        ("Absent", int((work["issue"] == cfg.ISSUE_ABSENT).sum()), "no punches", cfg.STATUS_COLORS["Absent"]),
        ("Leave days", int((d["expected"] == "Leave").sum()), "approved", cfg.STATUS_COLORS["Leave"]),
        ("Late / early", f"{int(work['late'].sum())} / {int(work['early_leave'].sum())}", "check-ins / check-outs", "#64748B"),
    ])
    st.write("")
    t1, t2 = st.columns(2)
    t1.metric("Average check-in", logic.fmt_min(work["ci_min"].mean()) or "-")
    t2.metric("Average check-out", logic.fmt_min(work["co_min"].mean()) or "-")

    st.subheader("Attendance calendar")
    h = d.copy()
    h["cell"] = logic.cell_label(h)
    h["week"] = h["date"] - pd.to_timedelta(h["date"].dt.dayofweek, unit="D")
    h["day"] = h["date"].dt.day_name().str[:3]
    domain = list(cfg.CELL_COLORS)
    chart = (
        alt.Chart(h)
        .mark_rect(cornerRadius=4, stroke="white", strokeWidth=2)
        .encode(
            x=alt.X("week:T", title="Week starting", axis=alt.Axis(format="%d %b", tickCount="week")),
            y=alt.Y("day:O", sort=["Mon", "Tue", "Wed", "Thu", "Fri"], title=None),
            color=alt.Color("cell:N", title=None, scale=alt.Scale(domain=domain, range=[cfg.CELL_COLORS[k] for k in domain])),
            tooltip=[alt.Tooltip("date:T", format="%a %d %b"), "cell:N", "check_in:N", "check_out:N"],
        )
        .properties(height=190)
    )
    st.altair_chart(chart, **ui.WIDE)

    st.subheader("Daily records")
    rec = d.sort_values("date", ascending=False)[
        ["date", "weekday", "expected", "check_in", "check_out", "hours", "status", "issue", "final_status"]
    ].copy()
    rec["date"] = rec["date"].dt.strftime("%d %b %Y")
    rec.columns = ["Date", "Day", "Expected", "Check-in", "Check-out", "Hours", "Status", "Issue", "After follow-up"]
    rec["Hours"] = rec["Hours"].map(lambda h: "" if pd.isna(h) else f"{h:.1f} h")
    st.dataframe(ui.style_status(rec, ["Status", "After follow-up"]), hide_index=True, **ui.WIDE, height=420)

    st.subheader("Exception history")
    e = exc[exc["mentor_id"] == mid].sort_values("date", ascending=False)
    if days:
        e = e[e["date"] > as_of - pd.Timedelta(days=days)]
    if e.empty:
        st.success("No exceptions in this period.")
    else:
        show = e[["date", "exception_type", "reason", "proof", "status", "level_label", "closed_at"]].copy()
        show["date"] = show["date"].dt.strftime("%d %b %Y")
        show.columns = ["Date", "Type", "Reason", "Proof", "Status", "Level", "Closed at"]
        st.dataframe(show, hide_index=True, **ui.WIDE)
