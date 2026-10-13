"""3c Part B (SPEC 1.2 §6c, §2a): the workspace property and the "3c decides" dispositions.

Properties: the files 3c retired are gone; no tracked or untracked file outside the history
allow-list carries the undefined root placeholder (spelled only in ``ROOT_LITERAL`` below, in two
halves, so this file is not its own hit), except a named, dated allowance for the five
pre-3c ``.bat`` entry points that Part A rebuilds (the allowance shrinks there, never grows);
the run recipes carry neither the root nor a retired entry point; the two P6 readers (F-D) are
kept as distinct shapes for distinct consumers, and agree on what they read.

The file walk is ``git ls-files --cached --others --exclude-standard``: tracked plus untracked
not-ignored files, the same visibility rule ``scripts/client_gate.py`` applies (GATESCOPE-01).
The first version listed tracked files only, so a new file in the working tree was invisible
until it was committed - the guard passed here and failed in the fresh clone on its own
docstring. A sweep that cannot see the file being written is not a sweep.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.git_identity import git_env

REPO = Path(__file__).resolve().parents[1]
ROOT_LITERAL = "%OUTTURN" + "_ROOT%"  # split so this file is not itself a hit

RETIRED_AT_PART_B = (
    "run_from_excel.py", "run_single_only.py", "run_assumptions_from_excel.py",
    "setup_vba.py", "vba_module.bas", "check_dist.py",
    "run_toc_sensitivity.py", "diagnose_reader_diff.py",
)

#: Files that may cite the root as history: the spec and roadmap (by reference), the
#: running records, briefs and the ledger (they quote what was found), the changelog.
HISTORY_ALLOWLIST_PREFIXES = ("docs/programme/", "docs/running_records/", "docs/stage_briefs/", "docs/OPEN_THREADS.md", "docs/OPEN_THREADS_archive.md", "CHANGELOG.md")  # link-rule: the workspace scan exempts the private records when they are present

#: EMPTIED at 3c Part A, as Part B said it would be. ``RUN_FINAL.bat`` was rebuilt to the
#: property - it sets nothing it was not given and refuses on an unset path - and the other
#: four were retired as separate entry points, their content now cells of the one notebook.
#: Nothing may ever be added here: an entry point that needs the undefined root has not been
#: rebuilt, and the sweep below is what says so.
PRE_3C_BAT_ALLOWANCE: tuple[str, ...] = ()


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, check=True, env=git_env())
    return [p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def test_retired_files_are_gone(tracked):
    present = [f for f in RETIRED_AT_PART_B if f in tracked or (REPO / f).exists()]
    assert present == [], present


def test_no_tracked_file_carries_the_root_outside_history_and_the_named_allowance(tracked):
    carriers = []
    for rel in tracked:
        p = REPO / rel
        if p.suffix in {".xlsx", ".xer", ".png", ".json"} or not p.is_file():
            continue
        try:
            if ROOT_LITERAL in p.read_text(encoding="utf-8", errors="ignore"):
                carriers.append(rel)
        except OSError:
            continue
    unexplained = [c for c in carriers
                   if not c.startswith(HISTORY_ALLOWLIST_PREFIXES) and c not in PRE_3C_BAT_ALLOWANCE]
    assert unexplained == [], f"the undefined root appears in: {unexplained}"


def test_run_recipes_carry_neither_the_root_nor_a_retired_entry_point():
    text = (REPO / "docs" / "run-recipes.md").read_text(encoding="utf-8")
    assert ROOT_LITERAL not in text
    body = text.split("## Retired (do not look for these)")[0]  # the retired list may name them once
    for name in RETIRED_AT_PART_B + ("RUN_REPORT.bat",):
        assert name not in body, name


def test_the_two_p6_readers_are_distinct_shapes_that_agree(tmp_path):
    """F-D disposition: both readers stay. The SR1 reader returns a DataFrame for the
    diagnostics and their tests; the strawman reader returns activity dicts for the strawman
    builder and the CP classifier. Different consumers, different shapes, one P6 export - so
    they must agree on what is in it."""
    import openpyxl
    from src.sra.p6_reader import read_p6_schedule as read_df
    from src.sra_strawman.p6_reader import activity_rows, read_p6_schedule as read_rows

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "P6-Schedule"
    # one header row both readers accept: the strawman reader wants Level and Duration and
    # forces column B to the WBS-summary flag (a column-letter override); the SR1 reader wants
    # a name, dates and a float column
    headers = ["Level", "WBS", "Activity ID", "Activity Name", "Duration", "Start", "Finish", "Total Float", "Critical"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    rows = [(3, None, "A1000", "Mobilise", 10, "2026-01-05", "2026-01-16", 0, "Yes"),
            (3, None, "A1010", "Civils", 20, "2026-01-19", "2026-02-13", 5, "No")]
    for r, row in enumerate(rows, start=2):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    path = tmp_path / "p6.xlsx"; wb.save(str(path))

    df = read_df(path)
    dicts = activity_rows(read_rows(path))
    assert list(df["activity_id"]) == [d["activity_id"] for d in dicts] == ["A1000", "A1010"]
