"""REG04 §3a.3 - the 10k bit-identity gate (the FAST per-sprint value-neutrality check).

Director ruling 21/07/2026: 100k runtime is too long for a per-sprint gate. Bit-identity
is a determinism / diff test, not a convergence test - with the seeded RNG and an
untouched read path, 10,000 iterations prove value-neutrality exactly as well as 100k.
So this 10k trio (wind + RefProject, standard seed) is the gate that runs every sprint;
the 100k fixture (`tests/test_qraxl01_0_bit_identity.py`, `@pytest.mark.slow`) is demoted
to a milestone / client-release check.

Regenerate the 10k baseline: python scripts/qraxl01_0_capture_baseline_10k.py
"""
from __future__ import annotations

import functools
import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.qraxl01_0_capture_baseline as cap
from tests.arch_guard import x86_64_only
from tests.golden import golden_harness as gh
from src.git_identity import git_env

FIXTURE = cap.FIXTURE_PATH.parent / "qraxl01_0_baseline_10k.json"

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
        f"10k baseline fixture missing: {FIXTURE}. "
        "Regenerate with python scripts/qraxl01_0_capture_baseline_10k.py"
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

    Two FALSE-GREEN-01 shapes lived here (brief A7.1/A7.2). A missing input
    *skipped* instead of redding, so on a machine without the inputs this gate
    reported green having compared nothing. And each input's ``sha256`` was
    recorded but never compared, so the gate went stale in silence - measured at
    S-D pre-paste, this fixture's wind register hash was six register revisions
    out of date and the 100k sibling's was nineteen, both green throughout.

    Tier partition (Director, 27/08, brief Amendment 9 - by tier, not by site).
    Public-tier inputs are committed, so a missing one is a broken checkout and
    reds. Confidential-tier inputs are gitignored, so on a fresh clone or in CI
    they are legitimately absent: unarmed, that skips naming the reason and the
    register row; armed, this machine holds the data and a missing input reds
    like any other.
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
            "python scripts/qraxl01_0_capture_baseline_10k.py once the input change "
            "is understood and approved." + hint
        )


def _assert_bit_identical(observed: dict, expected: dict, label: str) -> None:
    for key in _PINNED:
        assert observed[key] == expected[key], (
            f"10k bit-identity {label}: {key} MOVED\n"
            f"  expected (fixture): {expected[key]!r}\n"
            f"  observed (rerun):   {observed[key]!r}\n"
            f"A moved number is a bug, not an approved change."
        )
    assert observed["seed"] == expected["seed"]
    assert observed["iterations"] == expected["iterations"] == 10_000


def test_wind_showcase_inputs_unchanged_10k() -> None:
    """The input half of the wind 10k check, split out so it runs on every architecture.

    ARM64ULP-01 made the exact-sample comparison below x86-64-only. Whether the inputs are the
    files the baseline was captured against does not depend on the architecture, and it must
    not be skipped with it (found by the Mac's arm64 run, 11/09/2026).
    """
    _require_inputs(_fixture()["wind_showcase"], tier=_tier_for("wind_synth"))


@x86_64_only
def test_wind_showcase_bit_identity_10k() -> None:
    expected = _fixture()["wind_showcase"]
    _require_inputs(expected, tier=_tier_for("wind_synth"))
    _assert_bit_identical(cap.capture_wind(expected["iterations"]), expected, "wind")

