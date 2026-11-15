"""Report builders and CSV / Excel exporters."""
from __future__ import annotations

from io import BytesIO

import pandas as pd

from src import logic


def daily_report(att: pd.DataFrame, start, end) -> pd.DataFrame:
    d = att[(att["date"] >= start) & (att["date"] <= end)].copy()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    d["late"] = d["late"].map({True: "Yes", False: ""})
    d["early_leave"] = d["early_leave"].map({True: "Yes", False: ""})
    cols = [
        "date", "weekday", "mentor_id", "mentor_name", "track", "lead", "expected",
        "check_in", "check_out", "hours", "status", "issue", "late", "early_leave", "final_status",
    ]
    return d[cols].rename(columns={"final_status": "final_status_after_followup"})


def summary_report(att: pd.DataFrame, start, end) -> pd.DataFrame:
    return logic.mentor_summary(att, start, end)


def exceptions_report(exc_enriched: pd.DataFrame, start, end) -> pd.DataFrame:
    e = exc_enriched[(exc_enriched["date"] >= start) & (exc_enriched["date"] <= end)].copy()
    e["date"] = e["date"].dt.strftime("%Y-%m-%d")
    cols = [
        "exception_id", "date", "mentor_id", "mentor_name", "lead", "exception_type", "detected_at",
        "contacted_at", "reason", "proof", "status", "level_label", "sla", "closed_by", "closed_at",
        "close_hours", "remarks",
    ]
    return e[cols].sort_values(["date", "mentor_id"], ascending=[False, True])


def to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel(frames: dict) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in frames.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 38)
    return buf.getvalue()
