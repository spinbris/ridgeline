"""Tests for src.sra.cpm.cpm_simulation (SR-S3-Beta-05).

Covers the orchestrator's:

* Construction and input validation (6 tests)
* Mode gating — beta accepts mixed, prod refuses auto-mapped (4 tests)
* Severity-uniform construction (stand-alone path) (3 tests)
* Severity-uniform alignment — the architectural anchor (3 tests:
  positive, negative, full-pipeline)
* Chunking and streaming aggregation (5 tests; one marked slow)
* Reproducibility under seeded rng (4 tests)
* Reductions and result content (4 tests)
* Result dataclass shape and frozen-ness (3 tests)
* Edge cases (3 tests)

All tests construct ``ScheduleGraph`` and ``RiskDriver`` directly — no
RefProject .xer or register .xlsx file references. The reusability invariant
per Beta-00.3 is locked.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.cpm.cpm_simulation import (
    ScheduleMCConfig,
    ScheduleMCResult,
    _build_severity_uniforms,
    run_schedule_mc,
)


# ---------------------------------------------------------------------------
# Synthetic-graph helpers (mirror tests/sra/cpm/test_risk_injection.py)
# ---------------------------------------------------------------------------

_DEFAULT_CAL = Calendar()  # 8 working hours per day


def _make_activity(
    aid: str,
    *,
    duration_hours: float = 80.0,
    task_type: str = "TT_Task",
    code: str | None = None,
    total_float_hours: float | None = 0.0,
) -> Activity:
    return Activity(
        id=aid,
        code=code if code is not None else aid,
        name=aid,
        task_type=task_type,
        original_duration_hours=duration_hours,
        total_float_hours=total_float_hours,
        calendar_id=None,
    )


def _make_graph(
    activities: list[Activity],
    *,
    links: list[Link] | None = None,
    topo_order: list[str] | None = None,
    calendar: Calendar | None = None,
) -> ScheduleGraph:
    acts = {a.id: a for a in activities}
    link_list = list(links) if links is not None else []
    # Mirror tests/sra/cpm/test_cpm_kernel.py — wire links into the
    # per-activity predecessor / successor lists, since the kernel reads
    # those, not the top-level graph.links list.
    for link in link_list:
        if link.pred_id in acts:
            acts[link.pred_id].successor_links.append(link)
        if link.succ_id in acts:
            acts[link.succ_id].predecessor_links.append(link)
    return ScheduleGraph(
        activities=acts,
        links=link_list,
        topo_order=topo_order if topo_order is not None else [a.id for a in activities],
        project_default_calendar=calendar or _DEFAULT_CAL,
    )


def _driver(
    risk_id: str = "R001",
    *,
    affected: tuple[str, ...] = ("a1",),
    injection_method: str = "additive_pert_days",
    opt: float = 1.0,
    ml: float = 2.0,
    pess: float = 4.0,
    probability: float = 1.0,
    derived_at_run_time: bool = False,
    workshop_validated: bool = True,
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method=injection_method,  # type: ignore[arg-type]
        opt_pert=opt,
        ml_pert=ml,
        pess_pert=pess,
        probability=probability,
        derived_at_run_time=derived_at_run_time,
        workshop_validated=workshop_validated,
    )


def _five_activity_chain() -> ScheduleGraph:
    """Linear chain a1→a2→a3→a4→a5; deterministic finish = sum of durations.

    Each activity is 80 working hours = 10 working days.
    """
    acts = [_make_activity(f"a{i}", duration_hours=80.0) for i in range(1, 6)]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i + 1}", link_type="FS", lag_hours=0.0)
        for i in range(1, 5)
    ]
    return _make_graph(acts, links=links)


# ---------------------------------------------------------------------------
# Construction and validation
# ---------------------------------------------------------------------------

class TestConstructionAndValidation:

    def test_run_schedule_mc_smoke_default_config(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(affected=("a1", "a2"), probability=0.5)}
        cfg = ScheduleMCConfig(n_iter=200, batch_size=50, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert isinstance(result, ScheduleMCResult)
        assert result.project_finish_hours.shape == (200,)
        assert result.project_finish_days.shape == (200,)
        assert result.n_iter == 200
        assert result.n_act == 5
        assert result.n_risks == 1
        assert result.n_batches == 4
        assert result.seed_used == 42
        assert set(result.criticality_index) == {"a1", "a2", "a3", "a4", "a5"}

    def test_empty_risk_drivers_raises(self) -> None:
        graph = _five_activity_chain()
        with pytest.raises(ValueError, match="risk_drivers must be non-empty"):
            run_schedule_mc(graph=graph, risk_drivers={})

    def test_severity_uniform_shape_mismatch_raises(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(), "R002": _driver(risk_id="R002")}
        cfg = ScheduleMCConfig(seed=42, n_iter=100, batch_size=25, mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Wrong column count: 3 cols, but n_risks = 2.
        bad = np.zeros((100, 3), dtype=np.float32)
        with pytest.raises(ValueError, match="severity_uniforms shape mismatch"):
            run_schedule_mc(
                graph=graph,
                risk_drivers=drivers,
                config=cfg,
                severity_uniforms=bad,
            )

    def test_n_iter_zero_raises_via_config(self) -> None:
        with pytest.raises(ValueError, match="n_iter must be positive"):
            ScheduleMCConfig(n_iter=0, mode_multipliers=TEST_MODE_MULTIPLIERS)

    def test_batch_size_negative_raises_via_config(self) -> None:
        with pytest.raises(ValueError, match="batch_size must be positive"):
            ScheduleMCConfig(batch_size=-1, mode_multipliers=TEST_MODE_MULTIPLIERS)

    def test_invalid_precision_raises_via_config(self) -> None:
        with pytest.raises(ValueError, match="precision must be"):
            ScheduleMCConfig(precision="float16", mode_multipliers=TEST_MODE_MULTIPLIERS)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Mode gating
# ---------------------------------------------------------------------------

class TestModeGating:

    def test_prod_mode_rejects_auto_mapped_driver(self) -> None:
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(derived_at_run_time=False, workshop_validated=True),
            "R042": _driver(
                risk_id="R042",
                affected=("a3",),
                derived_at_run_time=True,
                workshop_validated=False,
            ),
        }
        cfg = ScheduleMCConfig(seed=42, n_iter=100, batch_size=25, mode="prod", mode_multipliers=TEST_MODE_MULTIPLIERS)
        with pytest.raises(ValueError) as excinfo:
            run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        msg = str(excinfo.value)
        assert "prod mode does not accept auto-mapped drivers" in msg
        assert "R042" in msg
        assert "R001" not in msg  # not auto-mapped → not surfaced

    def test_prod_mode_accepts_workshop_driver(self) -> None:
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(derived_at_run_time=False, workshop_validated=True),
        }
        cfg = ScheduleMCConfig(seed=42, n_iter=100, batch_size=25, mode="prod", mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.beta_flag is False

    def test_beta_mode_accepts_mixed_drivers(self) -> None:
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(derived_at_run_time=False, workshop_validated=True),
            "R042": _driver(
                risk_id="R042",
                affected=("a3",),
                derived_at_run_time=True,
                workshop_validated=False,
            ),
        }
        cfg = ScheduleMCConfig(seed=42, n_iter=100, batch_size=25, mode="beta", mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.beta_flag is True

    def test_beta_flag_false_when_all_workshop(self) -> None:
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(derived_at_run_time=False, workshop_validated=True),
            "R002": _driver(
                risk_id="R002",
                affected=("a2",),
                derived_at_run_time=False,
                workshop_validated=True,
            ),
        }
        cfg = ScheduleMCConfig(seed=42, n_iter=100, batch_size=25, mode="beta", mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.beta_flag is False


# ---------------------------------------------------------------------------
# Severity-uniform construction (stand-alone path)
# ---------------------------------------------------------------------------

class TestSeverityUniformConstruction:

    def test_built_severity_uniforms_shape_dtype(self) -> None:
        rng = np.random.default_rng(42)
        m = _build_severity_uniforms(
            n_iter=500, n_risks=4, rng=rng, precision="float32"
        )
        assert m.shape == (500, 4)
        assert m.dtype == np.float32

        rng2 = np.random.default_rng(42)
        m64 = _build_severity_uniforms(
            n_iter=500, n_risks=4, rng=rng2, precision="float64"
        )
        assert m64.dtype == np.float64

    def test_built_severity_uniforms_in_unit_interval(self) -> None:
        rng = np.random.default_rng(7)
        m = _build_severity_uniforms(
            n_iter=1000, n_risks=3, rng=rng, precision="float32"
        )
        assert m.min() >= 0.0
        # numpy.random.Generator.random returns values in [0, 1) — the
        # half-open interval. float32 cast preserves this since 1.0 is
        # exactly representable.
        assert m.max() < 1.0

    def test_severity_uniforms_constructed_only_when_none_passed(self) -> None:
        """When severity_uniforms is passed explicitly, the orchestrator
        does NOT consume rng for severity construction. Verified by
        comparing rng-state advancement: a run with explicit severity
        uniforms must advance the rng strictly less than a run that
        builds its own.
        """
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=1.0)}
        cfg = ScheduleMCConfig(n_iter=200, batch_size=50, seed=42, precision="float64", mode_multipliers=TEST_MODE_MULTIPLIERS)
        n_iter, n_risks = cfg.n_iter, len(drivers)

        # Path A: orchestrator builds its own severity uniforms.
        rng_built = np.random.default_rng(42)
        result_built = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg, rng=rng_built
        )

        # Path B: caller pre-builds severity uniforms with a SEPARATE
        # rng (still seed 42) so the orchestrator's rng is untouched
        # by severity construction. The orchestrator's rng is still
        # advanced by rng.spawn(n_batches) for the batch sub-generators.
        sev = _build_severity_uniforms(
            n_iter=n_iter,
            n_risks=n_risks,
            rng=np.random.default_rng(42),
            precision="float64",
        )
        rng_passed = np.random.default_rng(42)
        # Mirror the rng advancement that Path A's orchestrator does
        # internally for severity construction. After this, rng_passed
        # is at the same state Path A's rng is at when it spawns
        # batch sub-generators, so the two runs should be bit-identical.
        _ = rng_passed.random((n_iter, n_risks))
        result_passed = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg,
            severity_uniforms=sev,
            rng=rng_passed,
        )

        assert np.array_equal(
            result_built.project_finish_hours,
            result_passed.project_finish_hours,
        )
        assert result_built.criticality_index == result_passed.criticality_index


# ---------------------------------------------------------------------------
# Severity-uniform alignment — the architectural anchor (3 tests)
# ---------------------------------------------------------------------------

class TestSeverityUniformAlignment:
    """The column ordering of ``severity_uniforms`` is asserted at the
    call boundary against ``len(risk_drivers)``. The orchestrator does
    NOT permute the matrix and does NOT re-sort the drivers dict — the
    caller is responsible for constructing the matrix with columns in
    ``risk_drivers.keys()`` iteration order.

    These three tests exercise the contract from three angles:

    1. Positive: pass a dict + matching matrix; result behaves as expected.
    2. Negative: keep matrix columns fixed but permute the dict; result
       changes (proving alignment is real, not accidental).
    3. End-to-end: permute dict and column order together; result is
       invariant.
    """

    def test_severity_uniform_column_alignment_to_driver_order(self) -> None:
        """Positive alignment test — uses non-degenerate PERT triples so
        the test is *sensitive* to which severity column drives which
        risk's magnitude.

        Two parallel activities (a1, a2) with two drivers R1, R2 each
        affecting one activity. Severity column 0 carries a low uniform
        (0.05 → PERT low tail); column 1 carries a high uniform
        (0.95 → PERT high tail). With ``probability=1.0`` the Bernoulli
        is irrelevant — the only thing being tested is which column's
        uniform drives which driver's PERT inverse-CDF.

        The contract is: column ``j`` → risk at index ``j`` in
        ``iter(risk_drivers.keys())``. So R1 at index 0 must consume
        column 0 (low uniform → low magnitude), and R2 at index 1
        must consume column 1 (high uniform → high magnitude).

        We then permute ONLY the severity columns (not the dict). Now
        R1 is fed column 1 (high uniform → high magnitude) and R2 is
        fed column 0 (low uniform → low magnitude). The two activities'
        finishes flip — proving the column ordering is the binding the
        orchestrator follows.
        """
        graph = _make_graph(
            [
                _make_activity("a1", duration_hours=80.0),
                _make_activity("a2", duration_hours=80.0),
            ]
        )
        # Identical, non-degenerate PERT for both drivers, so the only
        # difference between them is which severity column they
        # consume.
        drivers = {
            "R1": _driver(
                risk_id="R1",
                affected=("a1",),
                opt=1.0, ml=2.0, pess=4.0,
                probability=1.0,
            ),
            "R2": _driver(
                risk_id="R2",
                affected=("a2",),
                opt=1.0, ml=2.0, pess=4.0,
                probability=1.0,
            ),
        }
        n_iter = 100
        cfg = ScheduleMCConfig(
            n_iter=n_iter, batch_size=n_iter, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)

        # Aligned: column 0 (low uniform) → R1 (a1); column 1 (high) → R2 (a2).
        sev_aligned = np.empty((n_iter, 2), dtype=np.float64)
        sev_aligned[:, 0] = 0.05   # R1 low magnitude
        sev_aligned[:, 1] = 0.95   # R2 high magnitude
        result_aligned = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg,
            severity_uniforms=sev_aligned,
        )
        # With identical PERT, R1 should produce a smaller delta on a1
        # than R2 on a2. Per-iteration: a1.EF < a2.EF.
        # Verified via the orchestrator's reductions: a1 is on the
        # critical path NEVER (its finish < a2's finish in every iter);
        # a2 is on the critical path always.
        assert result_aligned.criticality_index["a1"] == 0.0
        assert result_aligned.criticality_index["a2"] == 1.0

        # Misaligned: swap severity columns (but not the dict). Now R1
        # consumes the HIGH uniform and R2 the LOW. The activities'
        # criticality flips. This proves the orchestrator binds column
        # j to drivers.keys()[j] — if it had silently transposed, this
        # test would fail.
        sev_swapped = np.empty((n_iter, 2), dtype=np.float64)
        sev_swapped[:, 0] = 0.95   # R1 now reads the high uniform
        sev_swapped[:, 1] = 0.05   # R2 now reads the low uniform
        result_swapped = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg,
            severity_uniforms=sev_swapped,
        )
        assert result_swapped.criticality_index["a1"] == 1.0
        assert result_swapped.criticality_index["a2"] == 0.0

    def test_severity_uniform_dict_permutation_changes_output_when_columns_not_repermuted(
        self,
    ) -> None:
        """Negative test — proves alignment is real, not accidental.

        With non-degenerate PERT triples, swapping the dict iteration
        order WITHOUT also permuting the severity-uniform columns
        changes the output. R1's PERT(opt=1, ml=2, pess=4) gets fed
        whatever uniform is in column 0 of the matrix, and R2's
        PERT(opt=10, ml=15, pess=20) gets column 1. Permuting the dict
        re-binds R2 to column 0 and R1 to column 1 — different
        magnitudes, different output.
        """
        graph = _make_graph(
            [
                _make_activity("a1", duration_hours=80.0),
                _make_activity("a2", duration_hours=80.0),
            ]
        )
        d_R1 = _driver(
            risk_id="R1",
            affected=("a1",),
            opt=1.0, ml=2.0, pess=4.0,
            probability=1.0,
        )
        d_R2 = _driver(
            risk_id="R2",
            affected=("a2",),
            opt=10.0, ml=15.0, pess=20.0,
            probability=1.0,
        )
        n_iter = 200
        cfg = ScheduleMCConfig(
            n_iter=n_iter, batch_size=n_iter, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Column 0 = low uniform (PERT low tail); column 1 = high uniform.
        sev = np.empty((n_iter, 2), dtype=np.float64)
        sev[:, 0] = 0.05
        sev[:, 1] = 0.95

        drivers_AB = {"R1": d_R1, "R2": d_R2}
        drivers_BA = {"R2": d_R2, "R1": d_R1}

        result_AB = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers_AB,
            config=cfg,
            severity_uniforms=sev,
        )
        result_BA = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers_BA,
            config=cfg,
            severity_uniforms=sev,  # NOT repermuted — broken alignment
        )

        # Outputs must differ — R1 saw column 0 in run_AB, but column 1
        # (intended for R2) in run_BA. Same for R2.
        assert not np.allclose(
            result_AB.project_finish_hours,
            result_BA.project_finish_hours,
        )

    def test_severity_uniform_full_pipeline_alignment(self) -> None:
        """End-to-end — permute dict AND column order together; output
        invariant.
        """
        graph = _make_graph(
            [_make_activity(f"a{i}", duration_hours=80.0) for i in range(1, 6)]
        )
        d_R1 = _driver(
            risk_id="R1",
            affected=("a1",),
            opt=1.0, ml=2.0, pess=4.0,
            probability=1.0,
        )
        d_R2 = _driver(
            risk_id="R2",
            affected=("a2",),
            opt=5.0, ml=10.0, pess=15.0,
            probability=1.0,
        )
        d_R3 = _driver(
            risk_id="R3",
            affected=("a3",),
            opt=20.0, ml=25.0, pess=30.0,
            probability=1.0,
        )
        n_iter = 200
        cfg = ScheduleMCConfig(
            n_iter=n_iter, batch_size=n_iter, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        sev_orig = np.random.default_rng(99).random((n_iter, 3))

        drivers_orig = {"R1": d_R1, "R2": d_R2, "R3": d_R3}
        result_orig = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers_orig,
            config=cfg,
            severity_uniforms=sev_orig,
        )

        # Permute: dict order R3, R1, R2; column order accordingly.
        drivers_perm = {"R3": d_R3, "R1": d_R1, "R2": d_R2}
        # Original column j corresponds to risks (R1, R2, R3) at
        # positions (0, 1, 2). New dict places risks at
        # (R3=0, R1=1, R2=2) so the new severity column k must
        # reference original column [old_pos[new_risk_at_k]]:
        #   new col 0 (R3) → original col 2
        #   new col 1 (R1) → original col 0
        #   new col 2 (R2) → original col 1
        sev_perm = sev_orig[:, [2, 0, 1]]

        result_perm = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers_perm,
            config=cfg,
            severity_uniforms=sev_perm,
        )

        # Project finish, finish_days, and per-activity criticality
        # are functions of the (risk → activity → magnitude) wiring
        # which is invariant under simultaneous dict-and-column
        # permutation.
        assert np.allclose(
            result_orig.project_finish_hours,
            result_perm.project_finish_hours,
        )
        assert np.allclose(
            result_orig.project_finish_days,
            result_perm.project_finish_days,
        )
        for a_id in graph.topo_order:
            assert result_orig.on_critical_path_count[a_id] == \
                result_perm.on_critical_path_count[a_id]


# ---------------------------------------------------------------------------
# Chunking and streaming aggregation
# ---------------------------------------------------------------------------

class TestChunkingAndStreaming:

    def test_single_batch_when_batch_size_geq_n_iter(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        cfg = ScheduleMCConfig(seed=42, n_iter=50, batch_size=100, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.n_batches == 1

    def test_multiple_batches_when_batch_size_lt_n_iter(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        cfg = ScheduleMCConfig(seed=42, n_iter=350, batch_size=100, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        # 350 / 100 = 3.5 → 4 batches; final batch is 50 iterations.
        assert result.n_batches == 4

    def test_streaming_finish_array_correct_slice(self, monkeypatch) -> None:
        """Inject a deterministic mock _run_one_batch that encodes the
        batch_start as the per-iteration finish value. Verify that the
        orchestrator places each batch into the expected contiguous
        slice of finish_hours_full.
        """
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        cfg = ScheduleMCConfig(
            n_iter=350, batch_size=100, seed=42, precision="float32"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        n_act = len(graph.activities)
        captured_slices: list[tuple[int, int]] = []

        def fake_run_one_batch(
            *,
            batch_start: int,
            batch_end: int,
            graph: ScheduleGraph,
            risk_drivers,
            base_durations,
            severity_uniforms_batch,
            batch_rng,
            config,
            mode_multiplier_override=None,
            fires_out=None,
            fire_mask_batch=None,
        ) -> tuple[
            np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
        ]:
            captured_slices.append((batch_start, batch_end))
            # REPORT01 F-B: the real _run_one_batch fills this per batch; the loop
            # stitches it into the run-level mask. The double leaves every driver
            # unfired, which is enough for a slicing test and keeps the stitch
            # exercised rather than skipped.
            if fires_out is not None:
                for rid in risk_drivers:
                    fires_out[rid] = np.zeros(batch_end - batch_start, dtype=bool)
            batch_n = batch_end - batch_start
            finish = np.full(
                batch_n, fill_value=float(batch_start), dtype=np.float32
            )
            cp = np.zeros(n_act, dtype=np.int64)
            tf_sum = np.zeros(n_act, dtype=np.float64)
            tf_sum_sq = np.zeros(n_act, dtype=np.float64)
            # SR10.D: _run_one_batch return shape extended to 6-tuple
            # (added finish_sum_batch, finish_sum_sq_batch). The test's
            # streaming-slice assertions are unaffected; the new
            # accumulators are zeroed here and ignored by the streaming
            # invariants under test.
            finish_sum = np.zeros(n_act, dtype=np.float64)
            finish_sum_sq = np.zeros(n_act, dtype=np.float64)
            return finish, cp, tf_sum, tf_sum_sq, finish_sum, finish_sum_sq

        monkeypatch.setattr(
            "src.sra.cpm.cpm_simulation._run_one_batch", fake_run_one_batch
        )
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

        assert captured_slices == [(0, 100), (100, 200), (200, 300), (300, 350)]
        # Per-batch markers in their slices.
        assert np.array_equal(
            result.project_finish_hours[0:100],
            np.full(100, 0.0, dtype=np.float32),
        )
        assert np.array_equal(
            result.project_finish_hours[100:200],
            np.full(100, 100.0, dtype=np.float32),
        )
        assert np.array_equal(
            result.project_finish_hours[200:300],
            np.full(100, 200.0, dtype=np.float32),
        )
        assert np.array_equal(
            result.project_finish_hours[300:350],
            np.full(50, 300.0, dtype=np.float32),
        )

    def test_streaming_cp_count_monotone(self, monkeypatch) -> None:
        """Each per-batch cp_count is non-negative; the cumulative count
        is monotone non-decreasing per activity. Inject a mock that
        returns a fixed non-negative cp_count batch and confirm the
        running total grows by exactly that amount per batch.
        """
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        cfg = ScheduleMCConfig(
            n_iter=400, batch_size=100, seed=42, precision="float32"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        n_act = len(graph.activities)
        # Fixed per-batch contribution (a1, a3, a5 each fire 7 times).
        per_batch_cp = np.array([7, 0, 7, 0, 7], dtype=np.int64)

        def fake_run_one_batch(*, batch_start, batch_end, **_kwargs):
            batch_n = batch_end - batch_start
            finish = np.full(batch_n, 80.0, dtype=np.float32)
            tf_sum = np.zeros(n_act, dtype=np.float64)
            tf_sum_sq = np.zeros(n_act, dtype=np.float64)
            # SR10.D: _run_one_batch now returns a 6-tuple including
            # per-activity finish-sum accumulators. Mock returns zeros
            # for both new slots; the cp-count monotonicity assertion
            # under test is not affected.
            finish_sum = np.zeros(n_act, dtype=np.float64)
            finish_sum_sq = np.zeros(n_act, dtype=np.float64)
            return (
                finish,
                per_batch_cp.copy(),
                tf_sum,
                tf_sum_sq,
                finish_sum,
                finish_sum_sq,
            )

        monkeypatch.setattr(
            "src.sra.cpm.cpm_simulation._run_one_batch", fake_run_one_batch
        )
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

        # 4 batches × 7 = 28 each for a1/a3/a5; 0 for a2/a4.
        assert result.on_critical_path_count == {
            "a1": 28, "a2": 0, "a3": 28, "a4": 0, "a5": 28,
        }
        # criticality_index = count / n_iter.
        for a_id in ("a1", "a3", "a5"):
            assert result.criticality_index[a_id] == 28 / 400.0
        for a_id in ("a2", "a4"):
            assert result.criticality_index[a_id] == 0.0

    # TESTLANE-01 A sweep: unmarked - measured 0.07s in the lane-1 durations, no
    # subprocess, no notebook, no engine run. It was in the slow class by habit.
    def test_streaming_matches_nonstreaming_reference(self) -> None:
        """Single-batch and multi-batch runs over the same input must
        produce bit-identical results (float64). Deterministic drivers
        (probability=1.0) take the per-batch Bernoulli rng draw out of
        the equation; explicit severity_uniforms takes the per-batch
        severity construction out; the only difference between runs is
        ``rng.spawn(n_batches)``, which both runs handle correctly.
        """
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=1.0, ml=2.0, pess=4.0,
                probability=1.0,
            )
        }
        n_iter = 1000
        sev = np.random.default_rng(7).random((n_iter, 1))

        cfg_single = ScheduleMCConfig(
            n_iter=n_iter,
            batch_size=n_iter,
            seed=99,
            precision="float64",
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        cfg_multi = ScheduleMCConfig(
            n_iter=n_iter,
            batch_size=n_iter // 4,
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

        assert np.array_equal(
            result_single.project_finish_hours,
            result_multi.project_finish_hours,
        )
        assert np.array_equal(
            result_single.project_finish_days,
            result_multi.project_finish_days,
        )
        assert result_single.criticality_index == result_multi.criticality_index
        assert (
            result_single.on_critical_path_count
            == result_multi.on_critical_path_count
        )


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:

    def test_full_run_reproducible_with_seed(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg = ScheduleMCConfig(n_iter=400, batch_size=100, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        r1 = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        r2 = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert np.array_equal(r1.project_finish_hours, r2.project_finish_hours)
        assert r1.criticality_index == r2.criticality_index

    def test_full_run_reproducible_with_passed_severity_uniforms(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg = ScheduleMCConfig(n_iter=400, batch_size=100, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        sev = np.random.default_rng(7).random((400, 1)).astype(np.float32)
        r1 = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg,
            severity_uniforms=sev,
        )
        r2 = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg,
            severity_uniforms=sev,
        )
        assert np.array_equal(r1.project_finish_hours, r2.project_finish_hours)

    def test_seed_changes_output(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg42 = ScheduleMCConfig(n_iter=400, batch_size=100, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        cfg99 = ScheduleMCConfig(n_iter=400, batch_size=100, seed=99, mode_multipliers=TEST_MODE_MULTIPLIERS)
        r1 = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg42)
        r2 = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg99)
        # Different seeds → different uniform draws → different outputs
        # somewhere. Compare any-difference, not all-difference.
        assert not np.array_equal(
            r1.project_finish_hours, r2.project_finish_hours
        )

    def test_independent_rng_passed_overrides_seed(self) -> None:
        """Passing an explicit rng wins over config.seed — documented
        behaviour. Two runs with the same explicit rng (but different
        seeds in config) produce the same output. Audit field
        ``seed_used`` is ``None`` to signal that the run's seed is not
        recoverable from ``config.seed``.
        """
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg42 = ScheduleMCConfig(n_iter=400, batch_size=100, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        cfg99 = ScheduleMCConfig(n_iter=400, batch_size=100, seed=99, mode_multipliers=TEST_MODE_MULTIPLIERS)
        r1 = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg42,
            rng=np.random.default_rng(123),
        )
        r2 = run_schedule_mc(
            graph=graph,
            risk_drivers=drivers,
            config=cfg99,
            rng=np.random.default_rng(123),
        )
        assert np.array_equal(r1.project_finish_hours, r2.project_finish_hours)
        # Audit-field integrity: external rng → seed_used is None
        # regardless of config.seed (M1 from Beta-05 review).
        assert r1.seed_used is None
        assert r2.seed_used is None
        # config_summary preserves the declared config — that's a record
        # of intent, distinct from what was actually seeded.
        assert r1.config_summary["seed"] == 42
        assert r2.config_summary["seed"] == 99

    def test_seed_used_recorded_when_orchestrator_constructs_rng(self) -> None:
        """The companion to test_independent_rng_passed_overrides_seed.
        When ``rng`` is None and the orchestrator constructs from
        ``config.seed``, ``seed_used`` matches.
        """
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg = ScheduleMCConfig(n_iter=200, batch_size=50, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.seed_used == 42
        # config.seed=None: refused by name, where it once ran as seed 0 (SEEDZERO-01 D1).
        cfg_none = ScheduleMCConfig(n_iter=200, batch_size=50, seed=None, mode_multipliers=TEST_MODE_MULTIPLIERS)
        with pytest.raises(ValueError, match="no seed was given"):
            run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg_none)


# ---------------------------------------------------------------------------
# Reductions and result content
# ---------------------------------------------------------------------------

class TestReductionsAndResultContent:

    def test_project_finish_hours_equals_max_EF_per_iter(self) -> None:
        """Three-activity parallel graph — finish = max(durations).
        With probability=1.0 + opt=ml=pess=10 days for R001 affecting
        a1, R002 affecting a2: a1 = 80 + 80 = 160h, a2 = 80 + 80 = 160h,
        a3 = 80h. max = 160h.
        """
        graph = _make_graph(
            [
                _make_activity("a1", duration_hours=80.0),
                _make_activity("a2", duration_hours=80.0),
                _make_activity("a3", duration_hours=80.0),
            ]
        )
        drivers = {
            "R1": _driver(
                risk_id="R1",
                affected=("a1",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=1.0,
            ),
            "R2": _driver(
                risk_id="R2",
                affected=("a2",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=1.0,
            ),
        }
        cfg = ScheduleMCConfig(
            n_iter=50, batch_size=25, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert np.allclose(result.project_finish_hours, 160.0)

    def test_project_finish_days_conversion(self) -> None:
        """finish_days = finish_hours / working_hours_per_day. Calendar
        defaults to 8 h/day; explicit 6 h/day calendar exercises the
        non-default path.
        """
        cal_6h = Calendar(working_hours_per_day=6.0)
        graph = _make_graph(
            [_make_activity("a1", duration_hours=60.0)],
            calendar=cal_6h,
        )
        drivers = {"R001": _driver(probability=0.0)}  # never fire
        cfg = ScheduleMCConfig(
            n_iter=50, batch_size=25, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        # finish_hours = 60; finish_days = 60 / 6 = 10
        assert np.allclose(result.project_finish_hours, 60.0)
        assert np.allclose(result.project_finish_days, 10.0)

    def test_criticality_index_in_unit_interval(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg = ScheduleMCConfig(n_iter=200, batch_size=50, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        for a_id, ci in result.criticality_index.items():
            assert 0.0 <= ci <= 1.0, f"{a_id}: {ci}"

    def test_criticality_index_sums_consistent_with_count(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver(probability=0.5)}
        cfg = ScheduleMCConfig(n_iter=200, batch_size=50, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        for a_id in result.criticality_index:
            ci = result.criticality_index[a_id]
            cnt = result.on_critical_path_count[a_id]
            assert ci == cnt / float(result.n_iter)


# ---------------------------------------------------------------------------
# Result dataclass shape and frozen-ness
# ---------------------------------------------------------------------------

class TestResultDataclass:

    def test_result_is_frozen(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        cfg = ScheduleMCConfig(seed=42, n_iter=50, batch_size=25, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.n_iter = 999  # type: ignore[misc]

    def test_result_activity_ids_match_topo_order(self) -> None:
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        cfg = ScheduleMCConfig(seed=42, n_iter=50, batch_size=25, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.activity_ids == tuple(graph.topo_order)

    def test_result_risk_ids_match_drivers_iteration_order(self) -> None:
        graph = _five_activity_chain()
        drivers = {
            "R042": _driver(risk_id="R042"),
            "R001": _driver(risk_id="R001"),
            "R013": _driver(risk_id="R013"),
        }
        cfg = ScheduleMCConfig(seed=42, n_iter=50, batch_size=25, mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.risk_ids == ("R042", "R001", "R013")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_zero_probability_drivers_deterministic_baseline(self) -> None:
        """All drivers with probability=0.0 → finish constant across
        iterations and equal to the deterministic CPM finish.
        """
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(probability=0.0),
            "R002": _driver(
                risk_id="R002", affected=("a3",), probability=0.0
            ),
        }
        cfg = ScheduleMCConfig(
            n_iter=200, batch_size=50, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

        # All iterations identical.
        assert result.project_finish_hours.std() == 0.0
        # Deterministic chain finish = 5 × 80 = 400 working hours.
        assert np.allclose(result.project_finish_hours, 400.0)
        # Every activity in a chain is on the critical path.
        for a_id in ("a1", "a2", "a3", "a4", "a5"):
            assert result.criticality_index[a_id] == 1.0

    def test_one_probability_one_pert_value(self) -> None:
        """Single driver with probability=1.0 and opt=ml=pess=2 days.
        Finish = base_chain + 2 days × 8 h = 400 + 16 = 416 h.
        """
        graph = _five_activity_chain()
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=2.0, ml=2.0, pess=2.0,
                probability=1.0,
            )
        }
        cfg = ScheduleMCConfig(
            n_iter=100, batch_size=25, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert np.allclose(result.project_finish_hours, 416.0)
        assert result.project_finish_hours.std() == 0.0

    def test_probability_drives_bernoulli(self) -> None:
        """Per the framing addendum, ``RiskDriver.probability`` is the
        time-arm Bernoulli probability for schedule drivers. With
        ``probability=0.4`` over a sufficient sample, the firing rate
        should converge to 0.4 within ±2σ. Mitigates the
        probability_time vs probability confusion risk (brief §7
        last-but-one row).

        Approach: deterministic PERT (opt=ml=pess=10 days = 80h delta);
        single activity. A fired iteration adds 80h to the activity's
        duration; an unfired iteration leaves it unchanged. Counting
        the number of iterations whose finish > base duration gives
        the empirical firing rate.
        """
        graph = _make_graph(
            [_make_activity("a1", duration_hours=80.0)]
        )
        target_p = 0.4
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=target_p,
            )
        }
        n_iter = 10_000
        cfg = ScheduleMCConfig(
            n_iter=n_iter, batch_size=2_500, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

        # Base duration 80h; +10 days × 8 h/day = 160h on fire.
        # An "fired" iteration has finish == 240h; "unfired" has 80h.
        n_fired = int(np.sum(result.project_finish_hours > 80.0))
        empirical = n_fired / n_iter
        # Bernoulli(0.4, n=10k) standard error ≈ sqrt(0.4*0.6/10000)
        # ≈ 0.0049. ±3σ ≈ ±0.015 → use ±0.02 to be safe.
        assert abs(empirical - target_p) < 0.02, (
            f"empirical fire rate {empirical} too far from target "
            f"{target_p}; |Δ| = {abs(empirical - target_p)}"
        )

    def test_single_activity_graph(self) -> None:
        """Single-activity graph with no links — degenerate critical
        path. The single activity is on the CP in every iteration
        (slack = 0 trivially). Mitigates the "single-activity graph
        or graph with no links" risk (brief §7).
        """
        graph = _make_graph([_make_activity("only", duration_hours=80.0)])
        drivers = {"R001": _driver(affected=("only",), probability=0.5)}
        cfg = ScheduleMCConfig(
            n_iter=200, batch_size=50, seed=42, precision="float64"
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.n_act == 1
        # The single activity is on the critical path every iteration.
        assert result.criticality_index["only"] == 1.0
        assert result.on_critical_path_count["only"] == 200

    def test_auto_mapper_audit_path_passthrough(self) -> None:
        """config.auto_mapper_audit_path is mirrored onto the result;
        the orchestrator does NOT write to the path or check whether
        the file exists.
        """
        graph = _five_activity_chain()
        drivers = {"R001": _driver()}
        path = Path("/some/nonexistent/path/audit.parquet")
        cfg = ScheduleMCConfig(
            seed=42, n_iter=50, batch_size=25, auto_mapper_audit_path=path
        , mode_multipliers=TEST_MODE_MULTIPLIERS)
        result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert result.auto_mapper_audit_path == path
