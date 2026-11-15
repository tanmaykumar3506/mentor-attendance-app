"""Exceptions & Alerts: alerts, editable exception tracker, reminder/escalation messages."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import config as cfg
from src import logic, ui


def render(ctx: dict) -> None:
    att, exc, exc_raw, as_of = ctx["att"], ctx["exc"], ctx["exc_raw"], ctx["as_of"]
    ui.page_header("Exceptions & Alerts", f"Follow-up and closure tracker - as of {as_of:%d %b %Y}, end-of-day review")

    tab1, tab2, tab3 = st.tabs(["Alerts", "Exception tracker", "Reminder messages"])

    # ------------------------------------------------------------------ alerts
    with tab1:
        alerts = logic.build_alerts(att, exc, as_of)
        if not alerts:
            st.success("No alerts. All clear.")
        for a in alerts:
            ui.alert(a["severity"], a["title"], a["detail"])
        st.markdown("**Escalation ladder**")
        st.markdown(
            "- **L1 - Ops follow-up:** exception detected today; intern calls or messages the mentor.\n"
            "- **L2 - Lead:** still open the next morning (past the 11:00 closure deadline); lead is asked to confirm.\n"
            f"- **L3 - Program manager:** open for 2+ days, marked Unresolved, or {cfg.REPEAT_THRESHOLD}+ misses in 7 days."
        )

    # ----------------------------------------------------------------- tracker
    with tab2:
        flash = st.session_state.pop("exc_flash", None)
        if flash:
            st.success(flash) if "not closed" not in flash else st.warning(flash)
        c = st.columns(4)
        c[0].metric("Open", int((exc["status"] == "Open").sum()))
        c[1].metric("Unresolved", int((exc["status"] == "Unresolved").sum()))
        c[2].metric("Overdue", int((exc["sla"] == "Overdue").sum()))
        c[3].metric("Closed (all time)", int(exc["status"].isin(cfg.CLOSED_STATUSES).sum()))

        f1, f2, f3 = st.columns(3)
        show_status = f1.multiselect("Status", cfg.EXCEPTION_STATUSES, default=cfg.NEEDS_ACTION_STATUSES, key="exc_status")
        show_type = f2.multiselect("Type", [cfg.ISSUE_CHECKIN, cfg.ISSUE_CHECKOUT, cfg.ISSUE_ABSENT], key="exc_type")
        show_mentor = f3.multiselect("Mentor", sorted(exc["mentor_name"].dropna().unique()), key="exc_mentor")

        view = exc.copy()
        if show_status:
            view = view[view["status"].isin(show_status)]
        if show_type:
            view = view[view["exception_type"].isin(show_type)]
        if show_mentor:
            view = view[view["mentor_name"].isin(show_mentor)]

        if view.empty:
            st.success("Nothing to show with these filters.")
        else:
            st.caption("Edit reason, proof, status or remarks directly in the table, then press Save. A reason is required to close.")
            table = view[[
                "exception_id", "date", "mentor_name", "exception_type", "level_label", "sla",
                "contacted_at", "reason", "proof", "status", "remarks",
            ]].copy()
            table["date"] = table["date"].dt.strftime("%d %b %Y")
            edited = st.data_editor(
                table,
                hide_index=True,
                **ui.WIDE,
                height=min(60 + 36 * len(table), 520),
                disabled=["exception_id", "date", "mentor_name", "exception_type", "level_label", "sla"],
                column_config={
                    "exception_id": st.column_config.TextColumn("ID", width="small"),
                    "date": "Date",
                    "mentor_name": "Mentor",
                    "exception_type": "Type",
                    "level_label": "Escalation",
                    "sla": "SLA",
                    "contacted_at": st.column_config.TextColumn("Contacted at", help="YYYY-MM-DD HH:MM"),
                    "reason": st.column_config.SelectboxColumn("Reason", options=[""] + cfg.REASONS),
                    "proof": st.column_config.TextColumn("Proof"),
                    "status": st.column_config.SelectboxColumn("Status", options=cfg.EXCEPTION_STATUSES, required=True),
                    "remarks": st.column_config.TextColumn("Remarks"),
                },
                key="exc_editor_" + str(abs(hash(tuple(table["exception_id"]))) % 10**8),
            )
            if st.button("Save changes", type="primary"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                updated, saved, skipped = logic.apply_exception_edits(exc_raw, edited, now)
                logic.save_exceptions(updated)
                msg = f"Saved {saved} row(s)."
                if skipped:
                    msg += f" {len(skipped)} row(s) were not closed because no reason was given: {', '.join(skipped)}."
                st.session_state["exc_flash"] = msg
                st.rerun()

    # ---------------------------------------------------------------- messages
    with tab3:
        pending = exc[exc["status"].isin(cfg.NEEDS_ACTION_STATUSES)]
        if pending.empty:
            st.success("No pending exceptions, so no reminders to send.")
        else:
            labels = [
                f"{r.exception_id} - {r.mentor_name} - {r.exception_type} - {r.level_label}"
                for r in pending.itertuples()
            ]
            pick = st.selectbox("Pending exception", labels, key="msg_pick")
            r = pending.iloc[labels.index(pick)]
            st.markdown("**1. Message to the mentor (L1)**")
            st.code(logic.reminder_message(r.mentor_name, r.date, r.exception_type), language=None)
            if r.level >= 2:
                st.markdown("**2. Escalation to the lead (L2)**")
                st.code(logic.escalation_message(r.lead, r.mentor_name, r.date, r.exception_type, r.level_label), language=None)
            if r.level >= 3:
                st.markdown("**3. Note for the program manager (L3)**")
                st.code(
                    f"Attendance exception unresolved: {r.mentor_name} ({r.exception_type}, {r.date:%d %b %Y}). "
                    f"Open for {r.age_days} day(s); {r.misses_7d} miss(es) in the last 7 days. "
                    "Mentor and lead have been contacted. Please advise on closure.",
                    language=None,
                )
            st.caption("Copy the text and send it through your usual channel (WhatsApp, Slack or email).")
            with st.expander(f"All {len(pending)} pending reminders in one block"):
                st.code(
                    "\n\n".join(
                        f"[{x.mentor_name} - {x.phone}]\n{logic.reminder_message(x.mentor_name, x.date, x.exception_type)}"
                        for x in pending.itertuples()
                    ),
                    language=None,
                )
