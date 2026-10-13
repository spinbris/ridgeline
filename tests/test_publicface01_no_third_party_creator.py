"""PUBLICFACE-01 P5: the workbooks the repository tracks name no third party.

``git grep`` cannot see inside an .xlsx (declared binary, parts compressed), so the creator is read
the way a reader's file properties dialog reads it: ``docProps/core.xml``, and the ``Set_PreparedBy``
cell the builders write. The scaffold's default is checked at the source, since a default that names
a third party reaches every register built without one.

**The list of files is derived, not kept** (gate 3 round 1, N6): every tracked workbook or Office
document, found with ``git ls-files``. P5's first version named four files and missed
``tests/golden/wind_register_polished.xlsx``, which carried the name in two parts; a list written by
hand is a list that can miss a fifth.
"""
from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path

import openpyxl
import pytest

from src.final.product import MAKER
from src.git_identity import git_env

REPO = Path(__file__).resolve().parents[1]
#: A third party's initials, built so this file does not carry them.
THIRD_PARTY = re.compile("S" + "JP", re.I)
OFFICE_GLOBS = ("*.xlsx", "*.xlsm", "*.docx", "*.dotx", "*.pptx")


def tracked_office_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", *OFFICE_GLOBS], cwd=REPO, env=git_env(),
                         capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


#: The registers, by role: the template and the committed fixtures and golden. Each has a creator
#: and a Set_PreparedBy cell; the period workbooks and the status template do not.
REGISTERS = [
    "templates/register_template.xlsx",
    "tests/fixtures/synthetic_wind/wind_register.xlsx",
    "tests/fixtures/synthetic_road/road_register.xlsx",
    "tests/golden/wind_register_polished.xlsx",
]
WITH_PREPARED_BY_CELL = [r for r in REGISTERS if "fixtures" in r or "polished" in r]


def _core(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("docProps/core.xml").decode("utf-8")


def test_the_check_can_fail(tmp_path):
    planted = tmp_path / "p.xlsx"
    wb = openpyxl.Workbook()
    wb.properties.creator = "S" + "JP Consulting"
    wb.save(planted)
    assert THIRD_PARTY.search(_core(planted))


def test_the_derived_list_sees_every_workbook_the_roles_name():
    """A role list naming a file the derived list does not see would be checking nothing."""
    tracked = tracked_office_files()
    assert tracked, "git ls-files found no workbook"
    assert set(REGISTERS) <= set(tracked), sorted(set(REGISTERS) - set(tracked))
    assert any(f.endswith("wind_period_01.xlsx") for f in tracked)


def test_no_workbook_part_names_a_third_party():
    """Resolved when the test runs, not at import: collection must not need a git repository
    (GOLDCOLL-01's guard collects the suite in a sandbox that is not one)."""
    hits = {}
    for rel in tracked_office_files():
        with zipfile.ZipFile(REPO / rel) as z:
            parts = [n for n in z.namelist()
                     if THIRD_PARTY.search(z.read(n).decode("utf-8", "ignore"))]
        if parts:
            hits[rel] = sorted(parts)
    assert hits == {}, f"workbooks name a third party: {hits}"


@pytest.mark.parametrize("rel", REGISTERS)
def test_the_register_creator_is_the_product_maker(rel):
    assert "<dc:creator" in _core(REPO / rel)
    assert re.search(rf">{re.escape(MAKER)}<", _core(REPO / rel)), f"{rel}: creator is not {MAKER}"


@pytest.mark.parametrize("rel", WITH_PREPARED_BY_CELL)
def test_the_prepared_by_cell_is_the_product_maker(rel):
    wb = openpyxl.load_workbook(REPO / rel, read_only=False)
    cell = wb.defined_names["Set_PreparedBy"].destinations
    (sheet, ref), = list(cell)
    assert wb[sheet][ref.replace("$", "")].value == MAKER


def test_the_scaffold_default_names_no_third_party():
    src = (REPO / "tools" / "register_scaffold.py").read_text(encoding="utf-8")
    assert not THIRD_PARTY.search(src)
