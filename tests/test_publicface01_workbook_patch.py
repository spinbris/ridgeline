"""PUBLICFACE-01: the creator patch changes the parts that carry the name and nothing else.

``scripts/set_workbook_creator.py`` is run on a copy of a workbook that names the old creator, and the
result is compared with it member by member: the parts that held the name differ by the name and
nothing else, every other part is byte-identical, and the member list, order, compression and
timestamps are unchanged. The tracked polished golden is then checked as it stands.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl

from scripts.set_workbook_creator import DEFAULT_TARGET, patch_workbook
from src.final.product import MAKER

REPO = Path(__file__).resolve().parents[1]
#: The old creator, a third party's registered name, built so this file does not carry it.
OLD_NAME = "S" + "JP Consulting"
OLD, NEW = OLD_NAME.encode(), MAKER.encode()


def _workbook_naming_the_old_creator(path: Path) -> None:
    wb = openpyxl.Workbook()
    wb.properties.creator = OLD_NAME
    ws = wb.active
    ws.title = "TOC & Instructions"
    ws["B61"] = OLD_NAME
    ws["B62"] = "something else, untouched"
    wb.create_sheet("Other")["A1"] = 42
    wb.save(path)


def test_the_patch_changes_the_carrying_parts_by_the_name_and_nothing_else(tmp_path):
    src, dst = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    _workbook_naming_the_old_creator(src)
    changed = patch_workbook(src, dst, OLD_NAME)
    assert "docProps/core.xml" in changed and len(changed) >= 2, changed
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        assert a.namelist() == b.namelist(), "member list or order moved"
        for ia, ib in zip(a.infolist(), b.infolist()):
            assert (ia.compress_type, ia.date_time) == (ib.compress_type, ib.date_time), ia.filename
        differing = [n for n in a.namelist() if a.read(n) != b.read(n)]
        assert sorted(differing) == sorted(changed)
        for name in differing:
            assert a.read(name).replace(OLD, NEW) == b.read(name), f"{name}: more than the name changed"
        assert all(OLD not in b.read(n) for n in b.namelist())
    wb = openpyxl.load_workbook(dst)
    assert wb["TOC & Instructions"]["B61"].value == MAKER
    assert wb["TOC & Instructions"]["B62"].value == "something else, untouched"
    assert wb.properties.creator == MAKER


def test_a_workbook_free_of_the_name_is_left_alone(tmp_path):
    src, dst = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    wb = openpyxl.Workbook()
    wb.properties.creator = MAKER
    wb.save(src)
    assert patch_workbook(src, dst, OLD_NAME) == []
    assert not dst.exists()


def test_the_check_can_fail_when_a_part_still_holds_the_name(tmp_path):
    """A patch that missed a part would leave the name behind; the assertion above sees it."""
    src, dst = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    _workbook_naming_the_old_creator(src)
    patch_workbook(src, dst, old="not the creator")  # matches nothing: leaves the name in place
    assert not dst.exists()
    with zipfile.ZipFile(src) as z:
        assert any(OLD in z.read(n) for n in z.namelist())


def test_the_tracked_polished_golden_names_the_maker_and_still_opens():
    with zipfile.ZipFile(DEFAULT_TARGET) as z:
        assert all(OLD not in z.read(n) for n in z.namelist())
        assert len(z.namelist()) == 41
    wb = openpyxl.load_workbook(DEFAULT_TARGET)
    assert wb["TOC & Instructions"]["B61"].value == MAKER
    assert wb.properties.creator == MAKER
    assert patch_workbook(DEFAULT_TARGET, REPO / "outputs" / "never_written.xlsx", OLD_NAME) == []
