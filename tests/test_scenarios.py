"""Scenario tests for the attendance logic and the Streamlit UI.

Run:  python -m pytest tests -v
Each scenario uses small, hand-built data so the expected result is known in advance.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as cfg  # noqa: E402
from src import logic, reports  # noqa: E402

THU, FRI, MON, TUE = "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"
NORMAL = ("08:55", "16:40")


# --------------------------------------------------------------------------- helpers
def make_mentors() -> pd.DataFrame:
    return pd.DataFrame({
        "mentor_id": [f"M{i:02d}" for i in range(1, 21)],
        "mentor_name": [f"Mentor {i:02d}" for i in range(1, 21)],
        "track": "DSA",
        "lead": ["Lead A"] * 10 + ["Lead B"] * 10,
        "phone": [f"+91 90000 {i:05d}" for i in range(1, 21)],
        "shift": "09:00 - 16:30",
    })


def make_world(dates, punches=None, expected=None):
    """punches: {(date, mid): (check_in, check_out) | None}; missing keys get NORMAL; None = no row.
    expected: {(date, mid): 'Leave' | 'Holiday'}."""
    punches, expected = punches or {}, expected or {}
    mentors = make_mentors()
    r_rows, p_rows = [], []
    for d in dates:
        for mid in mentors["mentor_id"]:
            exp = expected.get((d, mid), "Working")
            r_rows.append((d, mid, exp))
            if exp != "Working":
                continue
            spec = punches.get((d, mid), NORMAL)
            if spec is not None:
                p_rows.append((d, mid, spec[0], spec[1]))
    roster = pd.DataFrame(r_rows, columns=["date", "mentor_id", "expected"])
    pun = pd.DataFrame(p_rows, columns=["date", "mentor_id", "check_in", "check_out"])
    for df in (roster, pun):
        df["date"] = pd.to_datetime(df["date"])
    att = logic.build_attendance(mentors, roster, pun)
    exc = pd.DataFrame({c: [] for c in logic.EXC_COLS})
    exc["date"] = pd.to_datetime(exc["date"])
    exc, _ = logic.sync_exceptions(att, exc)
    att = logic.apply_closure(att, exc)
    return mentors, roster, pun, att, exc


def row(att, d, mid):
    return att[(att["date"] == pd.Timestamp(d)) & (att["mentor_id"] == mid)].iloc[0]


# ------------------------------------------------------------ scenario 1: normal day
def test_1_normal_check_in_and_check_out():
    *_, att, exc = make_world([TUE])
    r = row(att, TUE, "M01")
    assert r.status == "Present" and r.issue == ""
    assert not r.late and not r.early_leave
    assert r.hours == pytest.approx(7.75)
    assert len(exc) == 0, "a fully punched day must create no exceptions"
    assert (att["status"] == "Present").all()


# ------------------------------------------------- scenario 2: forgets to check in
def test_2_forgot_check_in():
    mentors, _, _, att, exc = make_world([TUE], {(TUE, "M02"): ("", "16:41")})
    r = row(att, TUE, "M02")
    assert r.status == "Incomplete" and r.issue == cfg.ISSUE_CHECKIN
    assert r.final_status == "Pending follow-up"
    assert len(exc) == 1
    e = exc.iloc[0]
    assert e.exception_id == f"{TUE}_M02" and e.exception_type == cfg.ISSUE_CHECKIN and e.status == "Open"
    assert e.detected_at == f"{TUE} 09:30"
    assert "no biometric check-in" in logic.reminder_message("Mentor 02", TUE, e.exception_type)


# ------------------------------------------------ scenario 3: forgets to check out
def test_3_forgot_check_out():
    *_, att, exc = make_world([TUE], {(TUE, "M03"): ("08:58", "")})
    r = row(att, TUE, "M03")
    assert r.status == "Incomplete" and r.issue == cfg.ISSUE_CHECKOUT
    e = exc.iloc[0]
    assert e.exception_type == cfg.ISSUE_CHECKOUT and e.detected_at == f"{TUE} 17:30"
    assert "no biometric check-out" in logic.reminder_message("Mentor 03", TUE, e.exception_type)


# ------------------------------------------------------- scenario 4: absent all day
def test_4_absent_no_punches():
    *_, att, exc = make_world([TUE], {(TUE, "M04"): None})
    r = row(att, TUE, "M04")
    assert r.status == "Absent" and r.issue == cfg.ISSUE_ABSENT
    assert exc.iloc[0].exception_type == cfg.ISSUE_ABSENT


def test_4b_approved_leave_and_holiday_are_not_exceptions():
    *_, att, exc = make_world(
        [TUE], {}, {(TUE, "M05"): "Leave", (TUE, "M06"): "Holiday"}
    )
    assert row(att, TUE, "M05").status == "Leave" and row(att, TUE, "M05").issue == ""
    assert row(att, TUE, "M06").status == "Holiday"
    assert len(exc) == 0


# ------------------------------------------------- scenario 5: incomplete attendance
def test_5_incomplete_counts_both_kinds_and_summary_ties_out():
    *_, att, exc = make_world(
        [MON, TUE], {(MON, "M02"): ("", "16:40"), (TUE, "M02"): ("08:50", ""), (TUE, "M03"): ("08:50", "")}
    )
    s = logic.mentor_summary(att, att["date"].min(), att["date"].max()).set_index("mentor_id")
    assert s.loc["M02", "missing_check_in"] == 1 and s.loc["M02", "missing_check_out"] == 1
    assert s.loc["M02", "present"] == 0 and s.loc["M02", "punch_compliance_pct"] == 0.0
    assert s.loc["M03", "missing_check_out"] == 1 and s.loc["M03", "punch_compliance_pct"] == 50.0
    assert s.loc["M01", "punch_compliance_pct"] == 100.0
    assert (att["status"] == "Incomplete").sum() == 3 == len(exc)


# ----------------------------------- scenario 6: several mentors missing on one day
def test_6_multiple_mentors_same_day():
    specs = {
        (TUE, "M02"): ("", "16:41"),   # no check-in
        (TUE, "M07"): ("", "16:39"),   # no check-in
        (TUE, "M03"): ("08:58", ""),   # no check-out
        (TUE, "M08"): ("08:51", ""),   # no check-out
        (TUE, "M04"): None,            # absent
    }
    mentors, _, _, att, exc = make_world([TUE], specs, {(TUE, "M05"): "Leave"})
    day = att[att["date"] == pd.Timestamp(TUE)]
    assert (day["status"] == "Present").sum() == 14
    assert (day["status"] == "Incomplete").sum() == 4
    assert (day["status"] == "Absent").sum() == 1 and (day["status"] == "Leave").sum() == 1
    assert len(exc) == 5 and exc["exception_id"].is_unique
    e = logic.enrich_exceptions(exc, pd.Timestamp(TUE), mentors, att)
    assert (e["level"] == 1).all() and (e["sla"] == "Due next morning").all()
    alerts = logic.build_alerts(att, e, pd.Timestamp(TUE))
    titles = " | ".join(a["title"] for a in alerts)
    assert "2 mentor(s) with missing check-in today" in titles
    assert "2 mentor(s) with missing check-out today" in titles
    assert "1 mentor(s) with no punches today" in titles
    q = logic.action_queue(e)
    assert len(q) == 5 and set(q["Phone"]) <= set(mentors["phone"])
    text = logic.daily_summary_text(att, e, pd.Timestamp(TUE))
    assert "Present: 14" in text and "Incomplete: 4" in text and "Absent: 1" in text


# ------------------------------------------------------------------- flags and edges
def test_late_and_early_are_flags_not_exceptions():
    *_, att, exc = make_world([TUE], {(TUE, "M01"): ("09:16", "15:45"), (TUE, "M02"): ("09:15", "16:00")})
    assert row(att, TUE, "M01").late and row(att, TUE, "M01").early_leave
    assert not row(att, TUE, "M02").late and not row(att, TUE, "M02").early_leave  # boundaries are on time
    assert len(exc) == 0 and row(att, TUE, "M01").status == "Present"


def test_duplicate_punch_rows_do_not_duplicate_attendance():
    mentors, roster, pun, att, _ = make_world([TUE])
    dup = pd.concat([pun, pun.iloc[:3]], ignore_index=True)
    att2 = logic.build_attendance(mentors, roster, dup)
    assert len(att2) == 20 and att2["exception_id"].is_unique


def test_all_mentors_absent_day():
    specs = {(TUE, f"M{i:02d}"): None for i in range(1, 21)}
    *_, att, exc = make_world([TUE], specs)
    assert (att["status"] == "Absent").all() and len(exc) == 20


def test_exception_ageing_counts_working_days_not_calendar_days():
    """Friday exception reviewed Monday is ONE working day old (L2), not 3 days old (L3)."""
    mentors, _, _, att, exc = make_world([THU, FRI, MON], {(FRI, "M02"): ("", "16:40")})
    e = logic.enrich_exceptions(exc, pd.Timestamp(MON), mentors, att)
    r = e[e["mentor_id"] == "M02"].iloc[0]
    assert r.age_days == 1 and r.level == 2 and r.sla == "Overdue"


def test_escalation_ladder_l1_l2_l3_and_unresolved():
    mentors, _, _, att, exc = make_world([THU, FRI, MON, TUE], {(THU, "M02"): ("", "16:40")})
    lv = lambda d: logic.enrich_exceptions(exc, pd.Timestamp(d), mentors, att).query("mentor_id=='M02'").iloc[0].level
    assert [lv(THU), lv(FRI), lv(MON), lv(TUE)] == [1, 2, 3, 3]
    exc2 = exc.copy()
    exc2["status"] = "Unresolved"
    assert logic.enrich_exceptions(exc2, pd.Timestamp(THU), mentors, att).iloc[0].level == 3


def test_repeat_misses_escalate_to_l3():
    specs = {(d, "M09"): ("", "16:40") for d in (THU, FRI, MON)}
    mentors, _, _, att, exc = make_world([THU, FRI, MON], specs)
    e = logic.enrich_exceptions(exc, pd.Timestamp(MON), mentors, att)
    today = e[(e["mentor_id"] == "M09") & (e["date"] == pd.Timestamp(MON))].iloc[0]
    assert today.misses_7d == 3 and today.level == 3
    assert any("Repeat misses" in a["title"] for a in logic.build_alerts(att, e, pd.Timestamp(MON)))


def test_closed_exception_updates_final_status():
    mentors, _, _, att, exc = make_world([TUE], {(TUE, "M02"): ("", "16:40"), (TUE, "M04"): None})
    exc = exc.set_index("exception_id")
    exc.loc[f"{TUE}_M02", ["status", "reason"]] = ["Regularized", "Forgot to punch in"]
    exc.loc[f"{TUE}_M04", ["status", "reason"]] = ["Leave", "Sick leave not updated in roster"]
    att2 = logic.apply_closure(att, exc.reset_index())
    assert row(att2, TUE, "M02").final_status == "Present (regularized)"
    assert row(att2, TUE, "M04").final_status == "Leave (confirmed)"
    assert row(att2, TUE, "M02").status == "Incomplete", "raw biometric status must not be overwritten"


def test_exception_auto_resolves_when_missing_punch_arrives_later():
    mentors, roster, pun, att, exc = make_world([TUE], {(TUE, "M03"): ("08:58", "")})
    assert exc.iloc[0].status == "Open"
    fixed = pun.copy()
    fixed.loc[(fixed["mentor_id"] == "M03"), "check_out"] = "16:36"
    att2 = logic.build_attendance(mentors, roster, fixed)
    exc2, changed = logic.sync_exceptions(att2, exc)
    r = exc2[exc2["exception_id"] == f"{TUE}_M03"].iloc[0]
    assert changed == 1 and r.status == "Regularized" and r.closed_by == "System"
    assert "later biometric export" in r.reason.lower()


def test_exception_type_follows_the_data_when_punches_change():
    mentors, roster, pun, att, exc = make_world([TUE], {(TUE, "M03"): None})
    assert exc.iloc[0].exception_type == cfg.ISSUE_ABSENT
    partial = pd.concat([pun, pd.DataFrame([{"date": pd.Timestamp(TUE), "mentor_id": "M03", "check_in": "09:02", "check_out": ""}])])
    att2 = logic.build_attendance(mentors, roster, partial)
    exc2, _ = logic.sync_exceptions(att2, exc)
    assert exc2[exc2["exception_id"] == f"{TUE}_M03"].iloc[0].exception_type == cfg.ISSUE_CHECKOUT


def test_data_quality_flags():
    specs = {(TUE, "M01"): ("16:40", "08:55"), (TUE, "M02"): ("08:55", "08:55")}
    mentors, roster, pun, att, exc = make_world([TUE], specs, {(TUE, "M03"): "Leave"})
    assert row(att, TUE, "M01").dq_issue == "Check-out is not after check-in"
    assert row(att, TUE, "M02").dq_issue == "Check-out is not after check-in"
    pun2 = pd.concat([pun, pd.DataFrame([{"date": pd.Timestamp(TUE), "mentor_id": "M03", "check_in": "09:00", "check_out": "16:30"}])])
    att2 = logic.build_attendance(mentors, roster, pun2)
    assert row(att2, TUE, "M03").dq_issue == "Punched while on approved leave"
    assert row(att2, TUE, "M03").status == "Leave"
    e = logic.enrich_exceptions(exc, pd.Timestamp(TUE), mentors, att)
    assert any("data check" in a["title"] for a in logic.build_alerts(att, e, pd.Timestamp(TUE)))


# --------------------------------------------------------------- edit / close rules
def test_cannot_close_without_reason_but_can_with_one():
    mentors, _, _, att, exc = make_world([TUE], {(TUE, "M02"): ("", "16:40"), (TUE, "M03"): ("08:58", "")})
    e = logic.enrich_exceptions(exc, pd.Timestamp(TUE), mentors, att)
    t = e[["exception_id", "contacted_at", "reason", "proof", "status", "remarks"]].copy()
    t["status"] = "Regularized"
    t.loc[t["exception_id"] == f"{TUE}_M03", "reason"] = "Forgot to punch out"
    upd, saved, skipped = logic.apply_exception_edits(exc, t, f"{TUE} 17:50")
    assert saved == 1 and skipped == [f"{TUE}_M02"]
    u = upd.set_index("exception_id")
    assert u.loc[f"{TUE}_M03", "status"] == "Regularized" and u.loc[f"{TUE}_M03", "closed_at"] == f"{TUE} 17:50"
    assert u.loc[f"{TUE}_M02", "status"] == "Open"


# --------------------------------------------------------------------- import rules
def test_import_validation_cleans_and_rejects():
    mentors = make_mentors()
    good = pd.DataFrame({"date": [TUE, TUE], "mentor_id": ["M01", "M02"], "check_in": ["8:55", ""], "check_out": ["16:40", "16:41"]})
    clean, problems = logic.validate_import(good, mentors)
    assert problems == [] and clean.loc[0, "check_in"] == "08:55"
    bad = pd.DataFrame({
        "date": [TUE, "not-a-date", TUE, TUE, TUE],
        "mentor_id": ["M01", "M02", "M99", "M03", "M03"],
        "check_in": ["25:70", "09:00", "09:00", "17:00", "09:00"],
        "check_out": ["16:40", "16:40", "16:40", "09:00", "16:00"],
    })
    _, problems = logic.validate_import(bad, mentors)
    joined = " ".join(problems).lower()
    for needle in ("valid time", "date", "unknown mentor", "after check-in", "duplicate"):
        assert needle in joined, (needle, problems)


def test_import_upserts_and_adds_new_roster_dates():
    mentors, roster, pun, att, _ = make_world([TUE])
    new = pd.DataFrame({"date": pd.to_datetime([TUE, "2026-11-11"]), "mentor_id": ["M01", "M02"], "check_in": ["08:00", ""], "check_out": ["16:00", "16:41"]})
    merged, roster2 = logic.import_punches(pun, roster, mentors, new)
    assert len(merged) == len(pun) + 1                         # M01/Tue replaced, M02/Wed added
    assert merged[(merged["mentor_id"] == "M01") & (merged["date"] == pd.Timestamp(TUE))].iloc[0].check_in == "08:00"
    assert (roster2["date"] == pd.Timestamp("2026-11-11")).sum() == 20


# ---------------------------------------------------------------------- reports
def test_reports_contain_every_row_once_and_excel_opens():
    specs = {(TUE, "M02"): ("", "16:40"), (TUE, "M04"): None}
    mentors, _, _, att, exc = make_world([MON, TUE], specs)
    e = logic.enrich_exceptions(exc, pd.Timestamp(TUE), mentors, att)
    lo, hi = att["date"].min(), att["date"].max()
    daily = reports.daily_report(att, lo, hi)
    assert len(daily) == 40 and not daily.duplicated(["date", "mentor_id"]).any()
    frames = {"Daily attendance": daily, "Mentor summary": reports.summary_report(att, lo, hi), "Exception log": reports.exceptions_report(e, lo, hi)}
    from io import BytesIO
    sheets = pd.read_excel(BytesIO(reports.to_excel(frames)), sheet_name=None)
    assert {k: len(v) for k, v in sheets.items()} == {"Daily attendance": 40, "Mentor summary": 20, "Exception log": 2}


# ------------------------------------------------------------------------ UI tests
@pytest.fixture()
def scenario_app(tmp_path, monkeypatch):
    specs = {
        (TUE, "M02"): ("", "16:41"), (TUE, "M07"): ("", "16:39"),
        (TUE, "M03"): ("08:58", ""), (TUE, "M08"): ("08:51", ""),
        (TUE, "M04"): None, (TUE, "M06"): ("09:30", "16:45"),
    }
    mentors, roster, pun, att, exc = make_world([THU, FRI, MON, TUE], specs, {(TUE, "M05"): "Leave"})
    for name in ("MENTORS_CSV", "ROSTER_CSV", "PUNCHES_CSV", "EXCEPTIONS_CSV"):
        monkeypatch.setattr(cfg, name, tmp_path / f"{name.split('_')[0].lower()}.csv")
    mentors.to_csv(cfg.MENTORS_CSV, index=False)
    logic.save_roster(roster)
    logic.save_punches(pun)
    logic.save_exceptions(exc)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    assert not at.exception, at.exception
    return at


def kpis(at) -> dict:
    out = {}
    for m in at.markdown:
        for lab, val in re.findall(r'class="label">(.*?)</div><div class="value">(.*?)</div>', m.value):
            out[lab] = val
    return out


def page_text(at) -> str:
    return " ".join([m.value for m in at.markdown] + [h.value for h in at.subheader])


def test_ui_dashboard_numbers_match_the_scenario(scenario_app):
    k = kpis(scenario_app)
    assert k["Expected today"] == "19"
    assert k["Present"] == "14"
    assert k["Incomplete"] == "4"
    assert k["Absent"] == "1"
    assert k["On leave"] == "1"
    assert k["Late check-ins"] == "1"
    assert k["Open exceptions"] == "5"
    text = page_text(scenario_app)
    assert "2 mentor(s) with missing check-in today" in text and "Action queue" in text


def test_ui_every_page_renders_and_filters_do_not_crash(scenario_app):
    at = scenario_app
    for p in list(at.radio(key="nav").options):
        at.radio(key="nav").set_value(p).run()
        assert not at.exception, (p, at.exception)
    at.radio(key="nav").set_value("Exceptions & Alerts").run()
    at.multiselect(key="exc_status").set_value(["Regularized"]).run()
    assert not at.exception
    at.radio(key="nav").set_value("Mentor History").run()
    at.selectbox(key="hist_mentor").set_value("M09 - Mentor 09").run()
    assert not at.exception


def test_ui_review_date_switch_shows_weekend_aware_ageing(scenario_app):
    at = scenario_app
    at.selectbox(key="as_of").set_value(pd.Timestamp(MON).to_datetime64()).run()
    assert not at.exception
    assert kpis(at)["Expected today"] == "20"
