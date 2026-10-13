"""3c Part C-1: the TOC tells a generalist how to run, and stops naming a control that isn't there.

XLSX-01 BLOCKs 1, 2 and 5, from the Claude-in-Excel functional review of 03/09
(the XLSX functional review). As shipped, a generalist could
read the TOC end to end, fill the register, look for a Run button, never find one, and never be
told that one has to be created first - while `TOC!B39` sent them to press a "Validate Contract
button" that is in no tab of the workbook.

These assert the properties on the **tracked template**, which is what a user is handed. The
drift test (`test_register_template_artefact.py`) separately holds that the tracked template is
what the scaffolder emits, so together they mean: the scaffolder says this, and the shipped file
says what the scaffolder says.

The wind fixture shares `build_toc` and is deliberately NOT regenerated here - it is a golden
input, and moving it moves the golden's input digest, which is a Director's bless. See the Part
C record.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "templates" / "register_template.xlsx"
TOC = "TOC & Instructions"


@pytest.fixture(scope="module")
def toc_cells() -> dict[str, str]:
    wb = openpyxl.load_workbook(TEMPLATE)
    try:
        ws = wb[TOC]
        return {c.coordinate: str(c.value) for row in ws.iter_rows()
                for c in row if c.value is not None}
    finally:
        wb.close()


def _text(cells: dict[str, str]) -> str:
    return "\n".join(cells.values())


# --- BLOCK 5: the contract version is where a user looks -----------------------------------

def test_the_contract_version_is_on_the_front_page(toc_cells):
    assert "Register contract" in _text(toc_cells), (
        "the TOC does not show the register contract version; a user cannot tell whether "
        "their register matches the engine they are about to point at it (XLSX-01 BLOCK 5)"
    )


def test_the_version_is_a_formula_not_a_second_copy_of_the_number(toc_cells):
    """A literal here would drift the first time the contract moves - two sources, one truth."""
    version_cells = [v for v in toc_cells.values() if str(v).startswith("=Settings!")]
    assert version_cells, (
        f"no TOC cell reads the version from Settings; found instead: "
        f"{[v for k, v in toc_cells.items() if 'contract' in str(v).lower()]}"
    )
    assert any("B6" in v for v in version_cells), version_cells


def test_the_version_shown_is_the_contract_the_engine_checks():
    """The cell the TOC points at must be the one the contract actually lives in."""
    from src.register_contract import CONTRACT_VERSION

    wb = openpyxl.load_workbook(TEMPLATE, data_only=False)
    try:
        assert str(wb["Settings"]["B6"].value) == str(CONTRACT_VERSION), (
            "Settings!B6 is not the engine's CONTRACT_VERSION, so the TOC would display a "
            "version the engine does not check"
        )
    finally:
        wb.close()


# --- BLOCK 1 + R-8: there is a run section, and it says whose job activation is ------------

def test_the_toc_has_a_run_section(toc_cells):
    assert "Running a simulation" in _text(toc_cells), (
        "the TOC still has no run section (XLSX-01 BLOCK 1)")


def test_the_run_section_says_activation_is_the_specialists_task(toc_cells):
    """R-8. The generalist's path starts AFTER activation, and the TOC has to say so."""
    text = _text(toc_cells).lower()
    assert "specialist" in text, "the TOC never says activation is a specialist's task (R-8)"
    assert "once per workbook" in text, "the TOC does not say activation happens once"


def test_the_run_section_names_the_three_entry_points(toc_cells):
    text = _text(toc_cells)
    for control in ("Run Simulation", "Run Simulation 100k", "Validate Contract"):
        assert control in text, f"the run section does not name {control!r}"


def test_the_toc_says_what_works_without_activation(toc_cells):
    """The review's point: as shipped nothing is broken, and a user told only 'you cannot run'
    would reasonably conclude the workbook is faulty."""
    text = _text(toc_cells).lower()
    assert "without activation" in text
    assert "emv" in text and "summary" in text


# --- BLOCK 2: no cell claims a control exists in the file ----------------------------------

def test_no_toc_cell_sends_the_user_to_a_button_in_the_workbook(toc_cells):
    """The defect was `TOC!B39`: "run the Validate Contract button after any structural edit",
    with no button on any of the tabs. Every mention of a button must now say where it is -
    the xlwings Lite task pane, and only after activation.
    """
    QUALIFIERS = ("task-pane", "task pane", "not a button", "no code and no buttons")
    unqualified = {
        coord: value for coord, value in toc_cells.items()
        if "button" in str(value).lower()
        and not any(q in str(value).lower() for q in QUALIFIERS)
    }
    assert unqualified == {}, (
        "these TOC cells mention a button without saying it is a task-pane item that exists "
        f"only after activation: {unqualified}"
    )


def test_the_template_still_contains_no_such_control():
    """The other half - the assertion above is only meaningful while the file really has none.

    If a future change adds a real in-sheet control, this reds and the wording above should be
    revisited rather than the test relaxed.
    """
    wb = openpyxl.load_workbook(TEMPLATE)
    try:
        for ws in wb.worksheets:
            shapes = getattr(ws, "_charts", []) + getattr(ws, "_images", [])
            non_chart = [s for s in shapes if type(s).__name__ not in
                         ("BarChart", "PieChart", "LineChart", "ScatterChart")]
            assert not non_chart, f"{ws.title} now carries a control: {non_chart}"
    finally:
        wb.close()


# --- the guard that keeps the two writers apart --------------------------------------------

def test_the_instruction_block_cannot_silently_overwrite_project_identity():
    """`build_toc` and `build_project_block` are different functions writing one sheet, with
    no shared constant between them until Part C. Red-first: with the pre-Part-C value the
    run section collides, and the scaffolder must refuse rather than overwrite a user's
    project name."""
    import tempfile

    import tools.register_scaffold as rs

    original = rs._META_START_ROW
    try:
        rs._META_START_ROW = 44  # the value before the run section was added
        with pytest.raises(RuntimeError, match="collides with the project-identity block"):
            rs.build_template(Path(tempfile.mkdtemp()) / "collide.xlsx")
    finally:
        rs._META_START_ROW = original


def test_project_identity_is_still_present_and_below_the_instructions(toc_cells):
    assert "Project identity" in _text(toc_cells)
    identity_row = next(int(c[1:]) for c, v in toc_cells.items()
                        if v == "Project identity" and c.startswith("A"))
    run_row = next(int(c[1:]) for c, v in toc_cells.items()
                   if v == "Running a simulation" and c.startswith("A"))
    assert run_row < identity_row, "the run section is below the project block"


# --- C-2 (Director 04/09): what the generalist may do to a protected register --------------
#
# XLSX-01 BLOCK 4. Sorting and filtering were blocked, so the only way to order a register by
# package or narrow it by status was Review > Unprotect Sheet - which turns off every other
# guard at the same time. The protection meant to defend the contract was the reason a user
# would remove it.
#
# The flag sense is inverted: in OOXML `sort="1"` means LOCKED, and openpyxl defaults all of
# these to True. These tests read the OOXML value directly and say which way round it is, so
# a future reader cannot repeat the mistake the scaffolder itself made.

_PERMISSIONS = ("sort", "autoFilter")


@pytest.fixture(scope="module")
def workbook():
    wb = openpyxl.load_workbook(TEMPLATE)
    yield wb
    wb.close()


@pytest.mark.parametrize("action", _PERMISSIONS)
def test_the_generalist_may_sort_and_filter_the_register(action, workbook):
    value = getattr(workbook["Risk Register"].protection, action)
    assert value is False, (
        f"sheetProtection@{action} is {value!r}; False means PERMITTED and True means LOCKED. "
        f"The register is meant to allow {action} under protection (XLSX-01 BLOCK 4)."
    )


def test_the_register_is_still_protected_and_the_contract_still_guarded(workbook):
    """Permitting three actions must not have turned protection off wholesale."""
    p = workbook["Risk Register"].protection
    assert p.sheet is True, "sheet protection is off entirely"
    for locked in ("insertColumns", "deleteColumns", "formatCells", "insertRows"):
        assert getattr(p, locked) is True, f"{locked} is no longer locked"


@pytest.mark.parametrize("action", _PERMISSIONS)
def test_machine_tabs_permit_none_of_it(action, workbook):
    """The permission is the register's alone - Settings, Simulation and the grids stay shut."""
    for title in ("Settings", "Simulation", "Methodology"):
        assert getattr(workbook[title].protection, action) is True, (
            f"{title} now permits {action}; only the Risk Register should")


def test_filtering_is_usable_because_a_filter_already_exists(workbook):
    """Unprotecting autoFilter permits USING a filter, not creating one. Without one on the
    sheet the permission would be inert - which is the shape of the defect it is fixing."""
    assert workbook["Risk Register"].auto_filter.ref, (
        "no autofilter on the Risk Register, so permitting autoFilter grants nothing")


def test_the_cap_is_a_default_not_a_limit_and_is_documented():
    """C-2's other half: 40 is `build_template`'s default, and a bigger register is a
    regeneration. If that stops being true, the recipe is wrong and should red here."""
    import inspect

    from tools.register_scaffold import build_template

    default = inspect.signature(build_template).parameters["n_blank_input_rows"].default
    assert default == 40, f"the shipped default moved to {default}; update run-recipes.md"

    recipes = (REPO / "docs" / "run-recipes.md").read_text(encoding="utf-8")
    assert "n_blank_input_rows" in recipes, (
        "the regeneration parameter is not documented, so the cap has no in-repo answer")


# --- the TOC must not contradict itself -----------------------------------------------------

def test_the_tab_list_does_not_tell_the_user_to_ignore_a_tab_the_run_section_needs(toc_cells):
    """Caught at the Claude-in-Excel read-back, and it is the reason that step exists.

    Part C's run section (STEP 2) sends the user to `MC_Params` for the day rate, because
    `MC_day_rate` resolves to `MC_Params!$C$11` and feeds Summary, the register's AD column and
    the EMV tab. The tab list, three screens above, called that tab "Legacy VBA config surface
    (Settings is the live one)" - so a generalist reading top to bottom skipped it and left
    every schedule-dollar figure at zero.

    The functional review had this as a latent WARN. Adding the run section turned it into a
    contradiction inside one document, which is worse: two instructions, both apparently
    authoritative, and no way for the reader to tell which is wrong.
    """
    dismissals = ("legacy", "ignore", "not used", "superseded")
    mc_row = next((int(k[1:]) for k, v in toc_cells.items()
                   if k.startswith("A") and str(v) == "MC_Params"), None)
    assert mc_row is not None, "MC_Params is not in the tab list"
    description = str(toc_cells.get(f"B{mc_row}", ""))
    assert not any(d in description.lower() for d in dismissals), (
        f"the tab list dismisses MC_Params ({description!r}) while the run section sends the "
        f"user there for the day rate - the TOC contradicts itself"
    )
    assert "day rate" in description.lower(), (
        "the MC_Params tab description does not mention the day rate, which is the one value "
        "a generalist must put there for any schedule-dollar figure to be non-zero")


def test_row_insertion_stays_locked_and_the_toc_says_so(workbook, toc_cells):
    """A named decision, not an omission (Director read-back, 04/09).

    `insertRows` was granted at C-2 and withdrawn the same day: the flag was right, but Excel
    inserts a WHOLE row and every data row carries locked cells at AB/AC/AD - the EMV formula
    columns - plus everything from AF out, so the insert is refused across the row. Measured
    against 0, 20 and 956 unlocked rows below the data: refused in all three. Permitting it
    would advertise a capability the workbook does not have.

    So the assertion is that it stays locked AND that the TOC tells the user what to do
    instead - a locked flag with no explanation is how the next person re-opens this.
    """
    assert workbook["Risk Register"].protection.insertRows is True, (
        "row insertion is permitted again; it cannot work while the EMV columns are locked, "
        "and granting it advertises a capability the workbook does not have")

    from openpyxl.utils import get_column_letter
    ws = workbook["Risk Register"]
    locked_in_row = [get_column_letter(c) for c in range(1, 40)
                     if ws.cell(row=10, column=c).protection.locked]
    assert {"AB", "AC", "AD"} <= set(locked_in_row), (
        f"the EMV columns are no longer locked in a data row ({locked_in_row}) - if that is "
        "deliberate, row insertion may now be possible and this decision should be revisited")

    text = _text(toc_cells).lower()
    assert "cannot insert a row" in text or "cannot insert" in text, (
        "the TOC does not tell the user that row insertion is unavailable")
    assert "unprotect sheet" in text, (
        "the TOC does not say what to do instead of inserting a row")
