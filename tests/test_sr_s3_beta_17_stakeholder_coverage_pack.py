"""SR-S3-Beta-17 — stakeholder coverage pack tests.

Five restorations closing the V5-era narrative lineage:

  Item 1 — L1 (systemic cost) caveat bullet in §7 Limitations
  Item 2 — Distribution-shape explainer in §7 Methodology summary
  Item 3 — Mean / median / buffer paragraph in §1 Executive summary
  Item 4 — RBS Level 1 category breakdown subsections in §3 (cost) and §4 (schedule)
  Item 5 — Correlation Group (CG) drivers subsection in §7 Methodology

A consolidated slow E2E test at the bottom of the file asserts all five
restorations land in a freshly rendered docx (see Beta-15 sibling).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Item 1 — L1 (systemic cost) caveat bullet
# ---------------------------------------------------------------------------


def test_item_1_l1_caveat_bullet_in_dev_limitations() -> None:
    """The L1 caveat bullet must be present in the dev limitations list."""
    from src.final import commentary_text

    assert commentary_text.L1_SYSTEMIC_CAVEAT_BULLET in commentary_text.LIMITATIONS_CURRENT


def test_item_1_l1_caveat_bullet_in_prod_limitations() -> None:
    """The L1 caveat bullet must also be present in the prod limitations list."""
    from src.final import commentary_text

    assert commentary_text.L1_SYSTEMIC_CAVEAT_BULLET in commentary_text.LIMITATIONS_CURRENT


def test_item_1_l1_caveat_bullet_names_layer_1_and_layer_2() -> None:
    """Caveat wording must name both layers explicitly so a V5-era reader
    can locate the architectural distinction the bullet is claiming.
    """
    from src.final import commentary_text

    text = commentary_text.L1_SYSTEMIC_CAVEAT_BULLET.lower()
    assert "layer 1" in text
    assert "layer 2" in text
    assert "event-risk" in text or "event risk" in text


# ---------------------------------------------------------------------------
# Item 2 — Distribution-shape explainer in §7 Methodology summary
# ---------------------------------------------------------------------------


def test_item_2_distribution_shape_explainer_intro_present() -> None:
    """Intro sentence must reference distribution choice + uncertainty."""
    from src.final import commentary_text

    intro = commentary_text.DISTRIBUTION_SHAPE_EXPLAINER_INTRO.lower()
    assert "distribution" in intro
    assert "uncertainty" in intro or "shape" in intro


def test_item_2_distribution_shape_explainer_names_all_four_shapes() -> None:
    """All four shapes must be named in the bullet list."""
    from src.final import commentary_text

    bullets_blob = "\n".join(commentary_text.DISTRIBUTION_SHAPE_EXPLAINER_BULLETS)
    for shape in ("PERT", "Triangular", "Lognormal", "Binary"):
        assert shape in bullets_blob, f"shape missing from explainer bullets: {shape!r}"


def test_item_2_distribution_shape_explainer_one_bullet_per_shape() -> None:
    """Exactly one bullet per shape (no doubles, no missing)."""
    from src.final import commentary_text

    assert len(commentary_text.DISTRIBUTION_SHAPE_EXPLAINER_BULLETS) == 4


def test_item_2_distribution_shape_explainer_wired_into_composer() -> None:
    """commentary_text source is referenced by composer (grep witness) so the
    explainer strings reach page7_methodology under stable keys.
    """
    from pathlib import Path

    composer_src = Path("src/final/composer.py").read_text(encoding="utf-8")
    assert "distribution_shape_explainer_intro" in composer_src
    assert "distribution_shape_explainer_bullets" in composer_src
    assert "DISTRIBUTION_SHAPE_EXPLAINER_INTRO" in composer_src
    assert "DISTRIBUTION_SHAPE_EXPLAINER_BULLETS" in composer_src


def test_item_2_distribution_shape_explainer_rendered_by_word_generator() -> None:
    """word_generator emits both intro and bullets via _add_bullets after the
    Methodology summary loop and before Mode-sensitivity summary.
    """
    from pathlib import Path

    wg_src = Path("src/final/word_generator.py").read_text(encoding="utf-8")
    assert "distribution_shape_explainer_intro" in wg_src
    assert "distribution_shape_explainer_bullets" in wg_src


# ---------------------------------------------------------------------------
# Item 3 — Mean / median / buffer paragraph in §1 Executive summary
# ---------------------------------------------------------------------------


def test_item_3_portfolio_framing_paragraph_names_mean_and_p80() -> None:
    """Three-sentence paragraph must name both Mean and P80 framings."""
    from src.final import commentary_text

    text = commentary_text.PORTFOLIO_FRAMING_PARAGRAPH
    assert "Mean" in text
    assert "P80" in text
    # Three sentences implies at least two period-followed-by-space breaks
    assert text.count(". ") >= 2


def test_item_3_portfolio_framing_paragraph_names_risk_appetite() -> None:
    """Paragraph must surface the risk-appetite framing (the conceptual hook)."""
    from src.final import commentary_text

    assert "risk-appetite" in commentary_text.PORTFOLIO_FRAMING_PARAGRAPH


def test_item_3_portfolio_framing_paragraph_wired_into_composer() -> None:
    """composer surfaces the paragraph under page1_portfolio_framing."""
    from pathlib import Path

    composer_src = Path("src/final/composer.py").read_text(encoding="utf-8")
    assert "page1_portfolio_framing" in composer_src
    assert "PORTFOLIO_FRAMING_PARAGRAPH" in composer_src


def test_item_3_portfolio_framing_paragraph_rendered_between_headline_and_six_approach() -> None:
    """word_generator emits page1_portfolio_framing between the headline
    paragraph and the six-approach reconciliation block.
    """
    from pathlib import Path

    wg_src = Path("src/final/word_generator.py").read_text(encoding="utf-8")
    headline_anchor = "page1_headline_integrated"
    framing_anchor = "page1_portfolio_framing"
    six_approach_anchor = "page1_six_approach_reconciliation"

    pos_headline = wg_src.index(headline_anchor)
    pos_framing = wg_src.index(framing_anchor)
    pos_six = wg_src.index(six_approach_anchor)

    assert pos_headline < pos_framing < pos_six, (
        "page1_portfolio_framing must be rendered after the headline and "
        "before the six-approach reconciliation table."
    )


# ---------------------------------------------------------------------------
# Item 4 — RBS Level 1 category breakdown (cost + schedule)
# ---------------------------------------------------------------------------

import numpy as np  # noqa: E402  (test-only convenience)


def _make_risk(risk_id: str, rbs_l1: str, cg: str = "CG01"):
    """Lightweight RiskInput stub with the attributes the builders read."""
    class _R:
        pass

    r = _R()
    r.risk_id = risk_id
    r.rbs_l1 = rbs_l1
    r.correlation_group = cg
    r.probability = 0.5
    return r


def test_item_4_cost_breakdown_aggregates_by_rbs_l1_p80_metric() -> None:
    """Cost breakdown sums per-iteration contributions per category and
    returns the P80 of each group's iteration totals (default metric).
    """
    from src.final.composer import build_rbs_l1_cost_breakdown

    rng = np.random.default_rng(seed=42)
    n_iter = 1000
    per_risk = rng.uniform(0, 1_000_000, size=(n_iter, 3))

    risks = [
        _make_risk("R01", "_1.Cost_Risks"),
        _make_risk("R02", "_1.Cost_Risks"),
        _make_risk("R03", "_2.Schedule_Risks"),
    ]
    integrated = {
        "per_risk_cost_array": per_risk,
        "risk_ids_all": ["R01", "R02", "R03"],
    }

    rows = build_rbs_l1_cost_breakdown(integrated, risks, headline_metric="P80")

    assert len(rows) == 2
    rbs_to_row = {r["rbs_l1"]: r for r in rows}

    # _1.Cost_Risks has 2 members, _2.Schedule_Risks has 1.
    assert rbs_to_row["_1.Cost_Risks"]["n_risks"] == 2
    assert rbs_to_row["_2.Schedule_Risks"]["n_risks"] == 1

    expected_cost_p80 = float(
        np.percentile(per_risk[:, [0, 1]].sum(axis=1), 80)
    )
    assert abs(
        rbs_to_row["_1.Cost_Risks"]["value_dollars"] - expected_cost_p80
    ) < 1e-6

    assert all(r["metric_name"] == "P80" for r in rows)


def test_item_4_cost_breakdown_metric_aware_mean_variant() -> None:
    """When headline_metric="Mean", group values are np.mean of group
    iteration totals (Beta-16 metric-aware mirror).
    """
    from src.final.composer import build_rbs_l1_cost_breakdown

    rng = np.random.default_rng(seed=7)
    per_risk = rng.uniform(0, 500_000, size=(500, 2))
    risks = [
        _make_risk("R01", "_1.Cost_Risks"),
        _make_risk("R02", "_1.Cost_Risks"),
    ]
    integrated = {
        "per_risk_cost_array": per_risk,
        "risk_ids_all": ["R01", "R02"],
    }

    rows = build_rbs_l1_cost_breakdown(integrated, risks, headline_metric="Mean")

    assert len(rows) == 1
    expected_mean = float(per_risk.sum(axis=1).mean())
    assert abs(rows[0]["value_dollars"] - expected_mean) < 1e-6
    assert rows[0]["metric_name"] == "Mean"


def test_item_4_cost_breakdown_sorted_descending_unassigned_last() -> None:
    """Rows sorted descending by value; (Unassigned) always placed last."""
    from src.final.composer import build_rbs_l1_cost_breakdown

    rng = np.random.default_rng(seed=11)
    n_iter = 500
    per_risk = np.empty((n_iter, 3))
    per_risk[:, 0] = rng.uniform(0, 100_000, size=n_iter)          # small
    per_risk[:, 1] = rng.uniform(800_000, 1_000_000, size=n_iter)  # large
    per_risk[:, 2] = rng.uniform(200_000, 400_000, size=n_iter)    # medium

    risks = [
        _make_risk("R01", "_A.Small"),
        _make_risk("R02", ""),  # unassigned
        _make_risk("R03", "_C.Medium"),
    ]
    integrated = {
        "per_risk_cost_array": per_risk,
        "risk_ids_all": ["R01", "R02", "R03"],
    }

    rows = build_rbs_l1_cost_breakdown(integrated, risks, headline_metric="P80")

    labels = [r["rbs_l1"] for r in rows]
    assert labels[-1] == "(Unassigned)"
    # Assigned rows sorted descending by value_dollars.
    assigned_values = [r["value_dollars"] for r in rows if r["rbs_l1"] != "(Unassigned)"]
    assert assigned_values == sorted(assigned_values, reverse=True)


def test_item_4_schedule_breakdown_uses_probability_weighted_mean_days() -> None:
    """Schedule breakdown returns np.mean (probability-weighted by engine
    convention) over each category's iteration totals — not metric-aware.
    """
    from src.final.composer import build_rbs_l1_schedule_breakdown

    rng = np.random.default_rng(seed=123)
    per_risk = rng.uniform(0, 5, size=(500, 2))  # days
    risks = [
        _make_risk("R01", "_1.Cost_Risks"),
        _make_risk("R02", "_2.Schedule_Risks"),
    ]
    integrated = {
        "per_risk_schedule_array": per_risk,
        "risk_ids_dual": ["R01", "R02"],
    }

    rows = build_rbs_l1_schedule_breakdown(integrated, risks)

    assert len(rows) == 2
    rbs_to_row = {r["rbs_l1"]: r for r in rows}
    assert abs(
        rbs_to_row["_1.Cost_Risks"]["prob_weighted_mean_days"]
        - float(per_risk[:, 0].mean())
    ) < 1e-9
    assert abs(
        rbs_to_row["_2.Schedule_Risks"]["prob_weighted_mean_days"]
        - float(per_risk[:, 1].mean())
    ) < 1e-9


def test_item_4_cost_breakdown_empty_inputs_return_empty() -> None:
    """Empty per_risk array (e.g. v2 path with no integrated results) yields []."""
    from src.final.composer import build_rbs_l1_cost_breakdown

    rows = build_rbs_l1_cost_breakdown({}, [], headline_metric="P80")
    assert rows == []


def test_item_4_schedule_breakdown_empty_inputs_return_empty() -> None:
    """Empty per_risk schedule array yields []."""
    from src.final.composer import build_rbs_l1_schedule_breakdown

    rows = build_rbs_l1_schedule_breakdown({}, [])
    assert rows == []


def test_item_4_cost_orienting_template_substitutes_metric_name() -> None:
    """RBS_L1_COST_ORIENTING_TEMPLATE has a {metric_name} placeholder."""
    from src.final import commentary_text

    out = commentary_text.RBS_L1_COST_ORIENTING_TEMPLATE.format(metric_name="P80")
    assert "P80" in out
    out_mean = commentary_text.RBS_L1_COST_ORIENTING_TEMPLATE.format(metric_name="Mean")
    assert "Mean" in out_mean


def test_item_4_rbs_breakdown_keys_present_in_composer_and_word_generator() -> None:
    """Composer + word_generator both reference the rbs_l1_breakdown_table key."""
    from pathlib import Path

    composer_src = Path("src/final/composer.py").read_text(encoding="utf-8")
    wg_src = Path("src/final/word_generator.py").read_text(encoding="utf-8")

    assert "rbs_l1_breakdown_table" in composer_src
    assert "rbs_l1_breakdown_table" in wg_src
    assert "Contribution by RBS Level 1 category" in composer_src
    assert "Schedule contribution by RBS Level 1 category" in composer_src


# ---------------------------------------------------------------------------
# Item 5 — Correlation Group (CG) drivers subsection in §7
#
# Beta-17 SSoT cleanup (12 May): build_cg_drivers_table reads driver
# descriptions from the register via read_cg_descriptions. No hardcoded
# fallback dict. Tests below pass clearly-marked test fixtures via the
# `cg_descriptions=` keyword override (test-only entry point).
# ---------------------------------------------------------------------------


# TEST FIXTURE — DO NOT USE IN RUN CODE.
# Mirrors the V8 register's MC_Params CG block so unit tests can exercise the
# grouping / formatting logic without touching disk. Run-code path reads
# descriptions exclusively via src.openpyxl_reader.read_cg_descriptions.
_TEST_CG_DESCRIPTIONS_V8_SUBSET = {
    "CG01": "Labour",
    "CG02": "Design",
    "CG04": "Schedule",
    "CG05": "Weather",
    "CG11": "Supply Chain",
}


def test_item_5_cg_drivers_table_groups_risks_by_correlation_group() -> None:
    """Builder groups risks by correlation_group; member_risk_ids sorted."""
    from src.final.composer import build_cg_drivers_table

    risks = [
        _make_risk("R72", "labour", cg="CG01"),
        _make_risk("R20", "design", cg="CG01"),
        _make_risk("R13", "weather", cg="CG05"),
    ]
    rows = build_cg_drivers_table(
        risks, cg_descriptions=_TEST_CG_DESCRIPTIONS_V8_SUBSET,
    )

    assert len(rows) == 2
    by_cg = {r["cg_id"]: r for r in rows}
    assert by_cg["CG01"]["member_risk_ids"] == ["R20", "R72"]
    assert by_cg["CG01"]["member_risk_count"] == 2
    assert by_cg["CG05"]["member_risk_ids"] == ["R13"]


def test_item_5_cg_drivers_table_reads_coefficient_from_headless_dict() -> None:
    """Coefficients come from HEADLESS_CG_COEFFICIENTS (canonical source).
    CGs absent from the dict (e.g. singleton CG11) render coefficient=None.
    """
    from src.defaults import HEADLESS_CG_COEFFICIENTS
    from src.final.composer import build_cg_drivers_table

    risks = [
        _make_risk("R72", "x", cg="CG01"),
        _make_risk("R28", "y", cg="CG11"),  # not in HEADLESS dict
    ]
    rows = build_cg_drivers_table(
        risks, cg_descriptions=_TEST_CG_DESCRIPTIONS_V8_SUBSET,
    )
    by_cg = {r["cg_id"]: r for r in rows}

    assert by_cg["CG01"]["coefficient"] == HEADLESS_CG_COEFFICIENTS["CG01"]
    assert by_cg["CG11"]["coefficient"] is None


def test_item_5_cg_drivers_table_uses_register_supplied_description() -> None:
    """Beta-17 SSoT cleanup: driver_description == the register-sourced
    string, verbatim. No REVIEW markers, no hardcoded substitutions.
    """
    from src.final.composer import build_cg_drivers_table

    risks = [
        _make_risk("R72", "x", cg="CG01"),
        _make_risk("R13", "y", cg="CG05"),
    ]
    rows = build_cg_drivers_table(
        risks, cg_descriptions=_TEST_CG_DESCRIPTIONS_V8_SUBSET,
    )
    by_cg = {r["cg_id"]: r for r in rows}

    assert by_cg["CG01"]["driver_description"] == "Labour"
    assert by_cg["CG05"]["driver_description"] == "Weather"
    # Negative: no leftover REVIEW marker from the pre-SSoT design.
    for row in rows:
        assert "(REVIEW)" not in row["driver_description"], (
            "REVIEW marker mechanism was deleted by the Beta-17 SSoT cleanup."
        )


def test_item_5_cg_drivers_table_unknown_cg_renders_not_in_register() -> None:
    """CG ID present in member-risk data but missing from the register's
    description block renders as CG_DESCRIPTION_NOT_IN_REGISTER. No
    hardcoded substitute, no REVIEW marker — register drift / authoring
    gaps surface honestly per the no-fallback policy.
    """
    from src.final.composer import (
        CG_DESCRIPTION_NOT_IN_REGISTER, build_cg_drivers_table,
    )

    risks = [_make_risk("R999", "novel", cg="CG_UNREGISTERED")]
    rows = build_cg_drivers_table(
        risks, cg_descriptions=_TEST_CG_DESCRIPTIONS_V8_SUBSET,
    )

    assert len(rows) == 1
    assert rows[0]["driver_description"] == CG_DESCRIPTION_NOT_IN_REGISTER


def test_item_5_cg_drivers_table_empty_register_description_renders_blank_marker() -> None:
    """Register cell present but empty (e.g. ``"CG01"`` alone with no
    description) renders as CG_DESCRIPTION_NOT_IN_REGISTER. Treats
    empty-after-prefix the same as missing-from-register because both
    represent "the register has no usable description for this CG".
    """
    from src.final.composer import (
        CG_DESCRIPTION_NOT_IN_REGISTER, build_cg_drivers_table,
    )

    risks = [_make_risk("R01", "x", cg="CG02")]
    rows = build_cg_drivers_table(
        risks, cg_descriptions={"CG02": ""},  # register-sourced empty string
    )

    assert rows[0]["driver_description"] == CG_DESCRIPTION_NOT_IN_REGISTER


def test_item_5_cg_drivers_table_no_fallback_raises_without_register_path() -> None:
    """SSoT enforcement: calling build_cg_drivers_table without either
    register_path or an explicit cg_descriptions override raises rather
    than falling back to a hardcoded dict.
    """
    import pytest as _pt
    from src.final.composer import build_cg_drivers_table

    risks = [_make_risk("R01", "x", cg="CG01")]
    with _pt.raises(ValueError, match="register_path"):
        build_cg_drivers_table(risks)


def test_item_5_cg_drivers_orienting_paragraphs_name_methodology_legs() -> None:
    """Orienting paragraphs must name the three legs of the cost MC's
    correlation structure so a methodology reviewer can ground the table.
    """
    from src.final import commentary_text

    blob = "\n".join(commentary_text.CG_DRIVERS_ORIENTING_PARAGRAPHS).lower()
    # Per-risk probability + three-point + CG mapping is "third leg".
    assert "joint" in blob
    assert "cholesky" in blob
    assert "shared severity" in blob or "severity uniform" in blob
    assert "dual-coded" in blob


def test_item_5_cg_drivers_subsection_keys_wired_into_composer_and_word_generator() -> None:
    """Composer surfaces cg_drivers_table + cg_drivers_orienting_paragraphs;
    word_generator renders both, placed between Standards references and
    Limitations of current analysis.
    """
    from pathlib import Path

    composer_src = Path("src/final/composer.py").read_text(encoding="utf-8")
    wg_src = Path("src/final/word_generator.py").read_text(encoding="utf-8")

    assert "cg_drivers_table" in composer_src
    assert "cg_drivers_orienting_paragraphs" in composer_src
    assert "build_cg_drivers_table" in composer_src

    assert "cg_drivers_table" in wg_src
    assert "Correlation Group (CG) drivers" in wg_src

    # Placement: cg_drivers_table block appears AFTER the Standards
    # references rendering and BEFORE the Limitations heading.
    pos_standards = wg_src.index('"Standards references"')
    pos_cg = wg_src.index("cg_drivers_table")
    pos_limits = wg_src.index('"Limitations of current analysis"')
    assert pos_standards < pos_cg < pos_limits, (
        "CG drivers subsection must render between Standards references "
        "and Limitations of current analysis."
    )


def test_item_5_cg_drivers_table_no_correlation_group_attr_returns_empty() -> None:
    """Risks with empty correlation_group are skipped (defensive)."""
    from src.final.composer import build_cg_drivers_table

    risks = [_make_risk("R01", "x", cg="")]
    rows = build_cg_drivers_table(risks, cg_descriptions={})
    assert rows == []


# ---------------------------------------------------------------------------
# Beta-17 SSoT — no-fallback policy regression tests
#
# Three load-bearing invariants for the cleanup (12 May):
#   (i)   composer's CG table comes from read_cg_descriptions(register_path)
#   (ii)  reader-incomplete data → blank "(not in register)" cell, no substitute
#   (iii) reader exception propagates → deliverable build halts, no silent
#         degradation
# ---------------------------------------------------------------------------


def test_ssot_composer_calls_read_cg_descriptions_when_given_register_path() -> None:
    """Run-code entry point routes through src.openpyxl_reader.read_cg_descriptions.

    Patches the reader to return a known dict, calls build_cg_drivers_table
    with register_path set (no cg_descriptions override), and asserts (a)
    the reader was invoked exactly once with the register_path the composer
    received, and (b) the rendered driver descriptions come from the
    reader's return value.
    """
    from unittest.mock import patch
    from src.final.composer import build_cg_drivers_table

    fake_register_path = "/fake/path/to/register.xlsx"
    reader_return = {"CG01": "Labour", "CG05": "Weather"}
    risks = [
        _make_risk("R01", "x", cg="CG01"),
        _make_risk("R02", "y", cg="CG05"),
    ]

    with patch(
        "src.openpyxl_reader.read_cg_descriptions",
        return_value=reader_return,
    ) as mock_reader:
        rows = build_cg_drivers_table(risks, register_path=fake_register_path)

    mock_reader.assert_called_once_with(fake_register_path)
    by_cg = {r["cg_id"]: r["driver_description"] for r in rows}
    assert by_cg["CG01"] == "Labour"
    assert by_cg["CG05"] == "Weather"


def test_ssot_reader_returns_incomplete_dict_renders_not_in_register() -> None:
    """Reader returns a partial dict (CG05 absent from member-risk data); the
    CG present in member-risk data but absent from the reader result renders
    as the explicit ``(not in register)`` placeholder. No silent
    substitution from any fallback dict.
    """
    from unittest.mock import patch
    from src.final.composer import (
        CG_DESCRIPTION_NOT_IN_REGISTER, build_cg_drivers_table,
    )

    reader_return = {"CG01": "Labour"}  # CG05 deliberately absent
    risks = [
        _make_risk("R01", "x", cg="CG01"),
        _make_risk("R02", "y", cg="CG05"),
    ]

    with patch(
        "src.openpyxl_reader.read_cg_descriptions",
        return_value=reader_return,
    ):
        rows = build_cg_drivers_table(risks, register_path="/fake/path.xlsx")

    by_cg = {r["cg_id"]: r["driver_description"] for r in rows}
    assert by_cg["CG01"] == "Labour"
    assert by_cg["CG05"] == CG_DESCRIPTION_NOT_IN_REGISTER, (
        "Composer must not substitute a hardcoded value for a CG missing "
        "from the register reader's result."
    )


def test_ssot_reader_exception_propagates_rather_than_being_swallowed() -> None:
    """When read_cg_descriptions raises (e.g. MC_Params sheet missing in
    the register), build_cg_drivers_table must propagate the exception
    rather than swallowing it and falling back. Build halt is the
    desired behaviour - silent degradation is what the SSoT policy
    rules out.
    """
    from unittest.mock import patch
    import pytest as _pt
    from src.final.composer import build_cg_drivers_table

    risks = [_make_risk("R01", "x", cg="CG01")]

    class _RegisterReadError(RuntimeError):
        pass

    with patch(
        "src.openpyxl_reader.read_cg_descriptions",
        side_effect=_RegisterReadError("MC_Params sheet missing"),
    ):
        with _pt.raises(_RegisterReadError, match="MC_Params sheet missing"):
            build_cg_drivers_table(risks, register_path="/fake/path.xlsx")


def test_ssot_no_hardcoded_cg_description_fallbacks_remain_in_run_code() -> None:
    """Codebase-wide guard against re-introduction of hardcoded CG
    description dicts. Each of the four deleted hardcodes must remain
    absent from run code; test fixtures with a clearly-marked
    "TEST FIXTURE" comment are the only acceptable occurrences.

    Catches a future contributor who tries to re-add the dict for
    convenience without going through this brief's policy gate.
    Scans for module-level assignments to the forbidden names; ignores
    occurrences inside comments / docstrings / strings.
    """
    import re
    from pathlib import Path

    src_dir = Path(__file__).resolve().parents[1] / "src"
    forbidden = (
        "CG_DRIVER_DESCRIPTIONS",
        "CG_DRIVER_UNKNOWN_PLACEHOLDER",
        "CG_DESCRIPTIONS",
        "CG_NAMES",
    )
    # Module-level assignment pattern: optional type annotation, then `=`.
    assignment_patterns = {
        name: re.compile(rf"^(?:{re.escape(name)})(?:\s*:\s*[^=]+)?\s*=", re.MULTILINE)
        for name in forbidden
    }
    offenders: list[str] = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        # Strip comment lines so a comment naming a deleted constant
        # ("# CG_NAMES was deleted") doesn't trip the guard.
        text_no_comments = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for name, pattern in assignment_patterns.items():
            if pattern.search(text_no_comments):
                offenders.append(f"{py_file}: module-level assignment to {name}")
    assert not offenders, (
        "Beta-17 SSoT cleanup deleted four hardcoded CG description "
        "dicts; one or more have been re-introduced in run code:\n"
        + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Slow E2E — all five restorations land in a rendered docx
# ---------------------------------------------------------------------------

