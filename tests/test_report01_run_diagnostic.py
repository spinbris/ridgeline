"""REPORT01 F-G: the per-run one-page diagnostic.

GAP01 F-G called this absent. It was not absent - `scripts/sr9_diagnostic.py` wrote one,
in this format. It was **unreachable and stale**: no caller, a cache path that had
diverged from the deliverable's, artefact names belonging to retired standalone drivers,
and no Stage 3 awareness, so it printed the superseded Stage 2.5 headline.

So the tests that matter are not "does it produce text". They are: does it print the
headline the product actually reports, does it survive a failed gate, and is it listed
in its own manifest.

**DIAGFIX-01 (14/09/2026): the fixtures below are in the shapes a real run produces.**
REPORT01's first fixtures were hand-built in the shapes their author expected -
``random_seed``, ``{"sha256": ...}``, a ``checks`` key, a one-column schedule table - and the
deliverable hands the formatter none of those, so five lines were wrong on the page while
every test here passed. The key names now follow ``cross_validate_reports``, the provenance
``run_deliverable`` builds and the two driver tables. A real run is compared with the page in
``tests/test_3c_a_deliverable.py``'s §6a outputs test, which is where a future rename reds.
"""
from __future__ import annotations

import json

import pytest

from src.final.run_diagnostic import (
    FAIL_BANNER,
    PASS_BANNER,
    format_run_diagnostic,
)

STAGE3 = {
    "p_level": 80,
    "p_levels": (50, 80, 95),
    "p50_dollars": 8_000_000.0,
    "p80_dollars": 10_503_686.0,
    "p95_dollars": 13_250_000.0,
    "mean_dollars": 9_100_000.0,
    "headline_dollars": 10_503_686.0,
    "basis": "Stage 3 CPM replay: one distribution, percentiles of one modelled outcome.",
}

# The Stage 2.5 comparator. Present in every composed dict, and what the unwired
# predecessor of this module printed.
STAGE25 = {"lower": 1.0, "upper": 2.0, "point": 10_210_859.0}


def _composed(headline=STAGE3):
    es = {"headline_contingency_range_p80": STAGE25}
    if headline is not None:
        es["headline_stage3"] = headline
    else:
        es["headline_stage3_absent_reason"] = "the Stage 3 arm did not run"
    return {
        "executive_summary": es,
        "page3_cost_drivers": {"drivers_table": [
            {"Risk": "WT-002", "Title": "Turbine delivery slip",
             "P80 contribution ($M)": 2.4, "% of total": "31.0%",
             "Basis of estimate": "Not recorded"},
            {"Risk": "WT-009", "Title": "Grid connection delay",
             "P80 contribution ($M)": 1.1, "% of total": "14.2%",
             "Basis of estimate": "Not recorded"},
        ]},
        # Columns in the order schedule_drivers.py builds them. The table is ranked by
        # "Probability x mean impact (days)"; "Probability" comes first, which is F-4.
        "page4_schedule_drivers": {"drivers_table": [
            {"Risk": "WT-001", "Title": "Weather standby", "Probability": "45.0%",
             "Mean impact when fired (days)": 27.43, "Probability x mean impact (days)": 12.344,
             "Mode": "Series", "% of additive draws (comparator)": "38.1%",
             "Basis of estimate": "Not recorded"},
        ]},
        "appendix_audit_trail": {"engine_versions": {}},
    }


def _provenance(**over):
    p = {
        "project": "synthetic_wind",
        "run_date": "2026-09-12",
        "timestamp": "2026-09-12T15:00:00+00:00",
        "run_token": "tok-abc123",
        "engine_sha": "f52bd29",
        "engine_tree_dirty": False,
        "params": {"iterations": 100_000, "seed": 4242},
        "input_sha256": {
            "register": {"method": "git_blob_oid", "value": "c7de22c1adb99712e884"},
            "xer": {"method": "sha256_bytes", "value": "5cbed8f12994c6f82b1c"},
        },
        "cross_validation_all_pass": True,
        "stage3_standalone_error": None,
        "artefacts": ["outputs/executive_summary_2026-09-12.docx"],
    }
    p.update(over)
    return p


def _cross_validation(passed=True, **over):
    """The four flat keys ``cross_validate_reports`` ANDs into ``all_pass``. A failing gate
    fails on check 4 unless told otherwise."""
    cv = {
        "all_pass": passed,
        "cost_passes_calibration": True,
        "schedule_passes_calibration": True,
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": passed,
        "schedule_check_basis": "stage3_cross_surface",
    }
    cv.update(over)
    return cv


def _render(passed=True, composed=None, cross_validation=None, **prov):
    prov.setdefault("cross_validation_all_pass", passed)
    return format_run_diagnostic(
        composed=composed or _composed(),
        cross_validation=cross_validation or _cross_validation(passed),
        provenance=_provenance(**prov),
    )


def test_it_prints_the_stage_3_headline_not_the_stage_2_5_comparator():
    """The defect that made the predecessor dangerous rather than merely unwired.

    Both figures live in the same composed dict. The old script reached for
    ``headline_contingency_range_p80``, which since STAGE3HEADLINE-01 is a labelled
    comparator and never the headline.
    """
    text = _render()
    assert "10.504M" in text, "the Stage 3 headline is not on the page"
    assert "10.211M" not in text, (
        "the Stage 2.5 comparator reached the one-pager - this is the exact defect "
        "F-G exists to fix")


def test_every_reported_percentile_and_the_basis_appear():
    text = _render()
    for fragment in ("P50:", "P80:", "P95:", "8.000M", "13.250M", "Mean:", "9.100M"):
        assert fragment in text, fragment
    assert "Stage 3 CPM replay" in text


def test_a_missing_stage_3_headline_says_so_with_its_reason():
    """Absent and named, never silently replaced by the comparator."""
    text = _render(composed=_composed(headline=None))
    assert "NOT PRESENT" in text
    assert "the Stage 3 arm did not run" in text
    assert "10.211M" not in text


def test_a_failed_gate_banners_the_top_and_the_bottom():
    """D-11 writes this file on a failure, so it must announce one unmissably."""
    text = _render(passed=False)
    assert text.split("\n")[3] == FAIL_BANNER, "the banner is not in the first lines"
    assert text.rstrip().endswith("=" * 78)
    assert text.count(FAIL_BANNER) == 2, "banner top and bottom"
    assert PASS_BANNER not in text


def test_a_passing_run_does_not_carry_the_failure_banner():
    text = _render(passed=True)
    assert PASS_BANNER in text
    assert FAIL_BANNER not in text


def test_a_dirty_engine_tree_is_called_out_as_not_reproducible():
    """A number from a dirty tree cannot be reproduced, and the page must not imply it can."""
    assert "DIRTY - not a reproducible run" in _render(engine_tree_dirty=True)
    assert "clean" in _render(engine_tree_dirty=False)


def test_provenance_seed_iterations_and_digests_reach_the_page():
    text = _render()
    for fragment in ("f52bd29", "100000", "4242", "c7de22c1adb99712e884", "5cbed8f12994c6f82b1c",
                     "tok-abc123"):
        assert fragment in text, fragment


def test_top_drivers_from_both_arms_appear():
    text = _render()
    assert "WT-002" in text and "Turbine delivery slip" in text
    assert "WT-001" in text and "Weather standby" in text


def test_it_is_plain_text_with_no_stray_carriage_returns():
    """Greppable and diffable on any machine - the reason the format is what it is."""
    text = _render()
    assert "\r" not in text
    assert text.endswith("\n")


# ---------------------------------------------------------------------------
# P-7: listed in its own manifest
# ---------------------------------------------------------------------------

def test_the_diagnostic_is_listed_in_the_manifest_it_sits_beside(tmp_path):
    """The manifest is absent from its own artefact list for want of this ordering.

    The diagnostic must be appended to provenance["artefacts"] before the manifest is
    serialised, or it becomes a file on disk that the run's own record does not know
    about - which is how an artefact goes missing without anyone noticing.
    """
    from src.final import deliverable as d

    import inspect
    src = inspect.getsource(d.run_deliverable)
    order = [
        src.index("artefacts.append(diagnostic)"),
        src.index('provenance["artefacts"] = [str(a) for a in artefacts]'),
        src.index("diagnostic.write_text("),
        src.index("manifest.write_text("),
    ]
    assert order == sorted(order), (
        "the diagnostic must be appended and the artefact list refreshed before the "
        f"manifest is written; got offsets {order}")


def test_the_manifest_and_the_diagnostic_agree_on_the_artefact_list():
    """One source, not two. Both are rendered from the same provenance dict."""
    prov = _provenance(artefacts=["a.docx", "b.html", "run_diagnostic_2026-09-12.txt"])
    text = format_run_diagnostic(
        composed=_composed(), cross_validation=_cross_validation(True), provenance=prov)
    for artefact in json.loads(json.dumps(prov))["artefacts"]:
        assert artefact in text, artefact


#: Stage 2.5 Mode vocabulary. Carried over from the retired
#: ``test_sr9_v32_d1_mode_flag.py``, whose prod-diagnostic guard is the one property in
#: that file worth outliving the script it tested. It matters more now, not less: the
#: headline is Stage 3 with Mode multipliers off, and `Dummy_Realistic` is a Stage 2.5
#: scenario the Director confirmed is no longer used (DUMMYSCOPE-01).
FORBIDDEN_IN_A_CLIENT_ADJACENT_PAGE = [
    "Dummy Realistic", "Dummy_Realistic", "S" + "JP indicative",
    "indicative classification", "Mode classification", "PM review",
]


def test_no_stage_2_5_mode_vocabulary_reaches_the_page():
    text = _render()
    found = [p for p in FORBIDDEN_IN_A_CLIENT_ADJACENT_PAGE if p in text]
    assert not found, f"the run diagnostic carries retired Mode vocabulary: {found}"


def test_the_guard_would_catch_the_vocabulary_if_it_appeared():
    """The forbidden list is only evidence if a violation would be seen.

    The predecessor's version of this guard ran against a fixture pickle that happened
    not to contain the phrases; a guard that cannot fire is the shape this repository
    keeps finding.
    """
    composed = _composed()
    composed["executive_summary"]["headline_stage3"] = dict(
        STAGE3, basis="Dummy Realistic basis, pending PM review")
    text = format_run_diagnostic(
        composed=composed, cross_validation=_cross_validation(True),
        provenance=_provenance())
    found = [p for p in FORBIDDEN_IN_A_CLIENT_ADJACENT_PAGE if p in text]
    assert found, "the guard cannot see the vocabulary it exists to catch"


# ---------------------------------------------------------------------------
# DIAGFIX-01: the five lines that were wrong on a real run
# ---------------------------------------------------------------------------

def _line(text: str, start: str) -> str:
    hits = [ln for ln in text.splitlines() if ln.strip().startswith(start)]
    assert len(hits) == 1, f"expected one line starting {start!r}, got {hits}"
    return hits[0]


def test_the_gate_names_the_four_checks_the_verdict_is_made_of():
    """F-1: the page printed only "Overall", because it read a ``checks`` key that
    ``cross_validate_reports`` does not return."""
    text = _render(passed=True)
    for name in ("1 cost calibration", "2 schedule", "3 top-3 cost drivers", "4 top-3 schedule drivers"):
        assert "PASS" in _line(text, f"PASS  {name}"), name


def test_a_failing_check_is_named_fail():
    text = _render(passed=False)
    assert _line(text, "FAIL  4 top-3 schedule drivers")
    assert _line(text, "PASS  1 cost calibration")


def test_check_2_says_which_basis_it_ran_on():
    cross_surface = _render(cross_validation=_cross_validation(True))
    legacy = _render(cross_validation=_cross_validation(True, schedule_check_basis="stage25_sr5_legacy"))
    assert "Stage 3 cross-surface" in _line(cross_surface, "PASS  2 schedule")
    assert "Stage 2.5" in _line(legacy, "PASS  2 schedule")


def test_a_check_missing_from_the_result_is_said_to_be_missing():
    cv = _cross_validation(True)
    del cv["top_3_cost_contributors_consistent"]
    text = _render(cross_validation=cv)
    assert "not in the cross-validation result" in _line(text, "?")


def test_a_failed_verdict_with_no_listed_check_failing_says_so():
    """P-1: a fifth check added to all_pass must not leave a FAIL page listing four PASSes."""
    cv = _cross_validation(True, all_pass=False)
    text = _render(cross_validation=cv, cross_validation_all_pass=False)
    assert FAIL_BANNER in text
    assert "FAIL outside the checks listed here" in text


def test_a_stage3_emit_failure_banners_the_page_and_names_the_error():
    """F-5: the exit gate fails this run; the page used to read the cross-validation dict
    alone and print PASS."""
    text = _render(passed=True, cross_validation_all_pass=False,
                   stage3_standalone_error="RuntimeError: the Stage 3 emitter refused")
    assert text.count(FAIL_BANNER) == 2
    assert PASS_BANNER not in text
    assert "RuntimeError: the Stage 3 emitter refused" in _line(text, "FAIL  Stage 3 standalone")
    assert "FAIL outside the checks listed here" not in text, "the failure is named, not unexplained"


def test_a_provenance_without_the_run_verdict_falls_back_and_says_so():
    prov = _provenance()
    del prov["cross_validation_all_pass"]
    del prov["stage3_standalone_error"]
    text = format_run_diagnostic(
        composed=_composed(), cross_validation=_cross_validation(True), provenance=prov)
    assert PASS_BANNER in text
    assert "read from the cross-validation result" in text


def test_the_seed_is_the_provenance_seed():
    """F-2: it read ``random_seed`` and printed ``?``."""
    assert _line(_render(), "Seed:").split() == ["Seed:", "4242"]


def test_each_digest_prints_its_value_and_method_never_a_raw_dict():
    """F-3: digests are ``{method, value}`` and printed as Python dict reprs."""
    text = _render()
    assert _line(text, "register:").split() == ["register:", "c7de22c1adb99712e884", "(git_blob_oid)"]
    assert _line(text, "xer:").split() == ["xer:", "5cbed8f12994c6f82b1c", "(sha256_bytes)"]
    assert "{" not in text.split("PROVENANCE")[1].split("ARTEFACTS")[0]


def test_an_unrecognised_digest_shape_is_not_guessed():
    text = _render(input_sha256={"register": "c7de22c1", "xer": {"sha256": "5cbed8f1"}})
    assert "unrecognised" in _line(text, "register:")
    assert "unrecognised" in _line(text, "xer:")
    assert "c7de22c1" not in text and "5cbed8f1" not in text


def test_the_schedule_driver_value_is_the_measure_the_table_is_ranked_by():
    """F-4: the value was the first non-text column, which is Probability."""
    text = _render()
    assert "Probability x mean impact (days)" in text
    assert _line(text, "WT-001").split()[-1] == "12.344"
    assert "45.0%" not in text


def test_the_cost_driver_value_follows_its_document():
    composed = _composed()
    for row in composed["page3_cost_drivers"]["drivers_table"]:
        row["Mean contribution ($M)"] = row.pop("P80 contribution ($M)")
    text = _render(composed=composed)
    assert "Mean contribution ($M)" in text
    assert _line(text, "WT-002").split()[-1] == "2.4"


def test_the_cost_line_reads_the_column_its_own_section_names():
    """Panel WARN: the section names its value column; a hand-kept list of spellings is the
    fallback, not the source."""
    composed = _composed()
    composed["page3_cost_drivers"]["value_column_header"] = "P90 contribution ($M)"
    for row in composed["page3_cost_drivers"]["drivers_table"]:
        row["P90 contribution ($M)"] = row.pop("P80 contribution ($M)")
    text = _render(composed=composed)
    assert "Cost, by P90 contribution ($M):" in text
    assert _line(text, "WT-002").split()[-1] == "2.4"


def test_the_schedule_ranking_column_is_the_one_the_builder_writes():
    """The schedule section carries no header of its own, so the diagnostic's spelling is held
    against the builder's source here, in the stage lane, not only by the slow real-run test."""
    import ast
    from pathlib import Path

    from src.final.run_diagnostic import RANKING_COLUMNS

    root = Path(__file__).resolve().parents[1] / "src" / "final" / "sections"
    def literals(name):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert set(RANKING_COLUMNS["page4_schedule_drivers"]) <= literals("schedule_drivers.py")
    cost = literals("cost_drivers.py")
    assert " contribution ($M)" in cost and {"P80", "Mean"} <= cost
    assert set(RANKING_COLUMNS["page3_cost_drivers"]) == {f"{m} contribution ($M)" for m in ("P80", "Mean")}


def test_a_drivers_table_without_its_ranking_column_says_so():
    composed = _composed()
    for row in composed["page4_schedule_drivers"]["drivers_table"]:
        del row["Probability x mean impact (days)"]
    text = _render(composed=composed)
    assert "ranking column" in text
    assert "45.0%" not in text
