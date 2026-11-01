"""INTVIEW-01 stage 2b: contingency held against required, and the P80 bridge.

Properties 9 to 12 of ``docs/stage_briefs/PLAN_INTVIEW01_stage2_contract16.md``. The unit tests
pin the reader, the held arithmetic and the bridge's bookkeeping on hand-built inputs. The
integration class runs the four Tropic Ridge periods in order and checks the two things only a
real run can: the bridge closes on each period's own P80 (its positive control), and the held
figures follow the illustrative ledger.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from openpyxl import Workbook, load_workbook

from src.am.integrated_views import (
    BRIDGE_RESIDUAL_LABEL,
    contingency_block,
    jcl_against_held,
    period_bridge,
)
from src.am.workbook_reader import (
    AM_CONTINGENCY_SHEET,
    CONTINGENCY_COLUMNS,
    WorkbookReaderError,
    _read_contingency,
)
from tests.input_skips import skip_missing

REPO = Path(__file__).resolve().parents[1]
PERIODS = [REPO / "status_periods" / f"wind_period_0{n}.xlsx" for n in (1, 2, 3, 4)]
ITERATIONS = 2000
SEED = 42


# --- property 9: the contingency sheet ---------------------------------------------------------

def _sheet(*, commitment=_dt.date(2026, 3, 16), opening=7_500_000, header_row=6, rows=(),
           illustrative="Yes") -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = AM_CONTINGENCY_SHEET
    ws["A1"], ws["B1"] = "Commitment date", commitment
    ws["A2"], ws["B2"] = "Opening held (AUD)", opening
    ws["A3"], ws["B3"] = "Illustrative", illustrative
    for c, name in enumerate(CONTINGENCY_COLUMNS, start=1):
        ws.cell(row=header_row, column=c, value=name)
    for i, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            ws.cell(row=header_row + i, column=c, value=v)
    return wb


def test_no_contingency_sheet_reads_as_none():
    assert _read_contingency(Workbook()) is None


def test_the_sheet_is_read_by_its_labels_and_header_wherever_they_sit():
    """Invariant 10: the table found by its header row, not by a row number."""
    rows = [(_dt.date(2026, 3, 27), "Draw", 450000, "Approved", "WT-008", "standby")]
    for header_row in (6, 11):
        got = _read_contingency(_sheet(header_row=header_row, rows=rows))
        assert got["commitment_date"] == _dt.date(2026, 3, 16)
        assert got["opening_held"] == 7_500_000 and got["illustrative"] is True
        assert got["movements"] == [{
            "date": _dt.date(2026, 3, 27), "type": "Draw", "amount": 450000.0,
            "status": "Approved", "risk_id": "WT-008", "note": "standby"}]


def test_a_blank_commitment_date_is_not_committed():
    got = _read_contingency(_sheet(commitment=None, opening=None))
    assert got["commitment_date"] is None and got["opening_held"] is None


def test_a_commitment_date_without_an_opening_amount_is_refused():
    """It would read as committed and unfunded."""
    with pytest.raises(WorkbookReaderError, match="no opening held amount"):
        _read_contingency(_sheet(opening=None))


@pytest.mark.parametrize("row, match", [
    ((_dt.date(2026, 4, 1), "Transfer", 1, "Approved", None, None), "Type"),
    ((_dt.date(2026, 4, 1), "Draw", 1, "Maybe", None, None), "Status"),
    ((_dt.date(2026, 4, 1), "Draw", -5, "Approved", None, None), "negative"),
    ((None, "Draw", 5, "Approved", None, None), "no date"),
])
def test_a_malformed_movement_is_refused_by_row(row, match):
    with pytest.raises(WorkbookReaderError, match=match):
        _read_contingency(_sheet(rows=[row]))


# --- property 10: held against required --------------------------------------------------------

def _inputs(movements, commitment=_dt.date(2026, 3, 16), opening=7_500_000.0):
    return {"commitment_date": commitment, "opening_held": opening, "illustrative": True,
            "movements": [{"date": d, "type": t, "amount": float(a), "status": s,
                           "risk_id": r, "note": None} for d, t, a, s, r in movements]}


def test_before_commitment_the_block_is_recommended_and_unfunded():
    inputs = _inputs([], commitment=_dt.date(2026, 3, 16))
    c = contingency_block(7_366_574.6, inputs, period_end=_dt.date(2026, 2, 28))
    assert c["phase"] == "recommended" and c["label"] == "Recommended at P80"
    assert c["held_dollars"] is None and c["shortfall_dollars"] is None
    assert c["illustrative"] is True


def test_held_is_opening_less_approved_draws_plus_releases_in_the_window():
    inputs = _inputs([
        (_dt.date(2026, 3, 1), "Draw", 999, "Approved", "early"),        # before commitment
        (_dt.date(2026, 3, 27), "Draw", 450_000, "Approved", "WT-008"),
        (_dt.date(2026, 4, 28), "Draw", 600_000, "Pending", "WT-021"),    # pending: apart
        (_dt.date(2026, 4, 29), "Release", 100_000, "Approved", "WT-009"),
        (_dt.date(2026, 4, 30), "Release", 50_000, "Pending", "WT-009"),  # pending release
        (_dt.date(2026, 6, 2), "Draw", 777, "Approved", "later"),        # after period end
    ])
    c = contingency_block(8_000_000.0, inputs, period_end=_dt.date(2026, 4, 30))
    assert c["phase"] == "held" and c["commitment_date"] == "2026-03-16"
    assert c["approved_draws_dollars"] == 450_000 and c["releases_dollars"] == 100_000
    assert c["pending_draws_dollars"] == 600_000
    assert c["held_dollars"] == 7_500_000 - 450_000 + 100_000
    assert c["shortfall_dollars"] == round(8_000_000.0 - 7_150_000, 2)
    assert [m["date"] for m in c["movements"]] == [
        "2026-03-27", "2026-04-28", "2026-04-29", "2026-04-30"]


def test_shortfall_is_negative_when_held_exceeds_required():
    c = contingency_block(5_000_000.0, _inputs([]), period_end=_dt.date(2026, 4, 30))
    assert c["shortfall_dollars"] == -2_500_000.0


def test_the_jcl_against_held_equals_the_headline_jcl_when_held_is_the_recommendation():
    """Same axes as ``stage3_jcl``: only the budget line differs, so held = P80 must agree."""
    from src.final.sections.integrated_total import stage3_jcl
    from src.integrated.integrated_dollars import integrated_dollars_array

    rng = np.random.default_rng(3)
    n, rate = 4000, 35_000.0
    cost = rng.gamma(2.0, 1e6, n)
    days = rng.gamma(2.0, 15.0, n)
    finish = 500.0 + days
    base = {"base_dollars": rng.normal(50e6, 2e6, n), "base_total_dollars": 50e6}
    result = SimpleNamespace(cost_dollars_array=cost, project_finish_days=finish)
    headline = stage3_jcl({"cost_result": {"cost_dollars_array": cost},
                           "schedule_days_array": days,
                           "schedule_result": SimpleNamespace(project_finish_days=finish)},
                          base, rate)
    p80 = float(np.percentile(integrated_dollars_array(cost, days, rate), 80))
    held = jcl_against_held(result, base, p80)
    assert held["jcl"] == headline["jcl"]
    assert held["cost_confidence"] == headline["cost_confidence"]
    assert jcl_against_held(result, base, p80 - 1e6)["jcl"] < headline["jcl"]


# --- property 11: the bridge's bookkeeping ------------------------------------------------------

def _prior(probs: dict[str, float] | None, p80: float = 100.0) -> dict:
    return {"meta": {"period_end_date": "2026-02-28"},
            "integrated": {"p80_dollars": p80, "pinning": {"priced_probabilities": probs}}}


def _additive(weights: dict[str, float], offset: float = 0.0):
    """A stand-in for the replay whose P80 is a weighted sum, so each step is checkable."""
    calls: list[dict[str, float]] = []

    def p80_at(probs: dict[str, float]) -> float:
        calls.append(dict(probs))
        return offset + sum(weights[r] * p for r, p in probs.items())
    p80_at.calls = calls  # type: ignore[attr-defined]
    return p80_at


def test_period_0_has_no_bridge():
    assert period_bridge(current_p80_dollars=1.0, prior_doc=None, current_probabilities={},
                         closed_risk_ids=(), mitigated_risk_ids=(), p80_at=lambda p: 0.0) is None


def test_a_prior_without_priced_probabilities_says_why():
    b = period_bridge(current_p80_dollars=1.0, prior_doc=_prior(None),
                      current_probabilities={"A": 0.5}, closed_risk_ids=(),
                      mitigated_risk_ids=(), p80_at=lambda p: 0.0)
    assert b["available"] is False and "next period" in b["reason"]


def test_steps_follow_the_ruled_order_and_sum_to_the_movement():
    w = {"A": 100.0, "B": 200.0, "C": 300.0, "D": 400.0, "N": 50.0}
    prior = {"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5, "X": 0.2}  # X has left the run
    now = {"A": 0.0, "B": 0.8, "C": 0.3, "D": 0.5, "N": 0.6}
    p80_at = _additive(w, offset=10.0)
    current = p80_at(now)
    b = period_bridge(current_p80_dollars=current, prior_doc=_prior(prior, p80=700.0),
                      current_probabilities=now, closed_risk_ids=("A",),
                      mitigated_risk_ids=("C", "D"), p80_at=p80_at)
    steps = {s["key"]: s for s in b["steps"]}
    assert [s["key"] for s in b["steps"]] == ["closed", "new", "reassessed", "mitigations",
                                              "other"]
    assert steps["closed"]["risk_ids"] == ["A"] and steps["closed"]["dollars"] == -50.0
    assert steps["new"]["risk_ids"] == ["N"] and steps["new"]["dollars"] == 30.0
    assert steps["reassessed"]["risk_ids"] == ["B"] and steps["reassessed"]["dollars"] == 60.0
    # D has a mitigation but did not move, so it is in no step.
    assert steps["mitigations"]["risk_ids"] == ["C"] and steps["mitigations"]["dollars"] == -60.0
    start = 10.0 + 0.5 * (100 + 200 + 300 + 400)
    assert steps["other"]["dollars"] == start - 700.0 and steps["other"]["risk_ids"] == ["X"]
    assert steps["other"]["label"] == BRIDGE_RESIDUAL_LABEL
    assert sum(s["dollars"] for s in b["steps"]) == pytest.approx(current - 700.0)
    assert b["prior_p80_dollars"] == 700.0 and b["current_p80_dollars"] == current


def test_an_empty_step_is_zero_and_costs_no_replay():
    p80_at = _additive({"A": 1.0})
    period_bridge(current_p80_dollars=0.5, prior_doc=_prior({"A": 0.5}, p80=0.5),
                  current_probabilities={"A": 0.5}, closed_risk_ids=(),
                  mitigated_risk_ids=(), p80_at=p80_at)
    assert len(p80_at.calls) == 1  # the starting state only


def test_a_bridge_that_does_not_close_is_refused():
    with pytest.raises(ValueError, match="positive control"):
        period_bridge(current_p80_dollars=999.0, prior_doc=_prior({"A": 0.5}),
                      current_probabilities={"A": 0.7}, closed_risk_ids=(),
                      mitigated_risk_ids=(), p80_at=_additive({"A": 100.0}))


# --- property 12: the illustrative held table ----------------------------------------------------

def test_period_01_has_no_contingency_sheet_and_02_to_04_are_illustrative():
    for path in PERIODS:
        if not path.is_file():
            skip_missing(path, detail="run scripts/build_wind_am_periods.py")
    assert AM_CONTINGENCY_SHEET not in load_workbook(PERIODS[0]).sheetnames
    for path in PERIODS[1:]:
        ws = load_workbook(path)[AM_CONTINGENCY_SHEET]
        assert ws["B3"].value == "Yes" and "ILLUSTRATIVE" in ws["A4"].value


# --- integration: the four periods in order ------------------------------------------------------

@pytest.fixture(scope="module")
def four_periods(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    import src.sra.cpm.bindings.synthetic_wind  # noqa: F401  self-registers
    from src.am.run_period import run_period

    for path in PERIODS:
        if not path.is_file():
            skip_missing(path, detail="run scripts/build_wind_am_periods.py")
    saved = os.environ.get("QRA_PROJECT")
    os.environ["QRA_PROJECT"] = "synthetic_wind"
    out = tmp_path_factory.mktemp("intview01_2b")
    try:
        docs = []
        for path in PERIODS:
            written = run_period(
                workbook_path=path, project="synthetic_wind", output_dir=out,
                main_iterations=ITERATIONS, days_at_risk_iterations=500,
                counterfactual_iterations=500, seed=SEED, criticality_measurement_mode="both",
                project_start=_dt.date(2024, 1, 1), allow_dirty=True)
            docs.append(json.loads(written.read_bytes().decode("utf-8")))
        return docs
    finally:
        if saved is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = saved


@pytest.mark.integration
@pytest.mark.slow
class TestFourPeriods:
    def test_period_01_is_recommended_with_no_bridge(self, four_periods):
        c = four_periods[0]["contingency"]
        assert c["phase"] == "recommended" and c["bridge"] is None
        assert "contingency_illustrative" not in four_periods[0]["meta"]

    def test_each_bridge_closes_on_its_own_period(self, four_periods):
        for prior, doc in zip(four_periods, four_periods[1:]):
            b = doc["contingency"]["bridge"]
            assert b["available"] is True
            assert b["prior_p80_dollars"] == prior["integrated"]["p80_dollars"]
            assert b["current_p80_dollars"] == doc["integrated"]["p80_dollars"]
            assert sum(s["dollars"] for s in b["steps"]) == pytest.approx(
                doc["integrated"]["p80_dollars"] - prior["integrated"]["p80_dollars"], abs=0.06)

    def test_may_closes_wt009_and_lowers_the_p80(self, four_periods):
        steps = {s["key"]: s for s in four_periods[3]["contingency"]["bridge"]["steps"]}
        assert steps["closed"]["risk_ids"] == ["WT-009"] and steps["closed"]["dollars"] < 0

    def test_held_follows_the_illustrative_ledger(self, four_periods):
        held = [d["contingency"]["held_dollars"] for d in four_periods[1:]]
        assert held == [7_050_000.0, 6_770_000.0, 6_450_000.0]
        assert four_periods[2]["contingency"]["pending_draws_dollars"] == 600_000.0
        for d in four_periods[1:]:
            c = d["contingency"]
            assert c["phase"] == "held" and c["illustrative"] is True
            assert d["meta"]["contingency_illustrative"] is True
            assert c["shortfall_dollars"] == round(c["required_p80_dollars"] - c["held_dollars"],
                                                   2)
            assert 0.0 <= c["jcl_against_held"] <= 1.0

    def test_every_period_records_what_it_priced(self, four_periods):
        for d in four_periods:
            probs = d["integrated"]["pinning"]["priced_probabilities"]
            assert len(probs) == d["integrated"]["pinning"]["risks_priced"]
        assert four_periods[3]["integrated"]["pinning"]["priced_probabilities"]["WT-009"] == 0.0
