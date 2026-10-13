"""DASHGATE-01 P2: the dashboard copy ships only the projects named for publication, and no ghost.

**What this measures.** The real `dashboard/scripts/copy-data.js`, copied into a scratch folder laid
out as the repository is (`data/`, `dashboard/scripts/`, `dashboard/publish.json`,
`dashboard/public/data/`), so its own `__dirname` paths resolve there, and run by `node`. Nothing
under the real `data/` or `public/data/` is read or written. The declared list is the repository's
own `dashboard/publish.json`, copied in, unless a test writes one.

It shells out to node, so it is `slow` (`tests/conftest.py`'s shell-out guard; that file is on the
escalation list and is not edited).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH"),
]

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"
PERIOD = "period_20260228.json"


def _layout(tmp_path: Path, *, publish: dict | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "dashboard" / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "dashboard" / "scripts" / "copy-data.js", root / "dashboard" / "scripts")
    listed = REPO / "dashboard" / "publish.json"
    if publish is not None:
        (root / "dashboard" / "publish.json").write_text(json.dumps(publish), encoding="utf-8")
    elif listed.exists():
        shutil.copy2(listed, root / "dashboard" / "publish.json")
    for project in ("synthetic_wind", "synthetic_road", "third_unnamed"):
        (root / "data" / project).mkdir(parents=True)
        shutil.copy2(GOLDEN, root / "data" / project / PERIOD)
    shutil.copy2(GOLDEN, root / "data" / PERIOD)  # the pre-part-C flat layout
    ghost = root / "dashboard" / "public" / "data" / "other_project"
    ghost.mkdir(parents=True)
    (ghost / "index.json").write_text('{"periods": []}', encoding="utf-8")
    (root / "dashboard" / "public" / "data" / "index.json").write_text("{}", encoding="utf-8")
    return root


def _copy(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["node", "scripts/copy-data.js"], cwd=root / "dashboard",
                          capture_output=True, text=True, timeout=120)


def test_only_the_named_project_is_shipped_and_no_ghost_remains(tmp_path):
    root = _layout(tmp_path)
    r = _copy(root)
    assert r.returncode == 0, r.stderr
    target = root / "dashboard" / "public" / "data"
    assert sorted(p.name for p in target.iterdir()) == ["projects.json", "synthetic_wind"], (
        f"public/data/ holds more than the named project: {sorted(p.name for p in target.iterdir())}")
    assert json.loads((target / "projects.json").read_text(encoding="utf-8"))["projects"] == [
        "synthetic_wind"]
    assert sorted(p.name for p in (target / "synthetic_wind").iterdir()) == ["index.json", PERIOD]


def test_each_project_left_out_is_named_on_stderr(tmp_path):
    r = _copy(_layout(tmp_path))
    for left_out in ("synthetic_road", "third_unnamed", "_unkeyed"):
        assert left_out in r.stderr, f"{left_out} was left out silently:\n{r.stderr}"


def test_with_nothing_named_the_build_fails_loudly(tmp_path):
    r = _copy(_layout(tmp_path, publish={"projects": []}))
    assert r.returncode != 0, "an empty publish list built a dashboard with nothing in it"
    assert "publish" in r.stderr.lower()


def test_a_named_project_with_no_periods_does_not_ship_an_empty_picker(tmp_path):
    r = _copy(_layout(tmp_path, publish={"projects": ["no_such_project"]}))
    assert r.returncode != 0, "nothing named had any periods, and the build still succeeded"
