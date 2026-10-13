"""SR9 v3.3 Path A - the indicative scenario is the DP Review baseline.

Tests cover:
  - resolve_indicative_scenario_name/display answer with the DP Review baseline
  - The headline P80 matches the DP Review scenario's integrated P80, not the override's
  - Architectural debt comment exists above DUMMY_REALISTIC_MODE_OVERRIDE

PRESENT-01 (D-4) retired the dev report, and with it the mode argument that made each of the
first two a pair of answers. The dev halves are gone; the regression lock that the headline is
not inflated by the override is the reason this file still exists, and it is unchanged.
The `_PROD`-namespace phrase audit went with the namespace - the rendered indicative vocabulary
it was a proxy for is measured on DUMMYSCOPE-01, which owns it.
"""
from __future__ import annotations

import copy
import pickle
from pathlib import Path

import numpy as np
import pytest

from src.final import composer
from src.final.executive_summary import (
    DP_REVIEW_SCENARIO_DISPLAY,
    DP_REVIEW_SCENARIO_NAME,
    resolve_indicative_scenario_display,
    resolve_indicative_scenario_name,
)
from tests.input_skips import skip_reason


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PICKLE = REPO_ROOT / "tests" / "fixtures" / "sr9_state_cache_v31_baseline.pkl"


# ---------------------------------------------------------------------------
# Resolver helpers
# ---------------------------------------------------------------------------

def test_resolve_indicative_scenario_name_is_dp_review():
    """Path A: the indicative slot is the DP Review baseline."""
    assert resolve_indicative_scenario_name() == "DP_Review"
    assert resolve_indicative_scenario_name() == DP_REVIEW_SCENARIO_NAME


def test_resolve_indicative_scenario_display_is_neutral():
    """The display string must not name Dummy Realistic or the interim label."""
    label = resolve_indicative_scenario_display()
    assert label == DP_REVIEW_SCENARIO_DISPLAY
    assert "Dummy" not in label
    assert "indicative" not in label.lower()


# ---------------------------------------------------------------------------
# Composer behaviour: the indicative source is DP Review
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def baseline_composed():
    if not FIXTURE_PICKLE.exists():
        pytest.skip(skip_reason(FIXTURE_PICKLE))
    with FIXTURE_PICKLE.open("rb") as f:
        d = pickle.load(f)
    return d["composed"]


def test_compose_does_not_inflate_via_dummy_override():
    """Path A regression lock: indicative_dollars must equal the DP Review P80, NOT the
    Dummy_Realistic P80. If a future patch reverts the Path A surgery, this test catches it."""
    rng = np.random.default_rng(42)
    n = 500
    cost = rng.uniform(1e7, 2e7, size=n)
    sched_dp = rng.uniform(0, 1, size=n)        # negligible
    sched_dr = rng.uniform(20, 60, size=n)      # huge difference
    integrated = {
        "DP_Review": {
            "cost_dollars_array": cost.copy(),
            "schedule_days_array": sched_dp,
            "per_risk_cost_array": rng.uniform(0, 1e6, size=(n, 1)),
            "per_risk_days_array": rng.uniform(0, 1, size=(n, 1)),
            "risk_ids": ["R001"],
        },
        "Dummy_Realistic": {
            "cost_dollars_array": cost.copy(),
            "schedule_days_array": sched_dr,
            "per_risk_cost_array": rng.uniform(0, 1e6, size=(n, 1)),
            "per_risk_days_array": rng.uniform(0, 1, size=(n, 1)),
            "risk_ids": ["R001"],
        },
    }
    from src.final.executive_summary import get_headline_contingency_range
    prod_range = get_headline_contingency_range(integrated, p_level=80, day_rate=100000.0)
    # Compute the DP Review P80 directly and compare.
    dp_p80 = float(np.percentile(cost + sched_dp * 100000.0, 80))
    assert abs(prod_range["indicative_dollars"] - dp_p80) < 1.0


# ---------------------------------------------------------------------------
# Architectural debt comment
# ---------------------------------------------------------------------------

def test_dummy_override_has_architectural_debt_comment():
    """Comment block above DUMMY_REALISTIC_MODE_OVERRIDE must name the
    architectural debt and the SR10 retirement vector."""
    src = (REPO_ROOT / "src" / "sra" / "sra_simulation.py").read_text(encoding="utf-8")
    # Find the dict definition
    idx = src.index("DUMMY_REALISTIC_MODE_OVERRIDE: dict[str, str] = {")
    # Look at the 1500 chars before the dict to find the comment block.
    preceding = src[max(0, idx - 1500):idx]
    assert "ARCHITECTURAL DEBT" in preceding
    assert "SR10" in preceding
    assert "SR9 v3.3" in preceding
