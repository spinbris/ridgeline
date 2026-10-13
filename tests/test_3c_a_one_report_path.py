"""3c Part A A-4: one report path, and nothing left that could be mistaken for a second.

R-4 rules one report path. That is only true while the retired one stays gone AND no manual
still describes it as present - a reader who finds ``run_report.py`` named in the README will
reasonably conclude the product has two report paths, whatever the tree says. Both halves are
asserted here (SPEC §9.3, §9.5).

The sweep sees tracked plus untracked-not-ignored files, the visibility rule
``scripts/client_gate.py`` applies (GATESCOPE-01) and the one Part B's guard had to be fixed to
use: a check that cannot see an uncommitted file is not a check.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.git_identity import git_env

REPO = Path(__file__).resolve().parents[1]

#: Retired by R-4 and A-4: the second report path, the entry points that drove it, and the two
#: builders that could only edit a notebook that no longer exists.
RETIRED_AT_PART_A = (
    "run_report.py",
    "export_report.py",
    "RUN_REPORT.bat",
    "RUN_SRA.bat",
    "RUN_INTEGRATED.bat",
    "RUN_INTEGRATED_alternate.bat",
    "RUN_FINAL_alternate.bat",
    "scripts/_build_final_runner_notebook.py",
    "scripts/_build_final_runner_v3.py",
)

#: The retired notebooks' ``.gitignore`` negations go with the notebooks (SPEC §9.5).
RETIRED_NEGATIONS = (
    "!outputs/report_template.ipynb",
    "!outputs/client_runner.ipynb",
    "!outputs/client_appendices.ipynb",
)

#: Files that may still name a retired entry point, because their subject IS the history or
#: the absence: the spec and roadmap cite it, the records and briefs quote what was found, the
#: changelog is a log, and a guard that asserts a file is gone has to spell its name to do so.
#: ``tests/`` is exempt for that last reason, and only that reason - the property this test
#: holds is about **manuals**, which are what a reader would believe.
HISTORY_PREFIXES = ("docs/programme/", "docs/running_records/", "docs/stage_briefs/",  # link-rule: the retired-path scan exempts the private records when they are present
                    "docs/OPEN_THREADS.md", "docs/OPEN_THREADS_archive.md", "CHANGELOG.md", "tests/")  # link-rule: the retired-path scan exempts the private records when they are present


@pytest.fixture(scope="module")
def visible_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, check=True, env=git_env())
    return [p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def test_the_retired_report_path_is_gone(visible_files):
    present = [f for f in RETIRED_AT_PART_A if f in visible_files or (REPO / f).exists()]
    assert present == [], f"R-4 allows one report path; these are still here: {present}"


def test_the_gitignore_negations_went_with_the_notebooks():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    still_there = [n for n in RETIRED_NEGATIONS if n in text]
    assert still_there == [], still_there


def test_data_is_ignored_because_period_json_is_engagement_material():
    """SPEC §7a. Added by RS-A2 rather than 3c, and asserted here so it stays."""
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "data/*" in text or "data/" in text


def test_no_manual_describes_a_retired_entry_point_as_present(visible_files):
    """§9.3's half that a deletion alone does not achieve."""
    offenders: dict[str, list[str]] = {}
    for rel in visible_files:
        if rel.startswith(HISTORY_PREFIXES) or not rel.endswith((".md", ".bat", ".py", ".ipynb")):
            continue
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        named = [name for name in RETIRED_AT_PART_A if Path(name).name in text]
        if named:
            offenders[rel] = named
    assert offenders == {}, (
        "these still name a retired entry point, so a reader would conclude the product has "
        f"more than one report path: {offenders}"
    )


def test_the_deliverable_notebook_is_tracked_and_is_the_only_one(visible_files):
    notebooks = [f for f in visible_files if f.endswith(".ipynb")]
    assert notebooks == ["final_runner.ipynb"], notebooks


def test_the_notebook_names_no_project_and_raises_last():
    """A-1's portability rule, and D-11's ordering, read off the artefact itself."""
    nb = json.loads((REPO / "final_runner.ipynb").read_text(encoding="utf-8"))
    cells = nb["cells"]

    code_cells = [c for c in cells if c["cell_type"] == "code"]
    last = "".join(code_cells[-1]["source"])
    assert "raise_if_failed()" in last, (
        "the last code cell must be D-11's refusal; anything after it would not execute on a "
        "failing run, which is how the previous notebook's comment and code came to disagree"
    )

    # No project name baked into any cell: the title comes from the binding at run time.
    source = "\n".join("".join(c["source"]) for c in cells)
    for literal in ("refproject", "RefProject", "synthetic_wind", "SyntheticWind"):
        assert literal not in source, (
            f"{literal!r} is baked into the notebook; the title cell must derive from the "
            f"binding's display name (A-1, the RS-A2 portability rule)"
        )


def test_the_runner_sets_no_path_and_no_project():
    """A-1 / §6c: the entry point carries no literal input path and no default project."""
    text = (REPO / "RUN_FINAL.bat").read_text(encoding="utf-8")
    assert "set QRA_PROJECT=" not in text, "the runner picks a project for the operator"
    for var in ("REGISTER_FILE", "P6_FILE", "STRAWMAN_FILE"):
        assert f"set {var}=" not in text, f"the runner hardcodes {var}"
        assert var in text, f"the runner should still REFUSE on an unset {var}"
    # No literal input path. Checked on the executable lines only: the header comments name
    # the file types an operator has to supply, which is documentation, not a hardcoded path.
    executable = [
        line for line in text.splitlines()
        if line.strip() and not line.strip().upper().startswith("REM")
    ]
    for line in executable:
        assert ".xlsx" not in line and ".xer" not in line, (
            f"an input filename appears in an executable line of the runner: {line!r}")
        assert ":\\" not in line and "\\\\" not in line, (
            f"an absolute path appears in an executable line of the runner: {line!r}")

    # D-12: the retired path's PDF does not come back. Executable lines only - the header
    # comment says "there is no PDF", and a check that cannot tell a prohibition from its
    # own statement is not checking anything.
    for line in executable:
        assert "pdf" not in line.lower(), f"the runner produces a PDF: {line!r}"
