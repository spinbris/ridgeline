"""REGUX-01 A-0: the register can be filled at all.

The workbook's legend says blue cells are yours. As shipped, ten of eighteen sheets had nothing
unlocked — including four named deliverables, the day rate the TOC instructs twice, and the project
identity block that is the first thing anyone types. Meanwhile the model's own write-back area had
237 unlocked cells.

**What this suite can and cannot establish.** It holds the invariant against regression. It does
**not** establish that Excel honours it: `insertRows` was set correctly by this same scaffolder and
Excel ignored it entirely (`register_scaffold.py:1575-1588`). Acceptance is a person typing in the
file — REGUX-01 §6a. A green run here is necessary and nowhere near sufficient.
"""
from __future__ import annotations

import openpyxl
import pytest

TEMPLATE = "templates/register_template.xlsx"
INPUT_BLUE = "000000CC"

#: Sheets a person fills by hand. Every one must accept input somewhere, or the workbook
#: instructs an analyst to do something the file refuses.
MUST_ACCEPT_INPUT = (
    "TOC & Instructions",        # project identity — the first thing anyone types
    "Risk Register",
    "Mapping",
    "Risk_Activity_Patterns",
    "Risk_Pattern_Assignments",
    "Treatments",
    "MC_Params",                 # incl. C11, the day rate the TOC instructs twice
    "Settings",
    "Methodology",
    "Lists",
    # REGUX-01 A-0.4: the Layer-1 grids exist now, and the TOC's fill procedure can be followed
    "Layer1_Base",
    "Layer1_Factors",
    "Layer1_Allocation",
    "Layer1_Correlation",
)

#: Blue cells that are locked ON PURPOSE, and why. This list is a **debt register, not an
#: allowance**: each entry is a cell whose STYLE is wrong rather than its protection, and the fix
#: is to restyle it. The count is ratcheted below so the debt can shrink and cannot grow.
STYLING_DEBT = {
    "TOC & Instructions": "A27 is the legend's own 'input' swatch — it demonstrates blue",
}
#: Measured after stage 4 F-30, which made the Methodology settings rows inputs (unlock by style).
#: Was 11 after REGUX-01 A-0.4, 22 after part 2a and 42 before it.
STYLING_DEBT_CEILING = 1


@pytest.fixture(scope="module")
def wb():
    book = openpyxl.load_workbook(TEMPLATE)
    yield book
    book.close()


def _cells(ws, max_row: int = 90):
    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=32):
        yield from row


def _is_blue(cell) -> bool:
    colour = cell.font.color.rgb if (cell.font and cell.font.color and cell.font.color.rgb) else None
    return str(colour) == INPUT_BLUE


def _locked(cell) -> bool:
    return True if cell.protection is None else bool(cell.protection.locked)


class TestTheWorkbookCanBeFilled:
    @pytest.mark.parametrize("sheet", MUST_ACCEPT_INPUT)
    def test_every_sheet_an_analyst_fills_accepts_input_somewhere(self, sheet, wb):
        """**The property the whole part exists for.** Before REGUX-01 six of these ten had zero
        unlocked cells, so the workbook instructed an analyst to fill sheets that refuse."""
        unlocked = sum(1 for c in _cells(wb[sheet]) if not _locked(c))
        assert unlocked > 0, (
            f"{sheet} has no unlocked cells: an analyst told to fill it cannot type in it")

    def test_the_day_rate_cell_accepts_input(self, wb):
        """Named because the TOC instructs it twice, and because every schedule-dollar figure in
        the workbook reads zero until it is filled — silently."""
        assert not _locked(wb["MC_Params"]["C11"])

    def test_the_project_identity_block_accepts_input(self, wb):
        """The first thing anyone types, and the first thing that refused. The review's own point
        was that trust in the whole legend goes at this cell."""
        for ref in ("B61", "B62", "B63", "B64", "B65", "B66"):
            assert not _locked(wb["TOC & Instructions"][ref]), f"TOC!{ref} is locked"

    def test_the_four_list_sheets_read_as_forms_not_scratch_sheets(self, wb):
        """They shipped as a header row over blank space — no styled body, nothing unlocked. A
        body is what makes them a form, and what makes them unlockable at all: `_unlock` clamps
        to the sheet extent, and a header-only sheet clamps to nothing."""
        for sheet in ("Mapping", "Risk_Activity_Patterns",
                      "Risk_Pattern_Assignments", "Treatments"):
            blue = sum(1 for c in _cells(wb[sheet]) if _is_blue(c))
            assert blue > 0, f"{sheet} has no input-styled cells"


class TestTheFiveTableSheetsBehaveAsForms:
    """§5.4's five list-shaped sheets carry a Table, and their protection permits what a Table is
    for. A-0.6 (08/09): `insertRows` is granted here and only here - Excel was asked first, and a
    whole row inserts inside each Table under protection (scripts/ask_excel_register.py). On the
    Risk Register the same flag is inert, because locked formula cells sit across every row."""
    TABLE_SHEETS = ("Mapping", "Risk_Activity_Patterns", "Risk_Pattern_Assignments",
                    "Treatments", "Layer1_Factors")

    @pytest.mark.parametrize("sheet", TABLE_SHEETS)
    def test_a_table_over_the_body_and_the_permissions_it_needs(self, sheet, wb):
        ws = wb[sheet]
        assert list(ws.tables) == [f"tbl{sheet}"]
        # OOXML flags mark what is BLOCKED: False is permitted (see _permit)
        assert ws.protection.sort is False
        assert ws.protection.autoFilter is False
        assert ws.protection.insertRows is False

    def test_the_risk_register_does_not_get_insert_rows(self, wb):
        """Its locked EMV columns make the flag inert; granting it would advertise a capability
        the sheet cannot honour (3c C-2, measured by the Director in Excel)."""
        assert wb["Risk Register"].protection.insertRows is True


class TestTheStylingDebtRatchets:
    def test_blue_but_locked_cells_do_not_increase(self, wb):
        """A blue cell that refuses input is the workbook contradicting its own legend. Twenty-two
        remain, each one a cell whose STYLE is wrong rather than its protection - listed in
        `STYLING_DEBT` with the reason. Ratcheted so the debt can shrink and cannot grow."""
        offenders = [
            f"{name}!{c.coordinate}"
            for name in wb.sheetnames
            for c in _cells(wb[name])
            if _is_blue(c) and _locked(c)
        ]
        assert len(offenders) <= STYLING_DEBT_CEILING, (
            f"{len(offenders)} blue-but-locked cells, ceiling {STYLING_DEBT_CEILING}. "
            f"New ones: {offenders[:10]}")

    def test_every_sheet_carrying_debt_says_why(self, wb):
        """A ratchet with no reasons attached decays into a number nobody can act on."""
        with_debt = {
            name for name in wb.sheetnames
            for c in _cells(wb[name]) if _is_blue(c) and _locked(c)
        }
        undocumented = sorted(with_debt - set(STYLING_DEBT))
        assert not undocumented, (
            f"sheets carrying blue-but-locked cells with no recorded reason: {undocumented}")
