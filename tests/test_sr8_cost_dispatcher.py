"""SR8 - cost_dispatcher tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.integrated.cost_dispatcher import DISTRIBUTION_SAMPLERS, sample_cost


@dataclass
class _Risk:
    risk_id: str
    distribution: str
    opt_cost: float
    ml_cost: float
    pess_cost: float


def test_dispatcher_routes_pert_correctly():
    risk = _Risk("X1", "PERT", 0.0, 100.0, 200.0)
    v_low = sample_cost(risk, 0.05)
    v_high = sample_cost(risk, 0.95)
    assert 0.0 <= v_low <= 200.0
    assert 0.0 <= v_high <= 200.0
    assert v_high > v_low


def test_dispatcher_routes_lognormal_correctly():
    risk = _Risk("X2", "Lognormal", 100.0, 500.0, 2000.0)
    v_low = sample_cost(risk, 0.05)
    v_high = sample_cost(risk, 0.95)
    assert v_low > 0
    assert v_high > v_low
    # Lognormal has a long tail; v_high should exceed pess in some draws
    v_extreme = sample_cost(risk, 0.999)
    assert v_extreme > 0


def test_dispatcher_routes_triangular_correctly():
    risk = _Risk("X3", "Triangular", -1000.0, 500.0, 2000.0)
    v_low = sample_cost(risk, 0.05)
    v_high = sample_cost(risk, 0.95)
    assert v_low >= -1000.0
    assert v_high <= 2000.0
    assert v_high > v_low


def test_dispatcher_routes_binary_correctly():
    risk = _Risk("X4", "Binary", 0.0, 250.0, 0.0)
    # Binary returns ml regardless of u
    assert sample_cost(risk, 0.0) == 250.0
    assert sample_cost(risk, 0.5) == 250.0
    assert sample_cost(risk, 1.0) == 250.0


def test_dispatcher_unknown_distribution_raises():
    risk = _Risk("X5", "NotADist", 0.0, 100.0, 200.0)
    with pytest.raises(ValueError, match="Unknown distribution_type"):
        sample_cost(risk, 0.5)


def test_dispatcher_dict_has_expected_keys():
    expected = {"PERT", "Lognormal", "Triangular", "Binary"}
    assert expected.issubset(set(DISTRIBUTION_SAMPLERS.keys()))
