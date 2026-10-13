"""3c Part A: cross-validation check 4 ranks the register's own Mode basis, and can fail.

Director decision, 04/09/2026. Check 4 used to rank a second "Dummy Realistic" Mode scenario
built by applying ``sra_simulation.DUMMY_REALISTIC_MODE_OVERRIDE`` - eight hardcoded reference
project risk IDs. Measured against the wind register: the intersection with its 35 ``WT-``
risks is empty, so for any project but the reference one the override changed nothing, the
"second" scenario was the baseline, and the check compared a run with itself. It could not fail.
Omitting the scenario was not an escape either: the check then reported INCONSISTENT and every
run failed.

These tests hold the new property from both sides, because only one side is worth much on its
own: check 4 now reads the **baseline** arms (so a divergent second scenario cannot change its
answer), and it **can still fail** (so its pass means something).

The existing suite in ``test_sr9_cross_validator.py`` passed unchanged across this edit, which
is the reason this file exists: every one of those cases passed the same objects as both the
baseline and the "dummy realistic" arguments, so none of them could tell the two bases apart.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.final.cross_validator import cross_validate_reports
from src.sra.sra_simulation import DUMMY_REALISTIC_MODE_OVERRIDE
from tests.test_sr9_cross_validator import _build_results, _make_config


@pytest.fixture
def strawman_path(tmp_path) -> Path:
    p = tmp_path / "strawman.xlsx"
    p.write_bytes(b"")
    return p


def _consistent_case():
    return _build_results(
        n_iter=3000,
        cost_mean_dollars=11_000_000.0,
        sched_mean_days=1.5,
        risk_ids=["R001", "R002", "R003", "R004", "R005"],
        cost_per_risk_means=[5_000_000, 3_000_000, 2_000_000, 800_000, 200_000],
        sched_per_risk_means=[1.0, 0.4, 0.1],
        sched_risk_ids=["R001", "R002", "R003"],
    )


def test_check_4_can_fail_on_the_baseline_arms(strawman_path):
    """The property the old shape lost: a pass has to be capable of being a failure.

    The integrated arm's schedule ranking is reversed against the SR5 arm's, which is exactly
    the disagreement between two engines that this check exists to catch.
    """
    cost, sched, integ = _consistent_case()
    integ = dict(integ)
    # reverse the per-risk schedule columns so the integrated top-3 ranks the other way
    integ["per_risk_schedule_array"] = np.asarray(integ["per_risk_schedule_array"])[:, ::-1]

    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=_make_config(strawman_path),
    )
    assert result["top_3_schedule_contributors_consistent"] is False
    assert result["all_pass"] is False
    assert result["top_3_schedule_contributors_sr5"] != result["top_3_schedule_contributors_integrated"]


def test_check_4_passes_on_agreeing_baseline_arms_without_any_second_scenario(strawman_path):
    """Previously this combination failed by construction: no second scenario meant
    INCONSISTENT, so every project that had none could never produce a passing deliverable."""
    cost, sched, integ = _consistent_case()
    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=_make_config(strawman_path),
    )
    assert result["top_3_schedule_contributors_consistent"] is True
    assert result["all_pass"] is True


def test_a_divergent_second_scenario_cannot_change_check_4(strawman_path):
    """It reads the baseline arms - so passing a contradictory second scenario is inert.

    This is what proves the basis actually moved, rather than the old code path merely
    being fed the baseline by every caller.
    """
    cost, sched, integ = _consistent_case()
    contrary_integ = dict(integ)
    contrary_integ["per_risk_schedule_array"] = np.asarray(
        integ["per_risk_schedule_array"]
    )[:, ::-1]

    baseline_only = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=_make_config(strawman_path),
    )
    with_contrary_second = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=_make_config(strawman_path),
        integrated_results_dummy_realistic=contrary_integ,
        schedule_results_dummy_realistic=sched,
    )
    assert (baseline_only["top_3_schedule_contributors_consistent"]
            == with_contrary_second["top_3_schedule_contributors_consistent"] is True)
    assert (baseline_only["top_3_schedule_contributors_integrated"]
            == with_contrary_second["top_3_schedule_contributors_integrated"])


def test_the_result_records_which_basis_it_ranked(strawman_path):
    """A stored result from either side of this change must not be misreadable as the other."""
    cost, sched, integ = _consistent_case()
    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=_make_config(strawman_path),
    )
    assert result["schedule_top3_basis"] == "register_mode_baseline"
    assert "register Mode basis" in result["interpretation"]


def test_the_override_that_motivated_this_is_still_reference_project_only():
    """If a future edit made the override generic, the reasoning above would need revisiting.

    Not a defence of the dict - it is named as debt - but the measurement
    that drove the decision, kept live rather than left in a record.
    """
    assert set(DUMMY_REALISTIC_MODE_OVERRIDE) == {
        "R013", "R015.1", "R016.1", "R016.2", "R017.1", "R026.1", "R067", "R090",
    }, "DUMMY_REALISTIC_MODE_OVERRIDE has changed; re-check the 3c Part A check-4 reasoning"
