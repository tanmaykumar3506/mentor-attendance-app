"""Generates realistic, reproducible sample data for 20 mentors.

Run directly:  python -m src.data_generator
The app also calls this automatically on first launch if no data exists.

Sample data is fictional. It contains deliberate demo scenarios:
  * a biometric device fault day (4 mentors miss check-in),
  * a university holiday,
  * a repeat offender (M09) who triggers L3 escalation,
  * today's open exceptions, one overdue exception and one unresolved exception.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as cfg
from src import logic

NAMES = [
    "Aarav Sharma", "Priya Nair", "Rohan Mehta", "Ananya Iyer", "Karan Verma",
    "Sneha Reddy", "Vikram Singh", "Neha Gupta", "Arjun Patel", "Pooja Desai",
    "Rahul Khanna", "Divya Menon", "Siddharth Rao", "Meera Joshi", "Aditya Kulkarni",
    "Ishita Bansal", "Manish Yadav", "Kavya Pillai", "Harsh Agarwal", "Riya Chatterjee",
]
TRACKS = [
    "DSA", "Web Development", "Python", "Data Science", "Java",
    "Cloud & DevOps", "Aptitude", "Communication",
]
LEADS = ["Ritu Malhotra", "Sandeep Bhatt"]

DEFAULT_PROFILE = dict(miss_in=0.01, miss_out=0.02, absent=0.01, leave=0.03, late=0.05, early=0.03)
PROFILE_OVERRIDES = {
    "M03": dict(miss_out=0.14), "M08": dict(miss_out=0.12), "M12": dict(miss_out=0.16),
    "M17": dict(miss_out=0.15), "M05": dict(miss_in=0.10), "M14": dict(miss_in=0.09),
    "M09": dict(miss_in=0.08, miss_out=0.12, absent=0.03),
    "M06": dict(late=0.25), "M11": dict(late=0.22),
}

OUTCOMES = {
    cfg.ISSUE_CHECKIN: [
        ("Forgot to punch in", 0.45, "Regularized", "Lead confirmed presence"),
        ("Fingerprint not recognised", 0.35, "Regularized", "Lead confirmed presence + device log"),
        ("Network/power issue at device", 0.20, "Regularized", "IT device note"),
    ],
    cfg.ISSUE_CHECKOUT: [
        ("Forgot to punch out", 0.55, "Regularized", "Mentor message + lead confirmation"),
        ("Left early with approval", 0.25, "Regularized", "Approval email from lead"),
        ("Fingerprint not recognised", 0.20, "Regularized", "Lead confirmation"),
    ],
    cfg.ISSUE_ABSENT: [
        ("Uninformed absence", 0.50, "Absent", "No response - lead informed"),
        ("Sick leave not updated in roster", 0.30, "Leave", "Leave application"),
        ("Personal emergency", 0.20, "Leave", "Mentor message + lead approval"),
    ],
}


def _last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _working_days(end: date, n: int) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def _hhmm(m: int) -> str:
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def generate(end_date: date | None = None, n_days: int = 30, seed: int = 42):
    rng = np.random.default_rng(seed)
    end = _last_weekday(end_date or date.today())
    days = _working_days(end, n_days)

    mentors = pd.DataFrame({
        "mentor_id": [f"M{i:02d}" for i in range(1, 21)],
        "mentor_name": NAMES,
        "track": [TRACKS[i % len(TRACKS)] for i in range(20)],
        "lead": [LEADS[0] if i < 10 else LEADS[1] for i in range(20)],
        "phone": [f"+91 90000 {i:05d}" for i in range(1, 21)],
        "shift": "09:00 - 16:30",
    })
    ids = list(mentors["mentor_id"])
    prof = {m: {**DEFAULT_PROFILE, **PROFILE_OVERRIDES.get(m, {})} for m in ids}

    holiday = days[-16]
    device_day = days[-9]
    device_keys = {(device_day, m) for m in ("M02", "M07", "M13", "M18")}
    d1, d2, d4 = days[-1], days[-2], days[-4]

    forced: dict = {k: "no_in" for k in device_keys}
    forced.update({
        (d1, "M05"): "no_in", (d1, "M03"): "no_out", (d1, "M12"): "no_out", (d1, "M09"): "absent",
        (d2, "M17"): "no_out", (d2, "M09"): "no_out",
        (d4, "M14"): "no_in", (d4, "M09"): "no_in",
    })
    state_override = {(d2, "M17"): "open", (d4, "M14"): "unresolved"}

    roster_rows, punch_rows = [], []
    for d in days:
        for mid in ids:
            if d == holiday:
                roster_rows.append((d, mid, "Holiday"))
                continue
            f = forced.get((d, mid))
            p = prof[mid]
            if f is None and rng.random() < p["leave"]:
                roster_rows.append((d, mid, "Leave"))
                continue
            roster_rows.append((d, mid, "Working"))
            if f == "absent" or (f is None and rng.random() < p["absent"]):
                continue
            ci = int(np.clip(rng.normal(530, 8), 500, 553))
            co = int(np.clip(rng.normal(1000, 12), 990, 1035))
            if rng.random() < p["late"]:
                ci = int(rng.integers(556, 600))
            if rng.random() < p["early"]:
                co = int(rng.integers(900, 955))
            ci_s, co_s = _hhmm(ci), _hhmm(co)
            if f == "no_in":
                ci_s = ""
            elif f == "no_out":
                co_s = ""
            elif f is None:
                if rng.random() < p["miss_in"]:
                    ci_s = ""
                elif rng.random() < p["miss_out"]:
                    co_s = ""
            punch_rows.append((d, mid, ci_s, co_s))

    roster = pd.DataFrame(roster_rows, columns=["date", "mentor_id", "expected"])
    punches = pd.DataFrame(punch_rows, columns=["date", "mentor_id", "check_in", "check_out"])
    for df in (roster, punches):
        df["date"] = pd.to_datetime(df["date"])

    att = logic.build_attendance(mentors, roster, punches)
    det = att[att["issue"] != ""]

    next_day = {days[i]: days[i + 1] for i in range(len(days) - 1)}
    exc_rows = []
    for r in det.itertuples():
        d = r.date.date()
        key = (d, r.mentor_id)
        age = (end - d).days
        t = "17:30" if r.issue == cfg.ISSUE_CHECKOUT else "09:30"
        det_dt = pd.Timestamp(f"{d:%Y-%m-%d} {t}")
        row = {c: "" for c in logic.EXC_COLS}
        row.update(
            exception_id=r.exception_id, date=pd.Timestamp(d), mentor_id=r.mentor_id,
            exception_type=r.issue, detected_at=det_dt.strftime("%Y-%m-%d %H:%M"), status="Open",
        )
        if not (age == 0 and r.issue == cfg.ISSUE_CHECKOUT):
            row["contacted_at"] = (det_dt + pd.Timedelta(minutes=int(rng.integers(8, 46)))).strftime("%Y-%m-%d %H:%M")

        override = state_override.get(key)
        if age == 0 or override == "open":
            row["remarks"] = "Awaiting mentor reply" if override == "open" else ""
        elif override == "unresolved":
            row.update(reason="Mentor unreachable", proof="3 call attempts logged",
                       status="Unresolved", remarks="Escalated to lead and program manager")
        else:
            if key in device_keys:
                reason, status, proof = "Biometric device fault", "Regularized", "IT device-fault note"
            else:
                opts = OUTCOMES[r.issue]
                idx = rng.choice(len(opts), p=[o[1] for o in opts])
                reason, _, status, proof = opts[idx]
            nd = next_day.get(d, d + timedelta(days=1))
            row.update(
                reason=reason, proof=proof, status=status, closed_by="Ops Intern",
                closed_at=f"{nd:%Y-%m-%d} 10:{int(rng.integers(10, 56)):02d}",
            )
        exc_rows.append(row)
    exceptions = pd.DataFrame(exc_rows, columns=logic.EXC_COLS)
    return mentors, roster, punches, exceptions


def generate_and_save(**kwargs) -> None:
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    mentors, roster, punches, exceptions = generate(**kwargs)
    mentors.to_csv(cfg.MENTORS_CSV, index=False)
    logic.save_roster(roster)
    logic.save_punches(punches)
    logic.save_exceptions(exceptions)


if __name__ == "__main__":
    generate_and_save()
    print(f"Sample data written to {cfg.DATA_DIR}")
