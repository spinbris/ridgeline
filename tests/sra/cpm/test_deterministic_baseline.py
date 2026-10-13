"""Validation Gate 2 — the kernel's deterministic baseline, on a committed schedule.

With every risk probability at zero, the schedule arm must produce one finish, and the two ways
of reaching it must agree:

* **2a, kernel-direct.** ``parse_xer`` -> ``build_schedule_graph`` -> ``run_batch`` with one
  iteration and the graph's own original durations. No injection, no orchestrator, no rules.
* **2b, the full schedule pipeline.** The same graph, drivers built the way every project's are
  (``build_stage3_rules_from_scope`` -> ``expand_auto_rules``) with each driver's probability
  forced to zero, through ``run_schedule_mc``.

Two independent paths to one number. 2a passing while 2b fails puts the defect in the rules or
the orchestrator; both failing puts it in the kernel. The zero-probability run must also have
**no spread**: a Bernoulli that never fires cannot move a finish, so any spread at all is a leak.

REFRETIRE-01 (D-2) replaces ``tests/sra/cpm/bindings/test_p6_deterministic_baseline.py``, which
asserted this against a 22 MB export that is not in this repository - so it skipped on every
machine, and the gate it names was green nowhere. This runs on the committed wind schedule. The
absolute finish is derived from the graph rather than pinned as a literal: a literal captured
from this file would only say the file had not changed, and 2a==2b is the property that says the
chain is coherent.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.integrated.stage3_config import build_stage3_rules_from_scope
from src.integrated.stage3_inputs import Stage3BindingConfig
from src.sra.cpm.auto_mapper import expand_auto_rules
from src.sra.cpm.cpm_kernel import run_batch
from src.sra.cpm.cpm_simulation import ScheduleMCConfig, run_schedule_mc
from src.sra.cpm.deterministic import deterministic_finish_hours
from src.sra.cpm.graph_builder import build_schedule_graph
from src.sra.cpm.xer_reader import parse_xer
from src.sra.strawman_reader import read_risk_scope
from tests.conftest import TEST_MODE_MULTIPLIERS

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_wind"
_XER = _FIXTURES / "wind_schedule.xer"
_REGISTER = _FIXTURES / "wind_register.xlsx"

#: Enough iterations to show that a zero-probability run has no spread; the batch size is the
#: standard smoke pattern.
_N_ITER = 200
_BATCH = 100
_SEED = 42

#: One working hour, in days. The two paths accumulate in float32 through different orders, so
#: they are compared to a tolerance rather than bit-for-bit.
_TOLERANCE_DAYS = 0.125

pytestmark = pytest.mark.project("synthetic_wind")


@pytest.fixture(scope="module")
def graph():
    return build_schedule_graph(parse_xer(_XER))


def _gate_2a_days(graph) -> float:
    """Kernel-direct: one iteration at the graph's own durations, in working days."""
    durations = np.array(
        [graph.activities[a_id].original_duration_hours for a_id in graph.topo_order],
        dtype=np.float32,
    )[None, :]
    cpm_out = run_batch(
        durations, graph,
        calendar=graph.project_default_calendar, precision="float32", project_start=0.0,
    )
    finish_hours = float(cpm_out["EF"].max(axis=1)[0])
    return finish_hours / graph.project_default_calendar.working_hours_per_day


def _gate_2b_days(graph) -> tuple[float, float]:
    """The full schedule pipeline at zero probability: ``(median_days, spread_days)``."""
    scope = read_risk_scope(str(_REGISTER))
    cfg = Stage3BindingConfig(
        register_path=_REGISTER, xer_path=_XER, strawman_path=_REGISTER,
        float_threshold_hours=480.0,
    )
    drivers = expand_auto_rules(build_stage3_rules_from_scope(scope, graph, cfg), graph)
    assert drivers, "the wind register produced no schedule drivers; 2b would be vacuous"
    zero_drivers = {rid: replace(d, probability=0.0) for rid, d in drivers.items()}

    severity = np.random.default_rng(_SEED).random(
        (_N_ITER, len(zero_drivers))).astype(np.float32)
    result = run_schedule_mc(
        graph=graph,
        risk_drivers=zero_drivers,
        config=ScheduleMCConfig(n_iter=_N_ITER, batch_size=_BATCH, seed=_SEED,
                                precision="float32",
                                mode_multipliers=TEST_MODE_MULTIPLIERS),
        severity_uniforms=severity,
    )
    finish = result.project_finish_days
    return float(np.median(finish)), float(finish.max() - finish.min())


def _longest_path_hours(graph) -> float:
    """The project finish by an independent walk: plain Python, no kernel, no numpy.

    Written from the forward-pass contract (``src/sra/cpm/cpm_kernel.forward_pass``), not from
    its implementation: ES is the latest implied start over a predecessor's links, floored at
    the project start, and EF is ES plus the duration. This is the second implementation the
    absolute finish needs. Asserting the kernel against
    ``src.sra.cpm.deterministic.deterministic_finish_hours`` alone would not be one - that
    helper calls the same ``run_batch``, so it checks the wrapper, not the arithmetic
    (REFRETIRE-01 numerics review, WARN-3).
    """
    preds: dict[str, list] = {a_id: [] for a_id in graph.topo_order}
    for link in graph.links:
        preds[link.succ_id].append(link)

    es: dict[str, float] = {}
    ef: dict[str, float] = {}
    for a_id in graph.topo_order:
        duration = float(graph.activities[a_id].original_duration_hours)
        start = 0.0
        for link in preds[a_id]:
            lag = float(link.lag_hours)
            if link.link_type == "FS":
                implied = ef[link.pred_id] + lag
            elif link.link_type == "SS":
                implied = es[link.pred_id] + lag
            elif link.link_type == "FF":
                implied = ef[link.pred_id] + lag - duration
            else:                                    # SF
                implied = es[link.pred_id] + lag - duration
            start = max(start, implied)
        es[a_id] = start
        ef[a_id] = start + duration
    return max(ef.values())


def test_gate_2a_the_kernel_reproduces_an_independent_longest_path(graph) -> None:
    """The absolute finish, anchored outside the kernel. A calendar or duration-conversion
    error inside the kernel passes every check that measures the kernel against itself."""
    per_day = graph.project_default_calendar.working_hours_per_day
    assert _gate_2a_days(graph) == pytest.approx(
        _longest_path_hours(graph) / per_day, abs=_TOLERANCE_DAYS)


def test_the_shared_zero_risk_helper_agrees_with_the_kernel(graph) -> None:
    """``deterministic_finish_hours`` is what the deliverable and the period route subtract
    (STAGE3HEADLINE-01 D-7). It wraps the same kernel, so this is a wrapper-drift check and
    nothing more - the anchor is the test above."""
    per_day = graph.project_default_calendar.working_hours_per_day
    assert _gate_2a_days(graph) == pytest.approx(
        deterministic_finish_hours(graph) / per_day, abs=_TOLERANCE_DAYS)


def test_gate_2b_a_zero_probability_run_has_one_finish_and_no_spread(graph) -> None:
    """A Bernoulli that never fires cannot move a finish. Any spread is an injection leak."""
    _median, spread = _gate_2b_days(graph)
    assert spread == 0.0, f"zero-probability run spread {spread} working days"


def test_gate_2_the_two_paths_agree(graph) -> None:
    """The load-bearing check: kernel-direct and full-pipeline reach the same finish."""
    direct = _gate_2a_days(graph)
    median, _spread = _gate_2b_days(graph)
    assert median == pytest.approx(direct, abs=_TOLERANCE_DAYS), (
        f"kernel-direct {direct:.4f} d vs full pipeline {median:.4f} d: the rules or the "
        f"orchestrator move the finish where no risk fires"
    )
