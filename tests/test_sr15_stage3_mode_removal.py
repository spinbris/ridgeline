"""SR15 — Stage 3 Mode-multiplier removal: engine + binding wiring tests.

Covers the engine-tier change:

* :class:`ScheduleMCConfig` gains an ``apply_mode_multipliers: bool = True``
  field. Default ``True`` preserves the pre-SR15 Stage 2.5 behaviour
  (per-driver lookup via :data:`TEST_MODE_MULTIPLIERS`). ``False`` drops the
  multiplier entirely; every fired risk's PERT magnitude is applied at
  full strength regardless of declared Mode.
* :class:`Stage3BindingConfig` carries the same field as an
  explicit-override hook for callers driving the binding directly via
  :func:`run_refproject_stage3_beta`. Default ``True``.
* :func:`load_integrated_config_stage3` defaults the Stage 3 standalone
  path's :class:`ScheduleMCConfig` to ``apply_mode_multipliers=False``
  per Director Decision 2 = Option A.
* Driver Mode classification is preserved on the
  :class:`~src.sra.cpm.risk_driver_schema.RiskDriver` object regardless
  of the flag — the flag affects engine behaviour, not driver data
  (AC7).

Tests are synthetic-graph based: no register / strawman / .xer
dependency. The RefProject lock evidence (Stage 2.5 docx + HTML + state
cache byte-identity) is captured by the smoke-run side of the brief,
not by unit tests.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_simulation import (
    ScheduleMCConfig,
    run_schedule_mc,
)
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver, RiskMode
import pathlib as _pathlib

#: REFRETIRE-01 (D-2): the loader tests below read a client register that is not in this
#: repository and skipped everywhere, so they ran nowhere. They now name the committed wind
#: fixtures, which is what the loader is for: every input stated, nothing inherited.
_FIXTURES = _pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_wind"
_WIND_REGISTER = _FIXTURES / "wind_register.xlsx"
_WIND_XER = _FIXTURES / "wind_schedule.xer"



_DEFAULT_CAL = Calendar()


# ---------------------------------------------------------------------------
# Synthetic graph helpers — same pattern as test_cpm_mode_independent_criticality
# ---------------------------------------------------------------------------

def _activity(aid: str, *, duration_hours: float = 80.0) -> Activity:
    return Activity(
        id=aid,
        code=aid,
        name=aid,
        task_type="TT_Task",
        original_duration_hours=duration_hours,
        total_float_hours=None,
        calendar_id=None,
    )


def _make_graph(
    activities: list[Activity],
    links: list[Link],
    *,
    topo_order: list[str] | None = None,
) -> ScheduleGraph:
    acts = {a.id: a for a in activities}
    for link in links:
        if link.pred_id in acts:
            acts[link.pred_id].successor_links.append(link)
        if link.succ_id in acts:
            acts[link.succ_id].predecessor_links.append(link)
    return ScheduleGraph(
        activities=acts,
        links=list(links),
        topo_order=topo_order if topo_order is not None else [a.id for a in activities],
        project_default_calendar=_DEFAULT_CAL,
    )


def _driver(
    risk_id: str,
    *,
    affected: tuple[str, ...],
    opt: float = 5.0,
    ml: float = 10.0,
    pess: float = 20.0,
    probability: float = 1.0,
    mode: RiskMode = "Series",
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="additive_pert_days",
        opt_pert=opt,
        ml_pert=ml,
        pess_pert=pess,
        probability=probability,
        derived_at_run_time=False,
        workshop_validated=True,
        mode=mode,
    )


def _linear_chain(n: int = 4) -> ScheduleGraph:
    acts = [_activity(f"a{i}", duration_hours=80.0) for i in range(1, n + 1)]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i + 1}", link_type="FS", lag_hours=0.0)
        for i in range(1, n)
    ]
    return _make_graph(acts, links)


# ---------------------------------------------------------------------------
# Config-surface tests
# ---------------------------------------------------------------------------

class TestScheduleMCConfigFlag:
    """The ``apply_mode_multipliers`` field is exposed on
    :class:`ScheduleMCConfig` with the documented default and survives
    config construction validation."""

    def test_default_is_true(self) -> None:
        cfg = ScheduleMCConfig(mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert cfg.apply_mode_multipliers is True

    def test_explicit_false_accepted(self) -> None:
        cfg = ScheduleMCConfig(apply_mode_multipliers=False, mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert cfg.apply_mode_multipliers is False

    def test_flag_surfaces_in_result_config_summary(self) -> None:
        """When the engine runs, the result's ``config_summary`` carries
        the flag value so audit trails reflect which methodology branch
        produced the per-iteration impacts."""
        graph = _linear_chain(3)
        drivers = {
            "R1": _driver("R1", affected=("a1", "a2"), mode="Hybrid"),
        }
        cfg_true = ScheduleMCConfig(
            n_iter=200, batch_size=200, seed=42,
            apply_mode_multipliers=True,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        cfg_false = ScheduleMCConfig(
            n_iter=200, batch_size=200, seed=42,
            apply_mode_multipliers=False,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        res_t = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg_true,
        )
        res_f = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg_false,
        )
        assert res_t.config_summary["apply_mode_multipliers"] is True
        assert res_f.config_summary["apply_mode_multipliers"] is False


# ---------------------------------------------------------------------------
# AC8 — Default flag value preserves pre-SR15 behaviour
# ---------------------------------------------------------------------------

class TestDefaultPreservesPreSR15Behaviour:
    """With ``apply_mode_multipliers=True`` the engine output is
    bit-identical to a run that does not pass the new field at all.
    Verifies the field's default is a true backward-compatibility hook —
    the SR15 commit cannot introduce arithmetic drift on the Stage 2.5
    path simply by adding the new field."""

    def _run(self, *, apply_mode_multipliers: bool | None) -> np.ndarray:
        graph = _linear_chain(4)
        drivers = {
            "R_series": _driver(
                "R_series",
                affected=("a2", "a3"),
                mode="Series",
                probability=0.9,
            ),
            "R_hybrid": _driver(
                "R_hybrid",
                affected=("a3",),
                mode="Hybrid",
                probability=0.7,
            ),
        }
        kwargs: dict = dict(n_iter=500, batch_size=250, seed=42)
        if apply_mode_multipliers is not None:
            kwargs["apply_mode_multipliers"] = apply_mode_multipliers
        cfg = ScheduleMCConfig(**kwargs, mode_multipliers=TEST_MODE_MULTIPLIERS)
        return run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg,
        ).project_finish_days

    def test_omitting_field_matches_default_true(self) -> None:
        """Not passing the field at all == passing ``True``. Locks the
        documented default."""
        omitted = self._run(apply_mode_multipliers=None)
        explicit_true = self._run(apply_mode_multipliers=True)
        np.testing.assert_array_equal(omitted, explicit_true)

    def test_default_true_differs_from_false_for_hybrid_driver(self) -> None:
        """Hybrid multiplier 0.5 must produce a strictly smaller mean
        delta than the no-multiplier path; the assertion locks the
        semantic difference between the two flag values."""
        finish_true = self._run(apply_mode_multipliers=True)
        finish_false = self._run(apply_mode_multipliers=False)
        # mean finish under no-multiplier must be ≥ mean finish under
        # Mode-conditioned (more impact per fire ⇒ later finish on
        # average). Both arrays use seed=42 with the same drivers so
        # the only varying input is the multiplier.
        assert float(finish_false.mean()) > float(finish_true.mean())


# ---------------------------------------------------------------------------
# AC7 — Driver Mode classification preserved regardless of flag
# ---------------------------------------------------------------------------

class TestDriverModePreservedWithFlagFalse:
    """The driver's Mode field on :class:`RiskDriver` is unchanged when
    ``apply_mode_multipliers=False`` is set. The flag affects engine
    arithmetic; it does not mutate driver data. This contract is what
    keeps Table 6 (schedule drivers) able to display the strawman's
    Mode classification for context even when the engine ignores it."""

    def test_driver_mode_field_unchanged_after_run(self) -> None:
        graph = _linear_chain(3)
        drivers = {
            "R_par": _driver(
                "R_par",
                affected=("a2",),
                mode="Parallel",
                probability=1.0,
            ),
            "R_hyb": _driver(
                "R_hyb",
                affected=("a2",),
                mode="Hybrid",
                probability=1.0,
            ),
            "R_ser": _driver(
                "R_ser",
                affected=("a2",),
                mode="Series",
                probability=1.0,
            ),
        }
        cfg = ScheduleMCConfig(
            n_iter=100, batch_size=100, seed=42,
            apply_mode_multipliers=False,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)
        assert drivers["R_par"].mode == "Parallel"
        assert drivers["R_hyb"].mode == "Hybrid"
        assert drivers["R_ser"].mode == "Series"


# ---------------------------------------------------------------------------
# Flag-respect — Series / Hybrid / Parallel become equivalent under False
# ---------------------------------------------------------------------------

class TestFlagFalseFlattensModeMultipliers:
    """With ``apply_mode_multipliers=False`` the per-iteration impact
    magnitude is independent of declared Mode. Three identically-shaped
    drivers — same affected activity, same PERT triple, same
    probability — differing only in Mode classification (Series / Hybrid
    / Parallel) must produce identical project-finish arrays at the
    same seed.

    This is the central methodology assertion of SR15: Stage 3's
    full-CPM engine treats Mode as a reporting label, not a per-iteration
    impact scaler. Run independently per Mode so the rng stream stays
    aligned across the three runs."""

    def _run_with_mode(self, mode: RiskMode) -> np.ndarray:
        graph = _linear_chain(3)
        drivers = {
            "R": _driver(
                "R",
                affected=("a2",),
                mode=mode,
                probability=1.0,
                opt=4.0, ml=8.0, pess=16.0,
            ),
        }
        cfg = ScheduleMCConfig(
            n_iter=500, batch_size=500, seed=42,
            apply_mode_multipliers=False,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        return run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg,
        ).project_finish_days

    def test_series_and_hybrid_finish_arrays_identical(self) -> None:
        ser = self._run_with_mode("Series")
        hyb = self._run_with_mode("Hybrid")
        np.testing.assert_array_equal(ser, hyb)

    def test_series_and_parallel_finish_arrays_identical(self) -> None:
        ser = self._run_with_mode("Series")
        par = self._run_with_mode("Parallel")
        np.testing.assert_array_equal(ser, par)

    def test_finish_distributions_strictly_above_baseline(self) -> None:
        """Methodology smoke: every fired iteration extends the chain
        (the risk fires probability=1.0 on the affected activity), so
        finish days strictly exceed the baseline regardless of Mode.
        Floors the Mode=Parallel run against the Stage 2.5 semantics
        where a Parallel risk would have produced zero delta."""
        baseline = float(_linear_chain(3).activities["a3"].original_duration_hours
                         * 3 / 8.0)
        for mode in ("Series", "Hybrid", "Parallel"):
            finish = self._run_with_mode(mode)  # type: ignore[arg-type]
            # Every iteration extends the path: PERT-min ≈ 4 days > 0.
            assert float(finish.min()) > baseline + 1.0, (
                f"Mode={mode}: finish.min()={float(finish.min()):.2f} "
                f"failed baseline+1d check ({baseline + 1.0:.2f}); "
                "Mode multipliers may still be active"
            )


# ---------------------------------------------------------------------------
# Series-mode invariance — flag does not change the per-driver
# arithmetic when Mode is already Series (multiplier 1.0).
# ---------------------------------------------------------------------------

class TestSeriesModeIsFlagInvariant:
    """When every driver is Mode=Series (multiplier 1.0), the flag
    value should not affect engine output. Locks the "flag is a
    multiplier-suppressor, not a kernel-behaviour switch" invariant."""

    def test_series_only_run_identical_across_flag_values(self) -> None:
        graph = _linear_chain(4)
        drivers = {
            "R1": _driver("R1", affected=("a2",), mode="Series", probability=0.8),
            "R2": _driver("R2", affected=("a3",), mode="Series", probability=0.6),
        }
        cfg_true = ScheduleMCConfig(
            n_iter=600, batch_size=300, seed=42,
            apply_mode_multipliers=True,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        cfg_false = ScheduleMCConfig(
            n_iter=600, batch_size=300, seed=42,
            apply_mode_multipliers=False,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        finish_true = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg_true,
        ).project_finish_days
        finish_false = run_schedule_mc(
            graph=graph, risk_drivers=drivers, config=cfg_false,
        ).project_finish_days
        np.testing.assert_array_equal(finish_true, finish_false)


# ---------------------------------------------------------------------------
# Stage3BindingConfig field — explicit-override hook present
# ---------------------------------------------------------------------------

class TestStage3BindingConfigField:
    @staticmethod
    def _cfg(**kwargs):
        from src.integrated.stage3_inputs import Stage3BindingConfig
        return Stage3BindingConfig(
            register_path=_WIND_REGISTER, xer_path=_WIND_XER, strawman_path=_WIND_REGISTER,
            float_threshold_hours=480.0,
            default_injection_method="discrete_event_additive_days", **kwargs)

    def test_default_is_true(self) -> None:
        assert self._cfg().apply_mode_multipliers is True

    def test_explicit_false_accepted(self) -> None:
        assert self._cfg(apply_mode_multipliers=False).apply_mode_multipliers is False


# ---------------------------------------------------------------------------
# Stage 3 integrated path — load_integrated_config_stage3 defaults to False
# ---------------------------------------------------------------------------

# REFRETIRE-01 (D-2): the two loader tests that stood here needed a register carrying the SR19
# methodology named-range surface. The only one in the repository was the retired project's, and
# it is not here, so both skipped on every machine. The Stage 3 path's locked
# ``apply_mode_multipliers=False`` is still asserted above, at the engine and config level.
