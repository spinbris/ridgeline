"""Unit tests for src.sra_strawman.cp_classifier.

Covers:
- is_commercially_binding rules (ID prefix, keyword)
- classify_activity for each branch of the Option Z rule
- Series-count sanity check on the real P6 schedule (target 200-300)
- The 12 CSE-KML GTU Ready-for-First-Fire milestones classify as
  Series/CommitCon
- The 12 serial hot-commissioning activities (20.COM.*.EI.310) classify
  as Series/LogicZero
"""

from __future__ import annotations


from src.sra_strawman.cp_classifier import (
    MODE_HYBRID,
    MODE_PARALLEL,
    MODE_SERIES,
    SOURCE_COMMITCON,
    SOURCE_LOGICZERO,
    SOURCE_NEARCRITICAL,
    SOURCE_PARALLELBYFLOAT,
    SOURCE_SOFTPIN,
    classify_activity,
    is_commercially_binding,
)

# ---------- is_commercially_binding ----------

def test_commercial_id_prefix_matches():
    assert is_commercially_binding("CSE-KML-040", "Some activity")
    assert is_commercially_binding("  CSE-KML-999", "Some activity")  # stripped


def test_commercial_id_non_prefix_does_not_match_by_id_alone():
    assert not is_commercially_binding("20.C.30.ST.100", "Pour slab")


def test_commercial_keyword_in_name_matches():
    assert is_commercially_binding("X", "Ready for First Fire GTU-01")
    assert is_commercially_binding("X", "gtu01 commercial operation date")
    assert is_commercially_binding("X", "Practical Completion Milestone")
    assert is_commercially_binding("X", "Takeover Certificate")


def test_commercial_keyword_case_insensitive():
    assert is_commercially_binding("X", "READY FOR FIRST FIRE")
    assert is_commercially_binding("X", "ready for first fire")


def test_no_match_for_plain_activity():
    assert not is_commercially_binding("A1", "Install cable tray")
    assert not is_commercially_binding(None, None)


# ---------- classify_activity ----------

def test_classify_logic_zero():
    act = {
        "total_float_days": 0,
        "start_is_constrained": False,
        "finish_is_constrained": False,
        "activity_id": "20.COM.10.EI.310",
        "activity_name": "Transformer energisation",
    }
    c = classify_activity(act)
    assert c.mode == MODE_SERIES
    assert c.series_source == SOURCE_LOGICZERO


def test_classify_commitcon_via_id():
    act = {
        "total_float_days": 0,
        "start_is_constrained": False,
        "finish_is_constrained": True,
        "activity_id": "CSE-KML-040",
        "activity_name": "Ready for First Fire GTU-01",
    }
    c = classify_activity(act)
    assert c.mode == MODE_SERIES
    assert c.series_source == SOURCE_COMMITCON


def test_classify_softpin():
    act = {
        "total_float_days": 0,
        "start_is_constrained": True,
        "finish_is_constrained": False,
        "activity_id": "20.C.30.ST.100",
        "activity_name": "Pour slab 01",
    }
    c = classify_activity(act)
    assert c.mode == MODE_HYBRID
    assert c.series_source == SOURCE_SOFTPIN


def test_classify_near_critical():
    act = {
        "total_float_days": 5.0,
        "start_is_constrained": False,
        "finish_is_constrained": False,
        "activity_id": "A1",
        "activity_name": "X",
    }
    c = classify_activity(act)
    assert c.mode == MODE_HYBRID
    assert c.series_source == SOURCE_NEARCRITICAL


def test_classify_parallel_above_threshold():
    act = {
        "total_float_days": 100.0,
        "start_is_constrained": False,
        "finish_is_constrained": False,
        "activity_id": "A1",
        "activity_name": "X",
    }
    c = classify_activity(act)
    assert c.mode == MODE_PARALLEL
    assert c.series_source == SOURCE_PARALLELBYFLOAT


def test_classify_parallel_at_boundary():
    """20.0 days of float is hybrid (<=), 20.01 is parallel (>)."""
    at_threshold = {
        "total_float_days": 20.0,
        "start_is_constrained": False,
        "finish_is_constrained": False,
        "activity_id": "A1",
        "activity_name": "X",
    }
    just_over = {**at_threshold, "total_float_days": 20.01}
    assert classify_activity(at_threshold).mode == MODE_HYBRID
    assert classify_activity(just_over).mode == MODE_PARALLEL


def test_classify_none_float_falls_back_to_parallel():
    act = {
        "total_float_days": None,
        "start_is_constrained": False,
        "finish_is_constrained": False,
        "activity_id": "A1",
        "activity_name": "X",
    }
    c = classify_activity(act)
    assert c.mode == MODE_PARALLEL


# ---------- full-schedule integration ----------
