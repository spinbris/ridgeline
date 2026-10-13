"""SR2 - Critical-path classifier tests.

The integration tests that ran against the locked 22 April P6 export could only ever skip
here; SNAPSHOTCUT-01 retired them (Director, 11/10/2026).
"""

from __future__ import annotations


import pandas as pd

from src.sra.critical_path import (
    COMMERCIALLY_BINDING_KEYWORDS,
    classify_activities,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a synthetic SR1-shaped DataFrame from a list of overrides."""
    base = {
        "activity_id": "",
        "activity_name": "",
        "wbs": "",
        "duration_days": 1.0,
        "start_date": pd.Timestamp("2026-01-01"),
        "finish_date": pd.Timestamp("2026-02-01"),
        "total_float_days": pd.NA,
        "critical_flag": False,
        "primary_constraint": "",
        "row_type": "activity",
    }
    out = [{**base, **r} for r in rows]
    df = pd.DataFrame(out)
    df["total_float_days"] = (
        pd.to_numeric(df["total_float_days"], errors="coerce")
        .astype("Int64")
    )
    df["critical_flag"] = df["critical_flag"].astype(bool)
    return df


# ---- synthetic unit tests ----

def test_classifier_critical_flag_yes_classified_series_with_rule_s1():
    df = _make_df([{
        "activity_id": "ACT-001", "activity_name": "Some activity",
        "critical_flag": True, "total_float_days": 99,
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Series"
    assert res["rule"] == "S1"


def test_classifier_zero_float_no_constraint_classified_series_with_rule_s2():
    df = _make_df([{
        "activity_id": "ACT-002", "activity_name": "Some activity",
        "critical_flag": False, "total_float_days": 0,
        "primary_constraint": "",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Series"
    assert res["rule"] == "S2"


def test_classifier_zero_float_cse_kml_constraint_classified_series_with_rule_s3():
    df = _make_df([{
        "activity_id": "CSE-KML-001", "activity_name": "Some milestone",
        "critical_flag": False, "total_float_days": 0,
        "primary_constraint": "MS",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Series"
    assert res["rule"] == "S3"


def test_classifier_zero_float_cod_keyword_classified_series_with_rule_s3():
    df = _make_df([{
        "activity_id": "20.COM.95.OT.999",
        "activity_name": "Plant COD Achieved",
        "critical_flag": False, "total_float_days": 0,
        "primary_constraint": "MS",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Series"
    assert res["rule"] == "S3"


def test_classifier_near_critical_float_classified_hybrid_with_rule_h1():
    df = _make_df([{
        "activity_id": "ACT-003", "activity_name": "Some activity",
        "critical_flag": False, "total_float_days": 10,
        "primary_constraint": "",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Hybrid"
    assert res["rule"] == "H1"


def test_classifier_zero_float_soft_pin_classified_hybrid_with_rule_h2():
    df = _make_df([{
        "activity_id": "20.C.10.CI.100",
        "activity_name": "Internal milestone",
        "critical_flag": False, "total_float_days": 0,
        "primary_constraint": "MS",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Hybrid"
    assert res["rule"] == "H2"


def test_classifier_high_float_classified_parallel_with_rule_p():
    df = _make_df([{
        "activity_id": "ACT-004", "activity_name": "Some activity",
        "critical_flag": False, "total_float_days": 45,
        "primary_constraint": "",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Parallel"
    assert res["rule"] == "P"


def test_classifier_wbs_summary_rows_assigned_not_applicable():
    """WBS summary rows are excluded from classification regardless of other fields."""
    df = _make_df([
        {
            "activity_id": "WBS.A", "activity_name": "Top WBS",
            "row_type": "wbs_summary",
            "critical_flag": True, "total_float_days": 0,
        },
    ])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "NotApplicable"
    assert res["rule"] == "NA"


def test_classifier_rule_priority_s1_beats_s3():
    df = _make_df([{
        "activity_id": "CSE-KML-001", "activity_name": "COD milestone",
        "critical_flag": True, "total_float_days": 0,
        "primary_constraint": "MS",
    }])
    res = classify_activities(df).iloc[0]
    assert res["mode"] == "Series"
    assert res["rule"] == "S1"


def test_commercially_binding_keywords_constant_present():
    expected = {
        "cod", "commercial operation", "ready for first fire",
        "ready for hot commissioning", "practical completion", "takeover",
    }
    assert isinstance(COMMERCIALLY_BINDING_KEYWORDS, list)
    found = {k.lower() for k in COMMERCIALLY_BINDING_KEYWORDS}
    assert expected.issubset(found)


# ---- real-file integration tests ----
