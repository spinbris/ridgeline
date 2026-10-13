"""VENVGUARD-01: an entry point runs on the repository's own interpreter, or refuses.

A bare `python` in a batch file resolves to whatever is first on PATH. On the Builder's machine
that is a global 3.13 without pytest-xdist and off the lock's scipy patch - the interpreter that
produced serial lanes and false pinned-value failures three times before the pitfalls notes wrote it
down. RUN_FINAL.bat produces client numbers, so its interpreter is part of what they are.
PUBLISH_PERIOD.bat already refused without the venv; RUN_FINAL.bat and RUN_PERIOD.bat did not.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
VENV_PY = r".venv\Scripts\python.exe"
GUARD = f'if not exist "{VENV_PY}"'
BARE_PYTHON = re.compile(r"^\s*python(?:\.exe)?\s", re.IGNORECASE)
ANY_PYTHON = re.compile(r"python(?:\.exe)?\s+-", re.IGNORECASE)


def _executable(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().upper().startswith(("REM", "::"))]


ENTRY_POINTS = sorted(p for p in REPO.glob("*.bat") if any(ANY_PYTHON.search(ln) for ln in _executable(p)))


def test_the_entry_points_are_found():
    names = {p.name for p in ENTRY_POINTS}
    assert {"RUN_FINAL.bat", "RUN_PERIOD.bat", "PUBLISH_PERIOD.bat"} <= names, names


@pytest.mark.parametrize("bat", ENTRY_POINTS, ids=lambda p: p.name)
def test_no_entry_point_runs_a_bare_python(bat):
    bare = [ln for ln in _executable(bat) if BARE_PYTHON.match(ln)]
    assert not bare, f"{bat.name} runs whatever python is first on PATH: {bare}"


@pytest.mark.parametrize("bat", ENTRY_POINTS, ids=lambda p: p.name)
def test_every_entry_point_refuses_before_it_runs_python(bat):
    lines = _executable(bat)
    guard = next((i for i, ln in enumerate(lines) if ln.startswith(GUARD)), None)
    first_run = next(i for i, ln in enumerate(lines) if ANY_PYTHON.search(ln))
    assert guard is not None, f"{bat.name} has no refusal when {VENV_PY} is absent"
    assert guard < first_run, f"{bat.name} runs python before it checks for {VENV_PY}"
