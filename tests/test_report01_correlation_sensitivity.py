"""REPORT01 F-E: what correlation contributes, per GN3A section 4.1 and leave-one-out.

Director D-1 (12/09/2026): both measures, the GN3A bounding leading. They answer
different questions - does correlation matter at all, and which group drives the spread -
and neither substitutes for the other.

The tests that matter here are the ones that would still pass under a plausible wrong
implementation: a bounding that reseeds per mode (putting sampling noise where the signal
should be), a leave-one-out that drops risks singly rather than by group, and a variance
share that silently reports a negative contribution as zero.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.final.sections.correlation_sensitivity import (
    GN3A_MODES,
    NO_MEASURABLE_SHARE,
    _coefficients_at,
    build_bounding_table,
    build_cg_variance_shares,
    build_correlation_sensitivity_section,
    elicited_reproduces_run,
    risk_correlation_groups,
    run_bounding_triple,
    run_stage3_bounding,
    uncovered_groups,
)

ELICITED = {"CG01": 0.5, "CG02": 0.3}


def _risk(rid, group):
    return SimpleNamespace(risk_id=rid, correlation_group=group)


# ---------------------------------------------------------------------------
# The bounding modes
# ---------------------------------------------------------------------------

def test_zero_and_one_replace_every_coefficient_not_just_the_known_ones():
    assert _coefficients_at("zero", ELICITED) == {"CG01": 0.0, "CG02": 0.0}
    assert _coefficients_at("one", ELICITED) == {"CG01": 1.0, "CG02": 1.0}
    assert _coefficients_at("elicited", ELICITED) == ELICITED


def test_the_elicited_mode_is_not_a_copy_the_caller_can_mutate():
    out = _coefficients_at("elicited", ELICITED)
    out["CG01"] = 99.0
    assert ELICITED["CG01"] == 0.5


def test_an_unknown_mode_refuses():
    with pytest.raises(ValueError, match="mode must be one of"):
        _coefficients_at("half", ELICITED)


def test_every_mode_runs_on_the_same_seed():
    """The modes must differ by correlation structure alone.

    A fresh seed per mode would put sampling noise into the gap, which is the entire
    measurement. At realistic iteration counts that noise can be the same order as the
    correlation effect, so the error would look like a result.
    """
    seen = []

    def fake(*, n_iter, risks, cg_coefficients, seed, **kw):
        seen.append((seed, dict(cg_coefficients)))
        return {"cost_dollars_array": np.zeros(n_iter)}

    run_bounding_triple(fake, risks=[], cg_coefficients=ELICITED, n_iter=10, seed=42)
    assert [s for s, _ in seen] == [42, 42, 42]
    assert [c for _, c in seen] == [
        {"CG01": 0.0, "CG02": 0.0}, ELICITED, {"CG01": 1.0, "CG02": 1.0}]


def test_the_triple_returns_one_curve_per_mode():
    def fake(*, n_iter, risks, cg_coefficients, seed, **kw):
        return {"cost_dollars_array": np.full(n_iter, sum(cg_coefficients.values()))}

    curves = run_bounding_triple(
        fake, risks=[], cg_coefficients=ELICITED, n_iter=5, seed=1)
    assert set(curves) == set(GN3A_MODES)
    assert curves["zero"][0] == 0.0
    assert curves["one"][0] == 2.0


def test_other_engine_arguments_are_forwarded_untouched():
    """The caller owns the engine's other arguments; this module must not eat them."""
    captured = {}

    def fake(*, n_iter, risks, cg_coefficients, seed, **kw):
        captured.update(kw)
        return {"cost_dollars_array": np.zeros(n_iter)}

    run_bounding_triple(
        fake, risks=[], cg_coefficients=ELICITED, n_iter=4, seed=7,
        dual_lookup={"a": 1}, chain_risk_ids={"b": 2})
    assert captured == {"dual_lookup": {"a": 1}, "chain_risk_ids": {"b": 2}}


# ---------------------------------------------------------------------------
# The bounding table
# ---------------------------------------------------------------------------

def _curves(zero_hi=10e6, elic_hi=12e6, one_hi=16e6):
    rng = np.random.default_rng(0)
    return {
        "zero": rng.uniform(0, zero_hi, 20_000),
        "elicited": rng.uniform(0, elic_hi, 20_000),
        "one": rng.uniform(0, one_hi, 20_000),
    }


def test_the_gap_is_full_minus_zero_at_each_confidence_level():
    rows = {r["Confidence level"]: r for r in build_bounding_table(_curves())}
    assert set(rows) == {"P50", "P80", "P90"}
    for row in rows.values():
        zero = float(row["Zero correlation ($M)"].replace(",", ""))
        one = float(row["Full correlation ($M)"].replace(",", ""))
        gap = float(row["Gap, zero to full ($M)"].replace(",", ""))
        assert gap == pytest.approx(one - zero, abs=0.002)


def test_the_gap_widens_with_confidence_level_when_correlation_fattens_the_tail():
    """The reason the guidance measures at the contingency level rather than the mean."""
    rows = {r["Confidence level"]: r for r in build_bounding_table(_curves())}
    gaps = [float(rows[f"P{p}"]["Gap, zero to full ($M)"].replace(",", ""))
            for p in (50, 80, 90)]
    assert gaps[0] < gaps[1] < gaps[2], gaps


def test_the_elicited_row_is_reported_not_just_the_bounds():
    """It is the model as run, and the basis of every other figure in the document."""
    for row in build_bounding_table(_curves()):
        assert "Elicited correlation ($M)" in row


# ---------------------------------------------------------------------------
# Leave-one-out variance share
# ---------------------------------------------------------------------------

def _grouped_arrays(n=8_000):
    """Two groups: CG01 carries most of the variance, CG02 little."""
    rng = np.random.default_rng(3)
    big = rng.normal(0, 5e6, (n, 1)) + rng.normal(0, 5e6, (n, 1))  # 2 correlated-ish
    per_risk = np.hstack([
        rng.normal(1e6, 4e6, (n, 1)), rng.normal(1e6, 4e6, (n, 1)),  # CG01
        rng.normal(1e6, 2e5, (n, 1)),                                # CG02
    ])
    del big
    ids = ["R1", "R2", "R3"]
    risks = [_risk("R1", "CG01"), _risk("R2", "CG01"), _risk("R3", "CG02")]
    return per_risk, ids, risks


def test_a_group_is_dropped_whole_not_risk_by_risk():
    """The group is the unit; dropping members singly misses what the group expresses.

    CG01 has two members of equal variance. Removed together they must account for
    materially more than either alone - a per-risk implementation summing two
    single-risk shares would land near half of this on a correlated portfolio.
    """
    per_risk, ids, risks = _grouped_arrays()
    rows = {r["Correlation group"]: r for r in
            build_cg_variance_shares(per_risk, ids, risks, ELICITED)}
    cg01 = float(rows["CG01"]["Share of portfolio variance"].rstrip("%"))
    total = per_risk.sum(axis=1)
    single = (np.var(total) - np.var(total - per_risk[:, 0])) / np.var(total) * 100
    assert cg01 > single * 1.5, (cg01, single)


def test_risk_counts_and_coefficients_come_through():
    per_risk, ids, risks = _grouped_arrays()
    rows = {r["Correlation group"]: r for r in
            build_cg_variance_shares(per_risk, ids, risks, ELICITED)}
    assert rows["CG01"]["Risk count"] == 2
    assert rows["CG02"]["Risk count"] == 1
    assert rows["CG01"]["Coefficient"] == "0.50"


def test_a_group_with_no_registered_coefficient_says_so():
    per_risk, ids, risks = _grouped_arrays()
    rows = {r["Correlation group"]: r for r in
            build_cg_variance_shares(per_risk, ids, risks, {"CG01": 0.5})}
    assert rows["CG02"]["Coefficient"] == "n/a"


def test_rows_are_ordered_by_share_so_the_driver_reads_first():
    per_risk, ids, risks = _grouped_arrays()
    rows = build_cg_variance_shares(per_risk, ids, risks, ELICITED)
    assert rows[0]["Correlation group"] == "CG01"


def test_a_negative_contribution_is_labelled_not_rounded_to_zero():
    """Removing a group can raise the variance; that is information, not noise.

    Rounding it to 0.0% would tell a reader the group contributes nothing, when what
    happened is that it offsets other risks.
    """
    n = 4_000
    rng = np.random.default_rng(5)
    a = rng.normal(0, 3e6, n)
    per_risk = np.stack([a, -a * 0.98], axis=1)   # second offsets the first
    rows = {r["Correlation group"]: r for r in build_cg_variance_shares(
        per_risk, ["R1", "R2"], [_risk("R1", "CG01"), _risk("R2", "CG02")], ELICITED)}
    assert rows["CG02"]["Share of portfolio variance"] == NO_MEASURABLE_SHARE


def test_ungrouped_risks_do_not_become_a_group():
    """A blank correlation group is an absence, not a group named empty-string."""
    per_risk, ids, risks = _grouped_arrays()
    risks = [_risk("R1", "CG01"), _risk("R2", ""), _risk("R3", None)]
    groups = {r["Correlation group"] for r in
              build_cg_variance_shares(per_risk, ids, risks, ELICITED)}
    assert groups == {"CG01"}


# ---------------------------------------------------------------------------
# The section
# ---------------------------------------------------------------------------

def test_the_section_carries_the_guidance_rule_and_the_scope_caveat():
    per_risk, ids, risks = _grouped_arrays()
    sec = build_correlation_sensitivity_section(
        _curves(), per_risk, ids, risks, ELICITED)["page_correlation_sensitivity"]
    assert sec["bounding_table"] and sec["variance_share_table"]
    assert "negligible" in sec["decision_rule"]
    assert "judgement for the project team" in sec["decision_rule"], (
        "the guidance's rule must not be replaced by a threshold this report invents")
    assert "firing draws" in sec["scope_note"], (
        "the page must say the bounding varies firing correlation, not every input")
    assert "need not sum to 100%" in sec["variance_share_note"]


def test_a_partial_triple_yields_no_bounding_table_rather_than_a_wrong_one():
    """Two curves cannot be bounded. Better absent than silently mislabelled."""
    per_risk, ids, risks = _grouped_arrays()
    partial = {"zero": np.zeros(10), "elicited": np.zeros(10)}
    sec = build_correlation_sensitivity_section(
        partial, per_risk, ids, risks, ELICITED)["page_correlation_sensitivity"]
    assert sec["bounding_table"] == []
    assert sec["variance_share_table"], "the share table is independent and should remain"


# ---------------------------------------------------------------------------
# The fidelity gate, against the real engine
# ---------------------------------------------------------------------------

def test_elicited_reproduces_run_demands_exact_bytes():
    a = np.array([1.0, 2.0, 3.0])
    assert elicited_reproduces_run({"elicited": a.copy()}, a)
    # One ULP is a mismatch. A tolerance here would admit exactly the argument drift
    # this gate exists to catch.
    b = a.copy(); b[1] = np.nextafter(b[1], np.inf)
    assert not elicited_reproduces_run({"elicited": b}, a)
    assert not elicited_reproduces_run({"elicited": np.array([1.0, 2.0])}, a)
    assert not elicited_reproduces_run({}, a)


@pytest.mark.slow
@pytest.mark.parametrize("project,prefix", [
    ("synthetic_wind", "WT"), ("synthetic_road", "KH")])
def test_the_elicited_counterfactual_reproduces_the_real_stage3_cost_arm(project, prefix):
    """The wiring guard for F-E, and the reason the bounding is trustworthy.

    The three modes must differ by their coefficients alone. If any other argument
    drifts - a different severity-uniform set, a rebuilt config, a re-read risk scope -
    the zero-to-full gap carries that drift and gets reported as a correlation effect.
    The only way to know is to run the elicited mode and compare it against the arm the
    run actually produced, byte for byte.
    """
    from src.am.project_binding import resolve_project_inputs
    from src.final.sections.correlation_sensitivity import run_stage3_bounding
    from src.integrated.integrated_simulation import run_integrated_simulation
    from src.integrated.integrated_simulation_stage3 import (
        run_integrated_simulation_stage3)
    from src.integrated.stage3_config import (
        build_stage3_config, build_stage3_rules_from_scope)
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.integrated.stage3_inputs import Stage3BindingConfig
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    inp = resolve_project_inputs(project)
    reg, xer, straw = inp.register_path, inp.xer_path, inp.strawman_path
    xt = parse_xer(str(xer))
    graph = build_schedule_graph(xt)
    scope = read_risk_scope(str(straw))
    drivers = expand_auto_rules(build_stage3_rules_from_scope(
        scope, graph, Stage3BindingConfig(
            register_path=reg, xer_path=xer, strawman_path=straw,
            float_threshold_hours=480.0)), graph)
    risks = read_risks_v5(str(reg))
    cfg = build_stage3_config(
        register_path=reg, xer_path=xer, strawman_path=straw,
        iterations=2_000, seed=42, caller_module="tests/test_report01_correlation_sensitivity.py")
    res = run_integrated_simulation_stage3(
        cfg, risks=risks, risk_scope_df=scope, schedule_graph=graph,
        risk_drivers=drivers, xer_tables=xt)

    curves = run_stage3_bounding(
        run_integrated_simulation,
        integrated_config=cfg.integrated_config, risks=risks, risk_scope_df=scope,
        severity_uniforms_by_risk_id=res.severity_uniforms_by_risk_id)

    assert elicited_reproduces_run(curves, res.cost_result["cost_dollars_array"]), (
        "the elicited counterfactual did not reproduce the run's own cost arm; an "
        "argument other than the coefficients has drifted")
    # And the bounding modes must actually differ, or the gate above is vacuous.
    assert curves["zero"].tobytes() != curves["one"].tobytes()


# ---------------------------------------------------------------------------
# The render side
# ---------------------------------------------------------------------------

def _doc_text(composed):
    from docx import Document

    from src.final.word_generator import _add_correlation_sensitivity_section

    doc = Document()
    _add_correlation_sensitivity_section(doc, composed)
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    return "\n".join([p.text for p in doc.paragraphs] + cells)


def test_both_tables_and_both_notes_reach_the_document():
    per_risk, ids, risks = _grouped_arrays()
    sec = build_correlation_sensitivity_section(
        _curves(), per_risk, ids, risks, ELICITED)["page_correlation_sensitivity"]
    text = _doc_text({"page_correlation_sensitivity": sec})
    assert "What correlation contributes" in text
    assert "GN3A section 4.1" in text
    assert "negligible" in text
    assert "firing draws" in text
    assert "Share of portfolio variance by correlation group" in text
    assert "CG01" in text


def test_a_withheld_bounding_says_why_instead_of_printing_a_table():
    """The elicited row must match the headline or the table does not appear.

    Withheld and visible, not withheld and silent: a reader who sees no correlation
    section cannot tell it was suppressed from it never having been built.
    """
    from src.final.sections.correlation_sensitivity import ELICITED_MISMATCH

    per_risk, ids, risks = _grouped_arrays()
    sec = build_correlation_sensitivity_section(
        None, per_risk, ids, risks, ELICITED)["page_correlation_sensitivity"]
    sec["withheld_reason"] = ELICITED_MISMATCH
    text = _doc_text({"page_correlation_sensitivity": sec})
    assert "did not reproduce" in text
    assert "Zero correlation" not in text, "a withheld bounding must not print its table"
    # The variance shares are independent of the bounding and still appear.
    assert "Share of portfolio variance by correlation group" in text


def test_an_executive_summary_without_the_key_renders_nothing():
    assert _doc_text({}).strip() == ""


def test_the_renderer_is_actually_called_by_the_document_builder():
    import inspect

    from src.final.word_generator import _render_v3_executive_summary

    assert "_add_correlation_sensitivity_section(doc, composed)" in inspect.getsource(
        _render_v3_executive_summary)


# ---------------------------------------------------------------------------
# Numerics review BLOCKER 1, 12/09/2026: a group the mapping does not name
# ---------------------------------------------------------------------------

def test_the_bounds_cover_every_group_the_risks_carry_not_just_the_mapped_ones():
    """The failure the byte-exact fidelity gate is blind to.

    `build_risk_uniform_matrix` reads `corr_coefficients.get(group, 0.5)`, so a group a
    risk carries but the register's mapping does not name runs at 0.5. Build the bounds
    from the mapping's keys alone and that group sits at 0.5 in ALL THREE modes: zero is
    not zero, one is not one, and the gap the GN3A rule is applied to is understated.

    `elicited_reproduces_run` cannot catch it - the elicited replay stays faithful while
    both bounds are wrong - so this is the only thing standing between that defect and a
    client-facing number.
    """
    risks = [_risk("R1", "CG01"), _risk("R2", "CG_UNASSIGNED")]
    groups = risk_correlation_groups(risks)
    assert groups == {"CG01", "CG_UNASSIGNED"}
    assert _coefficients_at("zero", ELICITED, groups)["CG_UNASSIGNED"] == 0.0
    assert _coefficients_at("one", ELICITED, groups)["CG_UNASSIGNED"] == 1.0


def test_the_elicited_mode_stays_the_mapping_as_the_register_states_it():
    """It is the model as run. Adding keys would stop it reproducing the run."""
    groups = {"CG01", "CG02", "CG_UNASSIGNED"}
    assert _coefficients_at("elicited", ELICITED, groups) == ELICITED


def test_the_triple_derives_its_group_set_from_the_risks():
    seen = []

    def fake(*, n_iter, risks, cg_coefficients, seed, **kw):
        seen.append(dict(cg_coefficients))
        return {"cost_dollars_array": np.zeros(n_iter)}

    run_bounding_triple(
        fake, risks=[_risk("R1", "CG01"), _risk("R2", "CG99")],
        cg_coefficients=ELICITED, n_iter=10, seed=42)
    assert seen[0] == {"CG01": 0.0, "CG02": 0.0, "CG99": 0.0}, seen[0]
    assert seen[2] == {"CG01": 1.0, "CG02": 1.0, "CG99": 1.0}, seen[2]


def test_an_uncovered_group_is_reported_not_silently_absorbed():
    """Bounding it correctly is not the whole answer.

    Those groups ran at a default rather than an elicited value in the model the rest of
    the document reports, and the reader is entitled to know which.
    """
    risks = [_risk("R1", "CG01"), _risk("R2", "CG_UNASSIGNED")]
    assert uncovered_groups(risks, ELICITED) == ["CG_UNASSIGNED"]
    assert uncovered_groups([_risk("R1", "CG01")], ELICITED) == []

    per_risk, ids, grouped = _grouped_arrays()
    sec = build_correlation_sensitivity_section(
        _curves(), per_risk, ids, risks, ELICITED)["page_correlation_sensitivity"]
    assert sec["uncovered_groups"] == ["CG_UNASSIGNED"]
    assert "CG_UNASSIGNED" in sec["uncovered_groups_note"]
    assert "0.50" in sec["uncovered_groups_note"]


def test_a_fully_covered_register_carries_no_uncovered_note():
    per_risk, ids, risks = _grouped_arrays()
    sec = build_correlation_sensitivity_section(
        _curves(), per_risk, ids, risks, {"CG01": 0.5, "CG02": 0.3},
    )["page_correlation_sensitivity"]
    assert sec["uncovered_groups"] == []
    assert sec["uncovered_groups_note"] == ""


def test_the_uncovered_groups_note_reaches_the_document():
    """Built and not rendered is not delivered - the F-G lesson, applied here."""
    per_risk, ids, _ = _grouped_arrays()
    risks = [_risk("R1", "CG01"), _risk("R2", "CG_UNASSIGNED")]
    sec = build_correlation_sensitivity_section(
        _curves(), per_risk, ids, risks, ELICITED)["page_correlation_sensitivity"]
    text = _doc_text({"page_correlation_sensitivity": sec})
    assert "CG_UNASSIGNED" in text
    assert "0.50" in text


def test_the_production_bounding_path_passes_the_union_not_just_the_mapping():
    """Numerics re-review WARN, 12/09/2026: the production path had no test.

    `run_stage3_bounding` is the only entry point the deliverable calls
    (`deliverable.py`). The union tests above pin `_coefficients_at` and
    `run_bounding_triple`, and `run_bounding_triple` has NO production caller - so a
    regression dropping `all_groups` from `run_stage3_bounding` would re-introduce the
    exact fixed BLOCKER and pass the entire suite. The byte-exact fidelity gate cannot
    see it either: the elicited replay stays faithful and `zero != one` still holds via
    the mapped groups.
    """
    import dataclasses

    seen = []

    @dataclasses.dataclass(frozen=True)
    class _Defaults:
        cg_coefficients: dict

    @dataclasses.dataclass(frozen=True)
    class _Config:
        methodology_defaults: _Defaults

    def fake(*, config, risks, risk_scope_df, precomputed_severity_uniforms):
        seen.append(dict(config.methodology_defaults.cg_coefficients))
        return {"cost_dollars_array": np.zeros(4)}

    run_stage3_bounding(
        fake,
        integrated_config=_Config(_Defaults({"CG01": 0.5})),
        risks=[_risk("R1", "CG01"), _risk("R2", "CG_UNASSIGNED")],
        risk_scope_df=None,
        severity_uniforms_by_risk_id=None,
    )
    assert seen[0] == {"CG01": 0.0, "CG_UNASSIGNED": 0.0}, f"zero mode: {seen[0]}"
    assert seen[1] == {"CG01": 0.5}, f"elicited must stay the register's own: {seen[1]}"
    assert seen[2] == {"CG01": 1.0, "CG_UNASSIGNED": 1.0}, f"one mode: {seen[2]}"


def test_a_whitespace_padded_group_is_keyed_as_the_engine_keys_it():
    """The engine looks up the raw attribute; trimming here would hide an uncovered group."""
    assert risk_correlation_groups([_risk("R1", " CG01 ")]) == {" CG01 "}
    assert risk_correlation_groups([_risk("R1", "   "), _risk("R2", "")]) == set()
    assert uncovered_groups([_risk("R1", " CG01 ")], {"CG01": 0.5}) == [" CG01 "]
