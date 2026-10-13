"""SRA-02 S-F — P-F5/P-F6: ``wind_sra_schedule.md`` renders the mode mix.

MODEMIX-01: ``run_sra_schedule()`` computes the applied Mode per risk and
returns it as ``mode_used`` at ``scripts/run_wind_showcase.py:225``; that name
occurred once in the file and nothing consumed it, so the consolidated path
computed the mode mix on every run and rendered it nowhere. It is one of the
five SRA-01:122 no-regression surfaces, so SRA-02 cannot close on its signed
gate with the surface absent.

Presentation only (P-F6). No literal enters the surface: the label and the
per-risk Modes are read from the engine result already returned at ``:225``.
``test_label_is_not_a_literal`` is the control that says so — a hardcoded
``4S/4H/2P`` would satisfy every other assertion here.

No engine run: the tests drive ``_render_sra_schedule_md`` directly with a
scope-shaped result dict, per the paste's "do not add a slow-class test for
this".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.final.executive_summary import format_mode_mix

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "synthetic_wind"
WIND_REGISTER = FIXTURE_DIR / "wind_register.xlsx"

# A schedule result of the shape run_sra_schedule() returns. WT-021 carries a
# zero mean contribution on purpose: until RS-D-3 the contribution table filtered
# rows at 1e-6 days (S-F F-3 recorded the eight-of-ten gap); under D-15(ii) every
# simulated risk gets a row, so the header's mix and the table agree.
_SRA_RESULT = {
    "bands": {"mean": 12.3, "p50": 10.0, "p80": 18.4, "p90": 24.1, "p95": 31.7},
    "ranked": [("WT-008", 4.25), ("WT-001", 2.50), ("WT-021", 0.0)],
    "mode_used": {"WT-008": "Series", "WT-001": "Hybrid", "WT-021": "Parallel"},
    "n_sim": 3,
}


@pytest.fixture
def _wind(monkeypatch):
    """Activate the synthetic-wind binding and hand back the showcase module."""
    import scripts.run_wind_showcase as wind

    spec = importlib.util.spec_from_file_location(
        "wind_binding_modemix", FIXTURE_DIR / "wind_binding.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # self-registers 'synthetic_wind'
    monkeypatch.setenv("QRA_PROJECT", "synthetic_wind")
    return wind


def _rendered(wind, sra=None) -> str:
    return wind._render_sra_schedule_md(sra or _SRA_RESULT)


class TestModeMixLabel:

    def test_header_block_carries_the_mix_label(self, _wind) -> None:
        text = _rendered(_wind)
        header = text.split("## Finish-delay P-bands")[0]
        assert "1S/1H/1P" in header, header

    def test_label_matches_the_single_formatter(self, _wind) -> None:
        """One formatter, not a second reimplementation inside the script."""
        expected = format_mode_mix(_SRA_RESULT["mode_used"])
        assert expected in _rendered(_wind)

    def test_label_is_not_a_literal(self, _wind) -> None:
        """Control for P-F6: change the engine's modes, the surface must move."""
        altered = dict(_SRA_RESULT)
        altered["mode_used"] = {
            "WT-008": "Series", "WT-001": "Series", "WT-021": "Series",
        }
        text = _rendered(_wind, altered)
        assert "3S" in text
        assert "1S/1H/1P" not in text


class TestPerRiskMode:

    def test_every_rendered_risk_row_carries_its_mode(self, _wind) -> None:
        text = _rendered(_wind)
        rows = [ln for ln in text.splitlines() if ln.startswith("| WT-")]
        rendered_ids = {ln.split("|")[1].strip() for ln in rows}
        assert rendered_ids == {"WT-008", "WT-001", "WT-021"}  # RS-D-3: zero row renders
        for line in rows:
            rid = line.split("|")[1].strip()
            assert _SRA_RESULT["mode_used"][rid] in line, line

    def test_zero_contribution_risk_is_still_filtered_out(self, _wind) -> None:
        """RS-D-3 (D-15 ii): a zero-contribution risk gets a row, so the header's
        2P-style count and the table agree."""
        assert "| WT-021 | Parallel | 0.00 |" in _rendered(_wind)


def test_wind_fixture_mix_is_four_series_four_hybrid_two_parallel(_wind) -> None:
    """Ties the surface to the shipped fixture rather than to a chosen example.

    The ten Time=Yes wind risks are Series 4 / Hybrid 4 / Parallel 2, so a real
    showcase run renders ``4S/4H/2P``. Read from the register, not asserted from
    a constant in the script.
    """
    from src.sra.strawman_reader import read_risk_scope

    scope = read_risk_scope(str(WIND_REGISTER))
    modes = {
        row.risk_id: str(row.mode_aggregated).strip()
        for row in scope.itertuples()
        if str(getattr(row, "time_impact", "") or "").strip() == "Yes"
    }
    assert len(modes) == 10, modes
    assert format_mode_mix(modes) == "4S/4H/2P"
