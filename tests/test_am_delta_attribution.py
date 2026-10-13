"""Unit tests for AM08 / AIA-01 period-over-period delta attribution.

Exercises ``_build_delta`` directly with a hand-written previous-period JSON
and in-memory current risks, so the classification logic is tested without
invoking the Stage 3 engine. See the AM08 delta-attribution brief.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


from src.am.json_writer import (
    DELTA_ATTRIBUTION_THRESHOLD_DAYS as T,
    _build_delta,
    _delta_change_meta,
    _delta_net_summary,
)

pytestmark = pytest.mark.unit


def _risk(rid: str, dar: float, *, status: str = "open",
          prob: float = 0.40, title: str | None = None) -> dict:
    return {
        "risk_id": rid,
        "title": title or f"Risk {rid}",
        "status": status,
        "days_at_risk_p80": dar,
        "probability": prob,
    }


def _write_prev(tmp_path: Path, p80_finish: str, risks: list[dict]) -> Path:
    doc = {"headline": {"p80_finish": p80_finish}, "risks": risks}
    p = tmp_path / "period_20260101.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _delta(tmp_path: Path, *, curr_p80: str, prev_p80: str,
           current: list[dict], previous: list[dict]) -> dict:
    prev_path = _write_prev(tmp_path, prev_p80, previous)
    return _build_delta(
        headline={"p80_finish": curr_p80},
        current_risks=current,
        previous_period_path=prev_path,
    )


# ---------------------------------------------------------------------------
# Period 0 / degenerate
# ---------------------------------------------------------------------------

def test_period_0_when_no_prior() -> None:
    d = _build_delta(
        headline={"p80_finish": "2026-06-19"},
        current_risks=[_risk("WT-001", 5.0)],
        previous_period_path=None,
    )
    assert d["period_0"] is True


def test_missing_prev_p80_degrades_gracefully(tmp_path: Path) -> None:
    prev_path = tmp_path / "period_20260101.json"
    prev_path.write_text(json.dumps({"headline": {}, "risks": []}), encoding="utf-8")
    d = _build_delta(
        headline={"p80_finish": "2026-06-19"},
        current_risks=[_risk("WT-001", 5.0)],
        previous_period_path=prev_path,
    )
    assert d["period_0"] is False and "worse" not in d


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_worsening_above_threshold_is_worse(tmp_path: Path) -> None:
    d = _delta(
        tmp_path, curr_p80="2026-06-25", prev_p80="2026-06-10",
        current=[_risk("WT-008", 22.3)],
        previous=[_risk("WT-008", 13.0)],
    )
    assert [e["risk_id"] for e in d["worse"]] == ["WT-008"]
    assert d["worse"][0]["delta_days"] == pytest.approx(9.3, abs=0.05)
    assert d["better"] == [] and d["new"] == []


def test_improving_below_negative_threshold_is_better(tmp_path: Path) -> None:
    d = _delta(
        tmp_path, curr_p80="2026-06-19", prev_p80="2026-07-04",
        current=[_risk("WT-021", 7.9)],
        previous=[_risk("WT-021", 14.1)],
    )
    assert [e["risk_id"] for e in d["better"]] == ["WT-021"]
    assert d["better"][0]["delta_days"] == pytest.approx(-6.2, abs=0.05)


def test_subthreshold_move_suppressed(tmp_path: Path) -> None:
    # 0.6 d move sits below T (=1.5) and is pure precision-floor noise.
    d = _delta(
        tmp_path, curr_p80="2026-06-19", prev_p80="2026-06-19",
        current=[_risk("WT-008", 22.3)],
        previous=[_risk("WT-008", 21.7)],
    )
    assert d["worse"] == [] and d["better"] == []


def test_new_risk_appears_in_new(tmp_path: Path) -> None:
    d = _delta(
        tmp_path, curr_p80="2026-06-19", prev_p80="2026-06-10",
        current=[_risk("WT-008", 13.0), _risk("WT-099", 5.0)],
        previous=[_risk("WT-008", 13.0)],
    )
    assert [e["risk_id"] for e in d["new"]] == ["WT-099"]
    assert d["new"][0]["delta_days"] == pytest.approx(5.0)


def test_closed_risk_is_better_attributed_to_full_prior(tmp_path: Path) -> None:
    d = _delta(
        tmp_path, curr_p80="2026-06-19", prev_p80="2026-07-04",
        current=[_risk("WT-009", -0.4, status="closed")],
        previous=[_risk("WT-009", 4.0, status="actioned")],
    )
    assert [e["risk_id"] for e in d["better"]] == ["WT-009"]
    assert d["better"][0]["delta_days"] == pytest.approx(-4.0)
    assert "Closed this period" in d["better"][0]["change_meta"]


def test_removed_risk_is_better(tmp_path: Path) -> None:
    d = _delta(
        tmp_path, curr_p80="2026-06-19", prev_p80="2026-07-04",
        current=[_risk("WT-008", 13.0)],
        previous=[_risk("WT-008", 13.0), _risk("WT-050", 6.0)],
    )
    assert "WT-050" in [e["risk_id"] for e in d["better"]]


def test_negative_days_floored_before_attribution(tmp_path: Path) -> None:
    # Non-closed risk reading -0.3 (noise) vs prior 4.0 -> floored to 0 -> -4.0.
    d = _delta(
        tmp_path, curr_p80="2026-06-19", prev_p80="2026-07-04",
        current=[_risk("WT-020", -0.3, status="monitor")],
        previous=[_risk("WT-020", 4.0, status="monitor")],
    )
    assert d["better"][0]["delta_days"] == pytest.approx(-4.0)


# ---------------------------------------------------------------------------
# Ordering + cap (D3)
# ---------------------------------------------------------------------------

def test_worse_capped_at_three_largest_first(tmp_path: Path) -> None:
    current = [_risk(f"WT-{i:03d}", 20.0) for i in range(5)]
    previous = [_risk(f"WT-{i:03d}", float(i)) for i in range(5)]  # moves 20,19,18,17,16
    d = _delta(tmp_path, curr_p80="2026-07-04", prev_p80="2026-06-10",
               current=current, previous=previous)
    assert len(d["worse"]) == 3
    moves = [e["delta_days"] for e in d["worse"]]
    assert moves == sorted(moves, reverse=True)  # largest first
    assert moves[0] == pytest.approx(20.0)


def test_better_sorted_most_negative_first(tmp_path: Path) -> None:
    current = [_risk("A", 2.0), _risk("B", 1.0)]
    previous = [_risk("A", 8.0), _risk("B", 12.0)]  # A -6, B -11
    d = _delta(tmp_path, curr_p80="2026-06-10", prev_p80="2026-07-04",
               current=current, previous=previous)
    assert [e["risk_id"] for e in d["better"]] == ["B", "A"]


# ---------------------------------------------------------------------------
# change_meta + net summary
# ---------------------------------------------------------------------------

def test_change_meta_reports_probability_move() -> None:
    meta = _delta_change_meta(
        {"status": "open", "probability": 0.40, "days_at_risk_p80": 13.0},
        {"status": "actioned", "probability": 0.90, "days_at_risk_p80": 22.3},
    )
    assert "Status open -> actioned" in meta
    assert "probability 0.40 -> 0.90" in meta
    assert "13.0 -> 22.3 days at risk" in meta


def test_change_meta_omits_static_probability() -> None:
    meta = _delta_change_meta(
        {"status": "open", "probability": 0.40, "days_at_risk_p80": 6.0},
        {"status": "open", "probability": 0.40, "days_at_risk_p80": 14.0},
    )
    assert "probability" not in meta


def test_net_summary_names_lead_drivers() -> None:
    better = [{"risk_id": "WT-021", "delta_days": -6.2},
              {"risk_id": "WT-009", "delta_days": -4.0}]
    s = _delta_net_summary(-15, worse=[], better=better)
    assert "earlier" in s
    assert "Improvement led by" in s
    assert "WT-021" in s and "WT-009" in s


def test_net_summary_direction_words() -> None:
    assert "later" in _delta_net_summary(15, [], [])
    assert "earlier" in _delta_net_summary(-15, [], [])
    assert "unchanged" in _delta_net_summary(0, [], [])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_repeat(tmp_path: Path) -> None:
    args = dict(
        curr_p80="2026-06-19", prev_p80="2026-07-04",
        current=[_risk("WT-021", 7.9), _risk("WT-009", -0.4, status="closed")],
        previous=[_risk("WT-021", 14.1), _risk("WT-009", 4.0, status="actioned")],
    )
    a = _delta(tmp_path, **args)
    b = _delta(tmp_path, **args)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
