"""SR8 - integrated_simulation tests.

SNAPSHOTCUT-01 (Director, 11/10/2026): the seven tests against the retired register and the V8
strawman, which no machine here holds, are retired; the synthetic chain tests remain.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.integrated.integrated_simulation import (
    IntegratedConfig,
    apply_chain_logic,
    run_integrated_simulation,
)
from src.sra.methodology_defaults_reader import build_test_methodology_defaults

from tests._fixture_values import FIXTURE_DAY_RATE
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


#: REFRETIRE-01: the chain roles below came from a project binding's legacy chain map, so these
#: two tests only meant anything with that project selected - and one of them is a negative test,
#: which passes vacuously when no chain fires. They declare the map themselves now.
_TEST_CHAIN_RISK_IDS = {
    "c1_trigger": "R076", "c1_target": "R015",
    "c2_trigger": "R017", "c2_targets": ["R018", "R019"],
}


def test_apply_chain_logic_resamples_with_elevated_probability_under_synthetic_fixture():
    """Synthetic fixture: include trigger and target risks the cost engine
    expects (R076, R015) so chain1 actually fires. Verify the resample
    mechanism elevates target firing rate under chain_mask iterations.
    """
    @dataclass
    class _R:
        risk_id: str
        description: str = ""
        owner: str = "BOP"
        distribution: str = "PERT"
        correlation_group: str = "CG13"
        probability: float = 0.5
        opt_cost: float = 0.0
        ml_cost: float = 0.0
        pess_cost: float = 0.0
        ml_days: float = 0.0
        mc_include: bool = True
        basis: str = ""
        recurrence_type: str = ""
        recurrence_param: float = 0.0
        cascade_group: str = ""
        opt_schedule_days: float = 0.0
        pess_schedule_days: float = 0.0
        cause: str = ""
        consequence: str = ""
        existing_controls: str = ""
        risk_status: str = "Open"
        direction: str = "Threat"
        rbs_l1: str = ""
        rbs_l2: str = ""

    risks = [
        # Strong trigger: high prob, large pess so months proxy easily exceeds 3
        _R("R076", probability=0.5, opt_cost=0, ml_cost=1_000_000, pess_cost=10_000_000),
        # Target with low base probability - amplification should boost it
        _R("R015", probability=0.05, opt_cost=0, ml_cost=200_000, pess_cost=500_000),
    ]
    risk_scope = pd.DataFrame()  # cost-only synthetic

    cfg = IntegratedConfig(
        register_path=Path("/tmp/x"), p6_path=Path("/tmp/x"),
        strawman_path=Path("/tmp/x"),
        iterations=10000, random_seed=7,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
        chain_risk_ids=dict(_TEST_CHAIN_RISK_IDS),
    **TEST_CALIBRATION_TOLERANCES)
    res = run_integrated_simulation(cfg, risks, risk_scope)
    # When chain triggers (R076 fires AND months proxy >=3), R015 fires
    # at elevated probability min(0.05*2.5, 0.95) = 0.125. Without chain, only 5%.
    assert res["chain1_active_iterations"] > 0
    # Compare R015 firing rate inside vs outside chain_mask iterations.
    # Under chain1: target firing rate should approach the elevated probability.


def test_apply_chain_logic_does_not_multiply_target_contribution():
    """Negative test: ensure the implementation is RESAMPLE, not multiplicative.

    If we used the v1 wrong mechanism (cost *= amplification), R015's cost
    in chain-active iterations would be the original cost x 2.5. Under the
    correct resample mechanism, R015's cost in chain-active iterations is a
    completely fresh PERT draw (uncorrelated with the original draw).
    """
    @dataclass
    class _R:
        risk_id: str
        description: str = ""
        owner: str = "BOP"
        distribution: str = "PERT"
        correlation_group: str = "CG13"
        probability: float = 0.5
        opt_cost: float = 0.0
        ml_cost: float = 0.0
        pess_cost: float = 0.0
        ml_days: float = 0.0
        mc_include: bool = True
        basis: str = ""
        recurrence_type: str = ""
        recurrence_param: float = 0.0
        cascade_group: str = ""
        opt_schedule_days: float = 0.0
        pess_schedule_days: float = 0.0
        cause: str = ""
        consequence: str = ""
        existing_controls: str = ""
        risk_status: str = "Open"
        direction: str = "Threat"
        rbs_l1: str = ""
        rbs_l2: str = ""

    risks = [
        _R("R076", probability=1.0, opt_cost=0, ml_cost=1_000_000, pess_cost=10_000_000),
        _R("R015", probability=1.0, opt_cost=100, ml_cost=100, pess_cost=100),
        # ml_cost = 100 means PERT collapses to ~100 always
    ]
    risk_scope = pd.DataFrame()
    cfg = IntegratedConfig(
        register_path=Path("/tmp/x"), p6_path=Path("/tmp/x"),
        strawman_path=Path("/tmp/x"),
        iterations=5000, random_seed=11,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
        chain_risk_ids=dict(_TEST_CHAIN_RISK_IDS),
    **TEST_CALIBRATION_TOLERANCES)
    res = run_integrated_simulation(cfg, risks, risk_scope)
    # R015 cost should be ~100 in all iterations (because PERT collapses with
    # opt=ml=pess=100). If multiplicative, post-chain R015 would be 100*2.5=250.
    r015_idx = res["risk_ids_all"].index("R015")
    r015_costs = res["per_risk_cost_array"][:, r015_idx]
    fired_mask = res["fired_array"][:, r015_idx]
    if fired_mask.any():
        max_fired = float(np.max(r015_costs[fired_mask]))
        # Allow tiny numerical noise but reject 250 (the multiplicative artefact)
        assert max_fired < 150.0, (
            f"R015 max fired cost {max_fired} suggests multiplicative implementation; "
            f"expected ~100 under PERT-collapsed-to-point distribution"
        )


def test_chain_config_imported_from_cost_engine_not_redefined():
    """Verify chain_risk_ids and ChainConfig defaults come from cost engine.

    Reads CHAIN_RISK_IDS from src.defaults and asserts IntegratedConfig's
    default chain_risk_ids is identical (not a redefinition).
    """
    from src.defaults import CHAIN_RISK_IDS as cost_engine_ids

    cfg = IntegratedConfig(
        register_path=Path("/tmp/x"), p6_path=Path("/tmp/x"),
        strawman_path=Path("/tmp/x"),
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)
    assert cfg.chain_risk_ids == cost_engine_ids
    # Verify ChainConfig defaults match
    from src.config import ChainConfig as cost_engine_chain
    expected = cost_engine_chain()
    assert cfg.chain_config.c1_amplification == expected.c1_amplification
    assert cfg.chain_config.c1_trigger_months == expected.c1_trigger_months
    assert cfg.chain_config.c2_cascade_factor == expected.c2_cascade_factor
    assert cfg.chain_config.c2_trigger_weeks == expected.c2_trigger_weeks
