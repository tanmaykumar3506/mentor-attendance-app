"""Mentor Attendance Control Room - Streamlit app entry point.

Run with:  streamlit run app.py
"""
import pandas as pd
import streamlit as st

import config as cfg
from src import data_generator, logic, ui
from views import dashboard, daily, exceptions, mentor_history, reports, sop

st.set_page_config(page_title="Mentor Attendance Control Room", page_icon=":material/fact_check:", layout="wide")
ui.inject_css()

PAGES = {
    "Dashboard": dashboard,
    "Daily Attendance": daily,
    "Mentor History": mentor_history,
    "Exceptions & Alerts": exceptions,
    "Reports & Data": reports,
    "Workflow & SOP": sop,
}

data = logic.load_all()
att = data["att"]

with st.sidebar:
    st.markdown("### Attendance Control Room")
    st.caption(f"{cfg.UNIVERSITY} - 20 mentors")
    page = st.radio("Navigate", list(PAGES), label_visibility="collapsed", key="nav")
    st.divider()
    dates = sorted(att["date"].unique(), reverse=True)
    as_of = pd.Timestamp(
        st.selectbox(
            "Review date (as of)", dates,
            format_func=lambda d: pd.Timestamp(d).strftime("%a, %d %b %Y"), key="as_of",
        )
    )
    st.divider()
    if st.button("Reset sample data", help="Regenerates the demo data and discards your changes"):
        data_generator.generate_and_save()
        for k in list(st.session_state.keys()):
            if k not in ("nav",):
                del st.session_state[k]
        st.rerun()
    st.caption("Sample data is fictional and for demonstration only.")

ctx = {
    "mentors": data["mentors"],
    "roster": data["roster"],
    "punches": data["punches"],
    "att": att,
    "exc_raw": data["exc_raw"],
    "exc": logic.enrich_exceptions(data["exc_raw"], as_of, data["mentors"], att),
    "as_of": as_of,
}
with st.sidebar:
    _open = ctx["exc"][ctx["exc"]["status"].isin(cfg.NEEDS_ACTION_STATUSES)]
    st.markdown(f"**{len(_open)}** open exception(s) - **{int((_open['sla'] == 'Overdue').sum())}** overdue")

PAGES[page].render(ctx)
