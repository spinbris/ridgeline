"""REPORTPAGE-01 property 8: one run, one engine, everywhere it is quoted.

The report page served at ``/report/`` and the committed showcase set quote the same project. They
are produced by two entry points (``RUN_FINAL.bat`` and ``scripts/run_wind_showcase.py``), so
nothing but this file notices when one is re-cut and the other is not. Each carries its own
record - ``dashboard/public/report/provenance.json`` and ``docs/showcase/run/wind_run_meta.json``
- and these tests hold the two to the same engine commit, seed and inputs.

The dashboard period JSON is the third quoter. It is gitignored (``data/``), so CI cannot see it;
its limb runs where the periods exist, which is the machine that publishes them, and skips
elsewhere.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "dashboard" / "public" / "report"
REPORT_MANIFEST = REPORT_DIR / "provenance.json"
SHOWCASE_META = REPO_ROOT / "docs" / "showcase" / "run" / "wind_run_meta.json"
PERIOD_DIR = REPO_ROOT / "data" / "synthetic_wind"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_wind"
INPUTS = {"register": FIXTURE_DIR / "wind_register.xlsx", "xer": FIXTURE_DIR / "wind_schedule.xer"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_oid(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _digest_matches(recorded, path: Path) -> bool:
    """A recorded digest in either shape the repository writes: sha256 hex, or {method, value}."""
    if isinstance(recorded, str):
        return recorded == _sha256(path)
    if recorded.get("method") == "git_blob_oid":
        return recorded.get("value") == _git_blob_oid(path)
    if recorded.get("method") == "sha256":
        return recorded.get("value") == _sha256(path)
    return False


def test_the_report_page_and_the_showcase_name_one_engine_and_one_seed():
    report, showcase = _json(REPORT_MANIFEST), _json(SHOWCASE_META)
    assert report["engine_sha"] == showcase["engine_sha"], (
        f"the report page is engine {report['engine_sha']} and the showcase set is engine "
        f"{showcase['engine_sha']}. Re-cut both from one clean commit (REPORTPAGE-01 property 8)")
    assert report["seed"] == showcase["seed"]
    assert report["iterations"] == showcase["iterations"]
    assert report["engine_tree_dirty"] is False and showcase["engine_tree_dirty"] is False


@pytest.mark.parametrize("name", sorted(INPUTS))
def test_the_report_page_and_the_showcase_ran_on_the_committed_inputs(name):
    """Both records against the fixture as committed, each in its own digest shape."""
    path = INPUTS[name]
    assert _digest_matches(_json(REPORT_MANIFEST)["input_sha256"][name], path), (
        f"the report page's {name} digest is not the committed {path.name}")
    assert _digest_matches(_json(SHOWCASE_META)["input_sha256"][name], path), (
        f"the showcase set's {name} digest is not the committed {path.name}")


def _body_without_label(page: str) -> str:
    """The rendered report as the run wrote it: the page less the banner the label step adds."""
    import re

    body, n = re.subn(r'<div id="reportpage-label".*?</div>', "", page, count=1, flags=re.S)
    assert n == 1, "the page carries no reportpage-label banner"
    return body


def _states_the_run(page: str, manifest: dict) -> list[str]:
    """What the page fails to state about the run its manifest records. Empty is consistent."""
    import re

    out = []
    label = page[page.find('<div id="reportpage-label"'):]
    if manifest["engine_sha"][:7] not in label or f"seed {manifest['seed']}" not in label:
        out.append("the banner does not name the manifest's engine and seed")
    body = re.sub(r"<[^>]+>", " ", _body_without_label(page))
    if manifest["engine_sha"] not in body:
        out.append("the report body does not name the manifest's full engine SHA")
    if not re.search(rf"Seed:\s*{manifest['seed']}\b", body):
        out.append("the report body does not state the manifest's seed")
    if not re.search(rf"Iterations:\s*{int(manifest['iterations']):,}\b", body):
        out.append("the report body does not state the manifest's iterations")
    return out


def test_the_page_states_the_run_its_manifest_records():
    """The banner and the manifest are written together by the label step, so the banner alone
    proves nothing about the report under it (Gate 3, 14/10/2026: a body from another run, under
    this run's banner, passed). The body the run rendered must name the same engine, seed and
    iteration count."""
    page = (REPORT_DIR / "index.html").read_text(encoding="utf-8")
    manifest = _json(REPORT_MANIFEST)
    assert _states_the_run(page, manifest) == []
    assert "CROSS-VALIDATION FAILED" not in page


def test_a_body_from_another_run_under_this_banner_is_refused():
    page = (REPORT_DIR / "index.html").read_text(encoding="utf-8")
    manifest = _json(REPORT_MANIFEST)
    label_at = page.find('<div id="reportpage-label"')
    other = "f" * 40
    swapped = page[:label_at] + page[label_at:].replace(manifest["engine_sha"], other)
    # the banner keeps its short SHA in a title attribute too; restore the banner alone
    banner_end = page.find("</div>", label_at) + len("</div>")
    swapped = page[:banner_end] + swapped[banner_end:]
    assert "the report body does not name the manifest's full engine SHA" in _states_the_run(
        swapped, manifest)


def test_the_dashboard_periods_name_the_same_engine_where_they_exist():
    periods = sorted(PERIOD_DIR.glob("period_*.json"))
    if not periods:
        pytest.skip("no dashboard period here: data/ is gitignored, so this limb runs on the "
                    "machine that publishes the periods")
    report = _json(REPORT_MANIFEST)
    for p in periods:
        meta = _json(p)["meta"]
        assert meta["engine_sha"] == report["engine_sha"], f"{p.name} is engine {meta['engine_sha']}"
        assert meta["seed"] == report["seed"], p.name
        for name, path in INPUTS.items():
            assert _digest_matches(meta["input_sha256"][name], path), f"{p.name} {name}"
