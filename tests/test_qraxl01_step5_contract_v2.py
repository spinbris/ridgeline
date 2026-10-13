"""QRAXL-01 step 5 - contract v2 gates (the shared register schema).

v2a (additive, output-neutral): the optional Activity_binding annotation read,
and the AM per-period field lock (Status + Probability only).

v2b (the core): read_layer1_v5 rebuilds the Layer1Config the hardcoded
layer1_showcase module produced, LOSSLESSLY (deep-equal + the step-4 pinned
owner P80 reproduced raw ==); returns None for a client register with no
Layer-1 sheets (Layer 1 OFF); and fails loud on a malformed Layer-1 workbook.

The authoritative RefProject-OFF bit-identity gate is
tests/test_qraxl01_0_bit_identity.py (unchanged); the wind register's Layer-1
sheets are new sheets the existing readers ignore, so those baselines still
reproduce (re-verified there).
"""
from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import shutil
from pathlib import Path

import numpy as np
import openpyxl
import pytest

import src.qra_core as qra_core
from src.config import ChainConfig, RiskInput
from src.layer1_showcase import build_showcase_layer1
from src.v5_register_reader import (
    RegisterReadError,
    read_layer1_v5,
    read_risks_v5,
)
# Reuse the step-4 owner-view register + pinned result (the migration target).
from tests.arch_guard import same_value
from tests.test_qraxl01_step4_layer1 import _l2_register, _PINNED_100K, SEED

from tests._fixture_values import FIXTURE_DAY_RATE
WIND = Path("tests/fixtures/synthetic_wind/wind_register.xlsx")


# ===========================================================================
# v2a - schedule columns (FLAG E) + AM field lock (FLAG D), lock-and-document
# ===========================================================================
#
# Per Director sign-off (2026-07-17): the risk->activity CPM link is owned
# SOLELY by the Mapping sheet's Gating_Activity_ID (read_risk_activity_mapping +
# auto_mapper). v2a adds NO Activity_binding register column - it is pure
# lock-and-document of the already-present schedule + AM per-period surface.

def test_am_period_shape_locked_status_and_probability_only() -> None:
    # FLAG D lock: AM period updates carry Status + Probability ONLY (confirmed
    # against the downstream consumer). The register reader already surfaces both;
    # there is NO per-period impact field to read (impact stays register-level).
    risks = read_risks_v5(str(WIND), risk_id_prefix="WT")
    r = risks[0]
    assert hasattr(r, "risk_status") and r.risk_status  # the AM Status lever
    assert hasattr(r, "probability") and r.probability > 0  # the AM Probability lever
    # No per-period impact field exists on the row contract (lock, not add):
    assert "period_impact" not in RiskInput.__dataclass_fields__
    assert "impact_this_period" not in RiskInput.__dataclass_fields__


# ===========================================================================
# v2b - read_layer1_v5 lossless migration + None path + fail-loud
# ===========================================================================

def test_read_layer1_v5_lossless_vs_hardcoded_module() -> None:
    read = read_layer1_v5(WIND)
    ref = build_showcase_layer1("elicited")
    assert read is not None
    assert np.array_equal(read.base, ref.base)
    assert read.row_labels == ref.row_labels
    assert read.col_labels == ref.col_labels
    assert read.factors == ref.factors            # tuple-for-tuple, incl. driver/scope
    assert read.corr_names == ref.corr_names
    assert np.array_equal(read.corr_matrix, ref.corr_matrix)
    assert read.corr_mode == ref.corr_mode
    assert read.declared_total == ref.declared_total


def test_read_layer1_v5_returns_none_for_client_register(tmp_path: Path) -> None:
    p = tmp_path / "client_no_layer1.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Risk Register"
    wb.save(p)
    assert read_layer1_v5(p) is None  # no Layer-1 sheets -> Layer 1 OFF


def test_integratedconfig_threading_slots_in() -> None:
    # read_layer1_v5 slots into IntegratedConfig.layer1_config in place of the
    # hardcoded module (the step-4 field + passthrough).
    from src.integrated.integrated_simulation import IntegratedConfig
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults
    cfg = IntegratedConfig(
        register_path=WIND, p6_path=WIND, strawman_path=WIND,
        methodology_defaults=build_test_methodology_defaults(),
        layer1_config=read_layer1_v5(WIND),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)
    assert cfg.layer1_config is not None
    assert cfg.layer1_config.factors == build_showcase_layer1().factors


# --- fail-loud on malformed Layer-1 sheets (SR21 doctrine) ------------------

def _mutate_wind(tmp_path: Path, mutator) -> Path:
    """Copy the wind register, apply a mutation to its Layer-1 sheets, save."""
    dst = tmp_path / "malformed.xlsx"
    shutil.copy(WIND, dst)
    wb = openpyxl.load_workbook(dst)
    mutator(wb)
    wb.save(dst)
    return dst


def test_fail_loud_base_sum_off(tmp_path: Path) -> None:
    def mut(wb):
        wb["Layer1_Base"]["B2"] = wb["Layer1_Base"]["B2"].value + 5.0  # break the $50M sum
    with pytest.raises(RegisterReadError, match="declared total"):
        read_layer1_v5(_mutate_wind(tmp_path, mut))


def test_fail_loud_undefined_factor_in_allocation(tmp_path: Path) -> None:
    def mut(wb):
        al = wb["Layer1_Allocation"]
        al.cell(row=al.max_row + 1, column=1, value="Ghost_Factor")
    with pytest.raises(RegisterReadError, match="not a defined factor"):
        read_layer1_v5(_mutate_wind(tmp_path, mut))


def test_fail_loud_non_psd_correlation(tmp_path: Path) -> None:
    def mut(wb):
        cs = wb["Layer1_Correlation"]
        # find the FX row (2nd corr row) and set its R_Turbine coefficient > 1
        for row in cs.iter_rows(min_row=1):
            if row[0].value == "FX":
                row[1].value = 1.5  # correlation > 1 => not positive semi-definite
                break
    with pytest.raises(RegisterReadError, match="positive semi-definite"):
        read_layer1_v5(_mutate_wind(tmp_path, mut))


def test_fail_loud_missing_wbs_row_in_allocation(tmp_path: Path) -> None:
    def mut(wb):
        al = wb["Layer1_Allocation"]
        al.cell(row=1, column=2, value="Renamed_Row")  # allocation rows != base rows
    with pytest.raises(RegisterReadError, match="WBS rows"):
        read_layer1_v5(_mutate_wind(tmp_path, mut))


# --- slow: the pinned lossless-migration reproduction (raw ==) --------------

@pytest.mark.slow
def test_lossless_migration_pinned_owner_p80_100k() -> None:
    read = read_layer1_v5(WIND)
    on = qra_core.run_cost_layer(
        n_iter=100_000, risks=_l2_register(),
        cg_coefficients={"CG01": 0.5, "CG02": 0.5}, dual_lookup={},
        chain_risk_ids={}, chain_config=ChainConfig(), seed=SEED, layer1=read,
    )
    p80 = float(np.percentile(on["cost_dollars_array"], 80))
    assert same_value(p80, _PINNED_100K["owner_cost_p80"])  # 57213788.19364301; exact on x86-64
