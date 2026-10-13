"""SRA-02 S-E P-E3 - Excel and Python agree on the deterministic cross-check.

The committed fixture is a scaffolded register carrying six synthetic risks, five of
them Time=Yes, recalculated once in Excel so its ``Summary`` cells hold cached
values. Rebuild it with ``scripts/sra02_se_build_test_workbook.py``; this gate needs
no Excel, which is why the artefact is committed rather than produced at test time.

**What this file guards against, beyond the arithmetic.** The cheapest way for a
reconciliation test to pass is for both sides to be empty - the reader returns None
for an unrecalculated formula (S-A contract 1.5), and ``None == None``. That is
FALSE-GREEN-01's shape and A10.2's F-B in one. So the comparison is preceded by two
guards that assert there is something to compare: the Excel side must carry four
numbers, and the Python side must see a non-zero number of Time=Yes rows. Both are
the S-C2 lesson - print the row count before trusting either outcome.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.sra.schedule_cross_check import (
    COMPARATOR_KEYS,
    compute_schedule_comparators,
    read_register_day_rate,
    read_register_mode_multipliers,
)
from src.sra.strawman_reader import get_strawman_calibration_target, read_risk_scope
from tools.register_scaffold import DAY_RATE_NAME

# RS-B step 2: this module reads the reference project's register shape, RBS map
# or chain identifiers, so it selects that binding explicitly rather than
# inheriting the suite default. Visible here, greppable, and departing from a
# default that tests/test_project_selection.py pins.
pytestmark = pytest.mark.project("fixture_r_prefix")   # REFRETIRE-01: the fixtures here carry R-prefixed risk IDs

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "sra02_se" / "se_cross_check_register.xlsx"

#: Pinned so the fixture cannot drift underneath the gate unnoticed - NOOPCHECK-01
#: shape 9 is an unenforced provenance field, so this one is enforced. A legitimate
#: rebuild updates this constant in the same commit as the workbook.
FIXTURE_SHA256 = "85b76dfbc6674ad9a12ec3585979a3a98d6804c263d853df0a09fd985d2e988e"

#: The cross-runtime tolerance (QRAXL-01 step 6b). Excel and numpy may sum in a
#: different order; nothing else may differ.
RTOL = 1e-12

#: Time=Yes rows the fixture is built with. Asserted, not assumed - a reader change
#: that silently returned nothing would otherwise make every comparison vacuous.
EXPECTED_TIME_YES_ROWS = 5


@pytest.fixture(scope="module")
def excel_side() -> dict:
    return get_strawman_calibration_target(FIXTURE)


@pytest.fixture(scope="module")
def python_side() -> dict:
    scope = read_risk_scope(str(FIXTURE))
    return compute_schedule_comparators(
        scope,
        read_register_mode_multipliers(FIXTURE),
        read_register_day_rate(FIXTURE),
    )


# ---------------------------------------------------------------------------
# 1. The fixture is the artefact this gate was captured against
# ---------------------------------------------------------------------------

def test_fixture_hash_is_the_one_the_gate_was_captured_against():
    assert FIXTURE.exists(), f"fixture missing: {FIXTURE}"
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert digest == FIXTURE_SHA256, (
        "the committed fixture is not the workbook this gate was pinned to.\n"
        f"  expected {FIXTURE_SHA256}\n  got      {digest}\n"
        "Rebuild with scripts/sra02_se_build_test_workbook.py and update "
        "FIXTURE_SHA256 in the same commit."
    )


def test_fixture_carries_no_identity_metadata():
    """Excel stamps the signed-in user into ``cp:lastModifiedBy`` on every save, and
    this fixture goes through a recalc. Committing it with a name in it, and pinning
    its sha256 in the test above, would make that name a recorded identity - which is
    GOLDINPUT-USERNAME-01's class and the reason that row is still open.

    Two limbs, because the docProps field list turned out to be narrower than the
    class it is named for (C-1):

    * the docProps fields the strip writes must read back neutral, and
    * **no zip member** may carry an ``absPath`` attribute, a user-profile path or
      the current login name - Excel writes the build directory into
      ``xl/workbook.xml``, which on Windows names the account.

    Both limbs assert absence rather than naming anything, so the test itself carries
    no identity literal; the login name is resolved at run time inside
    :func:`identity_offenders`. The strip lives in the build script
    (`strip_identity_metadata`, a zip-member rewrite - an openpyxl round-trip would
    destroy the cached values this gate depends on).
    """
    from scripts.sra02_se_build_test_workbook import (
        NEUTRAL,
        identity_metadata,
        identity_offenders,
    )

    populated = {k: v for k, v in identity_metadata(FIXTURE).items() if v != NEUTRAL}
    assert not populated, (
        f"identity-bearing docProps fields are populated: {sorted(populated)}. "
        "Re-run scripts/sra02_se_build_test_workbook.py, which strips them."
    )

    offenders = identity_offenders(FIXTURE)
    assert not offenders, (
        "zip members name the machine or the person who built the workbook: "
        f"{ {m: sorted(rules) for m, rules in sorted(offenders.items())} }. "
        "Re-run scripts/sra02_se_build_test_workbook.py, which strips them."
    )


def test_day_rate_range_name_matches_the_scaffolders():
    """``src/`` keeps its own literal rather than importing ``tools/``; this is
    where the two are tied together."""
    from src.sra.schedule_cross_check import _DAY_RATE_NAME

    assert _DAY_RATE_NAME == DAY_RATE_NAME


# ---------------------------------------------------------------------------
# 2. Both sides have something to say - the anti-vacuous guards
# ---------------------------------------------------------------------------

def test_excel_side_carries_cached_values_not_nil(excel_side):
    """If the fixture were saved without a recalc, all four would be None and the
    comparison below would compare nothing to nothing and pass."""
    missing = [k for k in COMPARATOR_KEYS if excel_side.get(k) is None]
    assert not missing, (
        f"{missing} read as None - the fixture carries formulas with no cached "
        "values, so this gate would pass vacuously. Re-run the build script."
    )
    assert excel_side["source_summary_cells"], "reader matched no Summary labels"


def test_python_side_sees_the_expected_time_yes_rows():
    scope = read_risk_scope(str(FIXTURE))
    n_yes = int((scope["time_impact"] == "Yes").sum())
    assert n_yes == EXPECTED_TIME_YES_ROWS, (
        f"read {n_yes} Time=Yes rows, expected {EXPECTED_TIME_YES_ROWS}. An empty "
        "or short frame makes every assertion in this file vacuous."
    )


def test_both_comparators_are_non_zero_and_distinct(python_side):
    """The fixture is built with a Parallel row and a Time=No row precisely so the
    two comparators differ. Equal comparators would mean the Mode weighting was not
    exercised at all."""
    c1 = python_side["comparator_1_emv_days_pert"]
    c2 = python_side["comparator_2_finish_delay_days_pert"]
    assert c1 > 0 and c2 > 0
    assert c1 != c2, "Comparator 1 == Comparator 2: the Mode weighting did nothing"


# ---------------------------------------------------------------------------
# 3. The reconciliation itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", COMPARATOR_KEYS)
def test_excel_and_python_agree(key, excel_side, python_side):
    assert python_side[key] == pytest.approx(excel_side[key], rel=RTOL), (
        f"{key}: Excel {excel_side[key]!r} vs Python {python_side[key]!r}"
    )


# ---------------------------------------------------------------------------
# 4. Positive control - the comparison can fail
# ---------------------------------------------------------------------------

def test_a_python_only_perturbation_reds_the_reconciliation(excel_side):
    """A10.4's P-E3 control. Move one Probability on the Python side only (SPEC R-10); the Excel
    cached values cannot follow, so at least one comparator must disagree. Without
    this, a reconciliation that compared a value to itself would look identical."""
    scope = read_risk_scope(str(FIXTURE))
    perturbed = scope.copy()
    yes_rows = perturbed.index[perturbed["time_impact"] == "Yes"]
    first = yes_rows[0]
    perturbed.loc[first, "probability"] = (
        float(perturbed.loc[first, "probability"]) + 0.10
    )
    out = compute_schedule_comparators(
        perturbed,
        read_register_mode_multipliers(FIXTURE),
        read_register_day_rate(FIXTURE),
    )
    disagreements = [
        k for k in COMPARATOR_KEYS
        if out[k] != pytest.approx(excel_side[k], rel=RTOL)
    ]
    assert len(disagreements) == len(COMPARATOR_KEYS), (
        "a 0.10 shift in one Prob_T should move all four comparators away from the "
        f"Excel values; only {disagreements} moved"
    )
