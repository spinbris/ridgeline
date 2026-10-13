"""SR18 Item 1 — shared RBS mapping + Chart 2 Y-axis discipline names.

Locks the post-SR18 behaviour of:

1. `src/final/rbs_mapping.py` exports `RBS_L1_PREFIX_MAP` and
   `resolve_rbs_l1_label`.
2. `_build_phase_map_from_xer` no longer carries its own hardcoded dict;
   it imports `resolve_rbs_l1_label` from the shared module.
3. `make_criticality_density_gantt` Y-axis labels render through the
   shared map so numeric PROJWBS short-names appear as discipline names
   on the rendered chart.

The pre-SR18 defect (audit 2026-05-20): Chart 2 Y-axis rendered raw
codes `01 / 02 / 03 / 05 / 06 / 07 / 08 / 10 / 20 / 30 / 40 / 50 / 96 /
98 / 99`. Post-SR18 the same axis renders discipline names for each
code via `RBS_L1_PREFIX_MAP`.
"""
from __future__ import annotations

import inspect

import pytest

# RS-B step 2: this module reads the reference project's register shape, RBS map
# or chain identifiers, so it selects that binding explicitly rather than
# inheriting the suite default. Visible here, greppable, and departing from a
# default that tests/test_project_selection.py pins.
pytestmark = pytest.mark.project("synthetic_wind")


def test_rbs_mapping_module_exports():
    from src.final import rbs_mapping

    assert hasattr(rbs_mapping, "RBS_L1_PREFIX_MAP")
    assert hasattr(rbs_mapping, "resolve_rbs_l1_label")
    assert isinstance(rbs_mapping.RBS_L1_PREFIX_MAP, dict)


def test_rbs_mapping_covers_all_15_observed_refproject_codes():
    """The 15 codes that surface on Chart 2 from the live V8 .xer plus
    code 04 (Approvals / Permits, present in the .xer but not currently
    bound to any auto-mapped activity) and 97 (Pre-Commissioning)."""
    from src.final.rbs_mapping import RBS_L1_PREFIX_MAP

    observed_on_chart = {
        "01", "02", "03", "05", "06", "07", "08",
        "10", "20", "30", "40", "50",
        "96", "98", "99",
    }
    missing = observed_on_chart - set(RBS_L1_PREFIX_MAP.keys())
    assert not missing, (
        f"RBS_L1_PREFIX_MAP missing keys for codes that surface on "
        f"Chart 2: {sorted(missing)}"
    )


def test_resolve_passes_unknown_codes_through_unchanged():
    from src.final.rbs_mapping import resolve_rbs_l1_label

    assert resolve_rbs_l1_label("Unmapped") == "Unmapped"
    assert resolve_rbs_l1_label("XX_not_a_known_code") == "XX_not_a_known_code"


def test_resolve_handles_none_and_blank():
    from src.final.rbs_mapping import resolve_rbs_l1_label

    assert resolve_rbs_l1_label(None) == ""
    assert resolve_rbs_l1_label("") == ""
    assert resolve_rbs_l1_label("   ") == ""


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("01", "Key Milestones"),
        ("02", "Project Milestones"),
        ("96", "Construction Verification"),
        ("98", "Staged Commissioning"),
        ("99", "Operation & Handover"),
    ],
)
def test_resolve_known_base_map_codes(code, expected):
    """Codes the base map answers for. REFRETIRE-01: the codes 10-50 moved out of this
    parametrisation because every shipped binding overrides them with its own discipline
    names, which is the next test."""
    from src.final.rbs_mapping import resolve_rbs_l1_label

    assert resolve_rbs_l1_label(code) == expected


def test_the_active_bindings_label_wins_over_the_base_map():
    """The override path: a project's own WBS label is what the axis reads. The suite selects
    a project, so this reads that project's declaration rather than a literal."""
    from src.final.rbs_mapping import RBS_L1_PREFIX_MAP, resolve_rbs_l1_label
    from src.sra.cpm.bindings import get_active_binding

    labels = get_active_binding().wbs_labels
    overridden = [c for c in labels if c in RBS_L1_PREFIX_MAP]
    assert overridden, "the selected project overrides no base-map code; pick one that does"
    for code in overridden:
        assert resolve_rbs_l1_label(code) == labels[code]


def test_build_phase_map_imports_shared_resolver_not_local_dict():
    """The pre-SR18 inline `_RBS_L1_PREFIX_MAP` dict inside
    `_build_phase_map_from_xer` is gone; the function calls into the
    shared `resolve_rbs_l1_label` instead. Source-inspection guard
    against accidental re-introduction of the local dict."""
    from src.final.sections import criticality

    source = inspect.getsource(criticality._build_phase_map_from_xer)
    assert "_RBS_L1_PREFIX_MAP" not in source, (
        "Local _RBS_L1_PREFIX_MAP dict should have been lifted to "
        "src/final/rbs_mapping.py under SR18 Item 1"
    )
    assert "resolve_rbs_l1_label" in source, (
        "_build_phase_map_from_xer should call resolve_rbs_l1_label "
        "from the shared rbs_mapping module"
    )


def test_chart2_y_axis_renders_discipline_names(monkeypatch):
    """make_criticality_density_gantt applies resolve_rbs_l1_label to
    Y-axis tick labels so PROJWBS short-names display as discipline
    names. Capture the set_yticklabels calls via a monkeypatch on
    matplotlib's Axes class so we observe the labels the chart helper
    passes in (regardless of figure cleanup after render)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.axes
    import pandas as pd
    import tempfile
    from pathlib import Path

    from src.final.charts import make_criticality_density_gantt

    captured: list[list[str]] = []
    original = matplotlib.axes.Axes.set_yticklabels

    def _capture(self, labels, *args, **kwargs):
        captured.append([str(getattr(l, "get_text", lambda: l)()) for l in labels])
        return original(self, labels, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_yticklabels", _capture)

    activity_dates = pd.DataFrame({
        "activity_id": ["a1", "a2", "a3"],
        "start_date": pd.to_datetime(["2026-10-01", "2026-12-01", "2027-02-01"]),
        "finish_date": pd.to_datetime(["2026-11-30", "2027-01-31", "2027-03-31"]),
    })
    ci_table = pd.DataFrame({
        "activity_id": ["a1", "a2", "a3"],
        "mc_ci": [0.5, 0.6, 0.7],
        "mi_ci": [0.4, 0.5, 0.6],
    })
    phase_map = {"a1": "10", "a2": "40", "a3": "99"}

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "chart2.png"
        make_criticality_density_gantt(
            ci_table=ci_table,
            activity_dates=activity_dates,
            phase_map=phase_map,
            schedule_start=pd.Timestamp("2026-08-01"),
            schedule_finish=pd.Timestamp("2027-06-30"),
            output_path=out,
            mi_column="mi_ci",
            mc_column="mc_ci",
        )

    # set_yticklabels was called at least twice (MI panel + MC panel).
    # Flatten all captured label lists into a single set.
    tick_text_seen: set[str] = set()
    for call_labels in captured:
        tick_text_seen.update(call_labels)

    # REFRETIRE-01: the two project-specific names this pinned came from a binding that has
    # retired; codes 10 and 40 now read the selected project's own labels, resolved here rather
    # than spelt out, and 99 still comes from the base map.
    from src.sra.cpm.bindings import get_active_binding

    labels = get_active_binding().wbs_labels
    expected_any = {labels["10"], labels["40"], "Operation & Handover"}
    found = expected_any & tick_text_seen
    assert found == expected_any, (
        f"Chart 2 Y-axis missing expected discipline names. "
        f"Expected all of {expected_any}; labels passed to "
        f"set_yticklabels: {sorted(tick_text_seen)}"
    )

    # The pre-SR18 defect was numeric codes on the axis. Lock that they
    # are gone.
    for raw_code in ("10", "40", "99"):
        assert raw_code not in tick_text_seen, (
            f"Raw numeric code {raw_code!r} still passed to set_yticklabels; "
            f"SR18 transform missing. Labels seen: {sorted(tick_text_seen)}"
        )
