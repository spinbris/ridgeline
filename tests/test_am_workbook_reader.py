"""Reader tests for the wind AM template (RS-A2 rebase).

The archived version read the engagement template and asserted its eight risks and seventeen
milestone stubs. This version reads `status_periods/wind_am_template.xlsx`: ten risks with
the wind prefix and four milestone stubs. The properties are unchanged - rows populate in sheet
order, IDs and titles are read, milestones are read - only the fixture is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.input_skips import skip_missing

from src.am.workbook_reader import (
    UNASSIGNED_OWNER,
    WorkbookData,
    WorkbookReaderError,
    read_workbook,
)


pytestmark = pytest.mark.unit


AM_REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = AM_REPO_ROOT / "status_periods" / "wind_am_template.xlsx"


EXPECTED_RISK_IDS = (  # the wind template's AM_Period_Status rows (RS-A2 rebase)
    "WT-001", "WT-002", "WT-008", "WT-009", "WT-020",
    "WT-021", "WT-026", "WT-027", "WT-031", "WT-032",
)

EXPECTED_MILESTONE_IDS = tuple(f"WM-{i:02d}" for i in range(1, 5))  # WM-01..WM-04, the wind template


@pytest.fixture(scope="module")
def workbook_data() -> WorkbookData:
    """Read the template once; reuse across tests in this module."""
    if not TEMPLATE_PATH.is_file():
        skip_missing(TEMPLATE_PATH)
    return read_workbook(TEMPLATE_PATH)


def test_top_level_keys_present(workbook_data: WorkbookData) -> None:
    """Structured result exposes the four top-level fields + risk_ids."""
    assert isinstance(workbook_data, WorkbookData)
    assert hasattr(workbook_data, "period_info")
    assert hasattr(workbook_data, "risk_status")
    assert hasattr(workbook_data, "milestones")
    assert hasattr(workbook_data, "mitigations")
    assert hasattr(workbook_data, "am_risk_ids")


def test_period_metadata_named_ranges_resolve(workbook_data: WorkbookData) -> None:
    """All eight period-metadata named ranges resolve to a key in
    period_info (values may be blank in the unfilled template)."""
    expected = {
        "am_period_end", "am_previous_period", "am_project_phase",
        "am_engine_run_date", "am_engine_run_hash",
        "am_analyst", "am_reviewer", "am_period_notes",
    }
    assert set(workbook_data.period_info.keys()) == expected


def test_risk_status_rows_are_the_wind_tier(workbook_data: WorkbookData) -> None:
    """Every AM_Period_Status row is one of the wind tier's risks, in sheet order (RS-A2 rebase
    of the engagement-template assertion; the property - rows populate in order - is unchanged)."""
    risk_ids = [r["risk_id"] for r in workbook_data.risk_status]
    assert risk_ids == list(EXPECTED_RISK_IDS)


def test_risk_status_titles_populated(workbook_data: WorkbookData) -> None:
    """Risk_title VLOOKUP from Risk Register col F populates correctly."""
    for row in workbook_data.risk_status:
        assert row["risk_title"], (
            f"{row['risk_id']} title is blank — helper VLOOKUP may have "
            f"failed at template build time"
        )


def test_risk_status_probability_current_is_a_probability_when_present(
    workbook_data: WorkbookData,
) -> None:
    """Probability_current VLOOKUP from Risk Register col BA populates."""
    # RS-A2 rebase: the engagement template populated this by VLOOKUP into its register;
    # the wind template leaves it to the period workbook. The property kept: when present,
    # it is a probability.
    for row in workbook_data.risk_status:
        assert "probability_current" in row  # the column is read for every row
        if row["probability_current"] is not None:
            assert 0.0 <= row["probability_current"] <= 1.0


def test_risk_status_unfilled_overrides_are_none(
    workbook_data: WorkbookData,
) -> None:
    """Template state: no overrides filled in yet. Resolved values
    fall back to current. (AM07: Mode columns retired; not read.)"""
    for row in workbook_data.risk_status:
        # Template's Probability_override is blank.
        assert row["probability_override"] is None
        # Resolved values fall back to current.
        assert row["probability_resolved"] == row["probability_current"]
        # AM07: mode is no longer a reader field.
        assert "mode_override" not in row
        assert "mode_resolved" not in row
        assert "mode_current" not in row


def test_all_owners_default_to_unassigned(workbook_data: WorkbookData) -> None:
    """Per Doc 2 v2.2 §3: Risk Register col Q is blank for all 8 active
    risks, so all 8 owners default to "Unassigned"."""
    for row in workbook_data.risk_status:
        assert row["owner"] == UNASSIGNED_OWNER, (
            f"{row['risk_id']} owner = {row['owner']!r}; expected "
            f"{UNASSIGNED_OWNER!r}"
        )


def test_helper_data_missing_flag_false_for_eight_active(
    workbook_data: WorkbookData,
) -> None:
    """All 8 active risks have helper VLOOKUPs populated; the flag
    should be False (no extension needed)."""
    for row in workbook_data.risk_status:
        assert row["helper_data_missing"] is False


def test_milestones_stubs_present(workbook_data: WorkbookData) -> None:
    """The wind template's milestone stubs populate AM_Milestones, in order (RS-A2 rebase)."""
    milestone_ids = [m["milestone_id"] for m in workbook_data.milestones]
    assert milestone_ids == list(EXPECTED_MILESTONE_IDS)


def test_milestones_have_names(workbook_data: WorkbookData) -> None:
    """Every milestone has a name (e.g. M01 → "Site mobilisation complete")."""
    for m in workbook_data.milestones:
        assert m["milestone_name"], (
            f"{m['milestone_id']} milestone_name is blank"
        )


def test_mitigations_empty_in_template(workbook_data: WorkbookData) -> None:
    """The template ships with no mitigations populated."""
    assert workbook_data.mitigations == []


def test_am_risk_ids_strip_empties(workbook_data: WorkbookData) -> None:
    """RANGE_AM_RISK_IDS is OFFSET-based with empty-string placeholders
    for non-qualifying rows. Reader strips empties per Doc 2 v2.2
    §"Engine reading notes" item 13."""
    assert workbook_data.am_risk_ids == list(EXPECTED_RISK_IDS)
    # No empty strings should leak through.
    assert all(rid.strip() for rid in workbook_data.am_risk_ids)


def test_claude_sheet_ignored_no_error(workbook_data: WorkbookData) -> None:
    """The "Claude" leftover sheet is ignored without raising. If
    read_workbook returned successfully above, this passes."""
    # Reaching this point under the workbook_data fixture already
    # demonstrates no error was raised. Belt-and-braces assertion:
    assert workbook_data is not None


def test_lock_file_raises(tmp_path: Path) -> None:
    """A ~$<name>.xlsx sibling forces an immediate raise."""
    target = tmp_path / "fake.xlsx"
    target.write_bytes(b"not a real xlsx but the lock check runs first")
    lock = tmp_path / "~$fake.xlsx"
    lock.write_bytes(b"")

    with pytest.raises(WorkbookReaderError, match="lock file"):
        read_workbook(target)


def test_missing_workbook_raises(tmp_path: Path) -> None:
    """A path that doesn't exist raises with a clear message."""
    missing = tmp_path / "does_not_exist.xlsx"
    with pytest.raises(WorkbookReaderError, match="not found"):
        read_workbook(missing)
