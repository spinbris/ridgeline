"""DASHGATE-01 P3: `publish_period` refuses an unpublishable project before anything is filed.

In the style of `tests/test_7d_receive_path_and_render_gate.py`: `tmp_path`, pure, no shell-out.
The refusal comes from `resolve_plan`, so `publish` never reaches `place`, `build` or `deploy`,
and `main` prints it as `PUBLISH REFUSED: ...`.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import src.am.publish_period as pp
from src.am.publish_period import PublishError, resolve_plan
from src.sra.cpm.bindings import get_binding

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"


def _period(tmp_path: Path, project_key: str) -> Path:
    doc = json.loads(GOLDEN.read_bytes().decode("utf-8"))
    doc["meta"]["project_key"] = project_key
    src = tmp_path / "incoming" / "period.json"
    src.parent.mkdir(parents=True)
    src.write_bytes(json.dumps(doc).encode("utf-8"))
    return src


def _nothing_under(root: Path) -> bool:
    return not root.exists() or not any(root.rglob("*"))


def test_the_published_project_still_resolves(tmp_path):
    plan = resolve_plan(_period(tmp_path, "synthetic_wind"), None, data_root=tmp_path / "data")
    assert plan.project == "synthetic_wind"


def test_a_project_not_named_for_publication_is_refused_and_nothing_is_filed(tmp_path):
    data = tmp_path / "data"
    with pytest.raises(PublishError, match=r"'synthetic_road'.*not named for publication"):
        resolve_plan(_period(tmp_path, "synthetic_road"), None, data_root=data)
    assert _nothing_under(data)


def test_a_confidential_project_is_refused_even_when_it_asks_to_be_published(tmp_path, monkeypatch):
    import src.sra.cpm.bindings.registry as registry

    road = get_binding("synthetic_road")
    monkeypatch.setitem(registry._REGISTRY, "synthetic_road",
                        dataclasses.replace(road, publish=True, confidential=True))
    with pytest.raises(PublishError, match=r"'synthetic_road'.*confidential"):
        resolve_plan(_period(tmp_path, "synthetic_road"), None, data_root=tmp_path / "data")


def test_a_project_no_binding_declares_is_refused(tmp_path):
    with pytest.raises(PublishError, match=r"'other_project'.*no project binding"):
        resolve_plan(_period(tmp_path, "other_project"), None, data_root=tmp_path / "data")


def test_publish_refuses_before_placing_building_or_deploying(tmp_path, monkeypatch):
    data = tmp_path / "data"
    called = []
    monkeypatch.setattr(pp, "place", lambda plan: called.append("place"))
    monkeypatch.setattr(pp, "build", lambda *a, **k: called.append("build"))
    monkeypatch.setattr(pp, "deploy", lambda *a, **k: called.append("deploy"))
    with pytest.raises(PublishError):
        pp.publish(_period(tmp_path, "synthetic_road"), do_deploy=True, data_root=data)
    assert called == [] and _nothing_under(data)


def test_the_command_line_says_publish_refused(tmp_path, monkeypatch, capsys):
    """`main` files under the real `data/`, so filing, building and deploying are stubbed: a
    run on code that fails to refuse records the call instead of writing anything."""
    called = []
    monkeypatch.setattr(pp, "place", lambda plan: called.append("place"))
    monkeypatch.setattr(pp, "build", lambda *a, **k: called.append("build"))
    monkeypatch.setattr(pp, "deploy", lambda *a, **k: called.append("deploy"))
    rc = pp.main([str(_period(tmp_path, "synthetic_road"))])
    err = capsys.readouterr().err
    assert rc == 1 and "PUBLISH REFUSED" in err and "synthetic_road" in err, (rc, err)
    assert called == []


# --- Director ruling D-I (30/09/2026): a period that does not say whose it is is not published --

def _keyless(tmp_path: Path) -> Path:
    doc = json.loads(GOLDEN.read_bytes().decode("utf-8"))
    doc["meta"].pop("project_key", None)
    src = tmp_path / "incoming" / "keyless.json"
    src.parent.mkdir(parents=True)
    src.write_bytes(json.dumps(doc).encode("utf-8"))
    return src


def test_a_keyless_period_is_refused_even_with_a_publishable_project(tmp_path):
    data = tmp_path / "data"
    with pytest.raises(PublishError, match="meta.project_key"):
        resolve_plan(_keyless(tmp_path), "synthetic_wind", data_root=data)
    assert _nothing_under(data)


def test_a_keyless_period_is_refused_with_no_project_either(tmp_path):
    with pytest.raises(PublishError, match="meta.project_key"):
        resolve_plan(_keyless(tmp_path), None, data_root=tmp_path / "data")


def test_a_matching_project_is_still_allowed_and_a_mismatch_still_refused(tmp_path):
    src = _period(tmp_path, "synthetic_wind")
    assert resolve_plan(src, "synthetic_wind", data_root=tmp_path / "data").project == "synthetic_wind"
    with pytest.raises(PublishError, match="does not match"):
        resolve_plan(src, "synthetic_road", data_root=tmp_path / "data")


@pytest.mark.parametrize("key", [7, ["synthetic_wind"], {"k": "synthetic_wind"}])
def test_a_non_string_project_key_is_refused_not_a_traceback(tmp_path, key):
    """Round 2, NOTE-5."""
    doc = json.loads(GOLDEN.read_bytes().decode("utf-8"))
    doc["meta"]["project_key"] = key
    src = tmp_path / "incoming" / "odd.json"
    src.parent.mkdir(parents=True)
    src.write_bytes(json.dumps(doc).encode("utf-8"))
    data = tmp_path / "data"
    with pytest.raises(PublishError, match="project_key"):
        resolve_plan(src, None, data_root=data)
    assert _nothing_under(data)
