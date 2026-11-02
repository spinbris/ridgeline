"""JCLAXIS-01: the JCL cost axis on the budget's basis, and the correlation shown.

P1  the cost axis is base drawn + event-risk cost + delay cost, the total the budget funds,
    in the report (``stage3_jcl``), the period JSON and the held-budget JCL.
P2  ``jcl_data`` returns Spearman's rank correlation of the cost axis against finish.
P3  ``jcl_data`` returns the four quadrant shares, summing to one.
P4  the text says why the cloud is flat and why delay cost is on the cost axis.
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import numpy as np

from src.integrated.integrated_dollars import integrated_dollars_array
from src.integrated.jcl import jcl_data, rank_correlation

DAY_RATE = 35_000.0


def _paired(n: int = 4_000, seed: int = 11):
    rng = np.random.default_rng(seed)
    fired = rng.random((n, 6)) < 0.35
    sev = rng.random((n, 6))
    cost = (fired * sev * 2.0e6).sum(axis=1)
    days = (fired * sev * 30.0).sum(axis=1)
    return cost, days, 400.0 + days


def _stage3(cost, days, finish):
    return {"cost_result": {"cost_dollars_array": cost}, "schedule_days_array": days,
            "schedule_result": SimpleNamespace(project_finish_days=finish)}


# P1 -----------------------------------------------------------------------

def test_the_report_cost_axis_carries_delay_cost():
    from src.final.sections.integrated_total import stage3_jcl

    cost, days, finish = _paired()
    base = 50e6 + np.random.default_rng(1).normal(0, 2e6, cost.size)
    jcl = stage3_jcl(_stage3(cost, days, finish), {"base_dollars": base,
                                                   "base_total_dollars": 50e6}, DAY_RATE)
    assert np.array_equal(jcl["cost_axis"], base + integrated_dollars_array(cost, days, DAY_RATE))
    no_base = stage3_jcl(_stage3(cost, days, finish), None, DAY_RATE)
    assert np.array_equal(no_base["cost_axis"], integrated_dollars_array(cost, days, DAY_RATE))


def test_all_delay_money_now_counts_against_the_budget():
    """The INTSCURVE-01 control inverted: when all the money is delay, the budget can be missed."""
    from src.am.json_writer import _build_jcl

    days = np.linspace(0.0, 50.0, 1_000)
    result = SimpleNamespace(
        cost_dollars_array=np.zeros(days.size), schedule_days_array=days,
        integrated_dollars_array=integrated_dollars_array(np.zeros(days.size), days, DAY_RATE),
        deterministic_baseline_days=300.0, project_finish_days=300.0 + days, day_rate=DAY_RATE)
    j = _build_jcl(result, _dt.date(2024, 1, 1), None)
    assert j["cost_confidence"] < 0.81
    assert "delay cost" in j["basis"] and "excluded" not in j["basis"]


def test_the_held_budget_jcl_uses_the_same_axis():
    from src.am.integrated_views import jcl_against_held

    cost, days, finish = _paired()
    result = SimpleNamespace(cost_dollars_array=cost, schedule_days_array=days,
                             project_finish_days=finish, day_rate=DAY_RATE)
    held = jcl_against_held(result, None, 1e6)
    assert np.array_equal(held["cost_axis"], integrated_dollars_array(cost, days, DAY_RATE))


# P2, P3 --------------------------------------------------------------------

def test_rank_correlation_is_spearman_with_average_ranks():
    x = np.array([1.0, 2.0, 2.0, 4.0, 5.0])
    y = np.array([5.0, 6.0, 7.0, 8.0, 7.0])
    # Hand ranks: x -> 1, 2.5, 2.5, 4, 5; y -> 1, 2, 3.5, 5, 3.5; Pearson of those.
    rx, ry = np.array([1, 2.5, 2.5, 4, 5]), np.array([1, 2, 3.5, 5, 3.5])
    assert np.isclose(rank_correlation(x, y), np.corrcoef(rx, ry)[0, 1], rtol=0, atol=1e-12)
    assert np.isclose(rank_correlation(x, x**3), 1.0, rtol=0, atol=1e-12)
    assert np.isnan(rank_correlation(np.ones(5), y)), "no spread, no correlation"


def test_jcl_data_carries_the_correlation_and_the_four_quadrants():
    cost, _, finish = _paired()
    d = jcl_data(cost, finish, cost_target=float(np.percentile(cost, 80)),
                 finish_target=float(np.percentile(finish, 80)))
    assert d["rank_correlation"] == rank_correlation(cost, finish) and d["rank_correlation"] > 0.5
    q = d["quadrants"]
    assert set(q) == {"meets_both", "cost_only", "finish_only", "neither"}
    assert np.isclose(sum(q.values()), 1.0, rtol=0, atol=1e-12)
    assert q["meets_both"] == d["jcl"]
    assert np.isclose(q["meets_both"] + q["cost_only"], d["cost_confidence"], rtol=0, atol=1e-12)


# P4 ------------------------------------------------------------------------

def test_the_text_says_why_the_cloud_is_flat_and_drops_the_double_count():
    from src.am.integrated_views import jcl_basis_sentence
    from src.final import commentary_text
    from src.final.sections.integrated_total import jcl_sentence, stage3_jcl

    for text in (commentary_text.JCL_ORIENTING, commentary_text.JCL_BASIS):
        assert "counted twice" not in text
    assert "independent" in commentary_text.JCL_BASIS
    assert "delay cost" in commentary_text.JCL_ORIENTING
    cost, days, finish = _paired()
    jcl = stage3_jcl(_stage3(cost, days, finish), None, DAY_RATE)
    assert f"{jcl['rank_correlation']:.2f}" in jcl_sentence(jcl)
    assert "excluded" not in jcl_basis_sentence(jcl)
