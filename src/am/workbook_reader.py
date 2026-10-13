"""Read the AM status-period workbook (Doc 2 v2.2 schema).

Exposes ``read_workbook(path)`` which returns a structured dict with
four top-level keys:

- ``period_info``: dict of period metadata (named-range driven)
- ``risk_status``: list[dict] of per-risk status rows (rows 15-22 of
  ``AM_Period_Status``)
- ``milestones``: list[dict] of milestone rows (``AM_Milestones`` row 4
  header onwards)
- ``mitigations``: list[dict] of mitigation rows (``AM_Mitigation_Log``)

Discipline:

- ``openpyxl`` with ``data_only=True`` -- reads computed values, not
  formulas. Requires the workbook to have been saved by Excel after
  any edits so cached formula values are present.
- Named ranges resolved via ``openpyxl.workbook.defined_names`` where
  available. Per-row reads use the header row at row 14 (period
  status) / row 4 (milestones, mitigations) so column positions track
  any future re-order without code change.
- Lock-file detection (``~$<name>.xlsx``) raises immediately --
  openpyxl silently returns ``None`` for cached cells when Excel has
  the workbook open.
- ``Claude`` sheet (per Doc 2 v2.2 §4) is ignored if present.
- ``RANGE_AM_RISK_IDS`` is OFFSET-based with empty-string placeholders;
  the reader strips empties.
- Owner defaults to ``"Unassigned"`` when blank (Doc 2 v2.2 §"Owner
  column reality"); the reader emits a logger warning naming the
  affected risk IDs.
- ``Probability_override`` > ``Probability_current``; precedence
  resolved at read time so downstream consumers get a single canonical
  value. (AM07: the Mode columns are retired; the AM is Stage 3 only.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants -- Doc 2 v2.2 schema anchors
# ---------------------------------------------------------------------------

PERIOD_METADATA_RANGES: tuple[str, ...] = (
    "am_period_end",
    "am_previous_period",
    "am_project_phase",
    "am_engine_run_date",
    "am_engine_run_hash",
    "am_analyst",
    "am_reviewer",
    "am_period_notes",
)

AM_PERIOD_STATUS_SHEET = "AM_Period_Status"
AM_PERIOD_STATUS_HEADER_ROW = 14
AM_PERIOD_STATUS_FIRST_DATA_ROW = 15
AM_PERIOD_STATUS_MAX_DATA_ROW = 30  # validation extends; reader scans this range

AM_MILESTONES_SHEET = "AM_Milestones"
AM_MILESTONES_HEADER_ROW = 4
AM_MILESTONES_MAX_DATA_ROW = 30

AM_MITIGATION_SHEET = "AM_Mitigation_Log"
AM_MITIGATION_HEADER_ROW = 4
AM_MITIGATION_MAX_DATA_ROW = 30

# AM07: the AM is Stage 3 only; the Mode columns are retired from the reader
# contract. Older workbooks that still carry Mode_current / Mode_override
# (the rich template, wind period files) are unaffected -- the header-driven
# reader simply ignores columns it does not expect.
RISK_STATUS_COLUMNS: tuple[str, ...] = (
    "Risk_ID",
    "Risk_title",
    "Status_this_period",
    "Status_changed",
    "Probability_current",
    "Probability_override",
    "Owner",
    "Fired_date",
    "Closed_date",
    "Notes_this_period",
)

MILESTONE_COLUMNS: tuple[str, ...] = (
    "Milestone_ID",
    "Milestone_name",
    "WBS_code",
    "Planned_start",
    "Planned_finish",
    "Status",
    "Percent_complete",
    "Actual_start",
    "Actual_finish",
    "Notes",
)

MITIGATION_COLUMNS: tuple[str, ...] = (
    "Mitigation_ID",
    "Risk_ID",
    "Description",
    "Cost_AUD",
    "Lead_time_weeks",
    "Status",
    "Approved_date",
    "Completed_date",
    "Owner",
    "Estimated_days_saved",
    "Actual_days_saved",
    "Notes",
)

# Doc 2 v2.2 §"Engine reading notes" item 4: blank Owner -> "Unassigned"
UNASSIGNED_OWNER = "Unassigned"

# Doc 2 v2.2 §4: "Claude" sheet is leftover working notes; ignore.
IGNORED_SHEETS: frozenset[str] = frozenset({"Claude"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class WorkbookReaderError(ValueError):
    """Raised for any structural defect in the AM workbook."""


# ---------------------------------------------------------------------------
# Lock-file detection
# ---------------------------------------------------------------------------

def _check_no_lock(workbook_path: Path) -> None:
    """Raise if the Excel lock file is present.

    Excel writes a ``~$<filename>`` sibling while a workbook is open.
    Reading a locked workbook via openpyxl returns cached formula
    values that may be stale (last-saved state) or ``None``; either
    way the engine output becomes non-deterministic. Failing fast at
    the boundary is the safer convention.
    """
    lock = workbook_path.parent / f"~${workbook_path.name}"
    if lock.exists():
        raise WorkbookReaderError(
            f"Excel lock file present: {lock}. Close the workbook in "
            f"Excel before invoking the reader."
        )


# ---------------------------------------------------------------------------
# Named-range resolution
# ---------------------------------------------------------------------------

def _resolve_named_range_scalar(wb: Workbook, name: str) -> Any:
    """Return the single cell value referenced by a defined name.

    Returns ``None`` if the name is not defined OR resolves to no cells
    OR the referenced cell is empty. A name that resolves to multiple
    cells raises -- every metadata range in Doc 2 v2.2 is single-cell.
    """
    if name not in wb.defined_names:
        return None
    defn = wb.defined_names[name]
    destinations = list(defn.destinations)
    if not destinations:
        return None
    if len(destinations) > 1:
        raise WorkbookReaderError(
            f"Named range {name!r} resolves to {len(destinations)} "
            f"destinations; expected a single cell"
        )
    sheet_name, coord = destinations[0]
    return wb[sheet_name][coord].value


def _resolve_named_range_values(wb: Workbook, name: str) -> list[Any]:
    """Return the list of cell values referenced by a defined name.

    Used for ``RANGE_AM_RISK_IDS`` and the list dropdowns. Empty
    strings are NOT stripped here -- the caller decides whether to
    strip them (Doc 2 v2.2 §"Engine reading notes" item 13 for
    ``RANGE_AM_RISK_IDS``).
    """
    if name not in wb.defined_names:
        return []
    defn = wb.defined_names[name]
    values: list[Any] = []
    for sheet_name, coord in defn.destinations:
        cells = wb[sheet_name][coord]
        # openpyxl returns a single Cell, a tuple-of-Cells, or a
        # tuple-of-tuple-of-Cells depending on whether the range is a
        # single cell, a row/column, or a 2-D region.
        if hasattr(cells, "value"):
            values.append(cells.value)
        else:
            for sub in cells:
                if hasattr(sub, "value"):
                    values.append(sub.value)
                else:
                    for cell in sub:
                        values.append(cell.value)
    return values


# ---------------------------------------------------------------------------
# Header-driven row scanning
# ---------------------------------------------------------------------------

def _column_map(
    wb: Workbook, sheet_name: str, header_row: int, expected: tuple[str, ...]
) -> dict[str, int]:
    """Map column-name → 1-indexed openpyxl column.

    The header row is the single source of truth for column positions.
    Missing expected columns raise; extra columns in the sheet are
    silently ignored.
    """
    ws = wb[sheet_name]
    header_cells = ws[header_row]
    found: dict[str, int] = {}
    for cell in header_cells:
        raw = cell.value
        if raw is None:
            continue
        name = str(raw).strip()
        if name:
            found[name] = cell.column
    missing = [c for c in expected if c not in found]
    if missing:
        raise WorkbookReaderError(
            f"{sheet_name} row {header_row} is missing expected column "
            f"headers: {missing}. Found: {sorted(found)}"
        )
    return found


def _row_to_dict(
    wb: Workbook,
    sheet_name: str,
    row: int,
    column_map: dict[str, int],
) -> dict[str, Any]:
    """Read one row using the column map."""
    ws = wb[sheet_name]
    return {
        name: ws.cell(row=row, column=col).value
        for name, col in column_map.items()
    }


# ---------------------------------------------------------------------------
# Period metadata
# ---------------------------------------------------------------------------

def _read_period_info(wb: Workbook) -> dict[str, Any]:
    """Read the eight metadata named ranges on AM_Period_Status."""
    info: dict[str, Any] = {}
    for name in PERIOD_METADATA_RANGES:
        info[name] = _resolve_named_range_scalar(wb, name)
    return info


# ---------------------------------------------------------------------------
# Risk status (the 8-row table at rows 15-22)
# ---------------------------------------------------------------------------

def _resolve_probability(row: dict[str, Any]) -> float | None:
    """Probability_override > Probability_current per item 6."""
    override = row.get("Probability_override")
    if override is not None and override != "":
        return float(override)
    current = row.get("Probability_current")
    if current is not None and current != "":
        return float(current)
    return None


def _resolve_owner(row: dict[str, Any]) -> str:
    """Default blank/zero Owner to "Unassigned" per Doc 2 v2.2 §3."""
    raw = row.get("Owner")
    if raw is None:
        return UNASSIGNED_OWNER
    s = str(raw).strip()
    # The template's VLOOKUP returns 0 (Excel-displayed) when the
    # source Risk Register col Q is empty. openpyxl reads the cached
    # value as an integer 0.
    if s == "" or s == "0":
        return UNASSIGNED_OWNER
    return s


def _read_risk_status(wb: Workbook) -> list[dict[str, Any]]:
    """Read AM_Period_Status rows 15-22 (and any extension up to row 30).

    Returns a list of dicts, one per populated row, with resolved
    fields:

    - ``risk_id`` (str)
    - ``risk_title`` (str)
    - ``status_this_period`` (str | None)
    - ``status_changed`` (Any)
    - ``probability_current`` (float | None)
    - ``probability_override`` (float | None)
    - ``probability_resolved`` (float | None -- override > current)
    - ``owner`` (str -- "Unassigned" if blank)
    - ``fired_date`` (Any)
    - ``closed_date`` (Any)
    - ``notes_this_period`` (str | None)
    - ``helper_data_missing`` (bool -- warning flag if Risk_ID is set
      but Risk_title is blank; signals row 23+ needs helper formula
      extension)

    A warning is logged for each row where Owner defaults to
    "Unassigned" (Doc 2 v2.2 §"Owner column reality").
    """
    cols = _column_map(
        wb, AM_PERIOD_STATUS_SHEET, AM_PERIOD_STATUS_HEADER_ROW,
        RISK_STATUS_COLUMNS,
    )

    rows: list[dict[str, Any]] = []
    unassigned_owners: list[str] = []
    helper_gaps: list[str] = []

    for row in range(
        AM_PERIOD_STATUS_FIRST_DATA_ROW, AM_PERIOD_STATUS_MAX_DATA_ROW + 1
    ):
        raw = _row_to_dict(wb, AM_PERIOD_STATUS_SHEET, row, cols)
        risk_id = raw.get("Risk_ID")
        if risk_id is None or str(risk_id).strip() == "":
            continue
        risk_id_s = str(risk_id).strip()

        title = raw.get("Risk_title")
        helper_missing = title is None or str(title).strip() == ""
        if helper_missing:
            helper_gaps.append(risk_id_s)

        owner = _resolve_owner(raw)
        if owner == UNASSIGNED_OWNER:
            unassigned_owners.append(risk_id_s)

        rows.append({
            "risk_id": risk_id_s,
            "risk_title": str(title).strip() if title is not None else "",
            "status_this_period": (
                str(raw["Status_this_period"]).strip()
                if raw.get("Status_this_period") is not None
                else None
            ),
            "status_changed": raw.get("Status_changed"),
            "probability_current": (
                float(raw["Probability_current"])
                if raw.get("Probability_current") not in (None, "")
                else None
            ),
            "probability_override": (
                float(raw["Probability_override"])
                if raw.get("Probability_override") not in (None, "")
                else None
            ),
            "probability_resolved": _resolve_probability(raw),
            "owner": owner,
            "fired_date": raw.get("Fired_date"),
            "closed_date": raw.get("Closed_date"),
            "notes_this_period": raw.get("Notes_this_period"),
            "helper_data_missing": helper_missing,
        })

    if unassigned_owners:
        logger.warning(
            "AM_Period_Status: Owner blank for %d risks; defaulting to "
            "%r. Affected: %s",
            len(unassigned_owners),
            UNASSIGNED_OWNER,
            ", ".join(unassigned_owners),
        )

    if helper_gaps:
        logger.warning(
            "AM_Period_Status: Risk_ID populated but Risk_title blank for "
            "%d rows; helper VLOOKUP formulas may need extension beyond "
            "row 22. Affected: %s",
            len(helper_gaps),
            ", ".join(helper_gaps),
        )

    return rows


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

def _read_milestones(wb: Workbook) -> list[dict[str, Any]]:
    """Read AM_Milestones rows 5+ where Milestone_ID is populated."""
    cols = _column_map(
        wb, AM_MILESTONES_SHEET, AM_MILESTONES_HEADER_ROW, MILESTONE_COLUMNS,
    )
    rows: list[dict[str, Any]] = []
    for row in range(
        AM_MILESTONES_HEADER_ROW + 1, AM_MILESTONES_MAX_DATA_ROW + 1
    ):
        raw = _row_to_dict(wb, AM_MILESTONES_SHEET, row, cols)
        milestone_id = raw.get("Milestone_ID")
        if milestone_id is None or str(milestone_id).strip() == "":
            continue
        rows.append({
            "milestone_id": str(milestone_id).strip(),
            "milestone_name": (
                str(raw["Milestone_name"]).strip()
                if raw.get("Milestone_name") is not None
                else ""
            ),
            "wbs_code": raw.get("WBS_code"),
            "planned_start": raw.get("Planned_start"),
            "planned_finish": raw.get("Planned_finish"),
            "status": (
                str(raw["Status"]).strip()
                if raw.get("Status") is not None
                else None
            ),
            "percent_complete": (
                int(raw["Percent_complete"])
                if raw.get("Percent_complete") not in (None, "")
                else None
            ),
            "actual_start": raw.get("Actual_start"),
            "actual_finish": raw.get("Actual_finish"),
            "notes": raw.get("Notes"),
        })
    return rows


# ---------------------------------------------------------------------------
# Mitigations
# ---------------------------------------------------------------------------

def _read_mitigations(wb: Workbook) -> list[dict[str, Any]]:
    """Read AM_Mitigation_Log rows 5+ where Mitigation_ID is populated."""
    cols = _column_map(
        wb, AM_MITIGATION_SHEET, AM_MITIGATION_HEADER_ROW, MITIGATION_COLUMNS,
    )
    rows: list[dict[str, Any]] = []
    for row in range(
        AM_MITIGATION_HEADER_ROW + 1, AM_MITIGATION_MAX_DATA_ROW + 1
    ):
        raw = _row_to_dict(wb, AM_MITIGATION_SHEET, row, cols)
        mitigation_id = raw.get("Mitigation_ID")
        if mitigation_id is None or str(mitigation_id).strip() == "":
            continue
        rows.append({
            "mitigation_id": str(mitigation_id).strip(),
            "risk_id": (
                str(raw["Risk_ID"]).strip()
                if raw.get("Risk_ID") not in (None, "")
                else None
            ),
            "description": raw.get("Description"),
            "cost_aud": (
                float(raw["Cost_AUD"])
                if raw.get("Cost_AUD") not in (None, "")
                else None
            ),
            "lead_time_weeks": (
                float(raw["Lead_time_weeks"])
                if raw.get("Lead_time_weeks") not in (None, "")
                else None
            ),
            "status": (
                str(raw["Status"]).strip()
                if raw.get("Status") is not None
                else None
            ),
            "approved_date": raw.get("Approved_date"),
            "completed_date": raw.get("Completed_date"),
            "owner": (
                str(raw["Owner"]).strip()
                if raw.get("Owner") is not None
                else None
            ),
            "estimated_days_saved": (
                float(raw["Estimated_days_saved"])
                if raw.get("Estimated_days_saved") not in (None, "")
                else None
            ),
            "actual_days_saved": (
                float(raw["Actual_days_saved"])
                if raw.get("Actual_days_saved") not in (None, "")
                else None
            ),
            "notes": raw.get("Notes"),
        })
    return rows


# ---------------------------------------------------------------------------
# am_risk_ids -- the AM in-scope set from the AM_Include helper column
# ---------------------------------------------------------------------------
#
# AM06 (Build Brief 2): the in-scope set is sourced from the MASTER REGISTER's
# AM_Include helper (col BQ over the register's data rows 5-104), resolved
# project-aware via ``register_path``. The slim AM workbook no longer embeds a
# "Risk Register" sheet. The legacy embedded-sheet read (col BQ rows 5-60) is
# retained as a fallback for AM files that still carry the sheet (the rich
# AM template; the synthetic-wind period files), so ``test_workbook_reader``
# and ``test_wind_cycle`` stay green without passing ``register_path``.
#
# Doc 2 v2.2 §"Helper column on Risk Register":
# - BQ4: "AM_Include" (header)
# - BQ5 onwards: =IF(AND(B5="Open", AZ5="Yes"), A5, "")
RISK_REGISTER_SHEET = "Risk Register"
AM_INCLUDE_COLUMN = "BQ"
AM_INCLUDE_FIRST_ROW = 5
AM_INCLUDE_LAST_ROW = 60  # embedded-sheet scan range (legacy AM files)

# Master-register AM_Include scan: col BQ (index 69) over the register's data
# rows, matching scripts/the archived engagement period-builder.read_inscope_risks.
REGISTER_AM_INCLUDE_COLUMN_INDEX = 69  # BQ
REGISTER_AM_INCLUDE_FIRST_ROW = 5
REGISTER_AM_INCLUDE_LAST_ROW = 104


def _read_am_include_helper_column(wb: Workbook) -> list[str]:
    """Read an AM file's embedded Risk Register col BQ rows 5-60.

    Legacy path: mirrors what the OFFSET-based ``RANGE_AM_RISK_IDS`` named
    range produces in Excel for AM files that embed the helper sheet. The
    caller checks the sheet is present before calling this.
    """
    ws = wb[RISK_REGISTER_SHEET]
    out: list[str] = []
    for row in range(AM_INCLUDE_FIRST_ROW, AM_INCLUDE_LAST_ROW + 1):
        val = ws[f"{AM_INCLUDE_COLUMN}{row}"].value
        if val is None:
            continue
        s = str(val).strip()
        if s:
            out.append(s)
    return out


def _read_register_am_include(register_path: Path | str) -> list[str]:
    """Read the master register's AM_Include helper (col BQ rows 5-104).

    The register's BQ column is the precomputed in-scope set
    (``=IF(AND(Status="Open", TimeImpact="Yes"), RiskID, "")``). Read with
    ``data_only=True`` to get the cached formula values. Returns the non-empty
    stripped IDs in row order. Crash-safe: a missing file or a register
    without the ``Risk Register`` sheet returns ``[]`` (the caller falls back
    to the embedded sheet or an empty list).
    """
    path = Path(register_path)
    if not path.is_file():
        logger.warning(
            "Register not found for am_risk_ids resolution: %s", path
        )
        return []
    rwb = load_workbook(path, data_only=True, read_only=True)
    try:
        if RISK_REGISTER_SHEET not in rwb.sheetnames:
            return []
        ws = rwb[RISK_REGISTER_SHEET]
        out: list[str] = []
        for row in range(
            REGISTER_AM_INCLUDE_FIRST_ROW, REGISTER_AM_INCLUDE_LAST_ROW + 1
        ):
            val = ws.cell(
                row=row, column=REGISTER_AM_INCLUDE_COLUMN_INDEX
            ).value
            if val is None:
                continue
            s = str(val).strip()
            if s:
                out.append(s)
        return out
    finally:
        rwb.close()


def _resolve_am_risk_ids(
    wb: Workbook, register_path: Path | str | None
) -> list[str]:
    """Resolve the AM in-scope set, register-first with an embedded fallback.

    1. If ``register_path`` is given and yields a non-empty AM_Include set,
       use it (AM06: the master register is the source of truth).
    2. Else, if the AM file embeds a ``Risk Register`` sheet, read it
       (legacy AM files: the rich template, the wind period files).
    3. Else return ``[]`` (a slim AM06 workbook read without a register).
    """
    if register_path is not None:
        ids = _read_register_am_include(register_path)
        if ids:
            return ids
    if RISK_REGISTER_SHEET in wb.sheetnames:
        return _read_am_include_helper_column(wb)
    return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkbookData:
    """Structured result of reading the AM status-period workbook."""
    period_info: dict[str, Any]
    risk_status: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    mitigations: list[dict[str, Any]]
    am_risk_ids: list[str]  # AM in-scope set; register-sourced (AM06)


def read_workbook(
    workbook_path: Path | str,
    *,
    register_path: Path | str | None = None,
) -> WorkbookData:
    """Read the AM status-period workbook and return its structured
    contents.

    Parameters
    ----------
    workbook_path : Path | str
        Path to the ``.xlsx`` file. Must NOT have an Excel lock file
        sibling -- see :func:`_check_no_lock`.
    register_path : Path | str | None, optional
        Path to the master register (AM06). When given, ``am_risk_ids``
        is sourced from the register's AM_Include helper (col BQ rows
        5-104) rather than from a "Risk Register" sheet embedded in the
        AM file. ``run_period`` passes the project-resolved register here.
        When omitted, the reader falls back to an embedded helper sheet if
        present, else ``am_risk_ids`` is empty. The AM file is NOT required
        to carry a "Risk Register" sheet.

    Returns
    -------
    WorkbookData
        Frozen dataclass with the four data dicts/lists.

    Raises
    ------
    WorkbookReaderError
        On any structural defect: lock file present, named range
        missing or multi-cell when single-cell expected, header row
        missing an expected column, etc.
    """
    path = Path(workbook_path).resolve()
    if not path.is_file():
        raise WorkbookReaderError(f"Workbook not found: {path}")
    _check_no_lock(path)

    # data_only=True so we read computed values (post-Excel-save)
    # rather than formula strings. Loading is read-only-ish: openpyxl
    # writes back only if asked.
    wb = load_workbook(path, data_only=True)

    # Doc 2 v2.2 §4: ignore "Claude" sheet (no-op since we don't read it).
    if any(s in wb.sheetnames for s in IGNORED_SHEETS):
        logger.debug(
            "Ignoring sheets per Doc 2 v2.2: %s",
            sorted(s for s in IGNORED_SHEETS if s in wb.sheetnames),
        )

    # AM06: source the in-scope set from the master register's AM_Include
    # helper when ``register_path`` is given, falling back to an embedded
    # "Risk Register" sheet for legacy AM files. ``am_risk_ids`` is a
    # carried contract field; it does not drive the engine output, so the
    # source change is output-neutral.
    am_risk_ids = _resolve_am_risk_ids(wb, register_path)

    return WorkbookData(
        period_info=_read_period_info(wb),
        risk_status=_read_risk_status(wb),
        milestones=_read_milestones(wb),
        mitigations=_read_mitigations(wb),
        am_risk_ids=am_risk_ids,
    )
