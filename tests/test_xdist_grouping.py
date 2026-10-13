"""The ``outputs/`` xdist grouping is actually applied, not merely requested.

TESTLANE-01 A declared ``GATE_INCREMENT_LANE`` parallel-safe on the strength of
``tests/conftest.py`` putting every ``outputs/`` co-tenant into one
``xdist_group``. The first version of that hook was a **silent no-op**, and
nothing anywhere said so: the markers were added, the lane ran, and every
co-tenant load-balanced across workers exactly as if the hook did not exist.

The cause is hook ordering. xdist implements its own
``pytest_collection_modifyitems`` in ``xdist/remote.py``, which reads the
``xdist_group`` marker and rewrites ``item._nodeid`` to ``<nodeid>@<group>``;
the controller then schedules off that suffix, not off the marker. A conftest
hook without ``tryfirst`` runs *after* that rewrite, so the marker it adds is
never seen. The lane that resulted red 18 notebook tests spread over nine
workers.

The near-miss is the reason this file exists. Those 18 failed loudly only
because concurrent ``nbconvert`` subprocesses exhaust Windows desktop heap
(``0xC0000142``). On a machine where they had happened to pass, the serial and
parallel outcome sets would have matched, P-A1 would have been declared to hold,
and the agent manual would carry a parallel-safe declaration resting on a hook that
did nothing. That is a check certifying something it never performed.

So these tests assert the **property** - the suffix that xdist actually
schedules on - and not the mechanism that is supposed to produce it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# A module that constructs an outputs/ path, and one that does not. Both are
# cheap to collect. If either stops being representative the assertions below
# fail loudly rather than quietly testing nothing.
# SNAPSHOTCUT-01: was test_sr8_joint_sampler.py, whose only outputs/ path left with a retired test.
CO_TENANT = "tests/test_release_ritual_no_retired_claims.py"  # 1 test, reads outputs/ by content
NON_CO_TENANT = "tests/sra/cpm/test_cpm_kernel.py"  # 31 tests, in-memory, no outputs/ path


def test_the_two_reference_modules_are_still_what_this_file_assumes():
    """Guard the guard: a silently mis-chosen reference makes the rest vacuous."""
    co = (REPO_ROOT / CO_TENANT).read_text(encoding="utf-8", errors="ignore")
    non = (REPO_ROOT / NON_CO_TENANT).read_text(encoding="utf-8", errors="ignore")
    assert '"outputs' in co or "'outputs" in co, (
        f"{CO_TENANT} no longer constructs an outputs/ path, so it is no longer "
        f"a co-tenant and the grouping assertions below prove nothing. Pick "
        f"another reference module."
    )
    assert '"outputs' not in non and "'outputs" not in non, (
        f"{NON_CO_TENANT} now constructs an outputs/ path, so it is a co-tenant "
        f"and can no longer serve as the negative case. Pick another."
    )


@pytest.mark.slow  # spawns a nested pytest; belongs to the increment lane
def test_co_tenants_get_the_xdist_group_suffix_under_loadgroup():
    """The nodeid xdist schedules on actually carries ``@outputs``.

    This has to be a real run, not ``--collect-only``: under ``--collect-only``
    xdist reports plain nodeids and the ``@group`` suffix never appears, so a
    collect-only probe reads exactly the same whether the grouping works or not
    - which is the failure mode this file exists to catch, reintroduced inside
    the check itself. The two reference modules together cost ~0.01s of test
    time; what this pays for is two worker startups.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", CO_TENANT, NON_CO_TENANT,
         "-v", "-n", "2", "--dist", "loadgroup"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600,
    )
    assert proc.returncode == 0, f"collection failed:\n{proc.stdout}\n{proc.stderr}"

    suffixed = [l for l in proc.stdout.splitlines() if "@outputs" in l]
    assert suffixed, (
        "No collected nodeid carries the '@outputs' suffix, so the xdist_group "
        "marker added in tests/conftest.py is invisible to xdist's scheduler and "
        "the grouping is a silent no-op. The usual cause is the conftest hook "
        "losing @pytest.hookimpl(tryfirst=True) - xdist rewrites nodeids in its "
        "own pytest_collection_modifyitems, and a hook that runs after it adds "
        "markers nobody reads. GATE_INCREMENT_LANE is not parallel-safe in this "
        "state.\n\n" + proc.stdout[-3000:]
    )

    non_suffixed = [
        l for l in proc.stdout.splitlines()
        if NON_CO_TENANT.replace("tests/", "") in l and "@outputs" not in l
    ]
    assert non_suffixed, (
        f"Every collected node carried '@outputs', including ones from "
        f"{NON_CO_TENANT}. A group that contains everything serialises the whole "
        f"suite and is not a grouping."
    )
