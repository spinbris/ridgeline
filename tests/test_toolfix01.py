"""TOOLFIX-01: tooling that told the operator the wrong thing, or nothing (leg 1, 21/09/2026).

FW-16 an input from outside the tree accepted silently; FW-23 a flag whose omission substituted
another workbook; FW-25 72 warnings on a correct run; FW-26 deploy commands that differed from the
ones executed; and the FIREDDROP-01 guard, a refusal where the engine is actively wrong. Each test
here was seen red with its fix removed before it was trusted.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]


# --- FW-16: the pre-flight names where each input really is -------------------------------------

def _paths_env(tmp_path: Path, strawman: Path) -> dict[str, str]:
    return {
        "QRA_PROJECT": "synthetic_road",
        "REGISTER_FILE": "tests/fixtures/synthetic_road/road_register.xlsx",  # relative, as typed
        "P6_FILE": str(REPO / "tests" / "fixtures" / "synthetic_road" / "road_schedule.xer"),
        "STRAWMAN_FILE": str(strawman),
    }


def test_the_preflight_states_resolved_paths_and_flags_one_outside_the_tree(tmp_path, monkeypatch):
    from src.final.deliverable_preflight import WORKING_TREE, check_paths

    monkeypatch.chdir(REPO)
    outside = tmp_path / "register_elsewhere.xlsx"
    outside.write_bytes(b"")
    by_label = {r.label: r for r in check_paths(_paths_env(tmp_path, outside))}

    register = by_label["register path"].detail
    assert str(REPO / "tests" / "fixtures" / "synthetic_road" / "road_register.xlsx") in register, (
        f"the relative path is not stated resolved: {register!r}")
    assert "outside this working tree" not in register
    strawman = by_label["strawman path"].detail
    assert str(outside.resolve()) in strawman and "outside this working tree" in strawman, strawman
    assert str(WORKING_TREE) in strawman


def test_the_paths_check_refuses_a_missing_input(tmp_path, monkeypatch, capsys):
    from src.final import deliverable_preflight

    env = _paths_env(tmp_path, tmp_path / "no_such.xlsx")
    monkeypatch.chdir(REPO)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert deliverable_preflight._cli(["--paths"]) == 2
    assert "no such file" in capsys.readouterr().out


def test_the_runner_prints_the_inputs_before_the_long_run():
    text = (REPO / "RUN_FINAL.bat").read_text(encoding="utf-8")
    check = text.index("-m src.final.deliverable_preflight --paths")
    assert check < text.index("-m nbconvert"), "the inputs are checked after the run, not before"
    assert "if errorlevel 1 exit /b 2" in text[check:check + 120]


# --- FW-23: the strawman follows the register ---------------------------------------------------

class _Stop(Exception):
    pass


def _run_period_capturing(monkeypatch, **kwargs):
    from src.am import run_period as rp

    captured = {}

    def fake_resolve(project, **paths):
        captured.update(paths)
        raise _Stop

    monkeypatch.setattr(rp, "_resolve_tree_dirty", lambda: False)
    monkeypatch.setattr(rp, "_resolve_active_sha", lambda: "sha")
    monkeypatch.setattr(rp, "resolve_project_inputs", fake_resolve)
    with pytest.raises(_Stop):
        rp.run_period(workbook_path=Path("status.xlsx"), project="synthetic_road", **kwargs)
    return captured


def test_a_register_without_a_strawman_is_the_strawman(monkeypatch):
    register = Path("outputs/kestrel/register_v1.xlsx")
    captured = _run_period_capturing(monkeypatch, register_path=register)
    assert captured["strawman_path"] == register, (
        "omitting --strawman takes the binding's fixture instead of the reader's register")


def test_an_explicit_strawman_still_wins(monkeypatch):
    captured = _run_period_capturing(monkeypatch, register_path=Path("r.xlsx"),
                                     strawman_path=Path("s.xlsx"))
    assert captured["strawman_path"] == Path("s.xlsx")


# --- FW-25: a rule bound to its own gate does not warn ------------------------------------------

def _rule(prefix: str, gate: str | None):
    from src.sra.cpm.risk_driver_schema import AutoMapperRule

    return AutoMapperRule(
        risk_id="T-001", pattern_id="P-T", pattern_prefixes=(prefix,),
        float_threshold_hours=480.0, injection_method="discrete_event_additive_days",
        opt_pert=1.0, ml_pert=2.0, pess_pert=4.0, probability=0.5, gating_activity_id=gate,
    )


def _warnings(caplog, rule) -> list[str]:
    from src.sra.cpm.auto_mapper import expand_single_rule
    from tests.sra.cpm.test_gatecohort01_gate_relation import _graph

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="src.sra.cpm.auto_mapper"):
        expand_single_rule(rule, _graph())
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_rule_that_binds_only_its_gate_raises_no_threshold_warning(caplog):
    # prefix "G" binds activity 4 alone, and 4 is the declared gate: the cohort IS the gate.
    assert _warnings(caplog, _rule("G", "4")) == []


def test_a_small_cohort_that_is_not_just_the_gate_still_warns(caplog):
    # prefix "A" binds activities 2 and 3, gate 3 among them: two is a thin match, not a gate.
    found = _warnings(caplog, _rule("A", "3"))
    assert any("< 5 threshold" in m for m in found), found


# --- FW-26: printed is executed, preview by default ---------------------------------------------

def test_the_deploy_pair_is_one_list_and_the_preview_pair_carries_no_prod():
    from src.am.publish_period import deploy_commands

    preview = deploy_commands(production=False, scope="team-x")
    production = deploy_commands(production=True, scope="team-x")
    for build, deploy in (preview, production):
        assert build[:2] == ["vercel", "build"] and "--prebuilt" not in build, build
        assert deploy[:2] == ["vercel", "deploy"] and "--prebuilt" in deploy, deploy
        assert ("--prod" in build) == ("--prod" in deploy), "built for one target, deployed to another"
    assert not any("--prod" in c for c in preview)
    assert all("--prod" in c for c in production)
    assert all(c[c.index("--scope") + 1] == "team-x" for c in preview + production)
    assert not any("--scope" in c for c in deploy_commands(production=False))


def test_deploy_runs_exactly_the_preview_pair(monkeypatch):
    """Still exact, and still the printed sequence (FW-26). DASHGATE-01 puts the clear before
    `vercel build` and the build-output guard between the two `vercel` commands; the two commands
    remain exactly `deploy_commands`, in that position."""
    from src.am import publish_period as pp

    ran = []
    monkeypatch.setattr(pp, "_run", lambda command, **_: ran.append(command))
    monkeypatch.setattr(pp, "clear_build_output", lambda dashboard: ran.append("clear"))
    monkeypatch.setattr(pp, "guard_build_output", lambda dashboard: ran.append("guard"))
    pp.deploy(Path("dashboard"), scope="team-x")
    build, deploy = pp.deploy_commands(production=False, scope="team-x")
    assert ran == ["clear", build, "guard", deploy]


def test_what_is_printed_is_what_deploy_runs(monkeypatch, capsys):
    from src.am import publish_period as pp

    plan = SimpleNamespace(period_end="2026-08-31", project="synthetic_road",
                           destination=Path("data/synthetic_road/period_20260831.json"))
    monkeypatch.setattr(pp, "publish", lambda *a, **k: plan)
    monkeypatch.setattr(pp, "describe_outcome", lambda p: ("Published", ""))
    assert pp.main(["period.json", "--scope", "team-x"]) == 0
    out = capsys.readouterr().out
    assert "Built, NOT deployed" in out
    body = out.split("exactly what --deploy runs, in order:")[1].split("Production is a separate step")[0]
    printed = [line.strip() for line in body.splitlines() if line.strip()]
    assert printed == [pp.format_step(s) for s in pp.deploy_steps(production=False, scope="team-x")]


# --- FIREDDROP-01: a fired risk is refused, not silently dropped --------------------------------

def test_a_period_with_a_fired_risk_is_refused_naming_it(monkeypatch):
    from src.am import run_period as rp

    monkeypatch.setattr(rp, "_resolve_tree_dirty", lambda: False)
    monkeypatch.setattr(rp, "_resolve_active_sha", lambda: "sha")
    monkeypatch.setattr(rp, "resolve_project_inputs", lambda project, **_: SimpleNamespace(
        project="synthetic_road", register_path=Path("r.xlsx"), xer_path=Path("s.xer"),
        strawman_path=Path("r.xlsx")))
    monkeypatch.setattr(rp, "read_workbook", lambda *a, **k: SimpleNamespace(risk_status=[
        {"risk_id": "KH-002", "status_this_period": "Open"},
        {"risk_id": "KH-011", "status_this_period": "Fired"},
    ]))
    with pytest.raises(rp.FiredRiskRefused) as exc:
        rp.run_period(workbook_path=Path("status.xlsx"), project="synthetic_road",
                      output_dir=Path("unused"))
    msg = str(exc.value)
    for token in ("KH-011", "FIREDDROP-01", "AMGAP-01"):
        assert token in msg, msg
    assert "KH-002" not in msg


def test_the_guard_matches_the_runner_exactly():
    """The guard must refuse every risk the runner would drop - no more, no less."""
    from src.am.run_period import FiredRiskRefused, refuse_fired_risks

    refuse_fired_risks([{"risk_id": "R", "status_this_period": s} for s in ("Open", "Closed", None)])
    with pytest.raises(FiredRiskRefused):
        refuse_fired_risks([{"risk_id": "R", "status_this_period": "Fired"}])
    runner = (REPO / "src" / "am" / "conditional_runner.py").read_text(encoding="utf-8")
    assert 'if status == "Fired":' in runner, "the runner's test changed; re-align the guard"


def test_the_cli_prints_the_refusal_not_a_traceback(monkeypatch, capsys):
    import src.sra.cpm.bindings.synthetic_road  # noqa: F401  registers, so --project accepts it
    from src.am import run_period as rp

    def refuse(args):
        raise rp.FiredRiskRefused("this period marks 1 risk(s) Fired: KH-011.")

    monkeypatch.setattr(rp, "_run_from_args", refuse)
    assert rp._main(["--workbook", "status.xlsx", "--project", "synthetic_road"]) == 2
    assert "RUN REFUSED: this period marks 1 risk(s) Fired" in capsys.readouterr().err
