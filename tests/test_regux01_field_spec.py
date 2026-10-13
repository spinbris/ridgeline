"""REGUX-01 B-1: the documented formats cannot drift from the code that defines them.

Writing correct instructions is the easy half and the half that rots. `SOFTWARE_USER_GUIDE.md`
§3.1 was correct when written and now describes a workbook that no longer exists; nothing failed
when it stopped being true. This suite is what makes `src/register_field_spec.py` different: every
enumerated value it publishes is asserted against the parser constant that enforces it, and every
column on a fillable sheet must have a spec.
"""
from __future__ import annotations

import openpyxl
import pytest

from src.register_field_spec import (
    FIELD_SPECS,
    FILLABLE_SHEETS,
    NOT_CONSUMED,
    note_lines,
    specs_for,
)

TEMPLATE = "templates/register_template.xlsx"


@pytest.fixture(scope="module")
def headers() -> dict[str, list[str]]:
    """Header text per fillable sheet, read from the shipped template."""
    wb = openpyxl.load_workbook(TEMPLATE, read_only=True)
    try:
        out: dict[str, list[str]] = {}
        for sheet in FILLABLE_SHEETS:
            ws = wb[sheet]
            # The RICHEST row in the first twenty, not the first populated one: the Risk Register
            # carries a section band above its headers, and taking the first row with a few
            # cells picks the band. Found by this suite failing on its own fixture. Twenty rows
            # because part 3 writes a note block above the list sheets' headers - one cell per
            # row, so the header stays the richest - and the readers scan twenty.
            best: list[str] = []
            for row in ws.iter_rows(min_row=1, max_row=20, values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if len(cells) > len(best):
                    best = cells
            out[sheet] = best
        return out
    finally:
        wb.close()


class TestTheSpecCannotDriftFromTheParsers:
    def test_the_injection_methods_are_the_parsers_own_list(self):
        """The three legal values are published to the filler from one place and enforced from
        another. Asserted equal so a value added to the parser without the workbook - or the
        reverse - fails here rather than at a client's desk."""
        from src.qra_register_parse import _INJECTION_METHOD_NAMES

        spec = next(f for f in FIELD_SPECS if f.column == "Injection_Method")
        assert spec.legal_values is not None
        assert set(spec.legal_values) == set(_INJECTION_METHOD_NAMES), (
            "the documented Injection_Method values no longer match "
            "qra_register_parse._INJECTION_METHOD_NAMES")

    def test_the_modes_are_the_engines_own_multiplier_keys(self):
        """Mode is documented as Series/Hybrid/Parallel because those are the multiplier rows the
        methodology grid carries; a fourth mode would have to appear in both."""
        from src.qra_register_parse import _MODE_MULTIPLIER_NAMES

        spec = next(f for f in FIELD_SPECS if f.column == "Mode")
        assert spec.legal_values is not None
        assert set(spec.legal_values) == set(_MODE_MULTIPLIER_NAMES)

    def test_every_documented_distribution_is_one_the_sampler_handles(self):
        """A distribution offered to a filler that the sampler cannot draw is a dropdown leading
        to a crash."""
        import src.distributions as dist

        spec = next(f for f in FIELD_SPECS if f.column == "Distribution")
        assert spec.legal_values is not None
        doc = (dist.__doc__ or "")
        missing = [v for v in spec.legal_values if v not in doc]
        assert not missing, (
            f"documented distributions absent from src/distributions.py: {missing}")


class TestEveryFillableColumnCanBeExplained:
    def test_the_template_still_has_the_sheets_the_spec_describes(self, headers):
        """A spec for a sheet that no longer exists is worse than no spec: it reads as current."""
        missing = [s for s in FILLABLE_SHEETS if s not in headers]
        assert not missing, f"fillable sheets absent from the template: {missing}"

    @pytest.mark.parametrize("sheet", FILLABLE_SHEETS)
    def test_every_specified_column_still_exists_on_its_sheet(self, sheet, headers):
        """The other direction: a renamed column silently orphans its guidance."""
        present = set(headers[sheet])
        orphaned = [f.column for f in specs_for(sheet) if f.column not in present]
        assert not orphaned, (
            f"{sheet}: specs describe columns the sheet no longer has: {orphaned}")

    def test_the_columns_that_reach_nothing_are_named_as_such(self):
        """Three columns are read into the frame and never used. Saying so is the useful answer -
        a filler inventing a confidence scale is spending effort the model cannot see."""
        unconsumed = [f.column for f in FIELD_SPECS if f.consumed_by == NOT_CONSUMED]
        assert len(unconsumed) >= 3, (
            "the not-consumed columns have lost their label; if one is now read by the engine, "
            "give it a real consumed_by and a real format")

    def test_every_spec_says_something_a_filler_could_act_on(self):
        """Guidance that restates the column name teaches nothing. Cheap to check, and it is the
        failure mode of documentation written to satisfy a checklist."""
        for f in FIELD_SPECS:
            assert len(f.guidance) > 40, f"{f.sheet}.{f.column}: guidance is too thin to act on"
            assert f.column.lower().replace("_", " ") not in f.guidance.lower()[:len(f.column) + 2], (
                f"{f.sheet}.{f.column}: guidance opens by restating the column name")


class TestTheNoteBlockIsUsable:
    @pytest.mark.parametrize("sheet", FILLABLE_SHEETS)
    def test_a_sheet_with_specs_renders_a_note_block(self, sheet):
        lines = note_lines(sheet)
        if specs_for(sheet):
            assert lines and all(line.strip() for line in lines)

    def test_enumerated_values_reach_the_filler(self):
        """The legal values are the single most useful thing on the Mapping sheet, so they must
        appear in the rendered text and not only in the dataclass."""
        text = " ".join(note_lines("Mapping"))
        assert "additive_pert_days" in text
        assert "Blank =" in text, "blank-means guidance is not rendered"
