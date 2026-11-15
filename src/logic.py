"""Core attendance logic: status classification, exceptions, escalation, alerts, summaries."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg

EXC_COLS = [
    "exception_id", "date", "mentor_id", "exception_type", "detected_at",
    "contacted_at", "reason", "proof", "status", "closed_by", "closed_at", "remarks",
]
LEVEL_LABELS = {
    0: "Closed",
    1: "L1 - Ops follow-up",
    2: "L2 - Lead",
    3: "L3 - Program manager",
}


# ----------------------------------------------------------------------------
# Loading / saving
# ----------------------------------------------------------------------------
def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def ensure_data() -> None:
    needed = [cfg.MENTORS_CSV, cfg.ROSTER_CSV, cfg.PUNCHES_CSV, cfg.EXCEPTIONS_CSV]
    if not all(p.exists() for p in needed):
        from src.data_generator import generate_and_save

        generate_and_save()


def save_exceptions(exc: pd.DataFrame) -> None:
    out = exc.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.reindex(columns=EXC_COLS).fillna("")
    out.to_csv(cfg.EXCEPTIONS_CSV, index=False)


def save_punches(punches: pd.DataFrame) -> None:
    out = punches.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out[["date", "mentor_id", "check_in", "check_out"]].sort_values(["date", "mentor_id"]).to_csv(
        cfg.PUNCHES_CSV, index=False
    )


def save_roster(roster: pd.DataFrame) -> None:
    out = roster.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out[["date", "mentor_id", "expected"]].sort_values(["date", "mentor_id"]).to_csv(
        cfg.ROSTER_CSV, index=False
    )


def load_all() -> dict:
    """Load every CSV, derive attendance, sync exceptions, and apply closure outcomes."""
    ensure_data()
    mentors = _read(cfg.MENTORS_CSV)
    roster = _read(cfg.ROSTER_CSV)
    punches = _read(cfg.PUNCHES_CSV)
    exc = _read(cfg.EXCEPTIONS_CSV)

    for df in (roster, punches, exc):
        df["date"] = pd.to_datetime(df["date"])
    for col in EXC_COLS:
        if col not in exc.columns:
            exc[col] = ""
    exc = exc[EXC_COLS]

    att = build_attendance(mentors, roster, punches)
    exc, added = sync_exceptions(att, exc)
    if added:
        save_exceptions(exc)
    att = apply_closure(att, exc)
    return {"mentors": mentors, "roster": roster, "punches": punches, "att": att, "exc_raw": exc}


# ----------------------------------------------------------------------------
# Attendance classification
# ----------------------------------------------------------------------------
def hhmm_to_min(series: pd.Series) -> pd.Series:
    def conv(x):
        x = str(x).strip()
        if len(x) >= 5 and x[2] == ":":
            return int(x[:2]) * 60 + int(x[3:5])
        return np.nan

    return series.map(conv).astype(float)


def fmt_min(x) -> str:
    if x is None or pd.isna(x):
        return ""
    x = int(round(x))
    return f"{x // 60:02d}:{x % 60:02d}"


def build_attendance(mentors: pd.DataFrame, roster: pd.DataFrame, punches: pd.DataFrame) -> pd.DataFrame:
    punches = punches.drop_duplicates(["date", "mentor_id"], keep="last")
    df = roster.merge(mentors, on="mentor_id", how="left")
    df = df.merge(punches[["date", "mentor_id", "check_in", "check_out"]], on=["date", "mentor_id"], how="left")
    df["check_in"] = df["check_in"].fillna("").astype(str)
    df["check_out"] = df["check_out"].fillna("").astype(str)

    ci = (df["check_in"] != "").to_numpy()
    co = (df["check_out"] != "").to_numpy()
    working = (df["expected"] == "Working").to_numpy()
    holiday = (df["expected"] == "Holiday").to_numpy()
    leave = (df["expected"] == "Leave").to_numpy()

    df["status"] = np.select(
        [holiday, leave, working & ci & co, working & (ci ^ co), working & ~ci & ~co],
        ["Holiday", "Leave", "Present", "Incomplete", "Absent"],
        default="Unknown",
    )
    df["issue"] = np.select(
        [working & ~ci & co, working & ci & ~co, working & ~ci & ~co],
        [cfg.ISSUE_CHECKIN, cfg.ISSUE_CHECKOUT, cfg.ISSUE_ABSENT],
        default="",
    )

    df["ci_min"] = hhmm_to_min(df["check_in"])
    df["co_min"] = hhmm_to_min(df["check_out"])
    df["late"] = (df["ci_min"] > cfg.LATE_AFTER_MIN).fillna(False)
    df["early_leave"] = (df["co_min"] < cfg.EARLY_BEFORE_MIN).fillna(False)
    df["hours"] = ((df["co_min"] - df["ci_min"]) / 60).round(2)
    any_punch = ci | co
    bad_order = (ci & co & (df["co_min"] <= df["ci_min"]).fillna(False).to_numpy())
    df["dq_issue"] = np.select(
        [bad_order, leave & any_punch, holiday & any_punch],
        ["Check-out is not after check-in", "Punched while on approved leave", "Punched on a holiday"],
        default="",
    )
    df.loc[bad_order, "hours"] = np.nan
    df["weekday"] = df["date"].dt.day_name().str[:3]
    df["exception_id"] = df["date"].dt.strftime("%Y-%m-%d") + "_" + df["mentor_id"]
    return df.sort_values(["date", "mentor_id"]).reset_index(drop=True)


def apply_closure(att: pd.DataFrame, exc: pd.DataFrame) -> pd.DataFrame:
    """Add the post-follow-up (final) status alongside the raw biometric status."""
    att = att.copy()
    lookup = exc.set_index("exception_id")["status"]
    st_ = att["exception_id"].map(lookup).astype(object).fillna("")
    st_ = st_.where(att["issue"] != "", "")
    att["exception_status"] = st_
    att["final_status"] = np.select(
        [
            st_ == "Regularized",
            st_ == "Leave",
            st_ == "Absent",
            st_.isin(cfg.NEEDS_ACTION_STATUSES),
        ],
        ["Present (regularized)", "Leave (confirmed)", "Absent (confirmed)", "Pending follow-up"],
        default=att["status"],
    )
    return att


def cell_label(att: pd.DataFrame) -> pd.Series:
    """One label per mentor-day for heatmaps and matrices."""
    return pd.Series(
        np.select(
            [
                att["status"] == "Holiday",
                att["status"] == "Leave",
                att["status"] == "Present",
                att["issue"] == cfg.ISSUE_CHECKIN,
                att["issue"] == cfg.ISSUE_CHECKOUT,
                att["issue"] == cfg.ISSUE_ABSENT,
            ],
            ["Holiday", "Leave", "Present", "No check-in", "No check-out", "Absent"],
            default="Unknown",
        ),
        index=att.index,
    )


# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------
def sync_exceptions(att: pd.DataFrame, exc: pd.DataFrame):
    """Keep the exception log in step with the punch data.

    * adds an Open exception for every detected miss not yet logged,
    * follows the data when the type changes (e.g. Absent -> Missing check-out),
    * auto-closes Open/Unresolved exceptions whose miss no longer exists (punch arrived later).
    Returns (updated_log, number_of_changes).
    """
    exc = exc.copy()
    exc["date"] = pd.to_datetime(exc["date"])
    det = att[att["issue"] != ""][["exception_id", "date", "mentor_id", "issue"]]
    changes = 0

    # 1. type follows the data
    cur_type = det.set_index("exception_id")["issue"]
    live = exc["status"].isin(cfg.NEEDS_ACTION_STATUSES) & exc["exception_id"].isin(cur_type.index)
    new_type = exc.loc[live, "exception_id"].map(cur_type)
    differs = new_type != exc.loc[live, "exception_type"]
    if differs.any():
        idx = new_type[differs].index
        exc.loc[idx, "exception_type"] = new_type[differs]
        changes += len(idx)

    # 2. auto-close exceptions that are no longer detected
    stale = exc["status"].isin(cfg.NEEDS_ACTION_STATUSES) & ~exc["exception_id"].isin(det["exception_id"])
    if stale.any():
        exp = att.set_index("exception_id")["expected"]
        now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
        for i in exc.index[stale]:
            on_leave = exp.get(exc.at[i, "exception_id"], "") == "Leave"
            exc.loc[i, ["status", "reason", "proof", "closed_by", "closed_at"]] = [
                "Leave" if on_leave else "Regularized",
                "Leave recorded in roster" if on_leave else "Punch received in later biometric export",
                "Roster update" if on_leave else "Biometric export",
                "System", now,
            ]
            changes += 1

    # 3. add new exceptions
    new = det[~det["exception_id"].isin(exc["exception_id"])]
    if not new.empty:
        rows = []
        for r in new.itertuples():
            t = "17:30" if r.issue == cfg.ISSUE_CHECKOUT else "09:30"
            row = {c: "" for c in EXC_COLS}
            row.update(
                exception_id=r.exception_id, date=r.date, mentor_id=r.mentor_id,
                exception_type=r.issue, detected_at=f"{r.date:%Y-%m-%d} {t}", status="Open",
            )
            rows.append(row)
        exc = pd.concat([exc, pd.DataFrame(rows)], ignore_index=True)
        exc["date"] = pd.to_datetime(exc["date"])
        changes += len(rows)
    return exc, changes


def enrich_exceptions(exc: pd.DataFrame, as_of: pd.Timestamp, mentors: pd.DataFrame, att: pd.DataFrame) -> pd.DataFrame:
    """Compute age (in WORKING days), repeat count, escalation level and SLA state as of a given day."""
    e = exc[exc["date"] <= as_of].copy()
    e = e.merge(mentors[["mentor_id", "mentor_name", "track", "lead", "phone"]], on="mentor_id", how="left")
    work_days = np.sort(att.loc[att["expected"] == "Working", "date"].unique().astype("datetime64[ns]"))
    pos_asof = np.searchsorted(work_days, np.datetime64(as_of, "ns"), side="right")
    pos_exc = np.searchsorted(work_days, e["date"].to_numpy(dtype="datetime64[ns]"), side="right")
    e["age_days"] = (pos_asof - pos_exc).astype(int)

    window = e[e["date"] >= as_of - pd.Timedelta(days=6)]
    rep = window.groupby("mentor_id").size()
    e["misses_7d"] = e["mentor_id"].map(rep).fillna(0).astype(int)

    needs = e["status"].isin(cfg.NEEDS_ACTION_STATUSES).to_numpy()
    level = np.where(
        ~needs,
        0,
        np.where(
            (e["status"] == "Unresolved") | (e["age_days"] >= 2) | (e["misses_7d"] >= cfg.REPEAT_THRESHOLD),
            3,
            np.where(e["age_days"] >= 1, 2, 1),
        ),
    )
    e["level"] = level.astype(int)
    e["level_label"] = e["level"].map(LEVEL_LABELS)
    e["sla"] = np.where(~needs, "Closed", np.where(e["age_days"] >= 1, "Overdue", "Due next morning"))

    det = pd.to_datetime(e["detected_at"], errors="coerce")
    clo = pd.to_datetime(e["closed_at"], errors="coerce")
    hours = (clo - det).dt.total_seconds() / 3600
    e["close_hours"] = hours.where(~needs)
    return e.sort_values(["level", "date", "mentor_id"], ascending=[False, False, True]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Alerts and messages
# ----------------------------------------------------------------------------
def build_alerts(att: pd.DataFrame, exc: pd.DataFrame, as_of: pd.Timestamp) -> list[dict]:
    alerts: list[dict] = []

    def names(df):
        return ", ".join(df["mentor_name"].tolist())

    l3 = exc[exc["level"] == 3]
    if len(l3):
        alerts.append({
            "severity": "High",
            "title": f"{len(l3)} exception(s) escalated to the program manager (L3)",
            "detail": "; ".join(f"{r.mentor_name} - {r.exception_type} on {r.date:%d %b}" for r in l3.itertuples()),
        })

    overdue = exc[(exc["sla"] == "Overdue") & (exc["level"] < 3)]
    if len(overdue):
        alerts.append({
            "severity": "High",
            "title": f"{len(overdue)} exception(s) past the closure deadline",
            "detail": "; ".join(f"{r.mentor_name} - {r.exception_type} on {r.date:%d %b}" for r in overdue.itertuples()),
        })

    rep = (
        exc[exc["misses_7d"] >= cfg.REPEAT_THRESHOLD][["mentor_name", "misses_7d"]]
        .drop_duplicates("mentor_name")
    )
    if len(rep):
        alerts.append({
            "severity": "High",
            "title": "Repeat misses in the last 7 days",
            "detail": "; ".join(f"{r.mentor_name} ({r.misses_7d} misses)" for r in rep.itertuples()),
        })

    day = att[att["date"] == as_of]
    for issue, label in [
        (cfg.ISSUE_CHECKIN, "missing check-in today"),
        (cfg.ISSUE_CHECKOUT, "missing check-out today"),
        (cfg.ISSUE_ABSENT, "no punches today (possible absence)"),
    ]:
        sub = day[day["issue"] == issue]
        if len(sub):
            alerts.append({"severity": "Medium", "title": f"{len(sub)} mentor(s) with {label}", "detail": names(sub)})

    dq = day[day["dq_issue"] != ""]
    if len(dq):
        alerts.append({
            "severity": "Medium",
            "title": f"{len(dq)} record(s) need a data check",
            "detail": "; ".join(f"{r.mentor_name}: {r.dq_issue}" for r in dq.itertuples()),
        })

    late = day[day["late"]]
    if len(late):
        alerts.append({
            "severity": "Info",
            "title": f"{len(late)} late check-in(s) today",
            "detail": ", ".join(f"{r.mentor_name} ({r.check_in})" for r in late.itertuples()),
        })
    early = day[day["early_leave"]]
    if len(early):
        alerts.append({
            "severity": "Info",
            "title": f"{len(early)} early check-out(s) today",
            "detail": ", ".join(f"{r.mentor_name} ({r.check_out})" for r in early.itertuples()),
        })
    return alerts


def reminder_message(name: str, date, exception_type: str) -> str:
    d = pd.Timestamp(date).strftime("%d %b %Y")
    if exception_type == cfg.ISSUE_CHECKIN:
        body = (
            f"our records show no biometric check-in for {d}. Could you please confirm whether you "
            "attended, share the time you arrived, and tell us the reason (for example a device problem)?"
        )
    elif exception_type == cfg.ISSUE_CHECKOUT:
        body = (
            f"our records show a check-in but no biometric check-out for {d}. Please confirm the time you "
            "left and the reason it was missed, so we can close the record."
        )
    else:
        body = (
            f"we have no check-in or check-out for {d}, and no approved leave is on record. Please let us "
            "know today if you were on leave or had an issue, so we can update your attendance."
        )
    return f"Hi {name}, {body} Please reply by 11:00 AM tomorrow. Thank you - Operations Team"


def escalation_message(lead: str, name: str, date, exception_type: str, level_label: str) -> str:
    d = pd.Timestamp(date).strftime("%d %b %Y")
    return (
        f"Hi {lead}, attendance exception pending for {name}: {exception_type} on {d}. "
        f"We have contacted the mentor but the record is still open ({level_label}). "
        "Could you please confirm their attendance or the reason? - Operations Team"
    )


# ----------------------------------------------------------------------------
# Summaries
# ----------------------------------------------------------------------------
def mentor_summary(att: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    d = att[(att["date"] >= start) & (att["date"] <= end)]
    work = d[d["expected"] == "Working"].copy()
    work["is_present"] = work["status"] == "Present"
    work["no_in"] = work["issue"] == cfg.ISSUE_CHECKIN
    work["no_out"] = work["issue"] == cfg.ISSUE_CHECKOUT
    work["no_punch"] = work["issue"] == cfg.ISSUE_ABSENT
    g = work.groupby(["mentor_id", "mentor_name", "track", "lead"]).agg(
        working_days=("date", "count"),
        present=("is_present", "sum"),
        missing_check_in=("no_in", "sum"),
        missing_check_out=("no_out", "sum"),
        absent=("no_punch", "sum"),
        late=("late", "sum"),
        early_leave=("early_leave", "sum"),
        avg_check_in=("ci_min", "mean"),
        avg_check_out=("co_min", "mean"),
    ).reset_index()
    leave = d[d["expected"] == "Leave"].groupby("mentor_id").size()
    g["leave_days"] = g["mentor_id"].map(leave).fillna(0).astype(int)
    g["punch_compliance_pct"] = (g["present"] / g["working_days"] * 100).round(1)
    g["avg_check_in"] = g["avg_check_in"].map(fmt_min)
    g["avg_check_out"] = g["avg_check_out"].map(fmt_min)
    for c in ["present", "missing_check_in", "missing_check_out", "absent", "late", "early_leave"]:
        g[c] = g[c].astype(int)
    return g.sort_values("punch_compliance_pct").reset_index(drop=True)


# ----------------------------------------------------------------------------
# Write operations (kept here so they can be tested without the UI)
# ----------------------------------------------------------------------------
def apply_exception_edits(exc_raw: pd.DataFrame, edited: pd.DataFrame, now: str):
    """Apply tracker edits. Closing requires a reason. Returns (updated_df, saved, skipped_ids)."""
    raw = exc_raw.set_index("exception_id").copy()
    saved, skipped = 0, []
    for r in edited.itertuples():
        eid, status, reason = r.exception_id, r.status, (r.reason or "")
        if status in cfg.CLOSED_STATUSES and not reason:
            skipped.append(eid)
            continue
        raw.loc[eid, ["contacted_at", "reason", "proof", "status", "remarks"]] = [
            r.contacted_at or "", reason, r.proof or "", status, r.remarks or "",
        ]
        if status in cfg.CLOSED_STATUSES:
            if not raw.loc[eid, "closed_at"]:
                raw.loc[eid, ["closed_at", "closed_by"]] = [now, "Ops Intern"]
        else:
            raw.loc[eid, ["closed_at", "closed_by"]] = ["", ""]
        saved += 1
    return raw.reset_index(), saved, skipped


def import_punches(punches: pd.DataFrame, roster: pd.DataFrame, mentors: pd.DataFrame, new: pd.DataFrame):
    """Upsert imported punches by (date, mentor) and add roster rows for unseen dates."""
    key = lambda df: df["date"].dt.strftime("%Y-%m-%d") + "_" + df["mentor_id"]
    kept = punches[~key(punches).isin(key(new))]
    merged = pd.concat([kept, new[["date", "mentor_id", "check_in", "check_out"]]], ignore_index=True)
    new_dates = sorted(set(new["date"]) - set(roster["date"]))
    if new_dates:
        add = pd.DataFrame(
            [(d, m, "Working") for d in new_dates for m in mentors["mentor_id"]],
            columns=["date", "mentor_id", "expected"],
        )
        roster = pd.concat([roster, add], ignore_index=True)
    return merged, roster


# ----------------------------------------------------------------------------
# Action queue, daily summary, import validation
# ----------------------------------------------------------------------------
def action_queue(exc: pd.DataFrame) -> pd.DataFrame:
    """Everything that needs a human action right now, most urgent first."""
    q = exc[exc["status"].isin(cfg.NEEDS_ACTION_STATUSES)].copy()
    if q.empty:
        return pd.DataFrame(columns=["Mentor", "Issue", "Date", "Level", "SLA", "Phone", "Next step"])

    def step(r):
        if r.level >= 3:
            return "Escalate to program manager"
        if r.level == 2:
            return f"Ask {r.lead} to confirm"
        return "Contact mentor now" if not r.contacted_at else "Awaiting reply - chase before 11:00"

    q["Next step"] = [step(r) for r in q.itertuples()]
    q["Date"] = q["date"].dt.strftime("%d %b")
    out = q.rename(columns={"mentor_name": "Mentor", "exception_type": "Issue", "level_label": "Level",
                            "sla": "SLA", "phone": "Phone"})
    return out[["Mentor", "Issue", "Date", "Level", "SLA", "Phone", "Next step"]].reset_index(drop=True)


def daily_summary_text(att: pd.DataFrame, exc: pd.DataFrame, as_of: pd.Timestamp) -> str:
    day = att[(att["date"] == as_of) & (att["expected"] == "Working")]
    n = len(day)
    present = int((day["status"] == "Present").sum())
    leave = int(((att["date"] == as_of) & (att["expected"] == "Leave")).sum())
    names = lambda mask: ", ".join(day.loc[mask, "mentor_name"]) or "none"
    open_ = exc[exc["status"].isin(cfg.NEEDS_ACTION_STATUSES)]
    lines = [
        f"Attendance summary - {as_of:%a %d %b %Y}",
        f"Expected: {n} | Present: {present} | Incomplete: {int((day['status'] == 'Incomplete').sum())} | "
        f"Absent: {int((day['status'] == 'Absent').sum())} | On leave: {leave}",
        f"Punch compliance: {present / n * 100:.0f}%" if n else "Punch compliance: -",
        f"Missing check-in: {names(day['issue'] == cfg.ISSUE_CHECKIN)}",
        f"Missing check-out: {names(day['issue'] == cfg.ISSUE_CHECKOUT)}",
        f"No punches: {names(day['issue'] == cfg.ISSUE_ABSENT)}",
        f"Late check-ins: {names(day['late'])}",
        f"Open exceptions: {len(open_)} (overdue: {int((open_['sla'] == 'Overdue').sum())}, "
        f"escalated to L3: {int((open_['level'] == 3).sum())})",
    ]
    return "\n".join(lines)


_TIME_RE = r"^(\d{1,2}):(\d{2})$"


def _norm_time(v: str):
    """'9:05' -> '09:05'; '' stays ''; invalid -> None."""
    v = str(v).strip()
    if v == "":
        return ""
    m = pd.Series([v]).str.extract(_TIME_RE).iloc[0]
    if m.isna().any():
        return None
    h, mi = int(m[0]), int(m[1])
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def validate_import(new: pd.DataFrame, mentors: pd.DataFrame):
    """Validate and clean an uploaded biometric export. Returns (clean_df, list_of_problems)."""
    problems: list[str] = []
    df = new.copy().astype(str)
    for c in df.columns:
        df[c] = df[c].str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="%Y-%m-%d")
    if df["date"].isna().any():
        problems.append(f"{int(df['date'].isna().sum())} row(s) have a date that is not YYYY-MM-DD")
    unknown = sorted(set(df["mentor_id"]) - set(mentors["mentor_id"]))
    if unknown:
        problems.append(f"unknown mentor_id: {', '.join(unknown)}")
    for col in ("check_in", "check_out"):
        norm = df[col].map(_norm_time)
        bad = norm.isna()
        if bad.any():
            problems.append(f"{col} has {int(bad.sum())} value(s) that are not a valid time (use HH:MM, row {int(bad.idxmax()) + 2})")
        df[col] = norm.fillna(df[col])
    both = (df["check_in"] != "") & (df["check_out"] != "")
    ok_fmt = df["check_in"].str.match(r"^\d{2}:\d{2}$") & df["check_out"].str.match(r"^\d{2}:\d{2}$")
    order_bad = both & ok_fmt & (df["check_out"] <= df["check_in"])
    if order_bad.any():
        problems.append(f"check-out must be after check-in (row {int(order_bad.idxmax()) + 2})")
    dup = df.duplicated(["date", "mentor_id"], keep=False) & df["date"].notna()
    if dup.any():
        problems.append(f"duplicate rows for the same mentor and date ({int(dup.sum())} rows)")
    return df, problems
