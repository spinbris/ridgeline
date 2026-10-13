"""SRA-02 S-C deliverable 2 - the AC-5 pinned SCHEDULE-ONLY baseline.

Re-runs the consolidated wind path and asserts every pinned schedule statistic
reproduces the captured fixture exactly - ``float.hex()`` equality, no tolerance,
the golden-harness convention. Regenerate with
``python scripts/sra02_capture_schedule_baseline.py``.

Why it exists, and why neither limb alone would do (brief A2.3/A2.4, placed by A3.4)
------------------------------------------------------------------------------------
Before this gate the schedule arm had exactly one gate on it, the bit-identity
gate, and that gate is **both** aggregate-only **and** on the wrong branch:

* schedule reaches it only through ``ig = cost + sched * day_rate``
  (``scripts/qraxl01_0_capture_baseline.py:179``), so a schedule move arrives
  diluted and unattributable; and
* its RefProject capture reads ``Risk_Scope`` (A2.1), while S-C2's
  ``Mapping.Gating_Activity_ID`` change lands on the **consolidated** path, which
  that capture never touches.

So this gate is consolidated-path *and* schedule-only. A schedule-only pin on the
strawman branch would still miss the change; a combined aggregate on the
consolidated branch still could not attribute a move to the schedule arm.

G8 check on the existing gate, recorded beside the citation
-----------------------------------------------------------
``tests/test_qraxl01_0_bit_identity_10k.py:61`` is cited above as the gate this
one is modelled on and as evidence of what it does cover. It **counts as
evidence** for that: exact ``==`` on four values, no tolerance, seed and iteration
count re-asserted. Three shapes are recorded against it, the first two from the
S-A record and the third found while building this file:

1. **Skip-not-red paths.** Missing fixture (``:31-34``) and missing input
   (``:36-40``) both ``pytest.skip``. Honest as skips, invisible in a
   "no failures" reading. The 100k sibling adds a third, skipping when the
   register is open in Excel.
2. **Schedule enters only through the combined aggregate**, per above. No
   schedule-only pinned value exists there; the cost arm gets a per-iteration
   fingerprint and the schedule arm gets none.
3. **Provenance recorded but never asserted, so it goes stale silently.** Found
   23/08 by comparing a fresh capture against the committed fixture: the fixture
   records the wind register as ``7b758d78...`` while the register in the tree
   (clean, byte-identical to the committed blob) is ``1c98cc4b...``. The register
   changed under the gate in ``b1f0170`` (REG05-A2), after the fixture was
   captured in ``5270840``, and was never re-captured. Nothing reds, because the
   gate stores ``inputs[*].sha256`` and never compares it - ``_require_inputs``
   checks only that the path *exists*. The numbers still reproduce exactly, so the
   change was value-neutral and the gate is not wrong about what it asserts; it is
   wrong about what it says it asserted it against.

**This gate therefore ASSERTS its input hashes rather than recording them**, and
fails closed on a missing input rather than skipping - the brief's fail-closed
rule, and the direct remedy for shapes 1 and 3. A hash mismatch reports as INPUT
CHANGED, distinguished from a moved number, per the golden-harness failure
protocol (GOLDEN01 rule 4).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.sra02_capture_schedule_baseline as cap_sched

FIXTURE = cap_sched.OUT

#: The schedule-only scalars under the pin. Every one is derived from
#: ``sched_days`` alone - nothing here is combined with cost.
_PINNED_SCALARS = (
    "schedule_days_mean",
    "schedule_days_p50",
    "schedule_days_p80",
    "schedule_days_p90",
    "schedule_days_max",
)


def _fixture() -> dict:
    """Fail closed. A missing fixture is a broken gate, not a skippable one."""
    assert FIXTURE.exists(), (
        f"AC-5 schedule baseline fixture missing: {FIXTURE}. "
        "Regenerate with python scripts/sra02_capture_schedule_baseline.py"
    )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def expected() -> dict:
    return _fixture()["wind_consolidated_schedule"]


@pytest.fixture(scope="module")
def observed(expected) -> dict:
    return cap_sched.capture_wind_schedule(int(expected["iterations"]))


def test_inputs_present_and_unchanged(expected):
    """Fail closed on inputs, and ASSERT the hashes rather than recording them.

    This is the limb the existing gate does not have (shape 3 in the module
    docstring). A changed input here is INPUT CHANGED - a deliberate re-capture is
    the remedy, not a code fix - but it is never silent.
    """
    for name, spec in expected["inputs"].items():
        # FIXPROV-01: provenance paths are repo-relative, so resolve against the
        # repo root rather than the cwd. An absolute spec is passed through,
        # matching the capture script's fallback for an input outside the repo.
        spec_path = Path(spec["path"])
        path = spec_path if spec_path.is_absolute() else cap_sched.REPO_ROOT / spec_path
        assert path.exists(), (
            f"AC-5 schedule baseline input '{name}' missing: {path}. "
            "Fail-closed: a missing input stops the run rather than skipping."
        )
        actual = cap_sched.cap._sha256(path)
        assert actual == spec["sha256"], (
            f"INPUT CHANGED - '{name}' is not the file this baseline was captured "
            f"against.\n  expected sha256: {spec['sha256']}\n"
            f"  actual   sha256: {actual}\n  path: {path}\n"
            "This is not necessarily an engine bug. Re-capture deliberately with "
            "scripts/sra02_capture_schedule_baseline.py once the input change is "
            "understood and approved."
        )


def test_schedule_only_scalars_bit_identical(expected, observed):
    """THE gate. Exact float.hex() equality on every schedule-only statistic."""
    for key in _PINNED_SCALARS:
        assert observed[key] == expected[key], (
            f"SCHEDULE ARM MOVED - {key}\n"
            f"  expected (fixture): {float.fromhex(expected[key])!r}\n"
            f"  observed (rerun):   {float.fromhex(observed[key])!r}\n"
            "A moved schedule number is a bug unless it is an approved "
            "methodology change, and no such change is approved in SRA-02."
        )


def test_schedule_per_iteration_fingerprint_bit_identical(expected, observed):
    """The per-iteration limb the existing gate gives the cost arm and not the
    schedule arm. Catches a reordering or a per-iteration change that leaves the
    aggregates intact."""
    assert observed["schedule_days_first_n"] == expected["schedule_days_first_n"], (
        "SCHEDULE ARM MOVED - per-iteration fingerprint\n"
        f"  expected: {[float.fromhex(x) for x in expected['schedule_days_first_n']]}\n"
        f"  observed: {[float.fromhex(x) for x in observed['schedule_days_first_n']]}"
    )


def test_run_shape_reproduced(expected, observed):
    """Determinism/provenance sanity: the same seed, iteration count, day rate and
    dual-coded count were rerun. Without these a matching statistic could come
    from a different run that happened to agree."""
    for key in ("seed", "iterations", "day_rate", "n_dual_coded"):
        assert observed[key] == expected[key], key


def test_schedule_arm_is_live_enough_to_pin(expected):
    """Positive control on the fixture itself.

    A schedule arm that produced all-zero days would pin perfectly and prove
    nothing - every statistic would be 0.0 and stay 0.0 through any change. This
    asserts the captured baseline has real spread, so the equality above is a
    statement about a live arm.
    """
    assert expected["schedule_days_nonzero_count"] > 0, "schedule arm produced no delay at all"
    assert float.fromhex(expected["schedule_days_mean"]) > 0.0
    assert (
        float.fromhex(expected["schedule_days_p90"])
        > float.fromhex(expected["schedule_days_p50"])
    ), "no spread between P50 and P90 - the pin would not notice a distribution change"


def test_wiring_matches_the_existing_bit_identity_gate(expected):
    """Anti-divergence check on the capture script.

    ``capture_wind_schedule`` reproduces ``cap.capture_wind``'s environment and
    binding dance by hand rather than sharing it, so the two could drift apart and
    this pin could silently start describing a different run. The cost arm is
    common to both, so comparing its P80 against the existing 10k fixture proves
    the two wirings still produce the same run.
    """
    existing = json.loads(
        (FIXTURE.parent / "qraxl01_0_baseline_10k.json").read_text(encoding="utf-8")
    )["wind_showcase"]
    assert int(existing["iterations"]) == int(expected["iterations"])
    assert float.fromhex(expected["cost_arm_p80_crosscheck"]) == existing["cost_arm_p80"], (
        "This capture no longer reproduces the run the existing 10k gate captures. "
        "The schedule pin may be describing a different configuration."
    )
