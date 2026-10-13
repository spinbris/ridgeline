"""DASHGATE-01 P2: `dashboard/publish.json` is P1's answer, written down.

The dashboard copy reads the committed file; the bindings decide it, and the deploy guard asks the
bindings directly. This holds the file equal to the bindings, so a binding changed without
regenerating the list reds here rather than the copy shipping the old answer.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "release"))

import write_publish_list  # noqa: E402

from src.sra.cpm.bindings import get_binding  # noqa: E402
from src.sra.cpm.bindings.registry import publishable_projects  # noqa: E402


def test_the_committed_list_is_the_bindings_answer():
    assert write_publish_list.main(["--check"]) == 0
    listed = json.loads((REPO / "dashboard" / "publish.json").read_text(encoding="utf-8"))
    assert listed["projects"] == publishable_projects() == ["synthetic_wind"]


def test_the_check_reds_when_a_binding_changes_and_the_list_does_not(monkeypatch):
    import src.sra.cpm.bindings.registry as registry

    road = get_binding("synthetic_road")
    monkeypatch.setitem(registry._REGISTRY, "synthetic_road", dataclasses.replace(road, publish=True))
    assert publishable_projects() == ["synthetic_road", "synthetic_wind"]
    assert write_publish_list.main(["--check"]) == 1


def test_the_copy_reads_the_file_and_the_guard_asks_the_bindings():
    """Round 1, W2: the docs describe this split, so it is pinned where the code makes it."""
    import inspect

    from src.am.publish_period import guard_build_output

    copier = (REPO / "dashboard" / "scripts" / "copy-data.js").read_text(encoding="utf-8")
    assert "publish.json" in copier, "the dashboard copy no longer reads publish.json"
    guard = inspect.getsource(guard_build_output)
    assert "publishable_projects()" in guard, "the guard no longer asks the bindings"
    assert "publish.json" not in guard.split('"""')[2], "the guard now reads publish.json"


def test_no_copy_of_the_design_says_the_guard_reads_the_file():
    stale = "deploy guard read"
    for rel in ("dashboard/README.md", "src/sra/cpm/bindings/registry.py",
                "scripts/release/write_publish_list.py", "docs/RELEASE_PROCEDURE_dashboard.md"):
        text = " ".join((REPO / rel).read_text(encoding="utf-8").split())
        assert stale not in text, rel
