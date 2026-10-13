"""SR15.1 — Stage 3 composer engine-path wiring tests.

Unit-level coverage of :func:`src.final.stage3_composer._build_stage3_integrated_scenario`:

* The helper invokes :func:`run_integrated_simulation_stage3` with
  ``apply_mode_multipliers=False`` (verified via patch).
* Pre-loaded inputs from ``stage3_beta_result`` (risk_drivers,
  schedule_graph, xer_tables, severity_uniforms_by_risk_id) are
  threaded into the engine call so the XER is NOT re-parsed and the
  per-risk fire mask + severity uniforms are bit-identical to the
  smoke-runner output at the same seed.
* The returned scenario dict carries:
  - ``schedule_days_array`` sourced from the Stage 3 engine.
  - ``per_risk_schedule_array`` sourced from the Stage 2.5
    integrated engine's ``per_risk_schedule_pre_mode_array``
    (unsuppressed per-risk ranking for Table 6).
  - ``cost_dollars_array`` from the Stage 3 engine's cost arm
    (bit-identical to the Stage 2.5 cost arm at seed-paired level
    per the SR11 invariant).

These tests avoid file I/O by patching the engine call; the
end-to-end smoke covering the production-path docx is in
:mod:`tests.test_sr15_1_stage3_production_wiring` (the 1000-iter
seed=42 smoke).
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest
from tests._fixture_values import FIXTURE_DAY_RATE


def _make_stage25_integrated_dp() -> dict:
    """Build a synthetic Stage 2.5 DP_Review integrated result dict.

    Mirrors the keys :func:`run_integrated_simulation` actually returns,
    sized to a small synthetic 1000-iter / 3-cost-risk / 2-dual-risk
    scenario."""
    n_iter = 1000
    rng = np.random.default_rng(42)
    return {
        "cost_dollars_array": rng.lognormal(15.0, 1.0, size=n_iter),
        "schedule_days_array": rng.gamma(2.0, 5.0, size=n_iter),  # Mode-suppressed
        "per_risk_cost_array": rng.lognormal(13.0, 0.8, size=(n_iter, 3)),
        "per_risk_schedule_array": np.zeros((n_iter, 2)),  # Mode-zero
        "per_risk_schedule_pre_mode_array": rng.gamma(
            2.0, 5.0, size=(n_iter, 2),
        ),
        "fired_array": rng.random((n_iter, 3)) < 0.5,
        "risk_ids_all": ["R013", "R067", "R090"],
        "risk_ids_dual": ["R013", "R067"],
        "dual_lookup": {},
        "iterations": n_iter,
        "seed_used": 42,
    }


def _make_stage3_beta_result_stub() -> dict:
    """Stub of the run_refproject_stage3_beta return dict; carries pre-loaded
    state for the SR15.1 composer to thread into
    :func:`run_integrated_simulation_stage3` without re-parsing the .xer.
    """
    return {
        "risk_drivers": {"R013": MagicMock(), "R067": MagicMock()},
        "schedule_graph": MagicMock(),
        "xer_tables": {"TASK": pd.DataFrame()},
        "severity_uniforms_by_risk_id": {
            "R013": np.zeros(1000), "R067": np.zeros(1000),
            "R090": np.zeros(1000),
        },
    }


def _stub_stage3_result(n_iter: int = 1000) -> MagicMock:
    """Construct a stub Stage3IntegratedResult-like object."""
    rng = np.random.default_rng(7)
    result = MagicMock()
    # Schedule arm: substantially larger than the Mode-suppressed
    # Stage 2.5 fixture so the SR15.1 swap is visible.
    result.schedule_days_array = rng.gamma(50.0, 10.0, size=n_iter)
    # Cost arm: bit-identical to the Stage 2.5 fixture (the SR11 invariant
    # promises bit-identity at the seed-paired level; we don't actually
    # have that under the patched stub, but the field is exposed).
    result.cost_result = {
        "cost_dollars_array": rng.lognormal(15.0, 1.0, size=n_iter),
        "per_risk_cost_array": rng.lognormal(13.0, 0.8, size=(n_iter, 3)),
    }
    return result


class TestBuildStage3IntegratedScenario:
    """Direct unit tests on the SR15.1 helper."""

    @patch(
        "src.final.stage3_composer.run_integrated_simulation_stage3",
        return_value=_stub_stage3_result(),
    )
    @patch(
        "src.final.stage3_composer.strawman_reader.read_risk_scope",
        return_value=pd.DataFrame({"risk_id": ["R013"]}),
    )
    def test_helper_calls_stage3_engine_with_apply_mode_multipliers_false(
        self, _read_scope, mock_engine,
    ):
        from src.final.stage3_composer import _build_stage3_integrated_scenario
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        stage25_dp = _make_stage25_integrated_dp()
        beta = _make_stage3_beta_result_stub()
        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)

        _build_stage3_integrated_scenario(
            stage3_beta_result=beta,
            integrated_dp_review=stage25_dp,
            config=cfg,
            strawman_path=Path("/x/straw.xlsx"),
        )

        assert mock_engine.called, (
            "_build_stage3_integrated_scenario must invoke "
            "run_integrated_simulation_stage3"
        )
        # The positional config carries apply_mode_multipliers=False on
        # its schedule_mc_config — SR15 + SR15.1 contract.
        call_args = mock_engine.call_args
        s3_int_cfg = call_args.args[0] if call_args.args else call_args.kwargs["config"]
        assert s3_int_cfg.schedule_mc_config.apply_mode_multipliers is False, (
            "Stage 3 engine called with apply_mode_multipliers=True; "
            "SR15.1 requires False on the production path"
        )

    @patch(
        "src.final.stage3_composer.run_integrated_simulation_stage3",
        return_value=_stub_stage3_result(),
    )
    @patch(
        "src.final.stage3_composer.strawman_reader.read_risk_scope",
        return_value=pd.DataFrame({"risk_id": ["R013"]}),
    )
    def test_helper_threads_preloaded_inputs_from_stage3_beta_result(
        self, _read_scope, mock_engine,
    ):
        from src.final.stage3_composer import _build_stage3_integrated_scenario
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        stage25_dp = _make_stage25_integrated_dp()
        beta = _make_stage3_beta_result_stub()
        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)

        _build_stage3_integrated_scenario(
            stage3_beta_result=beta,
            integrated_dp_review=stage25_dp,
            config=cfg,
            strawman_path=Path("/x/straw.xlsx"),
        )

        kw = mock_engine.call_args.kwargs
        assert kw.get("schedule_graph") is beta["schedule_graph"]
        assert kw.get("xer_tables") is beta["xer_tables"]
        assert kw.get("risk_drivers") is beta["risk_drivers"]
        assert kw.get("severity_uniforms_by_risk_id") is beta[
            "severity_uniforms_by_risk_id"
        ]

    @patch(
        "src.final.stage3_composer.run_integrated_simulation_stage3",
    )
    @patch(
        "src.final.stage3_composer.strawman_reader.read_risk_scope",
        return_value=pd.DataFrame({"risk_id": ["R013"]}),
    )
    def test_scenario_dict_uses_stage3_schedule_days(
        self, _read_scope, mock_engine,
    ):
        from src.final.stage3_composer import _build_stage3_integrated_scenario
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        stub = _stub_stage3_result()
        mock_engine.return_value = stub
        stage25_dp = _make_stage25_integrated_dp()
        beta = _make_stage3_beta_result_stub()
        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)
        s3_dp = _build_stage3_integrated_scenario(
            stage3_beta_result=beta,
            integrated_dp_review=stage25_dp,
            config=cfg,
            strawman_path=Path("/x/straw.xlsx"),
        )
        np.testing.assert_array_equal(
            s3_dp["schedule_days_array"],
            stub.schedule_days_array,
        )
        # Stage 3 schedule mean is materially higher than the
        # Mode-suppressed Stage 2.5 schedule mean.
        assert float(np.mean(s3_dp["schedule_days_array"])) > float(
            np.mean(stage25_dp["schedule_days_array"]),
        )

    @patch(
        "src.final.stage3_composer.run_integrated_simulation_stage3",
        return_value=_stub_stage3_result(),
    )
    @patch(
        "src.final.stage3_composer.strawman_reader.read_risk_scope",
        return_value=pd.DataFrame({"risk_id": ["R013"]}),
    )
    def test_scenario_dict_uses_pre_mode_per_risk_schedule(
        self, _read_scope, _mock_engine,
    ):
        """SR15.1 — per_risk_schedule_array swapped to the Stage 2.5
        pre-Mode-multiplier variant so Parallel-mode risks surface
        non-zero contribution in Table 6."""
        from src.final.stage3_composer import _build_stage3_integrated_scenario
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        stage25_dp = _make_stage25_integrated_dp()
        beta = _make_stage3_beta_result_stub()
        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)
        s3_dp = _build_stage3_integrated_scenario(
            stage3_beta_result=beta,
            integrated_dp_review=stage25_dp,
            config=cfg,
            strawman_path=Path("/x/straw.xlsx"),
        )
        np.testing.assert_array_equal(
            s3_dp["per_risk_schedule_array"],
            stage25_dp["per_risk_schedule_pre_mode_array"],
        )
        # The pre-Mode array is non-zero (Stage 2.5 fixture supplies
        # gamma draws); the post-Mode array would have been zero.
        assert float(np.mean(s3_dp["per_risk_schedule_array"])) > 0.0

    @patch(
        "src.final.stage3_composer.run_integrated_simulation_stage3",
        return_value=_stub_stage3_result(),
    )
    @patch(
        "src.final.stage3_composer.strawman_reader.read_risk_scope",
        return_value=pd.DataFrame({"risk_id": ["R013"]}),
    )
    def test_scenario_dict_uses_stage3_cost_arm(
        self, _read_scope, mock_engine,
    ):
        """Cost arm sourced from the Stage 3 engine (Path 2 in
        brief §4.3 — single source of truth, bit-identical at
        seed-paired level to the Stage 2.5 cost arm per SR11)."""
        from src.final.stage3_composer import _build_stage3_integrated_scenario
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        stage25_dp = _make_stage25_integrated_dp()
        beta = _make_stage3_beta_result_stub()
        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)
        s3_dp = _build_stage3_integrated_scenario(
            stage3_beta_result=beta,
            integrated_dp_review=stage25_dp,
            config=cfg,
            strawman_path=Path("/x/straw.xlsx"),
        )
        np.testing.assert_array_equal(
            s3_dp["cost_dollars_array"],
            mock_engine.return_value.cost_result["cost_dollars_array"],
        )


class TestComposerWiring:
    """Verifies the composer's top-level entry point invokes the SR15.1
    helper and the resulting composed dict carries Stage 3 schedule
    figures rather than Stage 2.5 Mode-suppressed ones."""

    @patch(
        "src.final.stage3_composer._build_stage3_integrated_scenario",
    )
    @patch(
        "src.final.stage3_composer.compose_final_report_data",
        return_value={"deliverable_kind_pre": "stage25"},
    )
    def test_compose_stage3_invokes_helper_when_config_supplied(
        self, _mock_inner, mock_helper,
    ):
        """When ``config`` is supplied, the SR15.1 helper fires and
        ``compose_final_report_data`` receives the substituted
        ``integrated_results_by_scenario``."""
        from src.final.stage3_composer import compose_stage3_standalone_data
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)
        stage25_dp = _make_stage25_integrated_dp()
        # Helper returns a recognisable sentinel scenario dict.
        sentinel_dp = {**stage25_dp, "schedule_days_array": np.full(1000, 999.0)}
        mock_helper.return_value = sentinel_dp

        compose_stage3_standalone_data(
            cost_results={},
            schedule_results={},
            integrated_results_by_scenario={"DP_Review": stage25_dp},
            schedule_results_by_scenario={},
            strawman_path=Path("/x/straw.xlsx"),
            register_path=Path("/x/register.xlsx"),
            cross_validation={},
            stage3_beta_result=_make_stage3_beta_result_stub(),
            config=cfg,
        )

        assert mock_helper.called, "SR15.1 helper must fire when config supplied"
        kwargs_to_inner = _mock_inner.call_args.kwargs
        passed_scenarios = kwargs_to_inner["integrated_results_by_scenario"]
        # DP_Review entry is the sentinel.
        np.testing.assert_array_equal(
            passed_scenarios["DP_Review"]["schedule_days_array"],
            sentinel_dp["schedule_days_array"],
        )

    @patch(
        "src.final.stage3_composer._build_stage3_integrated_scenario",
    )
    @patch(
        "src.final.stage3_composer.compose_final_report_data",
        return_value={},
    )
    def test_compose_stage3_skips_helper_when_config_none(
        self, _mock_inner, mock_helper,
    ):
        """Defensive fallback: when ``config`` is ``None`` the SR15.1
        rewiring is skipped and the Stage 2.5 numbers flow through.
        Keeps the composer call valid for any synthetic test path that
        doesn't supply a config."""
        from src.final.stage3_composer import compose_stage3_standalone_data

        stage25_dp = _make_stage25_integrated_dp()
        compose_stage3_standalone_data(
            cost_results={},
            schedule_results={},
            integrated_results_by_scenario={"DP_Review": stage25_dp},
            schedule_results_by_scenario={},
            strawman_path=Path("/x/straw.xlsx"),
            register_path=Path("/x/register.xlsx"),
            cross_validation={},
            stage3_beta_result=_make_stage3_beta_result_stub(),
            config=None,
        )
        assert not mock_helper.called
