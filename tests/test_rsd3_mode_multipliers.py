"""RS-D-3 (D-15), part 3a: an unknown Mode raises on every multiplier lookup, and a
zero-contribution risk gets a row.

Before RS-D-3 four lookups fell back silently - the SRA engine and the integrated dual-lookup
to a multiplier of 0.0 (the risk vanished from the schedule), the report's tail-risk narrative
to 0.5 - while the cross-check raised by name. Property: every consumer resolves a Mode through
one resolver, and a Mode the grid does not define raises naming the risk. The wind showcase's
contribution table renders every simulated risk, including those whose Mode multiplier makes
their mean contribution exactly zero, so the header's mix and the table agree.

Written red-first: on the pre-RS-D-3 tree the four lookups return a number and the zero row is
filtered.
"""
from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "synthetic_wind"
COLS = ["risk_id", "time_impact", "mode_aggregated", "probability",
        "opt_days", "ml_days", "pess_days"]


def _scope(mode_for_r002: str) -> pd.DataFrame:
    rows = [
        {"risk_id": "R001", "time_impact": "Yes", "mode_aggregated": "Series",
         "probability": 0.5, "opt_days": 1.0, "ml_days": 2.0, "pess_days": 3.0},
        {"risk_id": "R002", "time_impact": "Yes", "mode_aggregated": mode_for_r002,
         "probability": 0.5, "opt_days": 1.0, "ml_days": 2.0, "pess_days": 3.0},
    ]
    return pd.DataFrame(rows, columns=COLS)


def test_resolver_is_shared_and_public():
    from src.sra.mode_multipliers import resolve_mode_multiplier
    from src.sra import schedule_cross_check

    assert schedule_cross_check._resolve_mode_multiplier is resolve_mode_multiplier
    grid = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}
    assert resolve_mode_multiplier("hybrid", grid, "R001") == 0.5
    with pytest.raises(ValueError, match="R009"):
        resolve_mode_multiplier("Foo", grid, "R009")


def test_integrated_dual_lookup_raises_on_unknown_mode():
    from src.integrated.integrated_simulation import _resolve_modes

    assert _resolve_modes(_scope("Hybrid"), None, mode_multipliers=TEST_MODE_MULTIPLIERS)["R002"]["mode_multiplier"] == 0.5
    with pytest.raises(ValueError, match="R002"):
        _resolve_modes(_scope("Foo"), None, mode_multipliers=TEST_MODE_MULTIPLIERS)


def test_joint_sampler_lookup_raises_on_unknown_mode():
    from src.integrated.joint_sampler import _build_dual_lookup

    assert _build_dual_lookup(_scope("Hybrid"), None, mode_multipliers=TEST_MODE_MULTIPLIERS)["R002"]["mode_multiplier"] == 0.5
    with pytest.raises(ValueError, match="R002"):
        _build_dual_lookup(_scope("Foo"), None, mode_multipliers=TEST_MODE_MULTIPLIERS)


def test_sra_engine_raises_on_unknown_mode():
    from src.sra.sra_config import SRAConfig
    from src.sra.sra_simulation import run_schedule_simulation

    cfg = SRAConfig(register_path=Path("x"), p6_path=Path("x"), strawman_path=Path("x"),
                    day_rate=1.0, iterations=50, random_seed=1, mode_multipliers=TEST_MODE_MULTIPLIERS)
    run_schedule_simulation(cfg, _scope("Hybrid"))  # the control: a known Mode runs
    with pytest.raises(ValueError, match="R002"):
        run_schedule_simulation(cfg, _scope("Foo"))


def test_tail_risk_narrative_raises_on_unknown_mode():
    from src.final.executive_summary import enrich_tail_risk_for_matrix

    tail = {"tail_risk_id": "R001"}
    risks = [{"risk_id": "R001", "opt_schedule_days": 1.0, "ml_days": 2.0, "pess_schedule_days": 3.0}]
    ok = enrich_tail_risk_for_matrix(tail, risks, {"R001": "Hybrid"}, "x", mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert ok["multiplier_value"] == 0.5
    with pytest.raises(ValueError, match="R001"):
        enrich_tail_risk_for_matrix(tail, risks, {"R001": "Foo"}, "x", mode_multipliers=TEST_MODE_MULTIPLIERS)


@pytest.fixture
def _wind(monkeypatch):
    import scripts.run_wind_showcase as wind

    spec = importlib.util.spec_from_file_location("wind_binding_rsd3", FIXTURE_DIR / "wind_binding.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # self-registers 'synthetic_wind'
    monkeypatch.setenv("QRA_PROJECT", "synthetic_wind")
    return wind


def test_showcase_table_renders_zero_contribution_rows(_wind):
    sra = {
        "bands": {"mean": 12.3, "p50": 10.0, "p80": 18.4, "p90": 24.1, "p95": 31.7},
        "ranked": [("WT-008", 4.25), ("WT-001", 2.50), ("WT-021", 0.0)],
        "mode_used": {"WT-008": "Series", "WT-001": "Hybrid", "WT-021": "Parallel"},
        "n_sim": 3,
    }
    text = _wind._render_sra_schedule_md(sra)
    rows = [ln for ln in text.splitlines() if ln.startswith("| WT-")]
    assert len(rows) == 3, rows
    assert "| WT-021 | Parallel | 0.00 |" in text


def test_fixture_builder_validates_against_the_grid_it_writes():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "build_synthetic_wind_fixture.py").read_text(encoding="utf-8")
    assert "from src.sra.sra_config import TEST_MODE_MULTIPLIERS" not in source
    assert "m not in METHODOLOGY_MODE_MULTIPLIERS" in source


@pytest.mark.parametrize("blank", ["", "   ", None, float("nan"), "nan", "NaN"])
def test_resolver_names_every_blank_shape_as_blank(blank):
    """Review WARN-2: None, empty, whitespace, a float NaN and the text "nan" an upstream
    ``str()`` makes of it are one thing - a blank - and the raise says so."""
    from src.sra.mode_multipliers import resolve_mode_multiplier

    with pytest.raises(ValueError, match="<blank>"):
        resolve_mode_multiplier(blank, {"Series": 1.0}, "R001")


def test_resolver_rejects_a_grid_with_case_duplicate_modes():
    """Review NOTE: two spellings of one Mode in the grid would fold to one key and the
    last would win silently; the resolver refuses the grid instead."""
    from src.sra.mode_multipliers import resolve_mode_multiplier

    with pytest.raises(ValueError, match="more than once"):
        resolve_mode_multiplier("Series", {"Series": 1.0, "series": 0.9}, "R001")


def test_blank_mode_at_engine_sites_still_takes_the_recorded_parallel_default():
    """Recorded, not changed (methodology, Director): a blank ``mode_aggregated`` reaches the
    resolver as ``DEFAULT_FALLBACK_MODE`` at the engine sites, so it multiplies by the grid's
    Parallel value rather than raising. This test pins that as a decision, not an accident."""
    from src.integrated.integrated_simulation import _resolve_modes
    from src.sra.sra_config import DEFAULT_FALLBACK_MODE
    from tests.conftest import TEST_MODE_MULTIPLIERS

    out = _resolve_modes(_scope(""), None, mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert out["R002"]["mode"] == DEFAULT_FALLBACK_MODE
    assert out["R002"]["mode_multiplier"] == TEST_MODE_MULTIPLIERS[DEFAULT_FALLBACK_MODE]
