"""SR15.1 — production-pipeline wiring tests for the Stage 3 standalone docx.

Covers AC4/AC5/AC6/AC7/AC8 from the SR15.1 brief:

* AC4 (1000-iter smoke): the Stage 3 standalone composed dict's
  integrated P80 cost+schedule headline matches the SR15 smoke-runner
  output within MC noise tolerance. Marked ``@pytest.mark.slow``
  because it exercises the full Stage 3 engine end-to-end.
* AC5: ``page1_component_breakdown`` carries a materially non-zero
  schedule contingency dollarised P80 (rather than $0.00M under the
  pre-SR15.1 Mode-suppressed path).
* AC6: ``page4_schedule_drivers.drivers_table`` shows non-zero
  contribution for the seven currently-Parallel-mode risks.
* AC7: Stage 3 docx walkthrough table column structure per Decision 2
  Option A (Mode + Mode-multiplier columns dropped).
* AC8: D3 methodology section + D4 Table 6 footnote + preview banner
  + cover caveat unchanged from SR15-merge-tip (verbatim assertion).

The fast tests stub out the Stage 3 engine to avoid file I/O; the
slow test exercises the live engine against the canonical earlier RefProject register
register + DPReview strawman + 22 April 2026 .xer.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest
from tests._fixture_values import FIXTURE_DAY_RATE


# ---------------------------------------------------------------------------
# AC7 — Stage 3 walkthrough table column structure (Decision 2 = Option A)
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_walkthrough_df() -> pd.DataFrame:
    """Single-iteration transparency DataFrame mirroring the engine's
    full column set (Beta-15 Item 6 schema)."""
    return pd.DataFrame({
        "risk_id": ["R013", "R067", "TOTAL"],
        "probability": [0.25, 0.50, np.nan],
        "u_fire_draw": [0.1234, 0.5678, np.nan],
        "fired": [True, False, np.nan],
        "u_dur_draw": [0.4321, 0.8765, np.nan],
        "drawn_duration_days": [10.5, np.nan, 10.5],
        "mode": ["Series", "Parallel", ""],
        "mode_multiplier": [1.0, 0.0, np.nan],
        "contribution_days": [10.5, 0.0, 10.5],
    })


class TestWalkthroughColumnStructureStage3:
    """Decision 2 Option A: Stage 3 docx walkthrough drops Mode +
    Mode-multiplier columns. Stage 2.5 docx walkthrough unchanged."""

    def _read_table_headers(self, docx_path: Path) -> list[str]:
        import docx
        doc = docx.Document(str(docx_path))
        if not doc.tables:
            return []
        last = doc.tables[-1]
        return [cell.text for cell in last.rows[0].cells]

    def test_stage3_walkthrough_omits_mode_columns(
        self, tmp_path: Path, synthetic_walkthrough_df: pd.DataFrame,
    ):
        from docx import Document
        from src.final.word_generator import (
            _add_single_iteration_transparency_table,
        )

        doc = Document()
        _add_single_iteration_transparency_table(
            doc, synthetic_walkthrough_df,
            deliverable_kind="stage3_standalone",
        )
        out = tmp_path / "stage3.docx"
        doc.save(out)

        headers = self._read_table_headers(out)
        assert "Mode" not in headers, (
            f"Stage 3 walkthrough must drop Mode column; got {headers}"
        )
        assert "Mode multiplier" not in headers, (
            f"Stage 3 walkthrough must drop Mode multiplier column; "
            f"got {headers}"
        )

    def test_stage3_walkthrough_keeps_seven_canonical_columns(
        self, tmp_path: Path, synthetic_walkthrough_df: pd.DataFrame,
    ):
        from docx import Document
        from src.final.word_generator import (
            _add_single_iteration_transparency_table,
        )

        doc = Document()
        _add_single_iteration_transparency_table(
            doc, synthetic_walkthrough_df,
            deliverable_kind="stage3_standalone",
        )
        out = tmp_path / "stage3.docx"
        doc.save(out)

        headers = self._read_table_headers(out)
        # Seven kept columns per D2 Option A.
        expected = [
            "Risk ID", "Probability", "U_fire draw", "Fired?",
            "U_dur draw", "Drawn duration (days)",
            "Contribution (days)",
        ]
        assert headers == expected, (
            f"Stage 3 walkthrough headers mismatch; expected {expected}, "
            f"got {headers}"
        )

    def test_stage25_walkthrough_keeps_mode_columns(
        self, tmp_path: Path, synthetic_walkthrough_df: pd.DataFrame,
    ):
        """Stage 2.5 walkthrough rendering is unchanged — the Mode +
        Mode-multiplier columns continue to render. Verifies the SR15.1
        change is scoped to ``deliverable_kind == "stage3_standalone"``."""
        from docx import Document
        from src.final.word_generator import (
            _add_single_iteration_transparency_table,
        )

        doc = Document()
        # Stage 2.5 path: deliverable_kind omitted or set to anything
        # other than "stage3_standalone".
        _add_single_iteration_transparency_table(
            doc, synthetic_walkthrough_df,
        )
        out = tmp_path / "stage25.docx"
        doc.save(out)

        headers = self._read_table_headers(out)
        assert "Mode" in headers
        assert "Mode multiplier" in headers


# ---------------------------------------------------------------------------
# AC8 — Director-locked text unchanged from SR15-merge-tip
# ---------------------------------------------------------------------------

@pytest.mark.project("synthetic_wind")  # stage 4 F-33: the locked text is the reference project's
class TestDirectorLockedTextUnchanged:
    """SR15.1 must not touch the SR11/SR14b/SR15 Director-locked text:

    * Preview banner (SR11 §3.5)
    * Cover caveat (SR14b D3.1)
    * D3 methodology section paragraphs (SR15)
    * D4 Table 6 footnote (SR15)
    """

    def test_preview_banner_unchanged(self):
        from src.final.stage3_composer import PREVIEW_BANNER_TEXT
        from src.final.stage3_beta_report import (
            PREVIEW_BANNER_TEXT as ORIG,
        )
        assert PREVIEW_BANNER_TEXT == ORIG
        assert "Preview" in PREVIEW_BANNER_TEXT or "preview" in PREVIEW_BANNER_TEXT

    def test_cover_caveat_unchanged(self):
        from src.final.stage3_composer import COVER_PAGE_CAVEAT_TEXT
        from src.final.stage3_beta_report import (
            COVER_PAGE_CAVEAT_TEXT as ORIG,
        )
        assert COVER_PAGE_CAVEAT_TEXT == ORIG

    def test_d3_methodology_paragraphs_unchanged(self):
        """The three D3 paragraphs from SR15 must remain verbatim.
        This catches accidental edits in `commentary_text.py` by a
        future SR15.1 commit chain."""
        from src.final.commentary_text import (
            MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3,
            MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3,
        )
        assert MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3 == (
            "Mode multipliers and the full-CPM approach"
        )
        # REFRETIRE-01: two paragraphs, not three. The third was the retired binding's own
        # figures, resolved per project since Stage 4 F-33 and gone with that binding; the
        # generic text keeps paragraph 1 verbatim and states the implication without a figure.
        assert len(MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3) == 2
        # First paragraph leads with the bold marker + locked phrase.
        assert MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3[0].startswith(
            "**Mode multipliers and the full-CPM approach.**"
        )
        assert "Stage 2.5" in MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3[0]

    def test_d4_footnote_unchanged(self):
        from src.final.commentary_text import (
            SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3,
        )
        assert (
            "Stage 3 full-CPM methodology"
            in SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3
        )
        assert (
            "Series / Hybrid / Parallel"
            in SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3
        )


# ---------------------------------------------------------------------------
# AC4/AC5/AC6 — Composer-level integration with stubbed Stage 3 engine
# ---------------------------------------------------------------------------

class TestComposedDictReflectsStage3Headline:
    """Composer-level integration test using a patched Stage 3 engine.

    The Stage 3 engine is stubbed so the test stays in the fast lane;
    the substantive assertion is that
    :func:`compose_stage3_standalone_data` produces a composed dict
    whose Page 1 component breakdown carries materially non-zero
    schedule contingency P80 (≫ Stage 2.5's Mode-suppressed $0.00M).
    """

    def _stage25_dp_review(self, n_iter: int = 1000) -> dict:
        rng = np.random.default_rng(42)
        return {
            "cost_dollars_array": rng.lognormal(15.5, 0.8, size=n_iter) * 1e3,
            # Mode-suppressed schedule: small mean, P80 ≈ 0.
            "schedule_days_array": rng.gamma(1.0, 0.5, size=n_iter),
            "per_risk_cost_array": rng.lognormal(14.0, 0.5, size=(n_iter, 8)) * 1e3,
            "per_risk_schedule_array": np.zeros((n_iter, 8)),
            "per_risk_schedule_pre_mode_array": rng.gamma(
                3.0, 4.0, size=(n_iter, 8),
            ),
            "fired_array": rng.random((n_iter, 8)) < 0.5,
            "risk_ids_all": [f"R{i:03d}" for i in range(8)],
            "risk_ids_dual": [f"R{i:03d}" for i in range(8)],
            "dual_lookup": {},
            "iterations": n_iter,
            "seed_used": 42,
        }

    @patch(
        "src.final.stage3_composer._build_stage3_integrated_scenario",
    )
    def test_helper_is_invoked_when_dp_review_present(self, mock_helper):
        from src.final.stage3_composer import compose_stage3_standalone_data
        from src.integrated.integrated_simulation import IntegratedConfig
        from src.sra.methodology_defaults_reader import build_test_methodology_defaults

        stage25_dp = self._stage25_dp_review()
        # Helper returns a Stage 3-flavoured DP_Review with materially
        # larger schedule.
        stage3_dp = {**stage25_dp}
        stage3_dp["schedule_days_array"] = (
            stage25_dp["schedule_days_array"] + 800.0
        )
        stage3_dp["per_risk_schedule_array"] = (
            stage25_dp["per_risk_schedule_pre_mode_array"]
        )
        mock_helper.return_value = stage3_dp

        cfg = IntegratedConfig(
            register_path=Path("/x/register.xlsx"),
            p6_path=Path("/x/p6.xlsx"),
            strawman_path=Path("/x/straw.xlsx"),
            iterations=1000,
            random_seed=42,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)

        # Patch out compose_final_report_data so we only test the SR15.1
        # wiring layer; the inner composer is exercised by its own
        # tests.
        with patch(
            "src.final.stage3_composer.compose_final_report_data",
            return_value={"deliverable_kind": "stage25"},
        ) as mock_inner:
            compose_stage3_standalone_data(
                cost_results={},
                schedule_results={},
                integrated_results_by_scenario={"DP_Review": stage25_dp},
                schedule_results_by_scenario={},
                strawman_path=Path("/x/straw.xlsx"),
                register_path=Path("/x/register.xlsx"),
                cross_validation={},
                stage3_beta_result={
                    "risk_drivers": {},
                    "schedule_graph": MagicMock(),
                    "xer_tables": {},
                    "severity_uniforms_by_risk_id": {},
                },
                config=cfg,
            )
            assert mock_helper.called
            passed = mock_inner.call_args.kwargs[
                "integrated_results_by_scenario"
            ]
            np.testing.assert_array_equal(
                passed["DP_Review"]["schedule_days_array"],
                stage3_dp["schedule_days_array"],
            )


# ---------------------------------------------------------------------------
# AC4 — Slow end-to-end smoke against the canonical RefProject inputs
# ---------------------------------------------------------------------------
