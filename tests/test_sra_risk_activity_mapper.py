"""Unit tests for src.sra_strawman.risk_activity_mapper.

Covers:
- RBS L2 term match drives the rule selection (not Risk ID)
- Narrative keyword fallback when RBS L2 doesn't match any term
- Activity-ID prefix matching against the P6 activity set
- Mode derivation: most-conservative (any Series -> Series, etc.)
- Unknown risks -> [NEEDS_REVIEW]
- Cost-only rules return Parallel with zero linked activities
"""

from __future__ import annotations

from src.sra_strawman.cp_classifier import (
    MODE_HYBRID, MODE_PARALLEL, MODE_SERIES,
)
from src.sra_strawman.risk_activity_mapper import (
    NEEDS_REVIEW_CONFIDENCE,
    _find_linked_activities,
    _match_rule,
    map_risk,
)


def _synthetic_activities() -> list[dict]:
    """Small P6-like activity list covering a few prefixes."""
    return [
        {"activity_id": "20.C.10.ST.100", "activity_name": "Civil pour",
         "is_wbs_summary": False, "total_float_days": 0.0,
         "start_is_constrained": False, "finish_is_constrained": False,
         "wbs_code": "BGP.BoP."},
        {"activity_id": "40.C.20.EW.010", "activity_name": "BOP earthwork",
         "is_wbs_summary": False, "total_float_days": 15.0,
         "start_is_constrained": False, "finish_is_constrained": False,
         "wbs_code": "BGP.BoP."},
        {"activity_id": "20.COM.10.EI.310", "activity_name": "Ready for Hot Commissioning",
         "is_wbs_summary": False, "total_float_days": 0.0,
         "start_is_constrained": False, "finish_is_constrained": False,
         "wbs_code": "BGP.BoP."},
        {"activity_id": "96.V.30.QA.010", "activity_name": "QA walkdown",
         "is_wbs_summary": False, "total_float_days": 50.0,
         "start_is_constrained": False, "finish_is_constrained": False,
         "wbs_code": "BGP.BoP."},
        {"activity_id": "SUMMARY.X", "activity_name": "Summary",
         "is_wbs_summary": True, "total_float_days": 0.0,
         "start_is_constrained": False, "finish_is_constrained": False,
         "wbs_code": "BGP.BoP."},
    ]


# ---------- rule matching ----------

def test_rbs_l2_match_weather():
    risk = {"rbs_l2": "Weather impacts", "description": "", "consequences": ""}
    rule = _match_rule(risk)
    assert rule is not None
    assert "20.C." in rule.activity_id_prefixes


def test_rbs_l2_match_force_majeure():
    risk = {"rbs_l2": "Force Majeure ", "description": "", "consequences": ""}
    rule = _match_rule(risk)
    assert rule is not None
    assert "20.C." in rule.activity_id_prefixes


def test_narrative_keyword_fallback():
    """An RBS L2 that doesn't match any rule term but narrative has 'subcontract'
    should fall back to the subcontractor rule."""
    risk = {
        "rbs_l2": "Schedule & Planning",  # not in any rule's rbs_l2_terms
        "description": "Threat of subcontract inefficiencies",
        "consequences": "",
    }
    rule = _match_rule(risk)
    assert rule is not None
    assert "40.C." in rule.activity_id_prefixes


def test_no_match_returns_none():
    risk = {
        "rbs_l2": "Completely unrelated",
        "description": "Nothing relevant here",
        "consequences": "Nothing relevant here either",
    }
    rule = _match_rule(risk)
    assert rule is None


# ---------- activity linkage ----------

def test_find_linked_by_prefix():
    acts = _synthetic_activities()
    linked = _find_linked_activities(acts, ("20.C.",), ())
    assert len(linked) == 1
    assert linked[0]["activity_id"] == "20.C.10.ST.100"


def test_find_linked_by_pattern_conjunction():
    acts = _synthetic_activities()
    # Pattern: contains BOTH '20.COM.' and '.EI.310' - one activity.
    linked = _find_linked_activities(acts, (), ("20.COM.", ".EI.310"))
    assert len(linked) == 1
    assert linked[0]["activity_id"] == "20.COM.10.EI.310"


def test_find_linked_skips_summary():
    acts = _synthetic_activities()
    linked = _find_linked_activities(acts, ("SUMMARY.",), ())
    assert linked == []


def test_find_linked_multiple_prefixes():
    acts = _synthetic_activities()
    linked = _find_linked_activities(acts, ("20.C.", "40.C."), ())
    assert len(linked) == 2


# ---------- map_risk integration ----------

def test_map_risk_weather_hits_construction_prefixes():
    risk = {
        "risk_id": "X1",
        "rbs_l1": "Site & External Risks",
        "rbs_l2": "Weather impacts",
        "description": "Threat that inclement weather exceeds the allowance",
        "consequences": "",
    }
    acts = _synthetic_activities()
    m = map_risk(risk, acts)
    assert m.risk_id == "X1"
    assert m.mapping_confidence == "Medium"
    assert m.linked_activity_count >= 1
    # The 20.C. activity has total_float=0 and is logic-zero -> Series.
    assert m.mode == MODE_SERIES


def test_map_risk_cost_only_has_no_schedule_linkage():
    risk = {
        "risk_id": "X2",
        "rbs_l1": "Financial & Economic Risks",
        "rbs_l2": "Cost escalation (labour/materials)",
        "description": "Threat that market rates exceed estimates",
        "consequences": "",
    }
    acts = _synthetic_activities()
    m = map_risk(risk, acts)
    assert m.linked_activity_count == 0
    assert m.mode == MODE_PARALLEL
    # Even when confidence is non-[NEEDS_REVIEW], linkage is cost-only.
    assert "cost-only" in m.linkage_label.lower()


def test_map_risk_unmapped_returns_needs_review():
    risk = {
        "risk_id": "X3",
        "rbs_l1": "Unknown category",
        "rbs_l2": "Completely unrelated",
        "description": "Nothing relevant",
        "consequences": "",
    }
    acts = _synthetic_activities()
    m = map_risk(risk, acts)
    assert m.mapping_confidence == NEEDS_REVIEW_CONFIDENCE
    assert m.mode == NEEDS_REVIEW_CONFIDENCE
    assert m.linked_activity_count == 0


def test_map_risk_qa_rule_picks_verification_prefix():
    risk = {
        "risk_id": "X4",
        "rbs_l1": "Construction & Execution Risks",
        "rbs_l2": "Quality Issues",
        "description": "Threat that QA fails timely identification of defects",
        "consequences": "",
    }
    acts = _synthetic_activities()
    m = map_risk(risk, acts)
    assert m.linked_activity_count == 1
    # 96.V.30.QA.010 has float=50 -> Parallel.
    assert m.mode == MODE_PARALLEL


def test_broad_linkage_downgrades_confidence_to_low():
    """Risks whose linkage resolves to more than the configured threshold
    must have their Mapping confidence auto-downgraded to 'Low'.
    Assumption recorded in defaults.BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD."""
    from src.sra_strawman.defaults import (
        BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD as THRESHOLD,
    )
    # Build a synthetic activity set with (THRESHOLD + 10) 20.C. activities.
    activities = [
        {
            "activity_id": f"20.C.10.ST.{i:04d}",
            "activity_name": f"Civil work {i}",
            "is_wbs_summary": False,
            "total_float_days": 50.0,  # all Parallel so rule-base confidence
            "start_is_constrained": False,
            "finish_is_constrained": False,
            "wbs_code": "BGP.BoP.",
        }
        for i in range(THRESHOLD + 10)
    ]
    risk = {
        "risk_id": "X5",
        "rbs_l1": "Site & External Risks",
        "rbs_l2": "Weather impacts",  # rule base confidence = Medium
        "description": "",
        "consequences": "",
    }
    m = map_risk(risk, activities)
    assert m.linked_activity_count > THRESHOLD
    assert m.mapping_confidence == "Low"


def test_narrow_linkage_preserves_rule_confidence():
    """Below-threshold linkage must keep the rule's base confidence."""
    risk = {
        "risk_id": "X6",
        "rbs_l1": "Site & External Risks",
        "rbs_l2": "Weather impacts",  # rule base confidence = Medium
        "description": "",
        "consequences": "",
    }
    m = map_risk(risk, _synthetic_activities())
    assert m.linked_activity_count < 500
    assert m.mapping_confidence == "Medium"


def test_no_hardcoded_risk_id_in_rubric():
    """Regression guard: the mapping rubric must not branch on Risk ID literals.
    Scan the source of risk_activity_mapper for any R00X pattern."""
    import re
    from pathlib import Path
    src_path = (
        Path(__file__).resolve().parents[1]
        / "src" / "sra_strawman" / "risk_activity_mapper.py"
    )
    source = src_path.read_text(encoding="utf-8")
    # Strip docstrings / comments is overkill here; just search for
    # R<digits> or R<digits>.<digits> patterns inside the body.
    matches = re.findall(r"\bR\d{3,}(?:\.\d+)?\b", source)
    assert not matches, (
        f"Risk ID literals found in source: {matches} - "
        "runtime code must derive everything from register content"
    )
