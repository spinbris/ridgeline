"""RISKDRV-01 stage 2: shared drivers simulated in the owner view, the headline untouched.

Each guarantee here is one the build relies on: drivers off is byte-identical; a driver's cost
and duration share one draw; the owner-view replay is the run until the drivers are added.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from src.integrated.base_layer import deliverable_base_layer, register_layer1
from src.integrated.driver_pass import (
    DurationShift,
    activity_wbs_codes,
    build_duration_shift,
    load_checked_drivers,
    owner_view,
)
from src.layer1_factors import Factor, run_layer1_base
from src.rng_streams import layer1_generator
from src.shared_drivers import read_shared_drivers
from src.sra.cpm.graph_builder import build_schedule_graph
from src.sra.cpm.xer_reader import parse_xer

REPO = Path(__file__).resolve().parents[1]
WIND = REPO / "tests" / "fixtures" / "synthetic_wind"
REGISTER = WIND / "wind_register.xlsx"
XER = WIND / "wind_schedule.xer"


@pytest.fixture(scope="module")
def tables() -> dict:
    return parse_xer(XER)


@pytest.fixture(scope="module")
def drivers(tables) -> tuple:
    return load_checked_drivers(REGISTER, tables)


def test_the_wind_register_declares_the_four_ruled_drivers(drivers) -> None:
    assert [(d.driver_id, d.kind) for d in drivers] == [
        ("D1", "P"), ("D2", "P"), ("D3", "P"), ("D4", "Q")]
    assert drivers[3].linked_factors == ("Q_Grid",)


def test_wt017_is_folded_into_d3() -> None:
    from src.v5_register_reader import read_risks_v5
    assert "WT-017" not in {str(r.risk_id) for r in read_risks_v5(str(REGISTER))}


# --- The base draw -------------------------------------------------------------------------

def test_no_extra_factors_is_byte_identical() -> None:
    cfg = register_layer1(REGISTER)
    a = run_layer1_base(500, cfg, layer1_generator(42))
    b = run_layer1_base(500, cfg, layer1_generator(42), extra_factors=())
    assert np.array_equal(a["base_array"], b["base_array"])


def test_extra_factors_leave_every_register_draw_unmoved() -> None:
    cfg = register_layer1(REGISTER)
    extra = (Factor("X1", "x_prod", -0.05, 0.0, 0.2, ("Labour",), ("BOP civils",)),)
    a = run_layer1_base(500, cfg, layer1_generator(42))
    b = run_layer1_base(500, cfg, layer1_generator(42), extra_factors=extra)
    for f in cfg.factors:
        assert np.array_equal(a["factor_deltas"][f.name], b["factor_deltas"][f.name])
    assert not np.array_equal(a["base_array"], b["base_array"])


def test_an_extra_factor_named_like_a_register_factor_is_refused() -> None:
    cfg = register_layer1(REGISTER)
    with pytest.raises(ValueError, match="collide"):
        run_layer1_base(10, cfg, layer1_generator(42),
                        extra_factors=(Factor("Q_Grid", "x", -0.1, 0.0, 0.1, ("ALL",), ("ALL",)),))


def test_driver_deltas_come_from_the_base_draw(drivers) -> None:
    on = deliverable_base_layer(REGISTER, 2_000, 42, shared_drivers=drivers)
    off = deliverable_base_layer(REGISTER, 2_000, 42)
    from src.integrated.base_layer import exclude_time_factors
    cfg, _ = exclude_time_factors(register_layer1(REGISTER))  # the deliverable's D-4 base
    # P: its own draw, which is also the cost factor; Q: the linked factor's draw x elasticity.
    assert set(on["driver_deltas"]) == {"D1", "D2", "D3", "D4"}
    out = run_layer1_base(2_000, cfg, layer1_generator(42))
    assert np.array_equal(on["driver_deltas"]["D4"], 1.0 * out["factor_deltas"]["Q_Grid"])
    # The P drivers add time-dependent cost on top of the same register draws.
    assert on["base_array"].mean() > off["base_array"].mean()
    assert off["driver_deltas"] == {}


# --- The schedule shift --------------------------------------------------------------------

def test_the_shift_loads_only_the_mapped_wbs(tables, drivers) -> None:
    graph = build_schedule_graph(tables)
    deltas = {d.driver_id: np.full(3, 0.1) for d in drivers}
    shift = build_duration_shift(drivers, deltas, graph, tables)
    wbs = activity_wbs_codes(tables)
    order = tuple(graph.topo_order)
    for i, d in enumerate(drivers):
        for j, a in enumerate(order):
            want = graph.activities[a].original_duration_hours if wbs[str(a)] in d.wbs_codes else 0.0
            assert shift.loading[i, j] == want
    assert shift.batch(0, 3).shape == (3, len(order))


def test_no_drivers_no_shift(tables) -> None:
    assert build_duration_shift((), {}, build_schedule_graph(tables), tables) is None


def test_the_owner_view_refuses_a_replay_that_is_not_the_run() -> None:
    shift = DurationShift(("D1",), np.zeros((4, 1)), np.zeros((1, 2)))
    finish = np.array([10.0, 11.0, 12.0, 13.0])
    with pytest.raises(ValueError, match="does not reproduce"):
        owner_view(lambda s: finish + 1.0, shift, event_only_finish_days=finish,
                   deterministic_finish_days=10.0)


def test_the_owner_delay_is_not_floored() -> None:
    shift = DurationShift(("D1",), np.zeros((2, 1)), np.zeros((1, 2)))
    finish = np.array([10.0, 12.0])
    view = owner_view(lambda s: finish if s is None else finish - 1.0, shift,
                      event_only_finish_days=finish, deterministic_finish_days=10.0)
    assert view["delay_days"].tolist() == [-1.0, 1.0]


# --- End to end (engine runs) --------------------------------------------------------------

@pytest.fixture(scope="module")
def wind_run():
    keys = dict(QRA_PROJECT="synthetic_wind", REGISTER_FILE=str(REGISTER), P6_FILE=str(XER),
                STRAWMAN_FILE=str(REGISTER), SR9_ITERATIONS="1000", SR9_SEED="42")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    try:
        from src.final.deliverable import resolve_inputs, run_engines
        yield run_engines(resolve_inputs())
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.slow
def test_a_zero_shift_replays_the_event_only_finish(wind_run, drivers, tables) -> None:
    from src.integrated.driver_pass import stage3_owner_view
    r = wind_run.stage3_result
    zero = build_duration_shift(drivers, {d.driver_id: np.zeros(r.iterations) for d in drivers},
                                r.schedule_graph, tables)
    view = stage3_owner_view(r, wind_run.stage3_config.schedule_mc_config, zero)
    assert np.array_equal(view["finish_days"],
                          np.asarray(r.schedule_result.project_finish_days, dtype=float))


@pytest.mark.slow
def test_the_owner_view_reaches_the_total_and_the_jcl_not_the_headline(wind_run) -> None:
    from src.final.sections.integrated_total import stage3_jcl, total_cost_data
    s3, r = wind_run.stage3_beta_result, wind_run.stage3_result
    view = s3["base_layer"]["owner_view"]
    rate = float(r.config_summary["day_rate"])
    total = total_cost_data(s3["base_layer"], r.cost_result["cost_dollars_array"],
                            r.schedule_days_array, rate)
    want = s3["base_layer"]["base_array"] + (
        r.cost_result["cost_dollars_array"] + view["delay_days"] * rate)
    assert np.array_equal(total["total_dollars"], want)
    jcl = stage3_jcl(s3, total, rate)
    assert jcl["shared_drivers"] is True
    # The headline's own delay is still the event-only pass's.
    assert np.array_equal(
        r.schedule_days_array,
        np.maximum(np.asarray(r.schedule_result.project_finish_days, float)
                   - float(r.config_summary["deterministic_baseline_days"]), 0.0))
    assert [row["driver_id"] for row in s3["base_layer"]["shared_drivers"]] == [
        "D1", "D2", "D3", "D4"]


def test_the_road_register_declares_none() -> None:
    assert read_shared_drivers(REPO / "tests" / "fixtures" / "synthetic_road"
                               / "road_register.xlsx") == ()


# --- The report ----------------------------------------------------------------------------

_ROW = {"driver_id": "D1", "name": "Civil productivity", "kind": "P", "wbs_codes": ["10", "20"],
        "range": "-5% / +0% / +20%", "source": "own range; cost on BOP civils (Labour, Plant)",
        "mean_delta": 0.05, "p80_delta": 0.1, "basis": "x"}


def _total(drivers: list) -> dict:
    total = {"base_total_dollars": 120e6, "percentiles_dollars": {80: 146e6},
             "contingency_dollars": {80: 26e6}, "excluded_factors": []}
    if drivers:
        total.update(owner_finish_days=np.arange(100.0), event_finish_days=np.arange(100.0) - 10,
                     shared_drivers=drivers)
    return total


def test_the_report_names_the_drivers_and_both_finishes() -> None:
    from src.final.composer import _apply_total_cost
    composed = {"page2_distribution": {}, "page7_methodology": {}}
    _apply_total_cost(composed, _total([_ROW]), {})
    p2 = composed["page2_distribution"]
    assert "shared drivers" in p2["total_cost_basis"]
    assert "working day 79" in p2["shared_drivers_sentence"]
    assert "against 69" in p2["shared_drivers_sentence"]
    assert p2["shared_drivers_table"][0]["Kind"] == "Productivity"


def test_the_report_without_drivers_is_unchanged() -> None:
    from src.final import commentary_text
    from src.final.composer import _apply_total_cost
    composed = {"page2_distribution": {}, "page7_methodology": {}}
    _apply_total_cost(composed, _total([]), {})
    p2 = composed["page2_distribution"]
    assert p2["shared_drivers_sentence"] == "" and p2["shared_drivers_table"] == []
    assert "independent of the event risks" in p2["total_cost_basis"]
    assert commentary_text.TOTAL_COST_BASIS.endswith("{illustrative}")


def test_the_jcl_basis_follows_the_drivers() -> None:
    from src.final import commentary_text
    from src.final.composer import _apply_jcl
    jcl = {"quadrants": {"meets_both": .3, "cost_only": .1, "finish_only": .2, "neither": .4},
           "jcl": .33, "cost_target": 1.4e8, "declared_base_dollars": 1.2e8, "p_level": 80,
           "base_drawn": True, "finish_target": 420.0, "cost_confidence": .36,
           "finish_confidence": .8, "rank_correlation": .43}
    for flag, want in ((True, commentary_text.JCL_BASIS_DRIVERS),
                       (False, commentary_text.JCL_BASIS)):
        composed = {"page2_distribution": {}}
        _apply_jcl(composed, {**jcl, "shared_drivers": flag}, {})
        assert composed["page2_distribution"]["jcl_basis"] == want


# --- Stage 3: the masked leave-one-driver-out (Director S2, 03/11/2026) ---------------------

def test_the_base_without_the_last_extra_factor_is_the_run_without_it() -> None:
    cfg = register_layer1(REGISTER)
    x1 = Factor("X1", "x_prod", -0.05, 0.0, 0.2, ("Labour",), ("BOP civils",))
    x2 = Factor("X2", "x_prod", -0.05, 0.0, 0.15, ("Labour", "Plant"), ("BOP civils",))
    both = run_layer1_base(800, cfg, layer1_generator(42), extra_factors=(x1, x2))
    only1 = run_layer1_base(800, cfg, layer1_generator(42), extra_factors=(x1,))
    # X2 is drawn last, so leaving it out moves no other draw: the two bases are the same sum.
    assert np.allclose(both["base_without_extra"]["X2"], only1["base_array"], rtol=1e-12, atol=0)
    assert set(both["base_without_extra"]) == {"X1", "X2"}
    assert run_layer1_base(10, cfg, layer1_generator(42))["base_without_extra"] == {}


def test_a_shift_without_a_driver_zeroes_only_that_driver() -> None:
    shift = DurationShift(("D1", "D2"), np.array([[0.1, 0.2], [0.3, 0.4]]), np.ones((2, 3)))
    out = shift.without("D2")
    assert out.deltas.tolist() == [[0.1, 0.0], [0.3, 0.0]]
    assert shift.deltas[0, 1] == 0.2  # the original is untouched
    with pytest.raises(KeyError):
        shift.without("D9")


def test_the_owner_view_replays_once_per_driver() -> None:
    shift = DurationShift(("D1", "D2"), np.zeros((2, 2)), np.zeros((2, 2)))
    finish = np.array([10.0, 12.0])
    seen = []

    def replay(s):
        seen.append(None if s is None else s.deltas.copy())
        return finish
    view = owner_view(replay, shift, event_only_finish_days=finish, deterministic_finish_days=9.0)
    assert len(seen) == 4  # control, drivers on, one per driver
    assert set(view["finish_days_without"]) == {"D1", "D2"}
    assert view["deterministic_finish_days"] == 9.0


def test_a_driver_with_no_effect_adds_exactly_nothing() -> None:
    from src.integrated.driver_pass import driver_leave_one_out
    rng = np.random.default_rng(1)
    base, cost = 1e8 + rng.random(1000) * 1e6, rng.random(1000) * 1e6
    finish = 100.0 + rng.random(1000) * 20
    owner = {"driver_ids": ["D1", "D2"], "finish_days": finish, "deterministic_finish_days": 100.0,
             "finish_days_without": {"D1": finish, "D2": finish - 2.0}}
    loo = driver_leave_one_out(base_array=base, base_without_driver={"D1": base},
                               cost_dollars_array=cost, owner=owner, day_rate=50_000.0)
    assert loo["D1"] == {"total_p_dollars": 0.0, "finish_p_days": 0.0}
    # D2 (a Q driver: no base entry) shortens every iteration by 2 days: 2 wd and 2 x rate.
    assert abs(loo["D2"]["finish_p_days"] - 2.0) < 1e-9
    assert abs(loo["D2"]["total_p_dollars"] - 100_000.0) < 1e-3


@pytest.mark.slow
def test_report_and_period_read_one_leave_one_out(wind_run) -> None:
    from src.am.json_writer import _build_shared_drivers
    from src.final.sections.integrated_total import shared_driver_display_rows, total_cost_data
    s3, r = wind_run.stage3_beta_result, wind_run.stage3_result
    total = total_cost_data(s3["base_layer"], r.cost_result["cost_dollars_array"],
                            r.schedule_days_array, float(r.config_summary["day_rate"]))
    rows = total["shared_drivers"]
    assert [x["loo_p_level"] for x in rows] == [80] * 4
    shown = shared_driver_display_rows(rows)
    period = _build_shared_drivers(total)
    for row, disp, out in zip(rows, shown, period):
        assert disp["Adds to P80 total ($M)"] == f"${row['loo_total_dollars'] / 1e6:.2f}M"
        assert out["adds_to_total_dollars"] == round(row["loo_total_dollars"], 2)
        assert out["adds_to_finish_days"] == round(row["loo_finish_days"], 1)
    # Every wind driver lengthens work on balance, so each adds to the P80 total.
    assert all(x["loo_total_dollars"] > 0 for x in rows)


def test_no_drivers_no_owner_view_blocks() -> None:
    from types import SimpleNamespace

    from src.am.json_writer import _build_owner_view, _build_shared_drivers
    assert _build_owner_view(SimpleNamespace(base_layer=None), None) is None
    assert _build_owner_view(SimpleNamespace(base_layer={"base_array": []}), None) is None
    assert _build_shared_drivers(None) is None and _build_shared_drivers({}) is None


def test_the_report_driver_table_carries_the_leave_one_out() -> None:
    from src.final.composer import _apply_total_cost
    row = {**_ROW, "loo_total_dollars": 472_209.44, "loo_finish_days": 7.1, "loo_p_level": 80}
    composed = {"page2_distribution": {}, "page7_methodology": {}}
    _apply_total_cost(composed, _total([row]), {})
    p2 = composed["page2_distribution"]
    assert p2["shared_drivers_table"][0]["Adds to P80 total ($M)"] == "$0.47M"
    assert p2["shared_drivers_table"][0]["Adds to P80 finish (wd)"] == "+7.1"
    assert "every other draw held fixed" in p2["shared_drivers_sentence"]
