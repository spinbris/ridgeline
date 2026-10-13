"""Validation Gate 1 — hand-worked CPM kernel reproduction.

This file is the formal Beta-07 Validation Gate 1 acceptance target,
locked at the filename specified in
the Stage 3 Beta build plan, §6 acceptance
criterion 1 ("hand-worked CPM kernel test against a 10-20-activity
synthetic graph with mixed FS/SS/FF/SF and lag, lock as
``tests/sra/cpm/test_kernel_handworked.py``").

Provenance — Beta-03 → Beta-07
------------------------------
The :class:`TestValidationGate1` class below was originally committed
under Beta-03 inside :mod:`tests.sra.cpm.test_cpm_kernel`. SR-S3-Beta-07
moves it to this dedicated file *without modification* (the only
in-class change is the docstring — Beta-07 promotion provenance
recorded; algorithm and assertions unchanged) so the gate can be
referenced by a stable file name in audit and review contexts. The
source-of-truth fixture at :mod:`tests.sra.cpm.fixtures.gate1_handworked`
is unchanged.

A reviewer can step through the fixture's module docstring with a
calculator and reproduce every expected ES / EF / LS / LF / slack value
without ever running the kernel; the tests below assert that the
kernel reproduces those numbers bit-exactly under
``precision='float64'`` and within ``CRITICAL_PATH_TOL`` under
``precision='float32'``.

SF link-type coverage cross-reference
-------------------------------------
Build Plan §6 acceptance criterion 1 calls for "mixed FS/SS/FF/SF and
lag". The 7-activity hand-worked fixture deliberately covers FS / SS /
FF only (the fixture docstring explains why: SF rarely binds anything
in a forward CPM scenario, so engineering it into the Gate-1
walkthrough adds distraction without coverage). The SF coverage is
satisfied by the per-link-type matrix tests in
:mod:`tests.sra.cpm.test_cpm_kernel_links` (see the ``link_type='SF'``
parametrised cases of ``test_two_activity_link_type_matrix`` and the
``test_chain_A_SF_B_FS_C`` / ``test_branch_A_FF_B_and_A_SF_C``
three-activity scenarios). Beta-07 documents that this satisfies AC1
without duplicating SF into the hand-walkthrough.

Why this gate exists
--------------------
Stage 3 has no third-party CPM tool available for cross-validation
(``STAGE3_ROADMAP.md`` §8). The hand-worked example is the only
independent verification of the forward + backward arithmetic for the
beta phase. Any silent off-by-one in any of the four link types would
propagate undetected through every Stage 3 simulation, so this gate is
treated as load-bearing.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_kernel import (
    CRITICAL_PATH_TOL,
    backward_pass,
    forward_pass,
    run_batch,
)
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from tests.sra.cpm.fixtures.gate1_handworked import (
    DURATIONS_HOURS,
    EXPECTED_EF,
    EXPECTED_ES,
    EXPECTED_LF,
    EXPECTED_LS,
    EXPECTED_ON_CRITICAL_PATH,
    EXPECTED_PROJECT_FINISH,
    EXPECTED_SLACK,
    LINK_SPECS,
    TOPO_ORDER,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic ScheduleGraph builders for tests
# ---------------------------------------------------------------------------

_DEFAULT_CALENDAR = Calendar()


def _make_graph(
    activity_durations: dict[str, float],
    links: list[tuple[str, str, str, float]],
    *,
    topo_order: list[str] | None = None,
    calendar: Calendar | None = None,
) -> ScheduleGraph:
    """Build a synthetic ScheduleGraph for tests.

    Mirrors the helper in :mod:`tests.sra.cpm.test_cpm_kernel`. Kept
    local to this file so the Gate 1 module can be read end-to-end
    without cross-file hop.
    """
    if topo_order is None:
        topo_order = list(activity_durations.keys())

    activities: dict[str, Activity] = {
        aid: Activity(
            id=aid,
            code=aid,
            name=aid,
            task_type="TT_Task",
            original_duration_hours=dur,
            total_float_hours=None,
            calendar_id=None,
        )
        for aid, dur in activity_durations.items()
    }

    link_objs: list[Link] = []
    for pred_id, succ_id, link_type, lag in links:
        link = Link(
            pred_id=pred_id,
            succ_id=succ_id,
            link_type=link_type,  # type: ignore[arg-type]
            lag_hours=lag,
        )
        link_objs.append(link)
        activities[pred_id].successor_links.append(link)
        activities[succ_id].predecessor_links.append(link)

    return ScheduleGraph(
        activities=activities,
        links=link_objs,
        topo_order=list(topo_order),
        project_default_calendar=calendar or _DEFAULT_CALENDAR,
    )


def _durations_array(
    graph: ScheduleGraph,
    per_activity_dur: dict[str, float],
    *,
    batch_n: int = 1,
    dtype: np.dtype = np.float64,
) -> np.ndarray:
    """Build a ``(batch_n, n_act)`` durations array aligned to topo order."""
    cols = [per_activity_dur[aid] for aid in graph.topo_order]
    return np.tile(np.array(cols, dtype=dtype), (batch_n, 1))


# ---------------------------------------------------------------------------
# Validation Gate 1
# ---------------------------------------------------------------------------

class TestValidationGate1:
    """Hand-worked CPM example — see fixtures/gate1_handworked.py.

    Runs under ``precision='float64'`` so any rounding-error gap from
    float32 doesn't false-fail the bit-exact comparison. The expected
    values are derived by hand in the fixture's module docstring.

    Promoted from :mod:`tests.sra.cpm.test_cpm_kernel` to this
    dedicated file at SR-S3-Beta-07 per Build Plan §6 acceptance
    criterion 1; no test logic changes, only the file location and
    the module-level docstring.
    """

    @pytest.fixture
    def graph(self) -> ScheduleGraph:
        durations = dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True))
        links = [
            (l.pred_id, l.succ_id, l.link_type, l.lag_hours) for l in LINK_SPECS
        ]
        return _make_graph(durations, links, topo_order=list(TOPO_ORDER))

    def test_gate1_forward_pass_bit_exact_float64(self, graph: ScheduleGraph) -> None:
        durations = _durations_array(
            graph, dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True))
        )
        ES, EF = forward_pass(
            durations, graph, _DEFAULT_CALENDAR, precision="float64"
        )
        # Bit-exact under float64.
        assert np.array_equal(ES[0], np.array(EXPECTED_ES))
        assert np.array_equal(EF[0], np.array(EXPECTED_EF))

    def test_gate1_backward_pass_bit_exact_float64(self, graph: ScheduleGraph) -> None:
        durations = _durations_array(
            graph, dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True))
        )
        project_finish = np.array([EXPECTED_PROJECT_FINISH], dtype=np.float64)
        LS, LF = backward_pass(
            durations,
            graph,
            _DEFAULT_CALENDAR,
            project_finish=project_finish,
            precision="float64",
        )
        assert np.array_equal(LS[0], np.array(EXPECTED_LS))
        assert np.array_equal(LF[0], np.array(EXPECTED_LF))

    def test_gate1_slack_within_1e_minus_9(self, graph: ScheduleGraph) -> None:
        durations = _durations_array(
            graph, dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True))
        )
        result = run_batch(
            durations, graph, calendar=_DEFAULT_CALENDAR, precision="float64"
        )
        # Brief §6 acceptance criterion 4: slack values match to 1e-9.
        np.testing.assert_allclose(result["slack"][0], EXPECTED_SLACK, atol=1e-9)

    def test_gate1_run_batch_bit_exact_float64(self, graph: ScheduleGraph) -> None:
        durations = _durations_array(
            graph, dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True))
        )
        result = run_batch(
            durations, graph, calendar=_DEFAULT_CALENDAR, precision="float64"
        )
        assert np.array_equal(result["ES"][0], np.array(EXPECTED_ES))
        assert np.array_equal(result["EF"][0], np.array(EXPECTED_EF))
        assert np.array_equal(result["LS"][0], np.array(EXPECTED_LS))
        assert np.array_equal(result["LF"][0], np.array(EXPECTED_LF))
        assert np.array_equal(result["slack"][0], np.array(EXPECTED_SLACK))
        assert np.array_equal(
            result["on_critical_path"][0], np.array(EXPECTED_ON_CRITICAL_PATH)
        )
        assert float(result["project_finish"][0]) == EXPECTED_PROJECT_FINISH

    def test_gate1_under_float32_within_critical_path_tol(
        self, graph: ScheduleGraph
    ) -> None:
        """Float32 default should match within CRITICAL_PATH_TOL (1e-3 h).

        This is the production-default precision. The Gate-1 example is
        small enough that even float32 round-trips well within the
        tolerance, so this test confirms the precision policy is
        compatible with the gate's expected values.
        """
        durations = _durations_array(
            graph,
            dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True)),
            dtype=np.float32,
        )
        result = run_batch(
            durations, graph, calendar=_DEFAULT_CALENDAR, precision="float32"
        )
        np.testing.assert_allclose(
            result["ES"][0], EXPECTED_ES, atol=CRITICAL_PATH_TOL
        )
        np.testing.assert_allclose(
            result["EF"][0], EXPECTED_EF, atol=CRITICAL_PATH_TOL
        )
        np.testing.assert_allclose(
            result["LS"][0], EXPECTED_LS, atol=CRITICAL_PATH_TOL
        )
        np.testing.assert_allclose(
            result["LF"][0], EXPECTED_LF, atol=CRITICAL_PATH_TOL
        )

    def test_gate1_critical_path_membership_matches_handwork(
        self, graph: ScheduleGraph
    ) -> None:
        """Critical-path mask must flag exactly A, C, D, F, G as critical.

        This is independent of the bit-exact arithmetic checks above —
        even with float32 rounding the membership decision should hold.
        """
        durations = _durations_array(
            graph,
            dict(zip(TOPO_ORDER, DURATIONS_HOURS, strict=True)),
            dtype=np.float32,
        )
        result = run_batch(durations, graph, precision="float32")
        assert list(result["on_critical_path"][0]) == list(EXPECTED_ON_CRITICAL_PATH)
