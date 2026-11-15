"""Workflow & SOP page: documents the process the prototype implements."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config as cfg
from src import ui

FLOW = """
digraph G {
  rankdir=LR; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, fillcolor="#EFF6FF", color="#93C5FD"];
  roster [label="Evening before:\\nconfirm roster\\n(leave / holiday)"];
  remind1 [label="09:00\\ncheck-in reminder"];
  sweep1 [label="09:30\\nsweep: who has\\nno check-in?"];
  remind2 [label="16:15\\ncheck-out reminder"];
  sweep2 [label="17:30\\nsweep: who has\\nno check-out?"];
  log [label="Log exception\\n(auto-detected)", fillcolor="#FEF3C7", color="#F59E0B"];
  l1 [label="L1: intern\\ncalls / messages", fillcolor="#FEF3C7", color="#F59E0B"];
  l2 [label="L2: lead\\n(next morning)", fillcolor="#FFEDD5", color="#FB923C"];
  l3 [label="L3: program manager\\n(2+ days / repeat)", fillcolor="#FEE2E2", color="#DC2626"];
  close [label="Close with reason\\n+ proof + final status", fillcolor="#DCFCE7", color="#16A34A"];
  report [label="Daily summary\\n+ weekly review"];
  roster -> remind1 -> sweep1 -> log; remind2 -> sweep2 -> log;
  log -> l1 -> l2 -> l3; l1 -> close; l2 -> close; l3 -> close; close -> report;
}
"""


def render(ctx: dict) -> None:
    ui.page_header("Workflow & SOP", "The operating process this prototype supports")

    st.graphviz_chart(FLOW, **ui.WIDE)

    st.subheader("Daily checkpoints")
    st.dataframe(pd.DataFrame([
        ("T-1 evening", "Confirm tomorrow's roster against approved leave and holidays", "Ops intern"),
        ("09:00", "Send check-in reminder to mentors not yet punched", "Ops intern"),
        ("09:30", "Sweep 1: compare biometric log with roster, log check-in exceptions, start follow-up", "Ops intern"),
        ("16:15", "Send check-out reminder to all mentors", "Ops intern"),
        ("17:30", "Sweep 2: log check-out exceptions, start follow-up", "Ops intern"),
        ("Next day 11:00", "Closure deadline: every exception has a reason, proof and final status", "Ops intern / lead"),
        ("End of day", "Send daily summary: present, exceptions, open items", "Ops intern"),
        ("Weekly", "Review repeat misses per mentor; agree actions with leads", "Program manager"),
    ], columns=["When", "What", "Owner"]), hide_index=True, **ui.WIDE)

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.subheader("Status rules used by the app")
        st.markdown(
            f"- **Present:** check-in and check-out both recorded.\n"
            f"- **Incomplete:** only one of the two punches (missing check-in or missing check-out).\n"
            f"- **Absent:** working day, no punches, no approved leave.\n"
            f"- **Leave / Holiday:** taken from the roster; no punches expected.\n"
            f"- **Late:** check-in after {cfg.CHECKIN_TARGET} + {cfg.CHECKIN_GRACE_MIN} min. "
            f"**Early leave:** check-out before {cfg.EARLY_LEAVE_BEFORE}. These are flags, not exceptions."
        )
        st.subheader("Closure rules")
        st.markdown(
            "An exception is closed only with a **reason**, **proof** and a **final status**:\n"
            "- **Regularized:** mentor was present; record corrected.\n"
            "- **Leave:** approved leave confirmed.\n"
            "- **Absent:** absence confirmed.\n"
            "- **Unresolved:** mentor unreachable or disputed; stays with the program manager."
        )
    with c2:
        st.subheader("Data maintained")
        st.markdown(
            "- `mentors.csv` - ID, name, track, lead, phone, shift\n"
            "- `roster.csv` - date, mentor, expected (Working / Leave / Holiday)\n"
            "- `punches.csv` - date, mentor, check-in, check-out (from the biometric export)\n"
            "- `exceptions.csv` - type, detected / contacted / closed times, reason, proof, status, remarks"
        )
        st.subheader("Escalation")
        st.markdown(
            "- **L1** on detection: intern follows up within about an hour.\n"
            "- **L2** if still open the next morning: lead confirms.\n"
            f"- **L3** if open 2+ days, Unresolved, or {cfg.REPEAT_THRESHOLD}+ misses in 7 days: program manager."
        )
