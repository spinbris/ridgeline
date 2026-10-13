"""Author the synthetic-wind AM status-period template + 3-4 filled periods
(showcase-P4 WS4-C).

Produces a clean, minimal-but-valid wind AM template and four monthly period
workbooks under ``status_periods/`` that ``src.am.run_period`` consumes
(project=synthetic_wind). The template carries exactly what
``src.am.workbook_reader.read_workbook`` requires:

  - a "Risk Register" sheet with the AM_Include helper column (BQ rows 5+),
    the source of ``am_risk_ids``;
  - AM_Period_Status: 8 metadata named ranges (am_period_end ... am_period_notes),
    a header at row 14 (the 12 RISK_STATUS_COLUMNS), risk rows from row 15;
  - AM_Milestones: header at row 4 (10 MILESTONE_COLUMNS), rows from 5;
  - AM_Mitigation_Log: header at row 4 (12 MITIGATION_COLUMNS), rows from 5.

The rich Excel-analyst UI of the archived engagement AM template (slicers, VLOOKUPs,
dropdowns, 25 extra sheets) is intentionally omitted: it serves the human
analyst in Excel, not the automated AM cycle, and the wind template is a
separate file (decision 2) so the archived engagement template is untouched.

Progress arc (Director-approved 2026-06-09; decision 3): baseline ->
delivery-risk escalates + mitigation actioned -> milestone slips + grid/
electrical escalate -> partial recovery. Period-over-period P80 movement is
driven by Probability_override on the schedule-driving WT risks (the lever
that actually moves the headline; the AM02 fired-uplift is audit-only, so a
literal Status=Fired would not worsen the headline - see the brief WS4-C
note). Status transitions (Open/Actioned/Closed) + the open/closed counts
+ mitigation states carry the rest of the narrative.

Run:
    python scripts/build_wind_am_periods.py
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "status_periods"

# Reader contract (must match src/am/workbook_reader.py exactly).
RISK_STATUS_COLUMNS = (
    "Risk_ID", "Risk_title", "Status_this_period", "Status_changed",
    "Probability_current", "Probability_override", "Owner", "Mode_current",
    "Mode_override", "Fired_date", "Closed_date", "Notes_this_period",
)
MILESTONE_COLUMNS = (
    "Milestone_ID", "Milestone_name", "WBS_code", "Planned_start",
    "Planned_finish", "Status", "Percent_complete", "Actual_start",
    "Actual_finish", "Notes",
)
MITIGATION_COLUMNS = (
    "Mitigation_ID", "Risk_ID", "Description", "Cost_AUD", "Lead_time_weeks",
    "Status", "Approved_date", "Completed_date", "Owner",
    "Estimated_days_saved", "Actual_days_saved", "Notes",
)
PERIOD_METADATA_RANGES = (
    "am_period_end", "am_previous_period", "am_project_phase",
    "am_engine_run_date", "am_engine_run_hash", "am_analyst",
    "am_reviewer", "am_period_notes",
)
AM_STATUS_SHEET = "AM_Period_Status"
AM_STATUS_HEADER_ROW = 14
AM_STATUS_FIRST_DATA_ROW = 15
AM_MILESTONES_SHEET = "AM_Milestones"
AM_MITIGATION_SHEET = "AM_Mitigation_Log"
RISK_REGISTER_SHEET = "Risk Register"
AM_INCLUDE_COL = 69  # column BQ
AM_INCLUDE_FIRST_ROW = 5

# The 10 schedule-driving WT risks (register baseline prob + mode + owner).
TRACKED_RISKS = [
    ("WT-001", "Turbine foundation rework", 0.45, "Series", "Civil Lead"),
    ("WT-002", "Access road wet-weather damage", 0.50, "Hybrid", "Civil Lead"),
    ("WT-008", "WTG delivery delay (long-lead)", 0.40, "Series", "Procurement Lead"),
    ("WT-009", "Main crane mobilisation delay", 0.45, "Hybrid", "Erection Lead"),
    ("WT-020", "HV array cable test failures", 0.35, "Parallel", "Electrical Lead"),
    ("WT-021", "Grid connection redesign", 0.30, "Series", "Grid Lead"),
    ("WT-026", "Substation civils delay", 0.35, "Hybrid", "Substation Lead"),
    ("WT-027", "Substation E&I commissioning slip", 0.35, "Parallel", "Substation Lead"),
    ("WT-031", "SCADA integration defects", 0.50, "Series", "Commissioning Lead"),
    ("WT-032", "Turbine commissioning faults", 0.45, "Hybrid", "Commissioning Lead"),
]
BASELINE_PROB = {r[0]: r[2] for r in TRACKED_RISKS}

# Wind construction milestones (display; no WBS_code -> no engine exclusion).
MILESTONES = [
    ("WM-01", "Foundations complete", _dt.date(2026, 3, 15)),
    ("WM-02", "Turbine erection complete", _dt.date(2026, 4, 30)),
    ("WM-03", "Grid connection energised", _dt.date(2026, 5, 31)),
    ("WM-04", "Commissioning complete", _dt.date(2026, 6, 30)),
]


# ---------------------------------------------------------------------------
# Per-period arc specification
# ---------------------------------------------------------------------------
# Each period: end date, previous end, phase, notes, per-risk overrides
# {risk_id: {status, prob, mode, fired, closed, note}}, milestone states
# {mid: (status, pct)}, mitigation rows.

PERIODS = [
    {
        "end": _dt.date(2026, 2, 28),
        "prev": None,
        "phase": "Civil & Foundations",
        "notes": "Baseline period. All schedule risks at register baseline; "
                 "early civil works underway.",
        "risks": {},  # all Open at baseline
        "milestones": {"WM-01": ("In progress", 40), "WM-02": ("Not started", 0),
                       "WM-03": ("Not started", 0), "WM-04": ("Not started", 0)},
        "mitigations": [],
    },
    {
        "end": _dt.date(2026, 3, 31),
        "prev": _dt.date(2026, 2, 28),
        "phase": "Foundations & Turbine Supply",
        "notes": "WTG long-lead delivery slipping (vessel availability); "
                 "probability raised to near-certain and expedite mitigation "
                 "actioned. Crane mobilisation risk rising.",
        "risks": {
            "WT-008": {"status": "Actioned", "prob": 0.90,
                       "note": "Long-lead delivery slipping; expedite underway"},
            "WT-009": {"status": "Monitor", "prob": 0.65,
                       "note": "Crane window tightening with delivery slip"},
        },
        "milestones": {"WM-01": ("Complete", 100), "WM-02": ("In progress", 25),
                       "WM-03": ("Not started", 0), "WM-04": ("Not started", 0)},
        "mitigations": [
            ("MIT-01", "WT-008", "Expedite WTG shipping; secure alternate "
             "vessel window", 450000, 6, "Actioned", "Procurement Lead", None),
            ("MIT-02", "WT-009", "Pre-mobilise backup main crane", 280000, 8,
             "Proposed", "Erection Lead", None),
        ],
    },
    {
        "end": _dt.date(2026, 4, 30),
        "prev": _dt.date(2026, 3, 31),
        "phase": "Turbine Erection & Grid",
        "notes": "Turbine erection milestone slips on delivery + crane knock-on; "
                 "grid connection redesign and HV cable test risks escalate.",
        "risks": {
            "WT-008": {"status": "Actioned", "prob": 0.85,
                       "note": "Delivery firming up but erection start delayed"},
            "WT-009": {"status": "Actioned", "prob": 0.65,
                       "note": "Backup crane mobilisation in progress"},
            "WT-021": {"status": "Monitor", "prob": 0.70,
                       "note": "Network operator requires connection redesign"},
            "WT-020": {"status": "Monitor", "prob": 0.55,
                       "note": "Early HV array cable test failures"},
        },
        "milestones": {"WM-01": ("Complete", 100), "WM-02": ("Delayed", 55),
                       "WM-03": ("Not started", 0), "WM-04": ("Not started", 0)},
        "mitigations": [
            ("MIT-01", "WT-008", "Expedite WTG shipping; secure alternate "
             "vessel window", 450000, 6, "Actioned", "Procurement Lead", None),
            ("MIT-02", "WT-009", "Pre-mobilise backup main crane", 280000, 8,
             "Approved", "Erection Lead", None),
            ("MIT-03", "WT-021", "Early network-operator design workshop",
             120000, 4, "Proposed", "Grid Lead", None),
        ],
    },
    {
        "end": _dt.date(2026, 5, 31),
        "prev": _dt.date(2026, 4, 30),
        "phase": "Grid Connection & Commissioning",
        "notes": "Partial recovery: WTG delivery resolved (mitigation completed); "
                 "grid redesign settled; crane risk back to baseline. Electrical "
                 "and commissioning risks remain.",
        "risks": {
            # Delivery resolved but the late arrival compressed commissioning,
            # leaving a residual readiness risk above baseline (so the period
            # is a PARTIAL recovery, not a full return below baseline - the
            # ml=20 delivery risk is the dominant lever).
            "WT-008": {"status": "Actioned", "prob": 0.55,
                       "note": "WTGs delivered late; residual commissioning-readiness risk"},
            "WT-009": {"status": "Closed", "closed": _dt.date(2026, 5, 5),
                       "note": "Erection complete; crane demobilised"},
            "WT-021": {"status": "Actioned", "prob": 0.40,
                       "note": "Redesign agreed with network operator"},
            "WT-020": {"status": "Monitor", "prob": 0.50,
                       "note": "HV cable test failures easing after rework"},
            # Construction risks ease, but the now-active commissioning phase
            # brings its own risks forward -> commissioning is the new front.
            "WT-031": {"status": "Actioned", "prob": 0.75,
                       "note": "SCADA integration defects materialising"},
            "WT-032": {"status": "Monitor", "prob": 0.65,
                       "note": "Turbine commissioning faults surfacing"},
        },
        "milestones": {"WM-01": ("Complete", 100), "WM-02": ("Complete", 100),
                       "WM-03": ("In progress", 60), "WM-04": ("Not started", 0)},
        "mitigations": [
            # MIT-01 actioned (not Completed) so WT-008 keeps its residual
            # risk rather than being removed from the MC.
            ("MIT-01", "WT-008", "Expedite WTG shipping; secure alternate "
             "vessel window", 450000, 6, "Actioned", "Procurement Lead", None),
            ("MIT-03", "WT-021", "Early network-operator design workshop",
             120000, 4, "Proposed", "Grid Lead", None),
        ],
    },
]


# ---------------------------------------------------------------------------
# Workbook construction
# ---------------------------------------------------------------------------

def _add_defined_name(wb: Workbook, name: str, ref: str) -> None:
    wb.defined_names[name] = DefinedName(name, attr_text=ref)


def _build_workbook(spec: dict | None) -> Workbook:
    """Build one wind AM workbook. ``spec=None`` builds the empty template."""
    wb = Workbook()

    # --- Risk Register sheet (only the AM_Include helper column is read) ---
    rr = wb.active
    rr.title = RISK_REGISTER_SHEET
    rr.cell(row=4, column=1, value="Risk ID")
    rr.cell(row=4, column=3, value="Risk Description")
    rr.cell(row=4, column=AM_INCLUDE_COL, value="AM_Include")
    for i, (rid, title, *_rest) in enumerate(TRACKED_RISKS):
        r = AM_INCLUDE_FIRST_ROW + i
        rr.cell(row=r, column=1, value=rid)
        rr.cell(row=r, column=3, value=title)
        rr.cell(row=r, column=AM_INCLUDE_COL, value=rid)  # Open + AM=Yes

    # --- AM_Period_Status ---
    ps = wb.create_sheet(AM_STATUS_SHEET)
    # Metadata block A1:B8, named B1:B8.
    meta_labels = [
        "Period end", "Previous period", "Project phase", "Engine run date",
        "Engine run hash", "Analyst", "Reviewer", "Period notes",
    ]
    for i, (label, name) in enumerate(zip(meta_labels, PERIOD_METADATA_RANGES)):
        row = i + 1
        ps.cell(row=row, column=1, value=label)
        _add_defined_name(wb, name, f"{AM_STATUS_SHEET}!$B${row}")
    # Header row 14.
    for c, col in enumerate(RISK_STATUS_COLUMNS, start=1):
        ps.cell(row=AM_STATUS_HEADER_ROW, column=c, value=col)
    # Metadata values (period-specific).
    if spec is not None:
        ps["B1"] = spec["end"]
        ps["B2"] = spec["prev"]
        ps["B3"] = spec["phase"]
        ps["B6"] = "Synthetic Wind PM"
        ps["B7"] = "Synthetic Wind Reviewer"
        ps["B8"] = spec["notes"]
    # Risk rows from row 15.
    risk_over = (spec or {}).get("risks", {})
    for i, (rid, title, base_prob, mode, owner) in enumerate(TRACKED_RISKS):
        row = AM_STATUS_FIRST_DATA_ROW + i
        o = risk_over.get(rid, {})
        vals = {
            "Risk_ID": rid,
            "Risk_title": title,
            "Status_this_period": o.get("status", "Open" if spec else None),
            "Status_changed": None,
            "Probability_current": base_prob if spec else None,
            "Probability_override": o.get("prob"),
            "Owner": owner if spec else None,
            "Mode_current": mode if spec else None,
            "Mode_override": o.get("mode"),
            "Fired_date": o.get("fired"),
            "Closed_date": o.get("closed"),
            "Notes_this_period": o.get("note"),
        }
        for c, col in enumerate(RISK_STATUS_COLUMNS, start=1):
            ps.cell(row=row, column=c, value=vals[col])

    # --- AM_Milestones ---
    ms = wb.create_sheet(AM_MILESTONES_SHEET)
    for c, col in enumerate(MILESTONE_COLUMNS, start=1):
        ms.cell(row=4, column=c, value=col)
    ms_states = (spec or {}).get("milestones", {})
    for i, (mid, mname, planned) in enumerate(MILESTONES):
        row = 5 + i
        status, pct = ms_states.get(mid, ("Not started", 0))
        vals = {
            "Milestone_ID": mid, "Milestone_name": mname, "WBS_code": None,
            "Planned_start": None, "Planned_finish": planned if spec else None,
            "Status": status if spec else None,
            "Percent_complete": (pct / 100.0) if spec else None,
            "Actual_start": None, "Actual_finish": None, "Notes": None,
        }
        for c, col in enumerate(MILESTONE_COLUMNS, start=1):
            ms.cell(row=row, column=c, value=vals[col])

    # --- AM_Mitigation_Log ---
    mt = wb.create_sheet(AM_MITIGATION_SHEET)
    for c, col in enumerate(MITIGATION_COLUMNS, start=1):
        mt.cell(row=4, column=c, value=col)
    for i, m in enumerate((spec or {}).get("mitigations", [])):
        mid, rid, desc, cost, lead, status, owner, completed = m
        row = 5 + i
        vals = {
            "Mitigation_ID": mid, "Risk_ID": rid, "Description": desc,
            "Cost_AUD": cost, "Lead_time_weeks": lead, "Status": status,
            "Approved_date": None, "Completed_date": completed, "Owner": owner,
            "Estimated_days_saved": None, "Actual_days_saved": None, "Notes": None,
        }
        for c, col in enumerate(MITIGATION_COLUMNS, start=1):
            mt.cell(row=row, column=c, value=vals[col])

    return wb


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmpl = _build_workbook(None)
    tmpl_path = OUT_DIR / "wind_am_template.xlsx"
    tmpl.save(tmpl_path)
    print(f"wrote {tmpl_path}")
    for i, spec in enumerate(PERIODS, start=1):
        wb = _build_workbook(spec)
        path = OUT_DIR / f"wind_period_{i:02d}.xlsx"
        wb.save(path)
        print(f"wrote {path}  (period_end={spec['end']}, prev={spec['prev']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
