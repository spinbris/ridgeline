"""RNGSTREAM-01: the fire draw and the severity uniforms are on independent streams.

Brief: RNGSTREAM-01. The fast
tests hold the stream derivation; the `slow` tests run a shipped register rearranged so its first
risk is a single-member correlation group - the case that coupled exactly - through the Stage 3
headline and the period route.
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.rng_streams import (SEVERITY_STREAM, fire_generator, kernel_generator,
                             severity_generator)

REPO = Path(__file__).resolve().parents[1]
ROAD_REGISTER = REPO / "tests" / "fixtures" / "synthetic_road" / "road_register.xlsx"
ROAD_XER = REPO / "tests" / "fixtures" / "synthetic_road" / "road_schedule.xer"
N = 1_000


def _draws(generator: np.random.Generator) -> np.ndarray:
    return generator.random(N)


# ---------------------------------------------------------------------------
# The derivation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 42, 2**31 - 1])
def test_fire_severity_and_every_kernel_batch_are_distinct_streams(seed: int) -> None:
    """P-1, including brief §2.3's trap: no severity stream may be a spawned child of the seed."""
    fire, severity = _draws(fire_generator(seed)), _draws(severity_generator(seed))
    batches = [_draws(child) for child in kernel_generator(seed).spawn(16)]
    assert not np.array_equal(fire, severity)
    assert not any(np.array_equal(severity, b) for b in batches)
    assert not any(np.array_equal(fire, b) for b in batches)


@pytest.mark.parametrize("seed", [0, 42])
def test_the_severity_stream_is_not_the_seed_s_child_at_its_own_key(seed: int) -> None:
    """RNGSTREAM-01 numerics review, WARN-1, refuted by measurement: the claim was
    that ``SeedSequence([seed, K])`` is spawn child K of the seed. It is not - numpy pads a spawned
    sequence's entropy to its pool size before the spawn key - and this pins that at child K itself.
    Construction checked against real ``.spawn()`` children first, so the shortcut is honest."""
    real = np.random.default_rng(seed).spawn(3)
    for i in range(3):
        built = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(i,)))
        assert np.array_equal(_draws(built), _draws(real[i]))
    child_k = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(SEVERITY_STREAM,)))
    assert not np.array_equal(_draws(child_k), _draws(severity_generator(seed)))


@pytest.mark.parametrize("bad", [42.0, 42.9, -1, 2**32, "42"])
def test_a_seed_that_is_not_one_32_bit_integer_is_refused(bad) -> None:
    """A float would be truncated silently; a seed of 2**32 or more is several entropy words, and
    the severity stream of one seed could be the fire stream of another."""
    with pytest.raises((TypeError, ValueError)):
        severity_generator(bad)
    with pytest.raises((TypeError, ValueError)):
        fire_generator(bad)


def test_the_severity_stream_key_is_not_zero() -> None:
    """``SeedSequence([seed, 0])`` is ``SeedSequence(seed)``: a zero key is the defect restored."""
    assert SEVERITY_STREAM != 0
    assert np.array_equal(_draws(fire_generator(42)),
                          _draws(np.random.default_rng(np.random.SeedSequence([42, 0])))), (
        "numpy no longer pads entropy with zeros; the warning on SEVERITY_STREAM is out of date")


def test_the_streams_are_seeded_and_reproducible() -> None:
    """P-6 at the derivation."""
    assert np.array_equal(_draws(severity_generator(7)), _draws(severity_generator(7)))
    assert not np.array_equal(_draws(severity_generator(7)), _draws(severity_generator(8)))


#: Constructors of a generator or bit stream, however imported.
_GENERATOR_MAKERS = {"default_rng", "SeedSequence", "Generator", "PCG64", "PCG64DXSM", "MT19937",
                     "Philox", "SFC64", "RandomState"}
#: Legacy global-state calls, recognised only on ``np.random`` / ``numpy.random`` so a Generator's
#: own ``rng.random(...)`` is not mistaken for one.
_LEGACY_GLOBAL = {"seed", "random", "rand", "randn", "uniform", "normal", "random_sample"}


def _makes_a_generator(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _GENERATOR_MAKERS
    if isinstance(func, ast.Attribute):
        if func.attr in _GENERATOR_MAKERS:
            return True
        owner = func.value
        return (func.attr in _LEGACY_GLOBAL and isinstance(owner, ast.Attribute)
                and owner.attr == "random")
    return False


@pytest.mark.parametrize("module", [
    "src/qra_core.py",
    "src/integrated/integrated_simulation_stage3.py",
    "src/am/conditional_runner.py",
])
def test_the_stage3_routes_make_no_generator_of_their_own(module: str) -> None:
    """P-1: `src.rng_streams` is the only place these routes' streams are made."""
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    calls = [n.lineno for n in ast.walk(tree) if _makes_a_generator(n)]
    assert not calls, f"{module} builds a generator at lines {calls}; use src.rng_streams"


@pytest.mark.parametrize("source", [
    "np.random.default_rng(1)", "default_rng(1)", "np.random.Generator(np.random.PCG64(1))",
    "numpy.random.seed(1)", "np.random.random(3)", "RandomState(1)",
])
def test_the_generator_guard_sees_every_form(source: str) -> None:
    """The guard above cannot pass by missing a spelling (numerics review WARN-2)."""
    assert any(_makes_a_generator(n) for n in ast.walk(ast.parse(source)))
    assert not any(_makes_a_generator(n) for n in ast.walk(ast.parse("rng.random(3)")))


# ---------------------------------------------------------------------------
# The case that coupled, through the engines
# ---------------------------------------------------------------------------

def _singleton_first(risks, risk_id: str):
    """The register's risks with ``risk_id`` moved to the front, alone in its correlation group."""
    first = next(r for r in risks if r.risk_id == risk_id)
    return [replace(first, correlation_group=f"S-{risk_id}")] + [r for r in risks if r is not first]


def _first_time_yes(scope) -> str:
    """The first Time Impact = Yes risk whose probability leaves room above it: the tests require a
    fired severity above max(0.9, p + 0.2), which no uniform can reach when p >= 0.8."""
    rows = scope[(scope["time_impact"] == "Yes") & (scope["probability"] <= 0.6)]
    assert len(rows), "no Time Impact = Yes risk with probability <= 0.6 in the fixture"
    return str(rows["risk_id"].iloc[0])


@pytest.mark.slow
def test_the_headline_severity_reaches_its_upper_range_when_a_singleton_is_drawn_first(monkeypatch):
    """P-2 on the Stage 3 headline. Before RNGSTREAM-01 this risk's severity uniform on a fired
    iteration could not exceed its probability, on both arms."""
    from src.integrated.integrated_simulation_stage3 import run_integrated_simulation_stage3
    from src.integrated.stage3_config import build_stage3_config, build_stage3_rules_from_scope
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.integrated.stage3_inputs import Stage3BindingConfig
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    tables = parse_xer(str(ROAD_XER))
    graph = build_schedule_graph(tables)
    scope = read_risk_scope(str(ROAD_REGISTER))
    rid = _first_time_yes(scope)
    risks = _singleton_first(read_risks_v5(str(ROAD_REGISTER)), rid)
    drivers = expand_auto_rules(build_stage3_rules_from_scope(
        scope, graph, Stage3BindingConfig(register_path=ROAD_REGISTER, xer_path=ROAD_XER,
                                          strawman_path=ROAD_REGISTER,
                                          float_threshold_hours=480.0)), graph)
    cfg = build_stage3_config(register_path=ROAD_REGISTER, xer_path=ROAD_XER,
                              strawman_path=ROAD_REGISTER, iterations=4_000, seed=42,
                              caller_module="tests/rngstream01")
    res = run_integrated_simulation_stage3(cfg, risks=risks, risk_scope_df=scope,
                                           schedule_graph=graph, risk_drivers=drivers,
                                           xer_tables=tables)
    fired = np.asarray(res.cost_result["fired_array"])[:, 0]
    severity = np.asarray(res.severity_uniforms_by_risk_id[rid])
    p = float(risks[0].probability)
    assert fired.sum() > 500
    assert severity[fired].max() > max(0.9, p + 0.2), (
        f"{rid} (p={p}) fired with severity uniforms no higher than {severity[fired].max():.4f}")


@pytest.mark.slow
def test_the_period_severity_reaches_its_upper_range_when_a_singleton_is_drawn_first(monkeypatch):
    """P-2 on the period route, whose schedule arm fires on the reproduced cost-arm draw."""
    import src.am.conditional_runner as cr
    from src.am.workbook_reader import WorkbookData
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    rid = _first_time_yes(read_risk_scope(str(ROAD_REGISTER)))
    risks = _singleton_first(read_risks_v5(str(ROAD_REGISTER)), rid)
    monkeypatch.setattr(cr, "read_risks_v5", lambda _path: list(risks))
    result = cr.run_conditional_mc(cr.ConditionalRunInputs(
        workbook_data=WorkbookData(period_info={}, risk_status=[], milestones=[], mitigations=[],
                                   am_risk_ids=[]),
        register_path=ROAD_REGISTER, xer_path=ROAD_XER, strawman_path=ROAD_REGISTER,
        n_iter=4_000, seed=42, criticality_measurement_mode="mode_conditioned",
        project="synthetic_road"))
    column = list(result.schedule_result.risk_ids).index(rid)
    fired = np.asarray(result.schedule_result.risk_fired_array)[:, column]
    severity = np.asarray(result.severity_uniforms_by_risk_id[rid])
    p = float(risks[0].probability)
    assert fired.sum() > 500
    assert severity[fired].max() > max(0.9, p + 0.2), (
        f"{rid} (p={p}) fired with severity uniforms no higher than {severity[fired].max():.4f}")
