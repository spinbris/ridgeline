"""The client gate's SELF-CONTAINMENT limb follows a climb all the way out (GATEPARENT-01).

`scripts/client_gate.py` reds on a parent traversal that resolves outside the repository. Until
GATEPARENT-01 it matched one parent step and one segment, and a parent step is itself a valid
segment, so three climbs stopped after two: from a file two levels deep that resolves to the
repository root - inside - and the climb out beyond it was never tested.

The limb had no test of its own before this module: `test_client_gate_scope.py` covers which
files are walked, not what the limb finds in them. These are pure - a path and a string, no
repository, no term list, no shell-out. **Every climb here is built at run time** (`_up`), so this
file carries no literal traversal for the gate to find in it; an allowlist entry would exclude
the file from every limb, the client-term scan included.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from client_gate import outside_refs  # noqa: E402

ROOT = REPO_ROOT  # any resolved directory will do; the files below are never opened
UP = ".." + "/"


def _up(n: int, tail: str = "") -> str:
    return UP * n + tail


def _refs(relative_file: str, text: str) -> list[str]:
    return outside_refs(text, ROOT / relative_file, ROOT)


def test_one_climb_out_of_the_root_reds() -> None:
    assert _refs("README.md", "see " + _up(1, "sibling/notes.md")) == [_up(1, "sibling")]


def test_a_climb_that_stays_inside_is_green() -> None:
    assert _refs("docs/a.md", "see " + _up(1, "README.md")) == []
    assert _refs("dashboard/app/x.css", "see " + _up(2, "README.md")) == []


def test_a_two_deep_climb_out_reds() -> None:
    """Two levels down, three climbs, then a sibling repository's file."""
    assert _refs("dashboard/app/globals.css", "/* from " + _up(3, "sibling/theme.scss") + " */") == [
        _up(3, "sibling")]


def test_the_shape_that_used_to_hide() -> None:
    """Two climbs reach the root from two levels down; the third leaves it. The old pattern took
    the first two as its whole match, resolved them inside, and never tested the third."""
    assert _refs("dashboard/app/globals.css", _up(3, "x")) == [_up(3, "x")]
    assert _refs("docs/sub/a.md", _up(3, "sibling/x.md")) == [_up(3, "sibling")]


def test_a_climb_ending_in_a_parent_step_is_still_resolved() -> None:
    assert _refs("docs/a.md", "cd " + _up(1, "..")) == [_up(1, "..")]
    assert _refs("docs/sub/a.md", "cd " + _up(1, "..")) == []


def test_an_ellipsis_is_not_a_climb() -> None:
    assert _refs("README.md", "and so on... then more") == []
