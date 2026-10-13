"""P6-Schedule reader for the SP17 SRA Option A strawman.

Parses the P6 Excel export (sheet `P6-Schedule`) into a list of activity
dicts with normalised fields. Uses dynamic header-name column lookup -
no positional-index assumptions - so a reshuffled export still works.

The returned list contains BOTH WBS summary rows (is_wbs_summary=True) and
activity rows (is_wbs_summary=False). Downstream consumers (classifier,
mapper) filter as needed.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

P6_SHEET_NAME = "P6-Schedule"

# Normalised header names (lowercased, trimmed) -> canonical field key.
# Duplicate headers in the export (e.g. both 'L1' and 'WBS' appear twice)
# are disambiguated by source column letter via HEADER_COLUMN_HINTS.
HEADER_ALIASES: dict[str, str] = {
    "level": "level",
    "wbs": "is_wbs_summary",
    "activity id": "activity_id",
    "activity name": "activity_name",
    "duration": "duration_days",
    "start": "start_raw",
    "finish": "finish_raw",
    "labour hour": "labour_hours",
    "labour hours": "labour_hours",
    "total float": "total_float_days",
    "primary constraint": "primary_constraint",
    "critical": "p6_critical_flag",
    "predecessors": "predecessors",
    "calendar": "calendar",
    "successors": "successors",
    "l1": "wbs_l1",
    "l2": "wbs_l2",
    "l3": "wbs_l3",
    "l4": "wbs_l4",
    "l5": "wbs_l5",
    "scope": "scope",
    "discipline": "discipline",
    "eq. tag": "eq_tag",
    "eq. name": "eq_name",
}

# When a header name is ambiguous (appears twice), resolve by column letter.
# In the reference P6 export, column B is the WBS=YES/NO flag and column W is
# the WBS code string - both labelled "WBS" in the header row.
COLUMN_LETTER_OVERRIDES: dict[str, str] = {
    "B": "is_wbs_summary",
    "W": "wbs_code",
}


_DURATION_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*d\s*$", re.IGNORECASE)
_DATE_STRING_RE = re.compile(
    r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{2,4})(\*?)\s*$"
)
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_duration(value: object) -> float | None:
    """Parse '912.0d' style strings to float days. Returns None if unparseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    m = _DURATION_RE.match(s)
    if m:
        return float(m.group(1))
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date_cell(value: object) -> tuple[datetime | None, bool]:
    """Parse a P6 date cell. Returns (date_or_None, is_constrained)."""
    if value is None or value == "":
        return None, False
    if isinstance(value, datetime):
        return value, False
    s = str(value).strip()
    if not s:
        return None, False
    is_constrained = s.endswith("*")
    core = s.rstrip("*").strip()
    m = _DATE_STRING_RE.match(s)
    if m:
        day, mon_abbr, year, _star = m.groups()
        mon = _MONTH_ABBR.get(mon_abbr.lower())
        if mon is None:
            return None, is_constrained
        yr = int(year)
        if yr < 100:
            yr += 2000
        try:
            return datetime(yr, mon, int(day)), is_constrained
        except ValueError:
            return None, is_constrained
    # Try a few common formats as fallback.
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(core, fmt), is_constrained
        except ValueError:
            continue
    return None, is_constrained


def _column_letter(col_index: int) -> str:
    """1-based column index -> Excel letter (A, B, ..., Z, AA, ...)."""
    letters = ""
    n = col_index
    while n > 0:
        n, r = divmod(n - 1, 26)
        letters = chr(ord("A") + r) + letters
    return letters


def _build_header_map(header_row: tuple) -> dict[str, int]:
    """Return {canonical_field_key: 0-based column index}."""
    col_map: dict[str, int] = {}
    for idx, raw in enumerate(header_row):
        if raw is None:
            continue
        col_letter = _column_letter(idx + 1)
        # Column-letter override wins over name-based mapping.
        if col_letter in COLUMN_LETTER_OVERRIDES:
            col_map[COLUMN_LETTER_OVERRIDES[col_letter]] = idx
            continue
        key = HEADER_ALIASES.get(str(raw).strip().lower())
        if key and key not in col_map:
            col_map[key] = idx
    return col_map


def _str_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _normalise_discipline(v: object) -> str | None:
    s = _str_or_none(v)
    if s is None:
        return None
    # 'CIVIL' / 'civil' / 'Civil' -> 'Civil'
    return s.title() if s.isupper() else s


def read_p6_schedule(path: str | Path) -> list[dict]:
    """Read the P6-Schedule sheet and return one dict per row.

    Parameters
    ----------
    path : str | Path
        P6 export xlsx (spaces in filename OK).

    Returns
    -------
    list[dict]
        Row dicts with these keys:
          level, is_wbs_summary, activity_id, activity_name,
          duration_days, start_date, start_is_constrained,
          finish_date, finish_is_constrained, labour_hours,
          total_float_days, p6_critical_flag, predecessors,
          successors, calendar,
          wbs_l1, wbs_l2, wbs_l3, wbs_l4, wbs_l5,
          scope, discipline, wbs_code, eq_tag, eq_name.
        Both WBS summary rows and activity rows are returned;
        filter with `is_wbs_summary` if you only want activities.
    """
    wb = load_workbook(str(path), read_only=True, data_only=True)
    if P6_SHEET_NAME not in wb.sheetnames:
        wb.close()
        raise ValueError(
            f"Sheet {P6_SHEET_NAME!r} not found in {path}. "
            f"Sheets: {wb.sheetnames}"
        )
    sht = wb[P6_SHEET_NAME]
    rows_iter = sht.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        wb.close()
        return []

    col = _build_header_map(header)
    required = ("level", "activity_id", "duration_days", "total_float_days")
    missing = [k for k in required if k not in col]
    if missing:
        wb.close()
        raise ValueError(
            f"P6 header is missing required columns: {missing}. "
            f"Found: {sorted(col.keys())}"
        )

    def g(row: tuple, key: str) -> object:
        idx = col.get(key)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    rows: list[dict] = []
    for raw_row in rows_iter:
        if raw_row is None:
            continue
        # Skip fully-empty rows.
        if all(v is None for v in raw_row):
            continue
        activity_id = _str_or_none(g(raw_row, "activity_id"))
        level = g(raw_row, "level")
        # Require either a level or activity_id to consider a real row.
        if activity_id is None and level is None:
            continue

        start_raw = g(raw_row, "start_raw")
        finish_raw = g(raw_row, "finish_raw")
        start_date, start_constr = _parse_date_cell(start_raw)
        finish_date, finish_constr = _parse_date_cell(finish_raw)

        wbs_flag = g(raw_row, "is_wbs_summary")
        is_summary = (
            isinstance(wbs_flag, str) and wbs_flag.strip().upper() == "YES"
        )

        critical_raw = g(raw_row, "p6_critical_flag")
        crit_flag = (
            isinstance(critical_raw, str)
            and critical_raw.strip().lower() == "yes"
        )

        labour = g(raw_row, "labour_hours")
        try:
            labour_hours = float(labour) if labour is not None else 0.0
        except (TypeError, ValueError):
            labour_hours = 0.0

        rows.append({
            "level": level,
            "is_wbs_summary": is_summary,
            "activity_id": activity_id,
            "activity_name": _str_or_none(g(raw_row, "activity_name")),
            "duration_days": _parse_duration(g(raw_row, "duration_days")),
            "start_date": start_date,
            "start_is_constrained": start_constr,
            "finish_date": finish_date,
            "finish_is_constrained": finish_constr,
            "labour_hours": labour_hours,
            "total_float_days": _parse_duration(g(raw_row, "total_float_days")),
            "primary_constraint": _str_or_none(g(raw_row, "primary_constraint")),
            "p6_critical_flag": crit_flag,
            "predecessors": _str_or_none(g(raw_row, "predecessors")),
            "successors": _str_or_none(g(raw_row, "successors")),
            "calendar": _str_or_none(g(raw_row, "calendar")),
            "wbs_l1": _str_or_none(g(raw_row, "wbs_l1")),
            "wbs_l2": _str_or_none(g(raw_row, "wbs_l2")),
            "wbs_l3": _str_or_none(g(raw_row, "wbs_l3")),
            "wbs_l4": _str_or_none(g(raw_row, "wbs_l4")),
            "wbs_l5": _str_or_none(g(raw_row, "wbs_l5")),
            "scope": _str_or_none(g(raw_row, "scope")),
            "discipline": _normalise_discipline(g(raw_row, "discipline")),
            "wbs_code": _str_or_none(g(raw_row, "wbs_code")),
            "eq_tag": _str_or_none(g(raw_row, "eq_tag")),
            "eq_name": _str_or_none(g(raw_row, "eq_name")),
        })

    wb.close()
    return rows


def activity_rows(rows: list[dict]) -> list[dict]:
    """Filter to activity rows only (is_wbs_summary == False)."""
    return [r for r in rows if not r["is_wbs_summary"]]
