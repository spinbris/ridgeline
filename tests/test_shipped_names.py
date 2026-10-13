"""SNAPSHOTCUT-01, gate 3 round 2 findings 1 and 2: no shipped file carries a scrubbed name.

Every file that ships - text, and every member of every zip container (a workbook, a document) - is
searched for the names in ``scripts/release/name_checks.py``: this machine's name and home folder,
the note app's name, a third party's first name, and a registered business name and its initials,
typed or disguised. The snapshot builder runs the same search over the cut tree, with every build
machine's name added from a private list.

Red-first: each name is planted in text and inside a workbook's parts below, and each must be named.
"""
from __future__ import annotations

import io
import socket
import zipfile
from pathlib import Path

import pytest

import scripts.release.snapshot_manifest as m
import scripts.release.name_checks as nc

REPO = Path(__file__).resolve().parents[1]
BOOK = "status_periods/p.xlsx"  # path-walker: plant - a workbook the plants go in


def test_no_shipped_file_carries_a_scrubbed_name():
    words = nc.needles()
    found = []
    for p in m.shipped(m.tracked_files()):
        found += nc.file_findings(p, (REPO / m.source(p)).read_bytes(), words)
    assert not found, "shipped files carry a scrubbed name:\n  " + "\n  ".join(found)


def _workbook(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_red_each_name_inside_a_workbooks_parts_is_named():
    """The three shapes gate 3 round 2 planted: a creator, a sheet's text, an application property."""
    host = socket.gethostname()
    if len(host) < nc.MIN_NEEDLE:
        pytest.skip("this machine's name is too short to search for")
    book = _workbook({
        "docProps/core.xml": f"<cp:coreProperties><dc:creator>{nc.BUSINESS[0]}</dc:creator></cp:coreProperties>",
        "xl/sharedStrings.xml": f"<sst><si><t>Reviewed by {nc.THIRD_PARTY}</t></si></sst>",
        "docProps/app.xml": f"<Properties><Company>{host}</Company></Properties>",
    })
    found = nc.file_findings(BOOK, book, nc.needles())
    assert sorted(found) == sorted([
        f"business name: {BOOK}!docProps/core.xml:1",
        f"third party: {BOOK}!xl/sharedStrings.xml:1",
        f"machine name: {BOOK}!docProps/app.xml:1",
    ])


def test_green_a_clean_workbook_and_a_hash_holding_the_initials():
    assert nc.file_findings("p.xlsx", _workbook({"docProps/core.xml": "<dc:creator>a maker</dc:creator>"}),
                            nc.needles()) == []
    lock = '{"integrity": "sha512-vCPvz' + nc.BUSINESS[1].lower() + 'PHEi1siZdlvAlsPx"}'
    assert nc.file_findings("package-lock.json", lock.encode(), nc.needles()) == []


@pytest.mark.parametrize("where, text", [
    ("README.md", "Prepared by " + nc.BUSINESS[0].upper()),
    ("docs/a.md", "| " + nc.BUSINESS[1] + " indicative | 4 |"),  # path-walker: plant
    ("pyproject.toml", 'authors = [{name = "' + nc.BUSINESS[1].lower() + '_theme"}]'),
    ("docs/b.md", nc.BUSINESS[0][:3] + "?" + nc.BUSINESS[0][4:]),  # path-walker: plant
])
def test_red_the_business_name_is_named_wherever_it_is_planted(where, text):
    assert nc.file_findings(where, ("x\n" + text + "\n").encode(), nc.needles()) == [f"business name: {where}:2"]


# --- the client's identifiers (task -9, Director 10/10/2026) ------------------------------------
#
# Found by ``nc.client_findings``: register and export names by words built from parts, the job
# number and register versions by shape, the project acronym by its hash. Plants below use made-up
# values of the same shape, or the words as ``name_checks`` builds them, so this file names none.

def test_no_shipped_file_carries_a_client_identifier():
    found = []
    for p in m.shipped(m.tracked_files()):
        found += nc.client_findings(p, (REPO / m.source(p)).read_bytes())
    assert not found, "shipped files carry a client identifier:\n  " + "\n  ".join(found)


#: Plants are joined at run time ("12-345" + "E"), so this file does not itself hold the shape.
@pytest.mark.parametrize("before, after", [
    ("inputs/12-345", "E Project register.xlsx"), ("job 12345", "E"), ("the 12_345 ", "e folder"),
    ("12-345", "E."), ("docs/12345", "eprojectregister_xlsx/"),
])
def test_red_a_job_number_is_found_by_its_shape(before, after):
    text = before + after
    assert nc.client_findings("a.py", ("x\n" + text + "\n").encode()) == ["client job number: a.py:2"]


@pytest.mark.parametrize("text", [
    "color: #92400e;", "0x1.12345e6p+3", "sha 912345e0a", "a12-345E", "2026-10-11 E", "1e-300",
])
def test_green_a_colour_a_float_a_hash_and_a_date_are_not_a_job_number(text):
    assert nc.client_findings("a.css", text.encode()) == []


@pytest.mark.parametrize("before, after", [("the V9", "_val register"), ("V12", "-VAL"),
                                           ("needs_v3", "_val = 1"), ("(v8", "val)")])
def test_red_a_register_version_is_found_by_its_shape(before, after):
    text = before + after
    assert nc.client_findings("a.py", text.encode()) == ["client register version: a.py:1"]


def _disguises(word: str) -> list[str]:
    """Typed, upper case, each separator swapped or dropped, and one letter as a glob character."""
    seps = [c for c in word if c in "-_ ."]
    out = [word, word.upper()]
    for s in "-_ .":
        out.append("".join(s if c in seps else c for c in word))
    out.append("".join(c for c in word if c not in seps))
    out += [word[:1] + "?" + word[2:], word[:-1] + "*", word[:2] + f"[{word[2]}]" + word[3:]]
    return out


@pytest.mark.parametrize("check, word", [(c, w) for c, ws in nc.CLIENT_WORDS.items() for w in ws])
def test_red_a_register_or_export_name_is_found_in_each_disguise(check, word):
    for text in _disguises(word):
        assert nc.client_findings("a.md", text.encode()) == [f"{check}: a.md:1"], text


def test_red_an_acronym_is_found_by_its_hash_standing_alone(monkeypatch):
    """A made-up acronym's hash in place of the client's: found alone in any case, not inside a word."""
    import hashlib
    monkeypatch.setitem(nc.CLIENT_SHAPES, "client project acronym",
                        nc._Hashed(hashlib.sha256(b"QZX").hexdigest()))
    for text in ("the QZX export", "- qzx -", "(Qzx)"):
        assert nc.client_findings("a.py", text.encode()) == ["client project acronym: a.py:1"], text
    for text in ("QZXA", "aqzx", "Q Z X"):
        assert nc.client_findings("a.py", text.encode()) == [], text


def test_an_image_is_searched_only_in_its_printable_runs(monkeypatch):
    """Compressed bytes hold any three letters by chance; text an image carries is a long printable run."""
    import hashlib
    monkeypatch.setitem(nc.CLIENT_SHAPES, "client project acronym",
                        nc._Hashed(hashlib.sha256(b"QZX").hexdigest()))
    noise = b"\x89PNG\r\n\x1a\n\xef\xde\xbdQZX\xa0\xfe\x00\xd0"
    assert nc.client_findings("a.png", noise) == []
    found = nc.client_findings("a.png", noise + b"tEXtAuthor\x00drawn for QZX\x00")
    assert found == ["client project acronym: a.png:2"]  # in a binary file, the line is the printable run


def test_red_a_client_identifier_inside_a_workbooks_part_is_named():
    word = nc.CLIENT_WORDS["client register name"][0]
    book = _workbook({"docProps/core.xml": f"<dc:title>{word} 12-345{'E'}</dc:title>"})
    assert sorted(nc.client_findings(BOOK, book)) == [
        f"client job number: {BOOK}!docProps/core.xml:1", f"client register name: {BOOK}!docProps/core.xml:1"]
