"""SR18 Item 4 — activity-name whitespace normalisation.

Locks the post-SR18 behaviour: every activity_name value flowing into
the composer's CI table, the risk-to-activity bridge, and the §10.5
linkage prose has whitespace runs collapsed to a single space.

Pre-SR18 audit (HTML line 8855 in `outputs/sra_final_report_PROD_2026-05-18.html`):
`<td>Ready for Hot Commissioning  - GTU12</td>` rendered the source
.xer name verbatim, with a double space before the hyphen.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

from src.final.sections.criticality import (
    _normalise_activity_name,
    build_risk_to_activity_bridge,
    build_risk_to_cp_linkage_table,
    compute_criticality_table,
)


DOUBLE_SPACE_RE = re.compile(r" {2,}")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ready for Hot Commissioning  - GTU12", "Ready for Hot Commissioning - GTU12"),
        ("Cold Commission - GTU11", "Cold Commission - GTU11"),
        ("  leading and trailing  ", "leading and trailing"),
        ("multi\tspaces\nbetween", "multi spaces between"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalise_collapses_whitespace_runs(raw, expected):
    assert _normalise_activity_name(raw) == expected


def test_compute_criticality_table_emits_clean_names():
    """The single upstream source of activity_name values; SR18 normalises
    here so every downstream consumer inherits the clean string."""

    class _StubScheduleResult:
        activity_ids = ("a1", "a2", "a3")
        criticality_index = {"a1": 0.9, "a2": 0.1, "a3": 0.5}
        total_float_mean_hours = (0.0, 80.0, 40.0)
        total_float_std_hours = (0.0, 16.0, 8.0)
        deterministic_critical_path = ("a1",)

    titles = {
        "a1": "Ready for Hot Commissioning  - GTU12",   # double space defect
        "a2": "Cold Commission - GTU11",                 # already clean
        "a3": "Hot   Commissioning    GTU13",            # triple/quadruple
    }

    table = compute_criticality_table(_StubScheduleResult(), activity_titles=titles)
    names = dict(zip(table["activity_id"], table["activity_name"]))

    assert names["a1"] == "Ready for Hot Commissioning - GTU12"
    assert names["a2"] == "Cold Commission - GTU11"
    assert names["a3"] == "Hot Commissioning GTU13"

    # Strong assertion: no double-space anywhere in the rendered names.
    for n in names.values():
        assert not DOUBLE_SPACE_RE.search(n), (
            f"compute_criticality_table emitted whitespace defect: {n!r}"
        )


def test_risk_to_activity_bridge_emits_clean_names():
    """The §10.5 risk-to-activity bridge inherits clean names via the
    upstream compute_criticality_table fix, AND re-normalises defensively
    so a CI table from any other source is also safe."""

    class _StubDriver:
        affected_activity_ids = ("a1", "a2")

    risk_drivers = {"R090": _StubDriver()}
    # Construct a CI table directly (bypassing compute_criticality_table)
    # to verify the bridge's own defensive normalisation works.
    ci_table = pd.DataFrame([
        {
            "activity_id": "a1",
            "activity_name": "Ready for Hot Commissioning  - GTU12",
            "ci": 1.0, "ci_band": "very_high",
            "total_float_mean_hours": 0.0, "total_float_std_hours": 0.0,
            "on_deterministic_cp": True,
        },
        {
            "activity_id": "a2",
            "activity_name": "Spaces\t\tin\nname",
            "ci": 0.5, "ci_band": "med",
            "total_float_mean_hours": 40.0, "total_float_std_hours": 8.0,
            "on_deterministic_cp": False,
        },
    ])

    bridge = build_risk_to_activity_bridge(
        risk_drivers, ci_table, top_schedule_risk_ids=["R090"],
    )

    names = bridge["activity_name"].tolist()
    assert "Ready for Hot Commissioning - GTU12" in names
    assert "Spaces in name" in names
    for n in names:
        assert not DOUBLE_SPACE_RE.search(n), (
            f"bridge table emitted whitespace defect: {n!r}"
        )


def test_linkage_table_top_activities_string_carries_clean_names():
    """build_risk_to_cp_linkage_table's top_3_activities_by_MI_CI column
    composes a string from activity names; SR18 normalises that
    composition site too."""

    class _StubDriver:
        affected_activity_ids = ("a1",)
        mode = "Parallel"
        injection_method = "discrete_event_additive_days"
        gating_activity_id = "a1"

    risk_drivers = {"R090": _StubDriver()}

    extended_ci_table = pd.DataFrame([
        {
            "activity_id": "a1",
            "activity_name": "Ready for Hot Commissioning  - GTU12",
            "ci_mode_conditioned": 1.0,
            "ci_mode_independent": 1.0,
            "ci_band": "very_high",
            "total_float_mean_hours": 0.0,
            "total_float_std_hours": 0.0,
            "divergence": 0.0,
            "divergence_band": "consistent",
            "on_deterministic_cp": True,
            "is_amplified_by_mode": False,
            "is_suppressed_by_mode": False,
        },
    ]).set_index("activity_id", drop=False)

    out = build_risk_to_cp_linkage_table(
        risk_drivers=risk_drivers,
        extended_ci_table=extended_ci_table,
        risk_titles={"R090": "Threat of commissioning"},
        risk_impact_lookup={"R090": 1.5},
    )

    top_str = out.iloc[0]["top_3_activities_by_MI_CI"]
    assert "Ready for Hot Commissioning - GTU12" in top_str
    assert "Ready for Hot Commissioning  -" not in top_str, (
        f"linkage table top_3 string carries double-space defect: {top_str!r}"
    )
