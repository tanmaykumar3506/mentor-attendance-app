"""Downloadable reports and biometric-export import."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import logic, reports, ui


def render(ctx: dict) -> None:
    att, exc, mentors = ctx["att"], ctx["exc"], ctx["mentors"]
    ui.page_header("Reports & Data", "Download attendance reports, or import the latest biometric export")

    tab1, tab2 = st.tabs(["Download reports", "Import biometric export"])

    with tab1:
        dates = sorted(att["date"].unique())
        fmt = lambda d: pd.Timestamp(d).strftime("%a, %d %b %Y")
        c1, c2 = st.columns(2)
        start = pd.Timestamp(c1.selectbox("From", dates, index=max(len(dates) - 10, 0), format_func=fmt, key="rep_from"))
        end = pd.Timestamp(c2.selectbox("To", dates, index=len(dates) - 1, format_func=fmt, key="rep_to"))
        if start > end:
            st.error("'From' must not be after 'To'.")
            return

        kind = st.radio("Report", ["Daily attendance", "Mentor summary", "Exception log"], horizontal=True, key="rep_kind")
        frames = {
            "Daily attendance": reports.daily_report(att, start, end),
            "Mentor summary": reports.summary_report(att, start, end),
            "Exception log": reports.exceptions_report(exc, start, end),
        }
        df = frames[kind]
        st.caption(f"{len(df)} rows - {start:%d %b %Y} to {end:%d %b %Y}")
        st.dataframe(df, hide_index=True, **ui.WIDE, height=420)

        stamp = f"{start:%Y%m%d}_{end:%Y%m%d}"
        b1, b2 = st.columns(2)
        b1.download_button(
            f"Download {kind} (CSV)", reports.to_csv(df),
            file_name=f"{kind.lower().replace(' ', '_')}_{stamp}.csv", mime="text/csv", **ui.WIDE,
        )
        b2.download_button(
            "Download full workbook (Excel, 3 sheets)", reports.to_excel(frames),
            file_name=f"attendance_report_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **ui.WIDE,
        )

    with tab2:
        st.markdown(
            "Upload the daily biometric export as CSV with columns **date, mentor_id, check_in, check_out** "
            "(dates as YYYY-MM-DD, times as HH:MM, leave a time empty if the mentor did not punch). "
            "Rows for the same date and mentor replace existing punches. New exceptions are detected automatically."
        )
        template = pd.DataFrame({
            "date": [pd.Timestamp(ctx["as_of"]).strftime("%Y-%m-%d")] * 2,
            "mentor_id": ["M01", "M02"], "check_in": ["08:52", ""], "check_out": ["16:41", "16:38"],
        })
        st.download_button("Download CSV template", reports.to_csv(template), file_name="punch_import_template.csv", mime="text/csv")
        up = st.file_uploader("Biometric export (CSV)", type="csv", key="punch_upload")
        if up is not None:
            try:
                new = pd.read_csv(up, dtype=str, keep_default_na=False)
            except Exception as ex:  # noqa: BLE001
                st.error(f"Could not read the file: {ex}")
                return
            missing = {"date", "mentor_id", "check_in", "check_out"} - set(new.columns)
            if missing:
                st.error(f"Missing column(s): {', '.join(sorted(missing))}")
                return
            new, problems = logic.validate_import(new, mentors)
            if problems:
                st.error("Please fix the file and upload it again:\n\n" + "\n".join(f"- {p}" for p in problems))
                return
            st.success(f"{len(new)} row(s) passed validation.")
            st.dataframe(new.head(50), hide_index=True, **ui.WIDE)
            if st.button(f"Import {len(new)} row(s)", type="primary"):
                merged, roster = logic.import_punches(ctx["punches"], ctx["roster"], mentors, new)
                logic.save_punches(merged)
                logic.save_roster(roster)
                st.success("Imported. The dashboard now reflects the new punches.")
                st.rerun()
