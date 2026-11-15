"""Date-wise attendance records: single day, date range, and mentor x date matrix."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import logic, ui


def _board(df: pd.DataFrame) -> pd.DataFrame:
    out = df[[
        "date", "weekday", "mentor_id", "mentor_name", "track", "lead", "expected",
        "check_in", "check_out", "hours", "status", "issue", "final_status",
    ]].copy()
    out["date"] = out["date"].dt.strftime("%d %b %Y")
    out["flags"] = [
        ", ".join(x for x in [("Late" if l else ""), ("Early leave" if e else "")] if x)
        for l, e in zip(df["late"], df["early_leave"])
    ]
    out.columns = [
        "Date", "Day", "ID", "Mentor", "Track", "Lead", "Expected", "Check-in", "Check-out",
        "Hours", "Status", "Issue", "After follow-up", "Flags",
    ]
    out["Hours"] = out["Hours"].map(lambda h: "" if pd.isna(h) else f"{h:.1f} h")
    return out


def render(ctx: dict) -> None:
    att, as_of = ctx["att"], ctx["as_of"]
    ui.page_header("Daily Attendance", "Date-wise records for all mentors, with filters and a mentor x date matrix")

    tab1, tab2, tab3 = st.tabs(["Single day", "Date range", "Mentor x date matrix"])

    with tab1:
        dates = sorted(att["date"].unique(), reverse=True)
        pick = st.selectbox(
            "Date", dates, index=dates.index(as_of.to_datetime64()) if as_of.to_datetime64() in dates else 0,
            format_func=lambda d: pd.Timestamp(d).strftime("%a, %d %b %Y"), key="daily_single",
        )
        d = att[att["date"] == pd.Timestamp(pick)]
        counts = d["status"].value_counts()
        c = st.columns(5)
        for col, s in zip(c, ["Present", "Incomplete", "Absent", "Leave", "Holiday"]):
            col.metric(s, int(counts.get(s, 0)))
        status_f = st.multiselect(
            "Filter by status", ["Present", "Incomplete", "Absent", "Leave", "Holiday"], key="daily_status_f"
        )
        if status_f:
            d = d[d["status"].isin(status_f)]
        st.dataframe(ui.style_status(_board(d), ["Status", "After follow-up"]), hide_index=True, **ui.WIDE, height=760)

    with tab2:
        dates_asc = sorted(att["date"].unique())
        c1, c2 = st.columns(2)
        start = c1.selectbox("From", dates_asc, index=max(len(dates_asc) - 10, 0),
                             format_func=lambda d: pd.Timestamp(d).strftime("%a, %d %b %Y"), key="rng_from")
        end = c2.selectbox("To", dates_asc, index=len(dates_asc) - 1,
                           format_func=lambda d: pd.Timestamp(d).strftime("%a, %d %b %Y"), key="rng_to")
        f1, f2, f3 = st.columns(3)
        mentors = f1.multiselect("Mentor", sorted(att["mentor_name"].unique()), key="rng_mentor")
        statuses = f2.multiselect("Status", ["Present", "Incomplete", "Absent", "Leave", "Holiday"], key="rng_status")
        leads = f3.multiselect("Lead", sorted(att["lead"].unique()), key="rng_lead")
        r = att[(att["date"] >= pd.Timestamp(start)) & (att["date"] <= pd.Timestamp(end))]
        if mentors:
            r = r[r["mentor_name"].isin(mentors)]
        if statuses:
            r = r[r["status"].isin(statuses)]
        if leads:
            r = r[r["lead"].isin(leads)]
        st.caption(f"{len(r)} records")
        st.dataframe(
            ui.style_status(_board(r.sort_values(["date", "mentor_id"], ascending=[False, True])), ["Status", "After follow-up"]),
            hide_index=True, **ui.WIDE, height=560,
        )

    with tab3:
        n = st.slider("Number of recent days", 5, 30, 15, key="matrix_days")
        recent_dates = sorted(att[att["date"] <= as_of]["date"].unique())[-n:]
        m = att[att["date"].isin(recent_dates)].copy()
        m["code"] = logic.cell_label(m).map(ui.CELL_CODES)
        pv = m.pivot(index="mentor_name", columns="date", values="code")
        pv.columns = [pd.Timestamp(c).strftime("%d %b") for c in pv.columns]
        st.caption("P present - IN check-in missing - OUT check-out missing - A absent - L leave - H holiday")
        st.dataframe(ui.style_codes(pv), **ui.WIDE, height=760)
