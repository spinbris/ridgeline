"""DELIVFIX-01 / FW-17 (= STAGE4-F37) and FW-22: the calibration gap is stated in one set of units.

``cost_relative_gap_pct`` holds a FRACTION (0.0023655), whatever its name. The audit sentence printed
it with a literal ``%`` - "0.002%" - while the cross-validation table multiplied by 100 - "0.237%":
one report, one quantity, a factor of one hundred apart. That sentence reaches the HTML audit trail
and both Word documents (``word_generator.py`` reads the same composed value), so this one builder is
the fix for all three. It also printed the dollar gap as "$11.9k" beside an "$11.32M" headline, and a
careful reader took one for the other (FW-22).

The class guard at the bottom is the sibling search this defect called for, made permanent: ten
renderers converted the fraction and one did not, and nothing noticed for fourteen days.
"""
import json
import re
from pathlib import Path

from src.final.sections.audit_trail import build_cross_validation_sentence

REPO = Path(__file__).resolve().parents[1]

#: The Kestrel run's own values (leg 1, 21/09/2026, cv_result in metadata.json).
KESTREL_CV = {
    "all_pass": True,
    "cost_absolute_gap_dollars": 11871.600038591772,
    "cost_relative_gap_pct": 0.0023654958885118036,
    "schedule_absolute_gap_days": 0.0,
    "top_3_cost_contributors_integrated": ["KH-011", "KH-004", "KH-022"],
    "top_3_schedule_contributors_integrated": ["KH-011", "KH-004", "KH-002"],
    "n_iter_used_for_scaling": 100000,
}


def test_the_relative_gap_is_a_percentage_equal_to_the_tables():
    sentence = build_cross_validation_sentence(KESTREL_CV)
    tables = f"{KESTREL_CV['cost_relative_gap_pct'] * 100:.3f}%"   # how the table renders it
    assert tables == "0.237%"
    assert tables in sentence, f"the audit sentence must state the gap as {tables}: {sentence!r}"
    assert "0.002%" not in sentence, f"the fraction is printed as a percentage: {sentence!r}"


def test_the_dollar_gap_is_whole_dollars_not_thousands():
    sentence = build_cross_validation_sentence(KESTREL_CV)
    assert "$11,872" in sentence, f"the gap must be stated in whole dollars: {sentence!r}"
    assert "11.9k" not in sentence, (
        f"a $11.9k gap reads as $11.9M beside an $11.32M headline (FW-22): {sentence!r}")


def test_the_notebook_table_states_the_gap_in_whole_dollars():
    """FW-22's second site: the notebook's own cross-validation table."""
    nb = json.loads((REPO / "final_runner.ipynb").read_text(encoding="utf-8"))
    source = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert "/1e3:.1f}k" not in source, "the notebook's table still prints the gap in thousands"


#: A ``*_pct`` value printed with a literal percent sign and no conversion: ``_pct`` followed DIRECTLY
#: by the format spec (a closing ``']`` allowed, for dict access). The first draft used
#: ``_pct[^}]*:``, which also matched the CORRECT ``{cost_pct*100:.3f}%`` - the ``[^}]*`` let ``*100``
#: through - so it flagged two right renderers. Tested against both before trusting it.
_UNCONVERTED = re.compile(r"_pct['\"\]]*\s*:\.\d+f\}%")


def unconverted_pct_renderings(roots=("src/final", "src/integrated")) -> list[str]:
    hits = []
    for root in roots:
        for path in sorted((REPO / root).rglob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _UNCONVERTED.search(line):
                    hits.append(f"{path.relative_to(REPO).as_posix()}:{n}: {line.strip()}")
    return hits


def test_no_pct_fraction_is_printed_without_conversion():
    """The class, not the instance: no renderer may print a ``*_pct`` fraction with a bare ``%``."""
    hits = unconverted_pct_renderings()
    assert not hits, ("a *_pct value (a FRACTION in this codebase) is printed with a literal %, "
                      "100x too small:\n  " + "\n  ".join(hits))


def test_red_the_class_guard_sees_the_original_defect():
    assert _UNCONVERTED.search('f"/ {cost_gap_pct:.3f}%; "')          # audit_trail.py:65, as it was
    assert not _UNCONVERTED.search('f"/ {cost_gap_pct:.3%}; "')       # the fix
    assert not _UNCONVERTED.search('f"{cost_pct*100:.3f}% relative"')  # integrated_analysis.py:73
    assert _UNCONVERTED.search("f\"{cv['cost_relative_gap_pct']:.3f}%\"")   # dict access, defective
    assert not _UNCONVERTED.search("f\"({cv['cost_relative_gap_pct']*100:.3f}%)\"")  # notebook:112
