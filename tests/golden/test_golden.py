"""GOLDEN01 - golden-number regression suite (discovery-driven off the registry).

One test per (project, scenario) in ``projects.toml``. Exact-equality on every
headline value on x86-64, where goldens are blessed; one part in a billion
elsewhere (XPLATTOL-01). Two tiers, chosen by the registry:

- Public tier (``confidential = false``) always runs; asserts against the
  committed manifest under ``tests/golden/manifests/<project>/``.
- Confidential tier (``confidential = true``) is guarded by ``QRA_GOLDEN_LOCAL``:
  * set (data machine)  -> MUST run; a missing/moved local manifest OR a
    missing/moved input is a FAILURE (guards against a false green when a path
    moves). Asserts against ``tests/golden/local/<project>/``.
  * unset (fresh clone / CI) -> skips cleanly with a clear reason. Never xfail,
    never a silent pass.

Failure protocol (do NOT work around): if a golden fails after a refactor, STOP
and report the diff (project, scenario, statistic, old vs new). Do not adjust
manifests, add tolerances, or re-bless to make it pass. Numbers move ONLY via
``scripts/bless_goldens.py --approve`` with Director sign-off.
"""
from __future__ import annotations

import os
import warnings

import pytest

from tests.arch_guard import same_value
from tests.golden import golden_harness as gh

_CASES = gh.iter_project_scenarios()
_IDS = [f"{p}::{s}" for (p, s, _c) in _CASES]


@pytest.mark.golden
@pytest.mark.parametrize("project,scenario,confidential", _CASES, ids=_IDS)
def test_golden(project: str, scenario: str, confidential: bool) -> None:
    guard = os.environ.get(gh.ENV_GUARD)

    # Confidential tier is armed by QRA_GOLDEN_LOCAL. Unset -> skip cleanly.
    if confidential and not guard:
        pytest.skip(
            f"confidential golden {project!r} skipped: {gh.ENV_GUARD} unset "
            f"(fresh clone / CI). Set {gh.ENV_GUARD}=1 on the data machine to run it."
        )

    mpath = gh.manifest_path_for(project, scenario)

    # A missing manifest is a FAILURE, never a silent pass:
    #  - public: the project is in the registry but not blessed.
    #  - confidential-with-guard: acceptance criterion 2b (missing local manifest
    #    is red, not a skip).
    if not mpath.exists():
        pytest.fail(
            f"no golden manifest for {project}::{scenario} at "
            f"{mpath.relative_to(gh.REPO_ROOT).as_posix()}. Bless it with "
            f"Director sign-off: python scripts/bless_goldens.py --approve "
            f"--project {project} --reason \"...\""
        )

    manifest = gh.load_manifest(mpath)

    # Consistency: the manifest's confidential flag must match the registry.
    assert manifest["confidential"] == confidential, (
        f"manifest confidential flag {manifest['confidential']} != registry "
        f"{confidential} for {project}::{scenario}"
    )
    # Consistency: the manifest seed must match the registry seed (the seed is
    # injected from here, so a drift would silently change the run).
    assert manifest["seed"] == gh.get_row(project).seed, (
        f"manifest seed {manifest['seed']} != registry seed for {project}"
    )

    # INPUT MISSING guard, and input identity. PROVCRLF01: each manifest entry is a
    # {method, value} record. PROCDIET-01 R7 (Director, 12/10/2026): an identity that differs
    # is provenance, not a finding, unless a number moved too - so it is collected here and
    # judged after the run, never failed on alone.
    changed_inputs = []
    for relpath, expected in manifest["inputs_sha256"].items():
        path = gh.resolve_input(relpath)
        if not path.exists():
            pytest.fail(
                f"INPUT MISSING/MOVED for {project}::{scenario}: {relpath} "
                f"is not present. A golden cannot verify against an absent input "
                f"(guard against a false green when a path moves)."
            )
        if isinstance(expected, str):
            pytest.fail(
                f"MANIFEST PREDATES PROVCRLF01 for {project}::{scenario}: "
                f"{relpath} records a bare digest string. Input identity is now "
                f"a {{method, value}} record, because a byte-hash of the working "
                f"copy recorded this machine's line endings rather than the "
                f"input. Re-bless this manifest; do not edit it by hand."
            )
        actual = gh.input_digest(path)
        if (actual["method"], actual["value"]) != (expected["method"], expected["value"]):
            changed_inputs.append(
                f"  {relpath}\n"
                f"    manifest {expected['method']} = {expected['value']}\n"
                f"    current  {actual['method']} = {actual['value']}"
            )

    # Run the engine at the manifest's seed + iteration count: exact on x86-64 (XPLATTOL-01).
    stats = gh.run(project, manifest["seed"], manifest["n_iterations"])
    expected = gh.headline_floats(manifest)

    mismatches = []
    for key in gh.HEADLINE_KEYS:
        got = stats[key]
        want = expected[key]
        if not same_value(got, want):  # exact on x86-64, 1e-9 relative elsewhere
            mismatches.append(
                f"  {key}: golden={want!r} ({want.hex()})  "
                f"current={got!r} ({got.hex()})"
            )

    if changed_inputs and not mismatches:
        warnings.warn(
            f"PROVENANCE ONLY for {project}::{scenario}: an input's identity differs from "
            f"the manifest and every headline number is identical, so nothing is owed "
            f"(PROCDIET-01 R7).\n" + "\n".join(changed_inputs),
            stacklevel=1,
        )
    assert not (changed_inputs and mismatches), (
        f"INPUT CHANGED for {project}::{scenario}, and a headline number moved.\n"
        + "\n".join(changed_inputs) + "\n" + "\n".join(mismatches)
        + "\nThis is an INPUT change, not an engine bug. If intended, re-bless with "
        "Director sign-off; do not edit the manifest by hand."
    )
    assert not mismatches, (
        f"GOLDEN MISMATCH for {project}::{scenario} - a headline number moved.\n"
        + "\n".join(mismatches)
        + f"\n  blessed env : {manifest['environment']}\n"
        + f"  current env : {gh.current_env()}\n"
        + "STOP and report the diff. Do NOT adjust the manifest or add a "
        "tolerance. If this is an approved methodology change, re-bless via "
        "scripts/bless_goldens.py --approve with Director sign-off."
    )


@pytest.mark.golden
def test_no_confidential_in_committed_tier() -> None:
    """Self-enforcing guard (PM ruling 3): no manifest under the committed
    ``manifests/`` tier may carry ``confidential: true``. A confidential project
    mis-blessed into the committed tier fails loudly here (and in the pre-commit
    hook, which runs this suite)."""
    committed = gh.REPO_ROOT / "tests" / "golden" / "manifests"
    offenders = []
    for path in sorted(committed.rglob("*.json")):
        manifest = gh.load_manifest(path)
        if manifest.get("confidential") is True:
            offenders.append(path.relative_to(gh.REPO_ROOT).as_posix())
    assert not offenders, (
        "CONFIDENTIAL manifest(s) found in the committed tier: "
        f"{offenders}. A confidential project must bless to tests/golden/local/ "
        "(gitignored), never to tests/golden/manifests/. Fix the registry "
        "`confidential` flag and re-bless."
    )
