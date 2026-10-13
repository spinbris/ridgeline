"""PUBLICFACE-01 P3: the app shows the product's name, not a binding key or a code name.

The footer prints ``meta.register_version`` and the analyst audit note quotes the project label, so
both are checked where they are produced: the resolver's fields for every shipped project, and the
period JSON a real wind run writes.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from src.am.project_binding import resolve_project_inputs
from src.sra.cpm.bindings import get_binding, project_display_name

REPO = Path(__file__).resolve().parents[1]
SHIPPED = ("synthetic_wind", "synthetic_road")


def _code_names(project: str) -> set[str]:
    binding = get_binding(project)
    names = {project, binding.project_name}
    names |= {Path(binding.default_filenames[k]).stem for k in ("register",)}
    return {n for n in names if n and n != project_display_name(binding)}


@pytest.mark.parametrize("project", SHIPPED)
def test_the_resolved_labels_are_the_public_display_name(project):
    resolved = resolve_project_inputs(project)
    display = project_display_name(get_binding(project))
    assert resolved.register_version == display
    assert resolved.methodology_label == display
    for field in (resolved.register_version, resolved.methodology_label):
        assert not any(code in field for code in _code_names(project)), (project, field)


@pytest.mark.parametrize("project", SHIPPED)
def test_the_code_names_the_scan_looks_for_are_real(project):
    """A scan over names that no project has would pass for ever."""
    assert {"SyntheticWind", "wind_register"} <= _code_names("synthetic_wind")
    assert any("road" in n for n in _code_names("synthetic_road"))


@pytest.mark.slow
def test_a_wind_period_json_names_the_product_not_a_code_name(tmp_path):
    from src.am.run_period import run_period

    workbook = REPO / "status_periods" / "wind_period_01.xlsx"
    if not workbook.is_file():
        pytest.skip("status_periods/wind_period_01.xlsx is not in this tree")
    out = run_period(
        workbook_path=workbook, output_dir=tmp_path, allow_dirty=True, project="synthetic_wind",
        main_iterations=300, days_at_risk_iterations=100, counterfactual_iterations=100,
        seed=42, criticality_measurement_mode="both", project_start=_dt.date(2024, 1, 1))
    doc = json.loads(Path(out).read_text(encoding="utf-8"))
    meta = doc["meta"]
    # meta.project_key is a contract field the loader checks against the directory it was read
    # from and quotes only in a wrong-directory error; no page renders it, and it keeps its name.
    meta.pop("project_key")
    text = json.dumps(doc)
    found = sorted(c for c in _code_names("synthetic_wind") if c in text)
    assert found == [], f"the period JSON a reader sees names {found}"
    assert meta["register_version"] == meta["project_display_name"]
