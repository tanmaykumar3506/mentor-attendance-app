# Mentor Attendance Control Room

A working Streamlit prototype for managing biometric check-in / check-out attendance of 20 mentors.
It implements the operations workflow: daily monitoring, automatic exception detection, escalation,
follow-up with closure, and downloadable reports. Sample data is fictional.

## Launch locally

Requires Python 3.11 or newer (tested on Python 3.11 and 3.13).

```bash
cd mentor_attendance_app

# optional but recommended: a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501. On first launch it generates 30 working days of sample data
in `data/`. Use **Reset sample data** in the sidebar to regenerate it (dated up to the latest weekday).

## What is inside

| Page | What it does |
|---|---|
| Dashboard | KPIs (present / incomplete / absent / leave / late), today's board for all 20 mentors, alerts, 3-week trend, top miss sources |
| Daily Attendance | Single day, date range with filters, and a mentor x date matrix (P, IN, OUT, A, L, H) |
| Mentor History | One mentor: compliance, average punch times, attendance calendar, daily records, exception history |
| Exceptions & Alerts | Alerts, editable follow-up tracker (reason, proof, status; reason required to close), ready-to-send reminder and escalation messages |
| Reports & Data | CSV and 3-sheet Excel downloads for any date range; import a real biometric CSV export |
| Workflow & SOP | The process diagram, daily checkpoints, status rules, closure rules, escalation ladder |

The sidebar **Review date** lets you view the system as of any day in the data.

## Rules (change them in `config.py`)

- **Present:** check-in and check-out both recorded. **Incomplete:** only one punch. **Absent:** working day, no punches, no leave.
- **Late:** check-in after 09:15. **Early leave:** check-out before 16:00. Flags only, not exceptions.
- **Escalation:** L1 on detection; L2 if still open the next morning; L3 if open 2+ days, Unresolved, or 3+ misses in 7 days.
- **Closure statuses:** Regularized, Leave, Absent (need a reason), Unresolved (stays with the program manager).

## Project structure

```
mentor_attendance_app/
  app.py                  entry point, sidebar, navigation
  config.py               rules, thresholds, colours
  requirements.txt
  smoke_test.py           headless test: opens every page
  .streamlit/config.toml  theme
  src/
    logic.py              status rules, exceptions, escalation, alerts, summaries
    data_generator.py     realistic sample data with demo scenarios
    reports.py            CSV / Excel report builders
    ui.py                 CSS, KPI cards, table styling
  views/                  one module per page
  data/                   mentors.csv, roster.csv, punches.csv, exceptions.csv
```

## Using your own data

On **Reports & Data > Import biometric export**, upload a CSV with columns
`date, mentor_id, check_in, check_out` (YYYY-MM-DD and HH:MM; leave a time empty if not punched).
Rows replace existing punches for the same date and mentor, and new exceptions are logged automatically.
Edit `data/mentors.csv` to change mentor names, leads and contact numbers.

## Demo scenarios built into the sample data

- A biometric device-fault day where four mentors miss check-in (closed as "Biometric device fault").
- A university holiday.
- A repeat offender (M09, Arjun Patel) with three misses in a week, who triggers L3 escalation.
- Current-day open exceptions, one overdue exception (L2) and one Unresolved exception.

## Tests

```bash
pip install pytest
python -m pytest tests -v        # 24 scenario and UI tests
python smoke_test.py             # opens every page against the sample data
```

The suite uses small hand-built datasets with known answers and covers: a normal day, forgot check-in,
forgot check-out, absent, incomplete attendance, several mentors missing on the same day, leave and holiday,
late/early flags, duplicate punch rows, an all-absent day, escalation L1 to L3, repeat misses, closing rules,
imports, reports, and the dashboard numbers through the real UI.

## Behaviours worth knowing

- **Ageing uses working days.** An exception from Friday reviewed on Monday is 1 working day old (L2), not 3 (L3).
- **Self-healing log.** If a later import supplies the missing punch, the open exception is closed automatically
  as "Regularized (System)"; if leave is added to the roster, it closes as "Leave".
- **Import validation.** Dates, mentor IDs, HH:MM times (`9:05` is normalised to `09:05`), check-out after check-in,
  and duplicate rows are all checked before anything is saved.
- **Data-quality alerts.** Check-out not after check-in, or punches on leave days or holidays, are flagged.

## Tested with

| Environment | Result |
|---|---|
| Python 3.13, Streamlit 1.67, pandas 3.1 (newest) | 24 tests pass; smoke test passes |
| Python 3.11, Streamlit 1.40, pandas 2.0.3 (oldest allowed by requirements.txt) | 24 tests pass; smoke test passes |

The data in this prototype is fictional. There is no real biometric connection and no real pilot.
