"""QRAXL-01.0 - bit-identity gate for the shared-QRA-core headlines.

Re-runs each baseline's OWN production path and asserts every pinned value
reproduces the captured fixture to the last digit (exact ``==``, the sr19
Gate C pattern - no tolerance). This is the merge condition the later
``qra_core`` extraction defends: with Layer 1 OFF, every figure here must
still come out byte-identical.

Both baselines are full 100k integrated + CPM-replay runs (multi-minute),
so both tests are ``@pytest.mark.slow`` (deselected in the fast lane). The
capture functions are reused verbatim so test and fixture share one wiring.

REG04 §3a.3 (Director ruling 21/07/2026): this 100k trio is DEMOTED to a
milestone / client-release check. The FAST per-sprint value-neutrality gate is
``tests/test_qraxl01_0_bit_identity_10k.py`` (10,000 iters, ~13s) - bit-identity
is a determinism/diff test, so 10k proves value-neutrality as exactly as 100k.

Regenerate the fixture with:
    python scripts/qraxl01_0_capture_baseline.py --baseline {wind,refproject,both}
"""
from __future__ import annotations

import functools
import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.qraxl01_0_capture_baseline as cap
from tests.arch_guard import same_value
from tests.golden import golden_harness as gh
from src.git_identity import git_env

FIXTURE = cap.FIXTURE_PATH

# Every pinned key that must reproduce bit-identically.
_PINNED = (
    "cost_dollars_array_first_n",
    "cost_arm_p80",
    "integrated_total_p80",
    "integrated_total_mean",
)


#: The confidential tier's inputs are gitignored, so their absence on a fresh
#: clone or in CI is expected rather than a defect. ``QRA_GOLDEN_LOCAL`` is the
#: switch the golden harness already uses for exactly that question (its
#: golden-harness rule 5), so this gate reads the same one rather than inventing
#: a second thing to forget to set on a data machine.
_CONFIDENTIAL_GUARD = "QRA_GOLDEN_LOCAL"


def _tier_for(project: str) -> str:
    """Tier is a DATA attribute of the project row, never a literal at the call site.

    ``projects.toml`` already carries ``confidential`` per project, and
    ``golden_harness.manifest_path`` derives its location from that flag alone -
    "derived from the registry flag ONLY - never a literal". A hand-passed literal
    here is the same fact written twice, and the two can disagree: a fixture
    committed under a ``confidential = true`` project would be called public by the
    call site and skipped on a fresh clone while claiming to have been compared.

    ``_assert_tier_matches_git`` still asserts that the data attribute and git agree,
    so a disagreement reds naming the project rather than being resolved silently
    in either direction.
    """
    return "confidential" if gh.get_row(project).confidential else "public"

#: Pointer carried on the one skip that survives, so a reader of a green run can
#: find out what did not run, and why that was legitimate.
_GOLDCOLL_POINTER = "GOLDCOLL-01; SRA-02 brief Amendment 9 (D-9 restated, 27/08)"


def _fixture() -> dict:
    """Fail closed. The fixture is committed, so a missing one is a broken gate."""
    assert FIXTURE.exists(), (
        f"baseline fixture missing: {FIXTURE}. "
        "Regenerate with python scripts/qraxl01_0_capture_baseline.py"
    )
    return json.loads(FIXTURE.read_text())


def _resolve(spec_path: str) -> Path:
    """Resolve a fixture's provenance path against the REPO ROOT, not the cwd.

    Provenance paths are repo-relative (FIXPROV-01), so a bare ``Path(...)``
    would silently resolve against wherever pytest happened to be invoked from.
    An absolute spec is passed through unchanged. Since S-D review F-2 no
    capture script can emit one - ``_relpath`` raises on an out-of-repo input
    rather than falling back - so in practice this branch means a hand-edited
    fixture, and the tier check above will already have had its say about it.
    """
    p = Path(spec_path)
    return p if p.is_absolute() else cap.REPO_ROOT / p


#: What each tier literal *claims* about its inputs. Asserted against git rather
#: than trusted: a public input is committed, so tracked and not ignored; a
#: confidential input is client data, so gitignored and not tracked.
_TIER_CLAIM = {"public": (True, False), "confidential": (False, True)}


@functools.lru_cache(maxsize=None)
def _git_tracked_and_ignored(spec_path: str) -> tuple[bool, bool]:
    """Ask git what this path is, rather than believing the call site.

    Two plumbing calls, ~49ms each on the build machine, cached per path - see the entry
    for this module in ``tests/conftest.py``'s ``_SHELLOUT_EXEMPT``.
    """
    def _rc(*args: str) -> int:
        return subprocess.run(
            ["git", *args, "--", spec_path],
            cwd=cap.REPO_ROOT, capture_output=True, text=True,
            env=git_env(),
        ).returncode

    return _rc("ls-files", "--error-unmatch") == 0, _rc("check-ignore", "-q") == 0


def _assert_tier_matches_git(name: str, spec_path: str, tier: str) -> None:
    """The tier literal is a claim about the input. Check it (S-D review F-1).

    Before this, all four literals happened to be right and nothing said so. The
    Reviewer swapped one and got a clean green; swapped the other way - a public
    input declared confidential - and got a *skip*, which is FALSE-GREEN-01
    restored over a committed fixture, with a skip reason asserting that a
    tracked test fixture was confidential client data. Both measured, not
    predicted.

    Checked before the existence and hash limbs, deliberately: the dangerous
    direction hides behind the confidential tier's skip, so a check placed after
    it would never run in the case that matters most.
    """
    tracked, ignored = _git_tracked_and_ignored(spec_path)
    want_tracked, want_ignored = _TIER_CLAIM[tier]
    assert (tracked, ignored) == (want_tracked, want_ignored), (
        f"TIER MISMATCH - input '{name}' is declared tier={tier!r} at this call "
        f"site, and git disagrees.\n"
        f"  path:            {spec_path}\n"
        f"  tier={tier!r} claims: tracked={want_tracked}, ignored={want_ignored}\n"
        f"  git reports:     tracked={tracked}, ignored={ignored}\n"
        "A public-tier input is committed, so it must be tracked and not ignored. "
        "A confidential-tier input is client data, so it must be gitignored and "
        "not tracked. Fix the project's `confidential` flag in tests/golden/projects.toml, which is where the tier now comes from, or fix the input's git "
        "status - do not relax this check: a wrong tier either reds a fresh "
        "clone on data it was never meant to need, or skips a committed fixture "
        "while calling it confidential."
    )


def _require_inputs(expected: dict, *, tier: str) -> None:
    """Fail closed on inputs, and ASSERT the recorded hashes rather than storing them.

    This docstring used to say the opposite - that a missing input must skip so
    "the fast lane / a fresh clone without RefProject inputs must not red on a
    missing register". The intent was right and the mechanism was wrong: it
    skipped for *any* absent input on *any* machine, so a checkout missing the
    committed wind fixtures reported green having compared nothing (FALSE-GREEN-01,
    brief A7.1/A7.2). The recorded ``sha256`` was likewise stored and never
    compared - measured at S-D pre-paste, this fixture's wind register hash was
    nineteen register revisions out of date and still green.

    Tier partition (Director, 27/08, brief Amendment 9 - by tier, not by site)
    keeps the original intent and drops the over-reach. Public-tier inputs are
    committed, so a missing one is a broken checkout and reds. Confidential-tier
    inputs are gitignored, so on a fresh clone or in CI they are legitimately
    absent: unarmed, that skips naming the reason and the register row; armed,
    this machine holds the data and a missing input reds like any other.
    """
    armed = bool(os.environ.get(_CONFIDENTIAL_GUARD))
    for name, spec in expected["inputs"].items():
        _assert_tier_matches_git(name, spec["path"], tier)
        path = _resolve(spec["path"])
        if not path.exists() and tier == "confidential" and not armed:
            pytest.skip(
                f"confidential-tier input '{name}' absent and {_CONFIDENTIAL_GUARD} "
                f"is unset, so this is not a data machine and the tier is not "
                f"expected to run. Set {_CONFIDENTIAL_GUARD}=1 to require it. "
                f"[{_GOLDCOLL_POINTER}]"
            )
        assert path.exists(), (
            f"{tier}-tier input '{name}' missing: {path}. Fail-closed: a missing "
            "input reds rather than skipping (FIXPROV-01)."
            + (
                f" {_CONFIDENTIAL_GUARD} is set, so the confidential tier must run."
                if tier == "confidential"
                else ""
            )
        )
        actual = cap._sha256(path)
        hint = ""
        if actual != spec["sha256"] and cap._lock_path(path).exists():
            hint = (
                f"\n  NOTE: {cap._lock_path(path).name} is present, so this file is "
                "open in Excel and Excel rewrites it on save. Close it and re-check "
                "before treating this as a real input change."
            )
        assert actual == spec["sha256"], (
            f"INPUT CHANGED - '{name}' is not the file this baseline was captured "
            f"against.\n  expected sha256: {spec['sha256']}\n"
            f"  actual   sha256: {actual}\n  path: {path}\n"
            "This is not necessarily an engine bug, and it is not a moved number. "
            "Re-capture deliberately with "
            "python scripts/qraxl01_0_capture_baseline.py once the input change is "
            "understood and approved." + hint
        )


def _assert_bit_identical(observed: dict, expected: dict, label: str) -> None:
    for key in _PINNED:
        assert same_value(observed[key], expected[key]), (
            f"QRAXL-01.0 {label}: {key} MOVED\n"
            f"  expected (fixture): {expected[key]!r}\n"
            f"  observed (rerun):   {observed[key]!r}\n"
            f"A moved number is a bug, not an approved change (brief s3)."
        )
    # Determinism / provenance sanity: same seed + iteration count were rerun.
    assert observed["seed"] == expected["seed"]
    assert observed["iterations"] == expected["iterations"]


@pytest.mark.slow
def test_wind_showcase_bit_identity() -> None:
    fx = _fixture()
    assert "wind_showcase" in fx, (
        f"wind baseline absent from the committed fixture {FIXTURE.name}. "
        "Regenerate with python scripts/qraxl01_0_capture_baseline.py "
        "--baseline wind"
    )
    expected = fx["wind_showcase"]
    _require_inputs(expected, tier=_tier_for("wind_synth"))
    observed = cap.capture_wind(expected["iterations"])
    _assert_bit_identical(observed, expected, "wind_showcase")

