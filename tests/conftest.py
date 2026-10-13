"""Test-suite conftest — QRAXL-01 generic decoupling (GD-0/GD-A).

Under the Director's no-defaults directive (QRAXL01_generic_decoupling.md), the
project binding has NO default: production code fails loud when no project is
selected (``QRA_PROJECT`` unset). Every PRODUCTION entry point selects a
project explicitly (the 6 ``RUN_*.bat`` set ``QRA_PROJECT`` *before* the Python
process starts, so even import-time binding resolution sees a selected project).

This file is the TEST-HARNESS analogue of those production selects: it selects
``DEFAULT_PROJECT`` for the whole suite, exactly as the .bat files do for production.
**This is NOT a reintroduced default** — it is an explicit selection made by the test
harness at its own entry point, and it is a synthetic project by design (see
``DEFAULT_PROJECT`` below). The docstring named the retired reference project until
REFRETIRE-01, while the code below had selected ``synthetic_wind`` since RS-B.

Selection happens at three depths because different code resolves the binding at
different times, all of which must see a project selected:

  * MODULE-LOAD (below, not in a fixture) — some modules resolve the binding at
    IMPORT time (e.g. ``src/single_run.py`` does ``from src.defaults import
    CHAIN_RISK_IDS``, and ``defaults.__getattr__`` resolves the active binding
    eagerly). pytest imports test modules during COLLECTION, before ANY fixture
    (even session-scoped autouse) runs, so a fixture cannot cover them. conftest
    is imported before collection, so setting the env here — the harness's
    earliest entry point — mirrors the .bat setting it before ``python`` runs.
  * SESSION baseline is subsumed by the module-load set above (it persists for
    the whole process), so no separate session fixture is needed.
  * FUNCTION reset (fixture below) — re-assert the selection at the start of every
    test with save/restore, so a leaked selection from a prior test (the
    recurring env-leak class, e.g. the 6b _wind_binding leak) cannot bleed
    across tests.

Tests needing a different project override AFTER the function fixture
(function-scoped ``monkeypatch.setenv`` in the wind tests, which runs after the
autouse). The fail-loud property test (test_qraxl01_generic_decoupling) overrides
with ``monkeypatch.delenv`` to UNSET the selection and assert the located error.
"""
from __future__ import annotations

from tests._fixture_values import FIXTURE_DAY_RATE  # noqa: E402,F401  (RS-D-1)

#: RS-D-3b (D-15): the Mode multiplier grid a test hands an engine config when it
#: constructs one directly instead of loading a register. A fixture value; the
#: production path reads the register (read_mode_multipliers). Tied to the wind
#: register's grid and to build_test_methodology_defaults() by a test.
TEST_MODE_MULTIPLIERS: dict[str, float] = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}

#: RS-D-2 (D-14): the calibration tolerances a test hands IntegratedConfig when it
#: constructs one directly. A fixture value; production reads the register
#: (read_calibration_tolerances). Tied to the wind register's grid by a test.
TEST_CALIBRATION_TOLERANCES: dict[str, float] = {
    "cost_calibration_tolerance_dollars": 50000.0,
    "cost_calibration_tolerance_pct": 0.001,
    "schedule_calibration_tolerance_days": 1.0,
    "schedule_calibration_tolerance_pct": 0.05,
    "schedule_top3_tie_tolerance_pct": 0.02,   # stage 4 F-30, the Director's 2%
}

import functools
import importlib
import importlib.util
import os
import pathlib
import site
import subprocess
import sys

import pytest

_ENV = "QRA_PROJECT"

# REFRETIRE-01: imported for its side effect - it registers the tests' own ``R``-prefixed
# binding, so a fixture register built with ``R`` IDs can be selected by name. Its module
# docstring says why that is a binding of the tests' own rather than a project's.
from tests import fixture_binding_r  # noqa: E402,F401

#: The default project for the whole suite. Deliberately the synthetic one: the
#: property this file exists to secure is that the suite NEVER silently defaults
#: to a client project, and a default that is a client project is exactly the
#: env-leak class this fixture was written to kill.
#:
#: Asserted by tests/test_project_selection.py, so changing it reds the lane
#: rather than quietly re-pointing every test that does not opt out.
DEFAULT_PROJECT = "synthetic_wind"

# Harness entry-point select, at conftest import (before pytest collects/imports
# test modules that resolve the binding eagerly).
os.environ.setdefault(_ENV, DEFAULT_PROJECT)


def _selected_project_for(item) -> str:
    marker = item.get_closest_marker("project")
    return marker.args[0] if marker and marker.args else DEFAULT_PROJECT


def _skip_if_declared_input_absent(item):
    # NOT named pytest_* : pytest treats every module-level pytest_* function
    # in a conftest as a hook and refuses to start if the name is not a real
    # one. Called explicitly from pytest_runtest_setup below.
    """Skip a test whose declared input is absent.

    Called from ``pytest_runtest_setup``. Declared at the test site::

        @pytest.mark.needs_input("final_runner.ipynb")
        def test_reads_the_runner(): ...

    RS-B step 3. The repository split cut whole classes of input by rule, and
    334 tests already skip cleanly when theirs is absent because someone guarded
    them. 30 did not, and raised instead - the same cause, two behaviours, and
    the difference was only whether anyone had written the guard.

    **The path is resolved and checked here, not in the test.** That is the rule
    the step exists to install: a guard checks the artefact the test READS. The
    defect it replaces was a guard that tested whether a directory existed while
    the reader needed a file inside it, so an empty directory passed the guard
    and failed the read.
    """
    from tests.input_skips import skip_missing
    for marker in item.iter_markers(name="needs_input"):
        for rel in marker.args:
            path = pathlib.Path(__file__).resolve().parents[1] / rel
            if not path.exists():
                skip_missing(path)


def pytest_runtest_setup(item):
    """Select this test's project BEFORE any of its fixtures are built.

    This is a hook and not an autouse fixture, and the difference is
    load-bearing. pytest builds higher-scoped fixtures first, so a
    ``scope="module"`` fixture is created before any function-scoped autouse
    fixture runs. A module fixture that resolves a binding at setup time would
    therefore see the previous test's project, not this one's.

    RS-B found that empirically: marking a module whose reader fixture is
    module-scoped fixed two of its seven failures and left five, because the
    fixture had already read under the wrong binding. ``pytest_runtest_setup``
    runs before fixture setup, so the selection is in place for every scope.
    """
    _skip_if_declared_input_absent(item)
    item._qra_saved_project = os.environ.get(_ENV)
    os.environ[_ENV] = _selected_project_for(item)


def pytest_runtest_teardown(item, nextitem):
    """Restore, so a selection cannot leak into the next test."""
    saved = getattr(item, "_qra_saved_project", None)
    if saved is None:
        os.environ.pop(_ENV, None)
    else:
        os.environ[_ENV] = saved


@pytest.fixture(autouse=True)
def _explicit_project_selection(request):
    """Exposes the selection to tests that want to assert on it.

    The selection itself is made by ``pytest_runtest_setup`` above, for the
    ordering reason recorded there. This fixture only reports it.
    """
    return _selected_project_for(request.node)


# ---------------------------------------------------------------------------
# TESTLANE-01 A, P-A2: the `slow` marker has to mean what it claims
# ---------------------------------------------------------------------------

# Node-ID substrings exempted from the shell-out guard, each with its reason.
# An exemption is a claim that the shell-out is cheap AND not an engine/notebook
# run. Per the Director (25/08): a benign shell-out that costs more than a
# second is not benign - mark it `slow` instead of exempting it. Every entry
# here is justified by a measured duration in the TESTLANE-01 running record.
_SHELLOUT_EXEMPT: dict[str, str] = {
    "tests/test_manual_pointers": (
        "DOCPOINT-01: reads the tracked-file list with `git ls-files` to answer whether a name "
        "the manuals use exists anywhere. A metadata read against the local object store - no "
        "engine run, no notebook, no network; measured 1.4 s for the whole module on the build machine "
        "19/09/2026. Declared rather than relied on: the read happens in a MODULE-scoped "
        "fixture, which is set up before this function-scoped autouse guard is installed, so it "
        "would have passed unguarded either way. That blind spot is SHELLGUARD-01"
    ),
    "tests/test_7d_receive_path_and_render_gate": (
        "Stage 7 part D: runs the app-render gate (SPEC 3 limb 4's second gate) by invoking the "
        "dashboard's vitest suite. It shells out because the assertions must execute in jsdom - "
        "part A established that a static-export assertion cannot see the app's content at all, "
        "since every page sits behind a provider that renders null until data loads client-side. "
        "Invoked from this lane rather than left to a separate npm test nobody remembers: a suite "
        "outside the gate is a suite that rots. Measured 4 s for the vitest run on the build machine "
        "06/09/2026. Skips when node, npm or node_modules is absent. No Python engine or notebook run"
    ),
    "tests/test_7c_project_key_and_migration": (
        "Stage 7 part C: runs the period engine twice against the same output root - once keyed, "
        "then again with a period planted in the flat root - because the trend-confinement defect "
        "was the CALLER handing a shared directory to _build_trend, not _build_trend itself. Two "
        "earlier versions of that test asserted source text and then called the private function "
        "directly; the re-review showed the second passes under the pre-part-C code too, so it "
        "could not fail on the regression it names. Going through run_period is what makes it "
        "evidence, and run_period shells out for the provenance stamp. 500 iterations; measured "
        "8.7 s for the whole module, best of 2, on the build machine 06/09/2026. No notebook run"
    ),
    "tests/test_7c_period_freshness": (
        "Stage 7 part C: compiles ONE pure-function module with the TypeScript already in "
        "dashboard/node_modules and evaluates the B-3 threshold cases in node. The dashboard has "
        "no test harness - that is D-2, and it needs a DOM - but assessFreshness needs only a JS "
        "runtime, so the ruling's arithmetic is EXECUTED here rather than asserted by reading the "
        "source, which for client-facing logic deciding whether a reader is told their figures are "
        "out of date would be worth very little. One module-scoped tsc invocation plus one short "
        "node -e per case; measured 1.55 s for the module, best of 3, on the build machine 06/09/2026. Skips when node "
        "or node_modules is absent. No engine or notebook run"
    ),
    "tests/test_7b_integrated_period": (
        "Stage 7 part B: runs the period engine twice (wind periods 01 and 02) because the "
        "Director's 05/09 ruling - the cost arm is conditioned by the period exactly as the "
        "schedule arm is - can only be asserted by comparing a period that conditions risks "
        "against one that does not. A single period cannot distinguish a pinned cost arm "
        "from an unpinned one, so the second run IS the control. Module-scoped fixtures, "
        "2000 iterations, measured 9.35 s for the whole module on the build machine 05/09/2026. "
        "Listed even though the guard does not currently fire on it: the engine runs in a "
        "module-scoped fixture, which this fixture cannot see (SHELLGUARD-01). The entry "
        "records the deliberate choice, and takes effect if that hole is ever closed"
    ),
    "tests/test_7a_period_json_golden": (
        "Stage 7 part A: SPEC 7a requires the period-JSON golden to be COMMITTED, not "
        "merely present - a golden on the author's disk gates nothing on a fresh clone. "
        "`ls-files --error-unmatch -- <path>` asks exactly that question and a filesystem "
        "check cannot: the file exists either way. One call, on one path, measured 38.1 ms "
        "best of 5 on the build machine 05/09/2026. AMENDED 05/09 at part B: this module ALSO runs "
        "the period engine, in a module-scoped fixture, which shells out for the provenance "
        "stamp - the first version of this reason said 'no engine run' because only the "
        "ls-files call ever fired. It belongs in the stage lane at ~6 s because it is the "
        "D-1 gate; see SHELLGUARD-01 for why the engine half was invisible"
    ),
    "tests/test_client_gate_scope": (
        "GATESCOPE-01: the property under test IS client_gate.walk() calling git ls-files, "
        "so the shell-out cannot be stubbed without testing something else. One repo per "
        "module (git init + git add), three walks, the no-git case makes no call. Measured "
        "611 ms for the whole module, best of 5, on the build machine 03/09/2026. "
        "No engine or notebook run"
    ),
    "tests/test_qraxl01_0_bit_identity": (
        "S-D review F-1: the tier literal at each call site is now asserted against "
        "git rather than trusted - `ls-files --error-unmatch` for tracked, "
        "`check-ignore -q` for ignored - because a swapped literal was green in both "
        "directions and the public->confidential direction silently restored "
        "FALSE-GREEN-01 over a committed fixture. Two plumbing calls per input, "
        "lru_cached per path, measured 48.9ms each on the build machine: 0.489s for all ten "
        "calls across all five inputs, and the fast-lane gate touches five of them. "
        "No engine or notebook run"
    ),
    "tests/test_dayrate02_day_rate_contract": (
        "DAYRATE-02 lock 2 enumerates TRACKED source with `git ls-files` and parses "
        "each file's AST, to assert no SRAConfig construction omits day_rate. The "
        "property is about tracked source, so a filesystem walk would measure the "
        "wrong set - it would sweep .venv and untracked scratch and miss nothing "
        "that matters. Two `ls-files` calls per run, ~50ms each, no engine or "
        "notebook run"
    ),
    "tests/test_doc_paths": (
        "REPORTDOC-01: the walker resolves the paths the guide, spec and playbook name against "
        "`git ls-files`, because a disk check answers differently on a data machine holding the "
        "gitignored confidential tier - and an exemption that goes stale on one machine only is "
        "worse than none. One module-scoped call plus one call against a non-repository "
        "directory to prove the tree refuses rather than resolving nothing. Measured 70.5 ms "
        "best of 5 (81 ms for the refusal) on the build machine 13/09/2026. No engine or notebook run"
    ),
    "tests/test_git_identity": (
        "DIGESTFALLBACK-01: the property is what git answers for a path under a given "
        "environment and folder layout - tracked, untracked, outside any repository, a refused "
        "`.git`, a hook's GIT_DIR - so a stub would test the stub. Two small `git init` repos "
        "and plumbing calls only. Measured 12.8 s for the whole module including import, best "
        "of 3, on the build machine 25/09/2026; the AST scan of four folders is 2.5 s of it. No engine "
        "or notebook run"
    ),
    "tests/golden/": (
        "records input provenance with git plumbing - `ls-files`, `hash-object` "
        "(the PROVCRLF01 blob-OID method) and `describe`. Three sub-second calls, "
        "no engine or notebook run; and the golden gate runs in the pre-commit "
        "hook, where a shell-out refusal would red every commit in the repo"
    ),
    "tests/test_publicface01_no_third_party_creator": (
        "PUBLICFACE-01: derives the list of tracked office files with one `git ls-files`, "
        "in the TEST BODIES. It sat at import until GOLDCOLL-01's collection guard (a sandbox "
        "that is not a git repository) failed collection on it; moved here so collection "
        "needs no git. A metadata read against the local object store, no engine or "
        "notebook run; measured 1.4 s for the whole module on the build machine 07/10/2026"
    ),
    "tests/test_snapshot_manifest": (
        "SNAPSHOTCUT-01 S1: the property IS every tracked file classified, so it asks git for "
        "the tracked-file list, one `git ls-files`. A metadata read, no engine or notebook run; "
        "measured 0.06 s for the read and classification, best of 5, on the build machine "
        "09/10/2026"
    ),
    "tests/test_shipped_names.py::test_no_shipped_file_carries_a_scrubbed_name": (
        "SNAPSHOTCUT-01 gate 3 round 2: which files ship is the manifest over the tracked-file list, "
        "one `git ls-files`, then a byte scan of each shipped file and of each zip member. No engine "
        "or notebook run; measured 2.40 s, best of 3, on the build machine 10/10/2026"
    ),
    "tests/test_shipped_names.py::test_no_shipped_file_carries_a_client_identifier": (
        "SNAPSHOTCUT-01 -9: the same manifest over one `git ls-files`, then the client-identifier "
        "byte scan of each shipped file and zip member. No engine or notebook run; measured 1.05 s, "
        "best of 3, on the build machine 11/10/2026"
    ),
    "tests/test_snapshot_links": (
        "SNAPSHOTCUT-01 gate 3 round 1, W3: which files ship is the manifest over the tracked-file "
        "list, one `git ls-files` (cached for the module), then a text scan of each shipped file. "
        "No engine or notebook run; measured 2.15 s for the whole module, best of 3, on the build "
        "machine 10/10/2026, and 4.72 s once the recogniser took gate 3 round 2's forms"
    ),
}

#: The private tests' entries live beside them, in a module the public snapshot does not carry
#: (gate 3 round 2, finding 3).
_PRIVATE_EXEMPT = "tests.private_shellout_exempt"  # link-rule: the private tests' own exemptions, imported when present
if importlib.util.find_spec(_PRIVATE_EXEMPT):  # absent from the public snapshot, with those tests
    _SHELLOUT_EXEMPT.update(importlib.import_module(_PRIVATE_EXEMPT).PRIVATE_SHELLOUT_EXEMPT)

_SHELLOUT_ATTRS = ("run", "Popen", "call", "check_call", "check_output")

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_THIS_FILE = pathlib.Path(__file__).resolve()


def _third_party_roots() -> tuple[pathlib.Path, ...]:
    """Where this interpreter keeps code that is not ours.

    ``sys.prefix`` differs from ``sys.base_prefix`` inside a virtualenv whatever the
    directory is called; ``site.getsitepackages()`` covers a system interpreter and any
    unusual layout.

    These roots are NOT filtered for being inside the repo, and that is deliberate:
    this repo's venv lives at ``outturn/.venv``, so filtering them out would empty
    this set and re-flag every ``numpy.testing`` frame - the 141-node sweep the guard
    above exists to avoid. Only a root exactly equal to the repo root is dropped, which
    would otherwise disable the guard completely. A frame's filename decides
    membership, and repo source files never live under site-packages, so an editable
    install is not a counter-example.
    """
    roots = []
    for cand in (sys.prefix, sys.base_prefix, *site.getsitepackages()):
        try:
            r = pathlib.Path(cand).resolve()
        except (OSError, ValueError):
            continue
        if r == _REPO_ROOT:
            continue
        roots.append(r)
    return tuple(dict.fromkeys(roots))


_THIRD_PARTY_ROOTS = _third_party_roots()


def _shell_out_is_repo_code(filename: str) -> bool:
    """True if the frame that called ``subprocess`` is this repo's own code.

    Third-party libraries shell out for their own reasons and it is not the
    test's doing. ``numpy.testing`` is the one that matters here: importing it
    runs ``check_support_sve()``, which calls ``subprocess.run('lscpu')`` once,
    at import. Guarding on the module attribute alone flagged 141 nodes on the
    first sweep - almost all of them pure unit tests whose only sin was
    ``np.testing.assert_array_equal``. A guard that reds 141 tests for a reason
    unrelated to what it guards does not get fixed, it gets blanket-exempted,
    and then it guards nothing.

    So the question is not "did a subprocess start" but "did *our* code start
    one". Frames inside the virtualenv are not ours.
    """
    # A frame whose filename is not a real path - "<string>", "<stdin>",
    # "<frozen importlib._bootstrap>" - is never repo code. It must be rejected
    # BEFORE resolve(), because resolve() interprets a bare name against the
    # current working directory: run the lane from inside the repo and
    # Path("<string>").resolve() lands under _REPO_ROOT, so a frozen frame was
    # being called ours (P-B5).
    if filename.startswith("<"):
        return False
    try:
        p = pathlib.Path(filename).resolve()
    except (OSError, ValueError):
        return False
    # Third-party code is decided by where the interpreter installs it, not by a
    # directory happening to be named ".venv". A venv at venv/ or env/, or one
    # copied to another name, is just as much not-ours (P-B5).
    if any(p == root or root in p.parents for root in _THIRD_PARTY_ROOTS):
        return False
    return p == _REPO_ROOT or _REPO_ROOT in p.parents


@pytest.fixture(autouse=True)
def _shell_out_only_in_slow_tests(request, monkeypatch):
    """Make the ``slow`` marker mean what it claims.

    ``-m "not slow"`` is the per-stage gate and the whole basis for tiering, so
    a test that shells out without the marker silently loads the fast lane with
    engine and notebook work. TESTLANE-01 measured the drift: 53 marks against
    19 files that actually execute something, which is drift in *both*
    directions - the durations list, not grep, decides which way each one goes.

    Marking them fixes it once. This fixture is what stops it drifting back: an
    unmarked test that reaches ``subprocess`` fails naming itself, instead of
    quietly rejoining the fast lane.

    The choke point is the ``subprocess`` module's own attributes rather than a
    function in ``src/``, because ``src/`` has no subprocess call sites at all -
    every notebook run in this suite is a direct
    ``subprocess.run([sys.executable, "-m", "nbconvert", "--execute", ...])``
    in the test module itself. (P-A2 named two ``src/final/`` choke points; both
    mention nbconvert only in docstrings. Recorded as PM error P-20.)

    Renewables' equivalent guard has to state that a hand-rolled
    ``subprocess.run`` bypasses it. This one does not: ``from subprocess import
    run`` appears nowhere in ``tests/``, ``src/`` or ``scripts/``, so every call
    resolves the attribute off the module at call time and passes through here.
    That is a checked property, not an assumption - if a future test adds a
    from-import, it bypasses this guard silently, so the grep is worth repeating
    whenever this fixture is touched.

    Module-level shell-outs (the ``node --version`` probes in the ``skipif``
    conditions of the QRAXL-01 tests) run at import time, before any fixture,
    and are deliberately out of scope: they are collection probes, not the test
    doing engine work.
    """
    if request.node.get_closest_marker("slow"):
        return

    nodeid = request.node.nodeid
    for fragment, reason in _SHELLOUT_EXEMPT.items():
        if fragment in nodeid:
            return

    real = {attr: getattr(subprocess, attr) for attr in _SHELLOUT_ATTRS}

    def _complain(nodeid, argv):
        return AssertionError(
            f"{nodeid} shelled out but is not marked @pytest.mark.slow - so it "
            f"runs in the fast lane, makes the per-stage gate slow, and makes "
            f"'-m \"not slow\"' a lie about what it skips. Add the marker, or add "
            f"the node to _SHELLOUT_EXEMPT in tests/conftest.py with a reason if "
            f"the shell-out is cheap and is not an engine or notebook run. "
            f"Attempted: {argv!r}"
        )

    def _make_refuser(attr):
        target = real[attr]

        # ``subprocess.Popen`` is a CLASS, and the standard library subclasses
        # it: ``asyncio/windows_utils.py`` does ``class Popen(subprocess.Popen)``
        # at import time. Replacing it with a function makes that subclassing
        # raise ``TypeError: function() argument 'code' must be code, not str``
        # from inside asyncio - a baffling traceback in an unrelated test, and
        # nothing that names this guard. Worse, it is import-order dependent:
        # if something imported asyncio before the fixture ran, it never
        # appears, which is why three full lanes were green with the bug in.
        # So a class target is refused with a class that still subclasses.
        if isinstance(target, type):
            class _RefusingPopen(target):
                def __init__(self, *args, **kwargs):
                    caller = sys._getframe(1)
                    if not _shell_out_is_repo_code(caller.f_code.co_filename):
                        super().__init__(*args, **kwargs)
                        return
                    raise _complain(nodeid, args[0] if args else kwargs.get("args", "<unknown>"))
            return _RefusingPopen

        def _refuse(*args, **kwargs):
            caller = sys._getframe(1)
            if not _shell_out_is_repo_code(caller.f_code.co_filename):
                return target(*args, **kwargs)
            argv = args[0] if args else kwargs.get("args", "<unknown>")
            raise AssertionError(
                f"{nodeid} shelled out but is not marked @pytest.mark.slow - "
                f"so it runs in the fast lane, makes the per-stage gate slow, "
                f"and makes '-m \"not slow\"' a lie about what it skips. Add the "
                f"marker, or add the node to _SHELLOUT_EXEMPT in "
                f"tests/conftest.py with a reason if the shell-out is cheap and "
                f"is not an engine or notebook run. Attempted: {argv!r}"
            )
        return _refuse

    for attr in _SHELLOUT_ATTRS:
        monkeypatch.setattr(subprocess, attr, _make_refuser(attr))


# ---------------------------------------------------------------------------
# TESTLANE-01 A, P-A1: co-tenants of outputs/ share a worker
# ---------------------------------------------------------------------------

_OUTPUTS_GROUP = "outputs"

# Modules that drive a notebook but were MEASURED to write nothing under
# outputs/ (TESTLANE-01 A partition sweep, 26/08/2026: both exit 0 with real
# notebook execution, 38s and 53s, 0 files written). They drive sra_runner and
# integrated_runner rather than final_runner. They are readers, not co-tenants,
# so they keep `slow` but stay OUT of the serial group and spread with
# everything else. Re-measure a
# new one with tests/tools/outputs_writeset.py rather than guessing.
# SNAPSHOTCUT-01 (Director, 11/10/2026): both were retired as dead tests; none is left.
_PROVEN_NON_WRITERS: tuple[str, ...] = ()


@functools.lru_cache(maxsize=None)
def _module_reaches_outputs(path: str) -> bool:
    """True if this test module constructs a path into ``outputs/``.

    Derived from module content rather than a hardcoded file list, so a new
    test that reaches ``outputs/`` is grouped the day it is written instead of
    the day someone remembers to update a list. The 39 files this matched at
    ``ec950e4`` are recorded in the TESTLANE-01 running record as the baseline;
    a change in that count is a real change, not drift.
    """
    try:
        src = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return '"outputs' in src or "'outputs" in src


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Serialise the ``outputs/`` co-tenants under ``--dist loadgroup``.

    ``-n auto`` on the full suite gave four spurious reds (SRA-02 S-B): tests
    that execute notebooks share a relative ``Path("outputs")`` against the
    working directory, so under load they read each other's half-written state.
    There is no output root to redirect - the three ``_resolve_path`` variants
    resolve *inputs*, and the output location is a bare relative path in
    ``src/final/stage3_beta_report.py:976``. Redirecting it is sub-stage C and
    is deferred.

    ``xdist_group`` needs neither. Every co-tenant lands on one worker, so they
    are serial *with respect to each other* while the other ~2,100 tests
    parallelise. Correctness comes from the grouping; the speed comes from
    everything that is not in the group.

    Two routes into the group, because the literal-mention test alone would
    miss the dangerous case:

    * the module constructs an ``outputs/`` path itself (39 files); and
    * the test is marked ``slow`` - every engine and notebook run writes under
      ``outputs/`` whether or not the test module says so, which is exactly the
      silent co-tenant a content grep cannot see.

    ``tryfirst`` is load-bearing and must not be removed. xdist implements its
    own ``pytest_collection_modifyitems`` (``xdist/remote.py``) which reads the
    ``xdist_group`` marker and rewrites ``item._nodeid`` to ``<nodeid>@<group>``;
    the controller schedules off that suffix. Without ``tryfirst`` this hook runs
    *after* that rewrite, the markers are added too late to be seen, and the
    grouping is a silent no-op - every co-tenant load-balances as usual and
    nothing anywhere reports a problem.

    That is not hypothetical: it is how this was first written, and the lane it
    produced red 18 notebook tests across nine workers. The check that finds it
    is ``test_xdist_grouping.py``, which asserts the suffix is actually applied
    rather than that the marker was requested.

    This is not proof of parallel-safety. The proof is P-A1: the serial and
    parallel outcome sets at the same commit, diffed per node. If that diff is
    non-empty, the group is too narrow and the offending nodes name themselves.
    """
    for item in items:
        nodeid = item.nodeid
        if any(nodeid.startswith(f) for f in _PROVEN_NON_WRITERS):
            continue
        if item.get_closest_marker("slow") or _module_reaches_outputs(str(item.path)):
            item.add_marker(pytest.mark.xdist_group(_OUTPUTS_GROUP))
