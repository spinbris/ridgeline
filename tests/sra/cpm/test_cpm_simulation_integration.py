"""End-to-end pipeline tests for SR-S3-Beta-05.

Exercises the full Beta-02 → Beta-04 → Beta-03 → Beta-05 chain over a
synthetic 10-activity graph constructed inline (no XER, no RefProject register).
The auto-mapper expands two synthetic rules against the graph; the
orchestrator runs.

Eight tests:

- test_full_pipeline_smoke
- test_full_pipeline_zero_probability_reproduces_deterministic
- test_full_pipeline_beta_flag_set_when_auto_mapped
- test_full_pipeline_workshop_drivers_no_beta_flag
- test_full_pipeline_prod_mode_rejects_auto_mapped
- test_full_pipeline_streaming_consistent_across_batch_sizes (slow)
- test_full_pipeline_severity_uniform_propagates_correctly
- test_full_pipeline_no_refproject_specifics — meta-test scanning the
  source file for forbidden tokens.

The reusability invariant per Beta-00.3 is locked: synthetic graphs
constructed via direct dataclass instantiation; no RefProject paths,
file references, or pattern codes appear here.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import dataclasses
import re
from pathlib import Path

import numpy as np
import pytest

import src.sra.cpm.cpm_simulation as cpm_simulation
from src.sra.cpm.auto_mapper import expand_auto_rules
from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_kernel import run_batch as kernel_run_batch
from src.sra.cpm.cpm_simulation import (
    ScheduleMCConfig,
    ScheduleMCResult,
    run_schedule_mc,
)
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import (
    AutoMapperConfig,
    AutoMapperRule,
    RiskDriver,
)


# ---------------------------------------------------------------------------
# Synthetic 10-activity fixture (project-agnostic)
# ---------------------------------------------------------------------------

_DEFAULT_CAL = Calendar()  # 8 working hours per day


def _make_synthetic_graph() -> ScheduleGraph:
    """Build a 10-activity graph with two parallel chains of 5.

    Activities split across two pattern-prefix families:

    * Chain X (prefix ``"X.C"``):  X.C.001 → X.C.002 → X.C.003 →
      X.C.004 → X.C.005, each 80h, total_float 0h (all on the chain CP).
    * Chain Y (prefix ``"Y.D"``):  Y.D.001 → Y.D.002 → Y.D.003 →
      Y.D.004 → Y.D.005, each 40h, total_float 200h (off the project
      CP since chain X is longer).

    The two chains are independent — no cross-links — so the project
    finish equals the longer chain's EF (= 5 × 80 = 400 working hours
    when no risks fire).
    """
    activities: dict[str, Activity] = {}

    # Chain X: 5 activities × 80h = 400h. All on CP under no risks.
    for i in range(1, 6):
        aid = f"X{i:03d}"
        code = f"X.C.{i:03d}"
        activities[aid] = Activity(
            id=aid,
            code=code,
            name=code,
            task_type="TT_Task",
            original_duration_hours=80.0,
            total_float_hours=0.0,
            calendar_id=None,
        )

    # Chain Y: 5 activities × 40h = 200h. Off CP (float = 200h).
    for i in range(1, 6):
        aid = f"Y{i:03d}"
        code = f"Y.D.{i:03d}"
        activities[aid] = Activity(
            id=aid,
            code=code,
            name=code,
            task_type="TT_Task",
            original_duration_hours=40.0,
            total_float_hours=200.0,
            calendar_id=None,
        )

    links: list[Link] = []
    for i in range(1, 5):
        link = Link(
            pred_id=f"X{i:03d}",
            succ_id=f"X{i + 1:03d}",
            link_type="FS",
            lag_hours=0.0,
        )
        links.append(link)
        activities[f"X{i:03d}"].successor_links.append(link)
        activities[f"X{i + 1:03d}"].predecessor_links.append(link)
    for i in range(1, 5):
        link = Link(
            pred_id=f"Y{i:03d}",
            succ_id=f"Y{i + 1:03d}",
            link_type="FS",
            lag_hours=0.0,
        )
        links.append(link)
        activities[f"Y{i:03d}"].successor_links.append(link)
        activities[f"Y{i + 1:03d}"].predecessor_links.append(link)

    topo_order = [f"X{i:03d}" for i in range(1, 6)] + [
        f"Y{i:03d}" for i in range(1, 6)
    ]
    return ScheduleGraph(
        activities=activities,
        links=links,
        topo_order=topo_order,
        project_default_calendar=_DEFAULT_CAL,
    )


def _make_auto_rules(probability: float = 0.5) -> dict[str, AutoMapperRule]:
    """Two pattern rules, one per chain-prefix family."""
    return {
        "RX": AutoMapperRule(
            risk_id="RX",
            pattern_id="PX",
            pattern_prefixes=("X.C",),
            float_threshold_hours=480.0,
            injection_method="additive_pert_days",
            opt_pert=1.0,
            ml_pert=2.0,
            pess_pert=4.0,
            probability=probability,
        ),
        "RY": AutoMapperRule(
            risk_id="RY",
            pattern_id="PY",
            pattern_prefixes=("Y.D",),
            float_threshold_hours=480.0,
            injection_method="additive_pert_days",
            opt_pert=1.0,
            ml_pert=2.0,
            pess_pert=4.0,
            probability=probability,
        ),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_full_pipeline_smoke(self) -> None:
        """Beta-02 → Beta-04 → Beta-03 → Beta-05: full chain runs cleanly."""
        graph = _make_synthetic_graph()
        rules = _make_auto_rules(probability=0.5)
        drivers = expand_auto_rules(rules, graph, AutoMapperConfig())
        assert len(drivers) == 2
        # Filter B-survivors: chain X has float 0 (all 5 pass at threshold
        # 480h); chain Y has float 200 (also passes at 480h).
        assert len(drivers["RX"].affected_activity_ids) == 5
        assert len(drivers["RY"].affected_activity_ids) == 5
        assert all(d.derived_at_run_time for d in drivers.values())

        cfg = ScheduleMCConfig(n_iter=100, batch_size=25, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg
        )
        assert isinstance(result, ScheduleMCResult)
        assert result.n_iter == 100
        assert result.n_act == 10
        assert result.n_risks == 2
        assert result.project_finish_hours.shape == (100,)
        assert result.beta_flag is True
        assert result.activity_ids == tuple(graph.topo_order)
        assert result.risk_ids == ("RX", "RY")

    def test_full_pipeline_zero_probability_reproduces_deterministic(
        self,
    ) -> None:
        """All drivers at probability=0.0 must reproduce the deterministic
        CPM finish — checked by an independent kernel call against
        base durations.
        """
        graph = _make_synthetic_graph()
        rules = _make_auto_rules(probability=0.0)
        drivers = expand_auto_rules(rules, graph, AutoMapperConfig())

        cfg = ScheduleMCConfig(
            n_iter=200, batch_size=50, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg
        )

        # Independent deterministic CPM call against base durations.
        base = np.array(
            [
                graph.activities[a_id].original_duration_hours
                for a_id in graph.topo_order
            ],
            dtype=np.float64,
        )
        det = kernel_run_batch(
            durations=base[None, :],  # (1, n_act)
            graph=graph,
            calendar=graph.project_default_calendar,
            precision="float64",
            project_start=0.0,
        )
        det_finish = float(det["EF"].max(axis=1)[0])

        # Every iteration of the orchestrator must equal det_finish.
        assert result.project_finish_hours.std() == 0.0
        assert np.allclose(result.project_finish_hours, det_finish)
        # Chain X is 5 × 80 = 400h; chain Y is 5 × 40 = 200h. Project
        # finish = max chain = 400h.
        assert det_finish == 400.0

    def test_full_pipeline_beta_flag_set_when_auto_mapped(self) -> None:
        graph = _make_synthetic_graph()
        rules = _make_auto_rules(probability=0.5)
        drivers = expand_auto_rules(rules, graph, AutoMapperConfig())
        assert all(d.derived_at_run_time for d in drivers.values())

        cfg = ScheduleMCConfig(n_iter=100, batch_size=25, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg
        )
        assert result.beta_flag is True

    def test_full_pipeline_workshop_drivers_no_beta_flag(self) -> None:
        """Manually-constructed drivers with derived_at_run_time=False
        keep beta_flag=False — the orchestrator's mode-gate scan
        recognises workshop output by the flag, not by who built it.
        """
        graph = _make_synthetic_graph()
        # Take an auto-mapper result and re-emit each driver with the
        # provenance flags flipped to workshop semantics, simulating
        # the prod-mode binding-layer construction (Beta-06).
        rules = _make_auto_rules(probability=0.5)
        auto_drivers = expand_auto_rules(rules, graph, AutoMapperConfig())
        workshop_drivers: dict[str, RiskDriver] = {
            rid: dataclasses.replace(
                d, derived_at_run_time=False, workshop_validated=True
            )
            for rid, d in auto_drivers.items()
        }
        cfg = ScheduleMCConfig(n_iter=100, batch_size=25, seed=42, mode="beta", mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(
            graph=graph, risk_drivers=workshop_drivers, config=cfg
        )
        assert result.beta_flag is False

    def test_full_pipeline_prod_mode_rejects_auto_mapped(self) -> None:
        graph = _make_synthetic_graph()
        rules = _make_auto_rules(probability=0.5)
        drivers = expand_auto_rules(rules, graph, AutoMapperConfig())
        cfg = ScheduleMCConfig(n_iter=100, batch_size=25, seed=42, mode="prod", mode_multipliers=TEST_MODE_MULTIPLIERS)
        with pytest.raises(ValueError) as excinfo:
            run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        msg = str(excinfo.value)
        assert "prod mode" in msg
        assert "RX" in msg
        assert "RY" in msg

    # TESTLANE-01 A sweep: unmarked - measured 0.12s in the lane-1 durations, no
    # subprocess, no notebook, no engine run. It was in the slow class by habit.
    def test_full_pipeline_streaming_consistent_across_batch_sizes(
        self,
    ) -> None:
        """Single-batch and five-batch runs over the same synthetic
        end-to-end input must produce bit-identical results at float64.

        Uses probability=1.0 to take the per-batch Bernoulli rng draw
        out of the batch-size dependence, and explicit
        severity_uniforms so per-batch severity construction is also
        independent of batch size. The remaining batch-size-sensitive
        machinery (rng.spawn for the magnitude rng, batch-slice
        arithmetic) must produce identical output.
        """
        graph = _make_synthetic_graph()
        rules = _make_auto_rules(probability=1.0)
        drivers = expand_auto_rules(rules, graph, AutoMapperConfig())

        n_iter = 1000
        sev = np.random.default_rng(7).random((n_iter, 2))

        cfg_single = ScheduleMCConfig(
            n_iter=n_iter,
            batch_size=n_iter,
            seed=99,
            precision="float64",
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        cfg_multi = ScheduleMCConfig(
            n_iter=n_iter,
            batch_size=n_iter // 5,
            seed=99,
            precision="float64",
        mode_multipliers=TEST_MODE_MULTIPLIERS)

        result_single = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg_single,
            severity_uniforms=sev,
        )
        result_multi = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg_multi,
            severity_uniforms=sev,
        )
        assert result_single.n_batches == 1
        assert result_multi.n_batches == 5
        assert np.array_equal(
            result_single.project_finish_hours,
            result_multi.project_finish_hours,
        )
        assert (
            result_single.criticality_index
            == result_multi.criticality_index
        )

    def test_full_pipeline_severity_uniform_propagates_correctly(self) -> None:
        """Pass a constructed severity_uniforms matrix with column 0 =
        all 0.5 and column 1 = all 0.5, and assert the orchestrator's
        per-iteration finish reflects the PERT median against the
        rules' (opt, ml, pess) triple.

        For a PERT(opt, ml, pess) with the canonical lambda=4 shape,
        the inverse-CDF at u=0.5 is exactly the PERT median (modal
        symmetric or skew-symmetric). For (1, 2, 4) days the median
        is approximately 2.13 days; for the test we use the symmetric
        (1, 2, 3) PERT where the median is exactly 2.0 days. With
        probability=1.0 this gives a deterministic delta of 2 days =
        16h on every affected activity.
        """
        graph = _make_synthetic_graph()
        # Override RX with symmetric PERT (1, 2, 3); only this driver
        # is needed for the propagation check. Drop RY to simplify.
        rules = {
            "RX": AutoMapperRule(
                risk_id="RX",
                pattern_id="PX",
                pattern_prefixes=("X.C",),
                float_threshold_hours=480.0,
                injection_method="additive_pert_days",
                opt_pert=1.0,
                ml_pert=2.0,
                pess_pert=3.0,
                probability=1.0,
            ),
        }
        drivers = expand_auto_rules(rules, graph, AutoMapperConfig())

        n_iter = 50
        # Single-column severity matrix (one risk).
        sev = np.full((n_iter, 1), 0.5, dtype=np.float64)

        cfg = ScheduleMCConfig(
            n_iter=n_iter,
            batch_size=n_iter,
            seed=42,
            precision="float64",
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg,
            severity_uniforms=sev,
        )
        # Symmetric PERT(1, 2, 3) at u=0.5 → median 2.0 days = 16h.
        # Each of the 5 X-chain activities gets +16h; chain X total
        # finish = 5 × (80 + 16) = 480h. Chain Y unaffected (200h).
        # Project finish = 480h, every iteration.
        assert np.allclose(result.project_finish_hours, 480.0)

    def test_full_pipeline_no_refproject_specifics(self) -> None:
        """Meta-test: walk the orchestrator's AST and assert no
        RefProject-specific business-logic tokens leak into executable
        code (identifiers, string literals consumed by control flow,
        default values). The reusability invariant per Beta-00.3
        demands the module be project-agnostic.

        Self-attestation prose in module/class/function docstrings (e.g.
        "no RefProject paths") is allowed and expected — it's the
        documented convention across every module in ``src/sra/cpm/``.
        Triple-quoted docstrings are excluded from the scan; non-
        docstring string literals and all identifier names are checked.
        """
        import ast

        src_path = Path(cpm_simulation.__file__)
        text = src_path.read_text(encoding="utf-8")
        tree = ast.parse(text)

        # Collect docstring node ids so we can skip them. Any
        # ``ast.Constant`` whose value is a string and whose direct
        # parent is a ``Module`` / ``FunctionDef`` / ``AsyncFunctionDef`` /
        # ``ClassDef`` first body element is a docstring.
        docstring_ids: set[int] = set()
        for parent in ast.walk(tree):
            if isinstance(
                parent,
                (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                if (
                    parent.body
                    and isinstance(parent.body[0], ast.Expr)
                    and isinstance(parent.body[0].value, ast.Constant)
                    and isinstance(parent.body[0].value.value, str)
                ):
                    docstring_ids.add(id(parent.body[0].value))

        # Forbidden business-logic tokens. Case-insensitive match against
        # all non-docstring string literals AND all identifier names.
        forbidden_substrings = (
            "refproject",
            "v8" + "_val",  # built, so this file does not name the register
            "v8" + "val",
            "contractor",
            "contractor",
            "prj-ref-0000",
            "s" + "jp",
        )
        # Strawman pattern code regex (P01-P14 etc.) and RefProject-style
        # risk-id literal regex (R001 etc.). Run only against non-
        # docstring strings.
        pattern_code_re = re.compile(r"\bP\d{2}\b")
        risk_literal_re = re.compile(r"\bR\d{3}\b")

        leaks: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_ids:
                    continue
                lit = node.value
                lit_lower = lit.lower()
                for tok in forbidden_substrings:
                    if tok in lit_lower:
                        leaks.append(f"string literal contains {tok!r}: {lit!r}")
                if pattern_code_re.search(lit):
                    leaks.append(f"P-code in string literal: {lit!r}")
                if risk_literal_re.search(lit):
                    leaks.append(f"R-code in string literal: {lit!r}")
            elif isinstance(node, ast.Name):
                lower = node.id.lower()
                for tok in forbidden_substrings:
                    if tok in lower:
                        leaks.append(f"identifier contains {tok!r}: {node.id}")
            elif isinstance(node, ast.Attribute):
                lower = node.attr.lower()
                for tok in forbidden_substrings:
                    if tok in lower:
                        leaks.append(
                            f"attribute access contains {tok!r}: .{node.attr}"
                        )

        assert not leaks, (
            "RefProject-specific business-logic tokens leaked into "
            f"src/sra/cpm/cpm_simulation.py: {leaks}"
        )
