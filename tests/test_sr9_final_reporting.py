"""SR9 Pass A tests for final_reporting accessors."""

from __future__ import annotations

import pandas as pd
import pytest

from src.final import final_reporting


def _composed_fixture():
    return {
        "cross_validation": {"all_pass": True},
        "executive_summary": {"headline_contingency_range_p80": {"p_level": 80}},
        "cost_section": {"cost_dollars_array": [1, 2, 3]},
        "schedule_section": {"finish_delay_days_array": [0.1, 0.2]},
        "integrated_section": {"scenarios": {"DP_Review": {}}},
        "appendix_counterfactual": pd.DataFrame({"scenario": [1, 2], "p80": [10, 20]}),
        "appendix_methodology": {"caveats": ["c1"]},
        "appendix_audit_trail": {"register_path": "/path"},
        "disclaimer_paragraphs": ["p1", "p2"],
    }


@pytest.mark.parametrize(
    "accessor_name, top_level_key, expected_subkey",
    [
        ("get_executive_summary_panel_data", "executive_summary", "headline_contingency_range_p80"),
        ("get_cost_section_panel_data", "cost_section", "cost_dollars_array"),
        ("get_schedule_section_panel_data", "schedule_section", "finish_delay_days_array"),
        ("get_integrated_section_panel_data", "integrated_section", "scenarios"),
        ("get_appendix_methodology_data", "appendix_methodology", "caveats"),
        ("get_appendix_audit_trail_data", "appendix_audit_trail", "register_path"),
    ],
)
def test_panel_accessors_return_expected_slices(accessor_name, top_level_key, expected_subkey):
    composed = _composed_fixture()
    accessor = getattr(final_reporting, accessor_name)
    out = accessor(composed)
    assert isinstance(out, dict)
    assert expected_subkey in out
    # Also confirm counterfactual accessor returns a DataFrame
    counterfactual = final_reporting.get_appendix_counterfactual_table(composed)
    assert isinstance(counterfactual, pd.DataFrame)
    assert len(counterfactual) == 2
