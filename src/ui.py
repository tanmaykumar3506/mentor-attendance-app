"""Small UI helpers: CSS, KPI cards, alert boxes, table styling."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config as cfg

CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.page-title {font-size: 1.9rem; font-weight: 700; margin-bottom: 0.1rem; color: #0F172A;}
.page-sub {color: #64748B; margin-bottom: 1.2rem; font-size: 0.95rem;}
.kpi {background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px 16px;
      box-shadow: 0 1px 2px rgba(15,23,42,0.04); height: 100%; border-top: 4px solid var(--accent);}
.kpi .label {font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748B; font-weight: 600;}
.kpi .value {font-size: 1.9rem; font-weight: 700; color: #0F172A; line-height: 1.25;}
.kpi .sub {font-size: 0.8rem; color: #64748B;}
.alert {border-radius: 10px; padding: 10px 14px; margin-bottom: 8px; border-left: 5px solid var(--c);
        background: var(--bg);}
.alert .t {font-weight: 600; color: #0F172A; font-size: 0.93rem;}
.alert .d {color: #475569; font-size: 0.85rem; margin-top: 2px;}
.sev {display:inline-block; font-size: 0.68rem; font-weight: 700; padding: 1px 8px; border-radius: 999px;
      color: #fff; background: var(--c); margin-right: 8px; vertical-align: middle;}
section[data-testid="stSidebar"] {background: #0F172A;}
section[data-testid="stSidebar"] * {color: #E2E8F0;}
section[data-testid="stSidebar"] .stRadio label p {font-size: 0.95rem;}
</style>
"""

SEVERITY = {
    "High": ("#DC2626", "#FEF2F2"),
    "Medium": ("#D97706", "#FFFBEB"),
    "Info": ("#2563EB", "#EFF6FF"),
}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="page-title">{title}</div><div class="page-sub">{subtitle}</div>', unsafe_allow_html=True)


def kpi_row(items: list[tuple]) -> None:
    """items: (label, value, sub, accent_color)"""
    cols = st.columns(len(items))
    for col, it in zip(cols, items):
        label, value, sub = it[0], it[1], it[2]
        accent = it[3] if len(it) > 3 else "#2563EB"
        col.markdown(
            f'<div class="kpi" style="--accent:{accent}"><div class="label">{label}</div>'
            f'<div class="value">{value}</div><div class="sub">{sub}</div></div>',
            unsafe_allow_html=True,
        )


def alert(severity: str, title: str, detail: str = "") -> None:
    c, bg = SEVERITY.get(severity, SEVERITY["Info"])
    st.markdown(
        f'<div class="alert" style="--c:{c};--bg:{bg}"><div class="t"><span class="sev">{severity.upper()}</span>'
        f'{title}</div><div class="d">{detail}</div></div>',
        unsafe_allow_html=True,
    )


def _status_css(v: str) -> str:
    base = str(v).split(" (")[0]
    if base in cfg.STATUS_BG:
        return f"background-color:{cfg.STATUS_BG[base]};color:{cfg.STATUS_COLORS[base]};font-weight:600"
    if base == "Pending follow-up":
        return "background-color:#FEF3C7;color:#B45309;font-weight:600"
    return ""


def style_status(df: pd.DataFrame, cols: list[str]):
    return style_map(df.style, _status_css, subset=cols)


CELL_CODES = {
    "Present": "P", "No check-in": "IN", "No check-out": "OUT",
    "Absent": "A", "Leave": "L", "Holiday": "H",
}
_CODE_STYLE = {
    "P": "background-color:#DCFCE7;color:#166534",
    "IN": "background-color:#FEF3C7;color:#92400E;font-weight:700",
    "OUT": "background-color:#FFEDD5;color:#9A3412;font-weight:700",
    "A": "background-color:#FEE2E2;color:#991B1B;font-weight:700",
    "L": "background-color:#DBEAFE;color:#1E40AF",
    "H": "background-color:#E2E8F0;color:#475569",
}


def style_codes(df: pd.DataFrame):
    return style_map(df.style, lambda v: _CODE_STYLE.get(v, ""))


def level_css(v: str) -> str:
    if str(v).startswith("L3"):
        return "background-color:#FEE2E2;color:#991B1B;font-weight:700"
    if str(v).startswith("L2"):
        return "background-color:#FFEDD5;color:#9A3412;font-weight:600"
    if str(v).startswith("L1"):
        return "background-color:#FEF3C7;color:#92400E"
    return "color:#64748B"


def sla_css(v: str) -> str:
    if v == "Overdue":
        return "background-color:#FEE2E2;color:#991B1B;font-weight:700"
    if v == "Due next morning":
        return "background-color:#FEF3C7;color:#92400E"
    return "color:#64748B"


# ---------------------------------------------------------------- version compatibility
# Newer Streamlit uses width="stretch"; older releases only know use_container_width=True.
# Newer pandas has Styler.map; pandas 2.0 only has Styler.applymap.
import inspect as _inspect

WIDE = {"width": "stretch"} if "width" in _inspect.signature(st.altair_chart).parameters else {"use_container_width": True}


def style_map(styler, func, **kwargs):
    """Cell-wise styling on any supported pandas version."""
    fn = styler.map if hasattr(styler, "map") else styler.applymap
    return fn(func, **kwargs)
