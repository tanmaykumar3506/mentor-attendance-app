"""Central configuration for the Mentor Attendance Control Room.

Change the rules here (cut-off times, statuses, reasons) and the whole app follows.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MENTORS_CSV = DATA_DIR / "mentors.csv"
ROSTER_CSV = DATA_DIR / "roster.csv"
PUNCHES_CSV = DATA_DIR / "punches.csv"
EXCEPTIONS_CSV = DATA_DIR / "exceptions.csv"

# ---- Attendance rules -------------------------------------------------------
CHECKIN_TARGET = "09:00"          # expected arrival
CHECKIN_GRACE_MIN = 15            # a check-in after 09:15 is flagged "late"
CLASS_END = "16:30"               # classes end; check-out expected after this
EARLY_LEAVE_BEFORE = "16:00"      # a check-out before 16:00 is flagged "early"
LATE_AFTER_MIN = 9 * 60 + CHECKIN_GRACE_MIN
EARLY_BEFORE_MIN = 16 * 60

# ---- Exception workflow -----------------------------------------------------
ISSUE_CHECKIN = "Missing check-in"
ISSUE_CHECKOUT = "Missing check-out"
ISSUE_ABSENT = "Absent - no punches"

EXCEPTION_STATUSES = ["Open", "Regularized", "Leave", "Absent", "Unresolved"]
CLOSED_STATUSES = ["Regularized", "Leave", "Absent"]
NEEDS_ACTION_STATUSES = ["Open", "Unresolved"]

REASONS = [
    "Forgot to punch in",
    "Forgot to punch out",
    "Fingerprint not recognised",
    "Biometric device fault",
    "Network/power issue at device",
    "Left early with approval",
    "Sick leave not updated in roster",
    "Personal emergency",
    "Uninformed absence",
    "Mentor unreachable",
    "Other",
]

COMPLIANCE_TARGET = 95           # % of working days fully punched (shown on trend chart)
REPEAT_THRESHOLD = 3              # misses in trailing 7 days => repeat-offender flag
CLOSURE_DEADLINE = "11:00 next working morning"

# ---- Look and feel ----------------------------------------------------------
STATUS_COLORS = {
    "Present": "#16A34A",
    "Incomplete": "#F59E0B",
    "Absent": "#DC2626",
    "Leave": "#3B82F6",
    "Holiday": "#94A3B8",
}
STATUS_BG = {
    "Present": "#DCFCE7",
    "Incomplete": "#FEF3C7",
    "Absent": "#FEE2E2",
    "Leave": "#DBEAFE",
    "Holiday": "#E2E8F0",
}
CELL_COLORS = {
    "Present": "#16A34A",
    "No check-in": "#F59E0B",
    "No check-out": "#FB923C",
    "Absent": "#DC2626",
    "Leave": "#3B82F6",
    "Holiday": "#CBD5E1",
}
UNIVERSITY = "Sample University"
