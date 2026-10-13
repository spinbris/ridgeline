"""DASHGATE-01 gate 3 round 1: the deploy sequence is one list, printed and executed alike, and the
guard never passes on build output this build did not produce.

- Breaker W1: the guard used to check only that `config.json` existed, so a previous run's output
  passed after a build that wrote nothing. Now a clear step removes the output and stamps a start
  marker before `vercel build`; the guard refuses output that is missing, unmarked or older than the
  marker, and each pass consumes the marker.
- Breaker W3: the printout said "exactly what --deploy runs" and omitted the guard. Now
  `deploy_steps` is the one list: `deploy()` executes it and `main` prints it, the clear and the
  guard as runnable commands with the directory each runs from.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.am.publish_period as pp
from src.am.publish_period import PublishError

REPO = Path(__file__).resolve().parents[1]

from tests.test_dashgate01_deploy_guard import _write_output  # noqa: E402


def _dashboard(tmp_path: Path) -> Path:
    d = tmp_path / "dashboard"
    d.mkdir()
    return d


# --- W1: stale output ----------------------------------------------------------------------

def test_a_previous_run_s_output_does_not_pass_after_a_build_that_wrote_nothing(tmp_path, monkeypatch):
    dashboard = _dashboard(tmp_path)
    _write_output(dashboard)  # a previous run's valid output, sitting there
    ran = []
    monkeypatch.setattr(pp, "_run", lambda command, **_: ran.append(command[:2]))  # writes nothing
    with pytest.raises(PublishError, match="Nothing was deployed"):
        pp.deploy(dashboard)
    assert ["vercel", "deploy"] not in ran


def test_the_guard_alone_refuses_output_no_clear_step_preceded(tmp_path):
    dashboard = _dashboard(tmp_path)
    _write_output(dashboard)
    with pytest.raises(PublishError, match="not produced by this build"):
        pp.guard_build_output(dashboard)


def test_the_guard_refuses_output_older_than_the_clear(tmp_path):
    dashboard = _dashboard(tmp_path)
    _write_output(dashboard)
    config = dashboard / ".vercel" / "output" / "config.json"
    old = config.stat().st_mtime - 3600
    pp.clear_build_output(dashboard)
    _write_output(dashboard)
    os.utime(config, (old, old))
    with pytest.raises(PublishError, match="not produced by this build"):
        pp.guard_build_output(dashboard)


def test_a_fresh_build_after_the_clear_passes_once_and_only_once(tmp_path):
    dashboard = _dashboard(tmp_path)
    pp.clear_build_output(dashboard)
    time.sleep(0.01)
    _write_output(dashboard)
    pp.guard_build_output(dashboard)  # passes
    with pytest.raises(PublishError, match="not produced by this build"):
        pp.guard_build_output(dashboard)  # the marker was consumed


def test_the_clear_keeps_the_vercel_link(tmp_path):
    dashboard = _dashboard(tmp_path)
    link = dashboard / ".vercel" / "project.json"
    link.parent.mkdir()
    link.write_text("{}", encoding="utf-8")
    _write_output(dashboard)
    pp.clear_build_output(dashboard)
    assert link.is_file() and not (dashboard / ".vercel" / "output").exists()


# --- W3: printed is executed, the guard included -------------------------------------------

def _executed(monkeypatch, production: bool) -> list:
    ran = []
    monkeypatch.setattr(pp, "_run", lambda command, **_: ran.append(("run", tuple(command))))
    monkeypatch.setattr(pp, "clear_build_output", lambda d: ran.append(("clear",)))
    monkeypatch.setattr(pp, "guard_build_output", lambda d: ran.append(("guard",)))
    pp.run_deploy_steps(Path("dashboard"), production=production, scope="team-x")
    return ran


@pytest.mark.parametrize("production", [False, True])
def test_the_executed_sequence_is_clear_build_guard_deploy(monkeypatch, production):
    ran = _executed(monkeypatch, production)
    kinds = [r[0] if r[0] != "run" else r[1][1] for r in ran]
    assert kinds == ["clear", "build", "guard", "deploy"], kinds
    assert [s.action for s in pp.deploy_steps(production=production, scope="team-x")] == [
        "clear", "vercel", "guard", "vercel"]


def test_deploy_runs_the_preview_steps(monkeypatch):
    ran = []
    monkeypatch.setattr(pp, "run_deploy_steps", lambda d, **k: ran.append(k))
    pp.deploy(Path("dashboard"), scope="team-x")
    assert ran == [{"production": False, "scope": "team-x"}]


def test_what_is_printed_is_the_step_list_the_deploy_executes(monkeypatch, capsys):
    plan = SimpleNamespace(period_end="2026-08-31", project="synthetic_wind",
                           destination=Path("data/synthetic_wind/period_20260831.json"))
    monkeypatch.setattr(pp, "publish", lambda *a, **k: plan)
    monkeypatch.setattr(pp, "describe_outcome", lambda p: ("Published", ""))
    assert pp.main(["period.json", "--scope", "team-x"]) == 0
    out = capsys.readouterr().out
    preview = out.split("exactly what --deploy runs, in order:")[1].split("Production is")[0]
    production = out.split("Production is")[1]
    for text, prod in ((preview, False), (production, True)):
        lines = [ln.strip() for ln in text.splitlines() if ln.startswith("    ")]
        assert lines == [pp.format_step(s) for s in pp.deploy_steps(production=prod, scope="team-x")]
    assert "build_guard.py check" in preview and "build_guard.py clear" in preview


def test_the_printed_guard_command_runs_the_same_checks(monkeypatch, tmp_path):
    """The printed `build_guard.py` calls the very functions `deploy()` calls, on the dashboard."""
    sys.path.insert(0, str(REPO / "scripts" / "release"))
    import build_guard

    called = []
    monkeypatch.setattr(pp, "clear_build_output", lambda d: called.append(("clear", Path(d))))
    monkeypatch.setattr(pp, "guard_build_output", lambda d: called.append(("guard", Path(d))))
    assert build_guard.main(["clear"]) == 0 and build_guard.main(["check"]) == 0
    assert called == [("clear", pp.DASHBOARD), ("guard", pp.DASHBOARD)]


def test_the_printed_guard_command_exits_non_zero_on_a_refusal(monkeypatch, capsys):
    sys.path.insert(0, str(REPO / "scripts" / "release"))
    import build_guard

    def refuse(d):
        raise PublishError("nope. Nothing was deployed.")

    monkeypatch.setattr(pp, "guard_build_output", refuse)
    assert build_guard.main(["check"]) == 1
    assert "nope" in capsys.readouterr().err


# --- N1: a malformed projects.json is a PublishError, not a traceback ------------------------

@pytest.mark.parametrize("listing", ['{"projects": null}', '{"projects": "synthetic_wind"}',
                                     '{"projects": [7]}', '["synthetic_wind"]'])
def test_a_malformed_projects_json_refuses_cleanly(tmp_path, listing):
    dashboard = _dashboard(tmp_path)
    pp.clear_build_output(dashboard)
    time.sleep(0.01)
    _write_output(dashboard)
    (dashboard / ".vercel" / "output" / "static" / "data" / "projects.json").write_text(
        listing, encoding="utf-8")
    with pytest.raises(PublishError, match="projects.json"):
        pp.guard_build_output(dashboard)
