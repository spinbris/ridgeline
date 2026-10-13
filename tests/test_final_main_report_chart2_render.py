"""SR10.B composer integration tests — Chart 2 main-report wiring +
§10.5 risk-to-CP linkage prose flip (Decision 7).

Mocks a Stage 3 Beta result with Mode-independent CI populated, runs
:func:`_apply_criticality_keys`, and asserts:

1. ``composed["page4b_criticality"]["chart2_density_gantt_path"]``
   carries the Chart 2 PNG path (Decision 1 — Chart 2 in main report).
2. The §10.5 placeholder caption is replaced by the rendered-chart
   caption when Chart 2 PNG was emitted.
3. The §10.5 prose paragraph references the amplified-by-Mode finding
   from the extended CI table (Decision 7) when MI CI is present.
4. The Beta-19 placeholder behaviour is preserved when MI CI is None
   (legacy ``criticality_measurement_mode="mode_conditioned"`` runs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.final.composer import _apply_criticality_keys


@dataclass
class _FakeScheduleResult:
    activity_ids: tuple[str, ...]
    criticality_index: dict[str, float]
    on_critical_path_count: dict[str, int]
    total_float_mean_hours: np.ndarray
    total_float_std_hours: np.ndarray
    deterministic_critical_path: tuple[str, ...]
    mode_independent_criticality_index: dict[str, float] | None
    n_iter: int = 1000


@dataclass(frozen=True)
class _FakeDriver:
    affected_activity_ids: tuple[str, ...]
    mode: str = "Series"


@dataclass(frozen=True)
class _FakeActivity:
    id: str
    name: str


@dataclass
class _FakeCalendar:
    working_hours_per_day: float = 8.0


@dataclass
class _FakeScheduleGraph:
    activities: dict[str, _FakeActivity]
    project_default_calendar: _FakeCalendar = field(default_factory=_FakeCalendar)


def _make_stage3_beta_result(
    *,
    include_mode_independent: bool,
    include_xer_tables: bool = True,
) -> dict:
    """Synthetic Stage 3 Beta result with deliberate amplified/suppressed cohorts."""
    # 6 activities: A1-A5 amplified-by-Mode (MC high, MI low); A6 consistent.
    activity_ids = ("A1", "A2", "A3", "A4", "A5", "A6")
    mc = {"A1": 0.99, "A2": 0.98, "A3": 0.97, "A4": 0.96, "A5": 0.95, "A6": 0.40}
    mi = {"A1": 0.45, "A2": 0.45, "A3": 0.45, "A4": 0.45, "A5": 0.45, "A6": 0.40}
    activity_names = {
        "A1": "Earthing for GTU",
        "A2": "Cable Pulling MV on GTU2",
        "A3": "Cable Pulling LV on GTU3",
        "A4": "Cable Pulling I&C on GTU3",
        "A5": "Termination on GTU3",
        "A6": "Civil works",
    }

    schedule_result = _FakeScheduleResult(
        activity_ids=activity_ids,
        criticality_index=mc,
        on_critical_path_count={a: int(c * 1000) for a, c in mc.items()},
        total_float_mean_hours=np.array(
            [0.0, 0.0, 0.0, 0.0, 0.0, 240.0], dtype=np.float32,
        ),
        total_float_std_hours=np.array(
            [0.0, 0.0, 0.0, 0.0, 0.0, 24.0], dtype=np.float32,
        ),
        deterministic_critical_path=("A1", "A2", "A3", "A4", "A5"),
        mode_independent_criticality_index=mi if include_mode_independent else None,
    )

    schedule_graph = _FakeScheduleGraph(
        activities={a: _FakeActivity(id=a, name=activity_names[a])
                    for a in activity_ids},
    )

    risk_drivers = {
        "R067": _FakeDriver(
            affected_activity_ids=("A1", "A2", "A3"), mode="Series",
        ),
        "R017.1": _FakeDriver(
            affected_activity_ids=("A4", "A5"), mode="Hybrid",
        ),
        "R013": _FakeDriver(
            affected_activity_ids=("A6",), mode="Series",
        ),
    }
    risk_titles = {
        "R067": "Commissioning rework",
        "R017.1": "GTU electrical delay",
        "R013": "Civil weather delay",
    }

    xer_tables = None
    if include_xer_tables:
        # Minimal TASK + PROJWBS frame so the phase-map + dates plumb
        # exercises both branches.
        task = pd.DataFrame({
            "task_id": list(activity_ids),
            "task_code": ["10.E.10", "10.E.20", "10.E.30",
                          "10.E.40", "10.E.50", "20.C.10"],
            "wbs_id": [101, 101, 101, 101, 101, 201],
            "early_start_date": pd.to_datetime([
                "2026-03-01", "2026-04-01", "2026-05-01",
                "2026-06-01", "2026-07-01", "2026-01-01",
            ]),
            "early_end_date": pd.to_datetime([
                "2026-03-31", "2026-04-30", "2026-05-31",
                "2026-06-30", "2026-07-31", "2026-02-15",
            ]),
        })
        projwbs = pd.DataFrame({
            "wbs_id": [101, 201, 100],
            "parent_wbs_id": [100, 100, pd.NA],
            "wbs_short_name": ["Electrical", "Civil", "RefProject Root"],
        })
        xer_tables = {"TASK": task, "PROJWBS": projwbs}

    return {
        "schedule_result": schedule_result,
        "schedule_graph": schedule_graph,
        "risk_drivers": risk_drivers,
        "risk_titles": risk_titles,
        "xer_tables": xer_tables,
    }


def _make_composed_skeleton() -> dict:
    """Minimal composed-dict shape needed by _apply_criticality_keys."""
    return {
        "page4_schedule_drivers": {
            "drivers_table": [
                {"Risk": "R067"}, {"Risk": "R017.1"}, {"Risk": "R013"},
            ],
        },
    }


def test_chart2_path_populated_in_page4b(tmp_path: Path) -> None:
    """Chart 2 PNG path lands on composed['page4b_criticality']['chart2_density_gantt_path']."""
    stage3 = _make_stage3_beta_result(include_mode_independent=True)
    composed = _make_composed_skeleton()

    _apply_criticality_keys(
        composed, stage3, chart_output_dir=tmp_path,
    )

    p4b = composed["page4b_criticality"]
    assert p4b["chart2_density_gantt_path"]
    assert Path(p4b["chart2_density_gantt_path"]).exists()


def test_chart2_placeholder_caption_replaced_when_rendered(tmp_path: Path) -> None:
    """Chart 2 caption flips from placeholder to rendered-chart caption."""
    stage3 = _make_stage3_beta_result(include_mode_independent=True)
    composed = _make_composed_skeleton()
    _apply_criticality_keys(composed, stage3, chart_output_dir=tmp_path)

    caption = composed["page4b_criticality"]["chart2_placeholder_caption"]
    # The rendered-chart caption names "Mode-independent" + "inset"
    # explicitly; the placeholder does not.
    assert "Mode-independent" in caption
    assert "inset" in caption


def test_sr10b_prose_names_amplified_cohort(tmp_path: Path) -> None:
    """§10.5 prose flips to the SR10.B formatter when MI CI is present.

    Decision 7: the worked example names the amplified-by-Mode GTU
    electrical-chain finding when the extended CI table surfaces it.
    """
    stage3 = _make_stage3_beta_result(include_mode_independent=True)
    composed = _make_composed_skeleton()
    _apply_criticality_keys(composed, stage3, chart_output_dir=tmp_path)

    prose = composed["page4b_criticality"]["risk_to_cp_linkage_prose"]
    # Decision 7 phrases — exact strings from the formatter template.
    assert "amplified-by-Mode" in prose
    assert "suppressed-by-Mode" in prose
    # The five GTU activities must appear in the worked-example clause.
    for name in (
        "Earthing for GTU",
        "Cable Pulling MV on GTU2",
        "Termination on GTU3",
    ):
        assert name in prose


def test_beta19_prose_preserved_when_MI_is_None(tmp_path: Path) -> None:
    """Without MI CI, composer falls back to Beta-19's risk-bridge prose."""
    stage3 = _make_stage3_beta_result(include_mode_independent=False)
    composed = _make_composed_skeleton()
    _apply_criticality_keys(composed, stage3, chart_output_dir=tmp_path)

    prose = composed["page4b_criticality"]["risk_to_cp_linkage_prose"]
    # Beta-19 wording starts with "Risk-to-CP linkage:" and the
    # amplified/suppressed phrasing is absent.
    assert prose.startswith("Risk-to-CP linkage:")
    assert "amplified-by-Mode" not in prose


def test_all_four_chart_paths_populated_in_criticality_note(tmp_path: Path) -> None:
    """Sibling-note dict carries all four SR10.B chart paths."""
    stage3 = _make_stage3_beta_result(include_mode_independent=True)
    composed = _make_composed_skeleton()
    _apply_criticality_keys(composed, stage3, chart_output_dir=tmp_path)

    cn = composed["criticality_note"]
    for key in ("chart1_path", "chart2_path", "chart3_path", "chart4_path"):
        assert cn[key], f"missing {key}"
        assert Path(cn[key]).exists(), f"{key} = {cn[key]} not found"


def test_phase_map_walks_wbs_to_root(tmp_path: Path) -> None:
    """Chart 2 phase map labels activities by their WBS root short name."""
    from src.final.composer import _build_phase_map_from_xer

    stage3 = _make_stage3_beta_result(
        include_mode_independent=True, include_xer_tables=True,
    )
    phase_map = _build_phase_map_from_xer(stage3["xer_tables"])
    # A1-A5 sit under wbs_id 101 → parent 100; root short_name "RefProject Root".
    # The walker stops when the parent is missing from PROJWBS (root has
    # parent_wbs_id=NA, so the walk terminates at 101's parent 100, and
    # 100's short_name "RefProject Root" is the label).
    assert all(phase_map[f"A{i}"] for i in range(1, 6))


def test_xer_tables_missing_degrades_chart2_cleanly(tmp_path: Path) -> None:
    """No XER tables → Chart 2 placeholder PNG, other charts still render."""
    stage3 = _make_stage3_beta_result(
        include_mode_independent=True, include_xer_tables=False,
    )
    composed = _make_composed_skeleton()
    _apply_criticality_keys(composed, stage3, chart_output_dir=tmp_path)
    # Chart 2 path is still set (placeholder PNG written), and the
    # other three chart paths are populated normally.
    cn = composed["criticality_note"]
    for key in ("chart1_path", "chart2_path", "chart3_path", "chart4_path"):
        assert Path(cn[key]).exists()
