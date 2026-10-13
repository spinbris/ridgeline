"""Link-type matrix tests for src.sra.cpm.cpm_kernel (SR-S3-Beta-03).

The brief (§5) requires exhaustive coverage of all four link types
(FS, SS, FF, SF) crossed with three lag values (0, +8, -8). The
two-activity ``A → B`` scenarios cover the per-link-type forward and
backward formulas in isolation; the three-activity scenarios cover
the case where the ``durations[:, j]`` term enters the backward
implied_finish (SS / SF on the predecessor side of an outbound link).

All tests construct ``ScheduleGraph`` directly — no RefProject file
references. Float64 is used throughout so the ES/EF/LS/LF values are
bit-exact (the matrix expected values are integers, so there is no
rounding to accommodate).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_kernel import run_batch
from src.sra.cpm.graph import Activity, Link, ScheduleGraph

_DEFAULT_CALENDAR = Calendar()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_two_activity_graph(
    link_type: str, lag: float, *, dur_a: float = 8.0, dur_b: float = 12.0
) -> tuple[ScheduleGraph, np.ndarray]:
    """Build a two-activity ``A → B`` graph with the given link.

    Returns the graph and a single-iteration durations array
    aligned to topo order ``[A, B]``.
    """
    link = Link(pred_id="A", succ_id="B", link_type=link_type, lag_hours=lag)  # type: ignore[arg-type]
    a = Activity(
        id="A",
        code="A",
        name="A",
        task_type="TT_Task",
        original_duration_hours=dur_a,
        total_float_hours=None,
        calendar_id=None,
        successor_links=[link],
    )
    b = Activity(
        id="B",
        code="B",
        name="B",
        task_type="TT_Task",
        original_duration_hours=dur_b,
        total_float_hours=None,
        calendar_id=None,
        predecessor_links=[link],
    )
    graph = ScheduleGraph(
        activities={"A": a, "B": b},
        links=[link],
        topo_order=["A", "B"],
        project_default_calendar=_DEFAULT_CALENDAR,
    )
    durations = np.array([[dur_a, dur_b]], dtype=np.float64)
    return graph, durations


def _make_three_activity_graph(
    links: list[tuple[str, str, str, float]],
    durations_by_id: dict[str, float],
    topo_order: list[str],
) -> tuple[ScheduleGraph, np.ndarray]:
    """Build a 3-activity graph from explicit links + durations + topo."""
    activities = {
        aid: Activity(
            id=aid,
            code=aid,
            name=aid,
            task_type="TT_Task",
            original_duration_hours=dur,
            total_float_hours=None,
            calendar_id=None,
        )
        for aid, dur in durations_by_id.items()
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
    graph = ScheduleGraph(
        activities=activities,
        links=link_objs,
        topo_order=list(topo_order),
        project_default_calendar=_DEFAULT_CALENDAR,
    )
    cols = [durations_by_id[aid] for aid in topo_order]
    durations = np.array([cols], dtype=np.float64)
    return graph, durations


# ---------------------------------------------------------------------------
# Two-activity matrix
# ---------------------------------------------------------------------------

# Hand-derived expected outputs for A → B at dur_A=8, dur_B=12 across
# the 4 link-types × 3 lags. Each row is keyed by (link_type, lag) and
# carries (ES_A, ES_B, EF_A, EF_B, LS_A, LS_B, LF_A, LF_B,
# project_finish, slack_A, slack_B). See the docstring of each
# parametrised test for the per-case derivation.
_TWO_ACT_MATRIX: dict[tuple[str, float], dict[str, float]] = {
    # --- FS ---
    ("FS", 0.0): dict(
        ES_A=0, ES_B=8, EF_A=8, EF_B=20,
        LS_A=0, LS_B=8, LF_A=8, LF_B=20,
        project_finish=20, slack_A=0, slack_B=0,
    ),
    ("FS", 8.0): dict(
        # ES_B = EF_A + 8 = 16; EF_B = 28.
        ES_A=0, ES_B=16, EF_A=8, EF_B=28,
        # Backward: LS_B = 16; LF_A = LS_B - 8 = 8; LS_A = 0.
        LS_A=0, LS_B=16, LF_A=8, LF_B=28,
        project_finish=28, slack_A=0, slack_B=0,
    ),
    ("FS", -8.0): dict(
        # ES_B = max(0, EF_A - 8) = max(0, 0) = 0; EF_B = 12.
        # project_finish = max(EF_A, EF_B) = max(8, 12) = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; LF_A = LS_B - (-8) = 8; LS_A = 0.
        LS_A=0, LS_B=0, LF_A=8, LF_B=12,
        project_finish=12, slack_A=0, slack_B=0,
    ),
    # --- SS ---
    ("SS", 0.0): dict(
        # ES_B = max(0, ES_A + 0) = 0; EF_B = 12.
        # project_finish = max(8, 12) = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = LS_B - 0 + dur_A = 8;
        # LF_A = 8; LS_A = 0.
        LS_A=0, LS_B=0, LF_A=8, LF_B=12,
        project_finish=12, slack_A=0, slack_B=0,
    ),
    ("SS", 8.0): dict(
        # ES_B = max(0, ES_A + 8) = 8; EF_B = 20.
        ES_A=0, ES_B=8, EF_A=8, EF_B=20,
        # Backward: LS_B = 8; implied_finish_A = 8 - 8 + 8 = 8; LS_A = 0.
        LS_A=0, LS_B=8, LF_A=8, LF_B=20,
        project_finish=20, slack_A=0, slack_B=0,
    ),
    ("SS", -8.0): dict(
        # ES_B = max(0, ES_A - 8) = max(0, -8) = 0; EF_B = 12.
        # project_finish = max(8, 12) = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = 0 - (-8) + 8 = 16;
        # LF_A = 16; LS_A = 8. A has 8h slack (an SS lead means A can
        # slip relative to B because B already permitted to start before A).
        LS_A=8, LS_B=0, LF_A=16, LF_B=12,
        project_finish=12, slack_A=8, slack_B=0,
    ),
    # --- FF ---
    ("FF", 0.0): dict(
        # ES_B = max(0, EF_A + 0 - dur_B) = max(0, -4) = 0; EF_B = 12.
        # project_finish = max(8, 12) = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = LF_B - 0 = 12;
        # LF_A = 12; LS_A = 4. A has 4h slack — FF lag=0 lets A finish
        # any time before B finishes (and B finishes at 12, A at 8).
        LS_A=4, LS_B=0, LF_A=12, LF_B=12,
        project_finish=12, slack_A=4, slack_B=0,
    ),
    ("FF", 8.0): dict(
        # ES_B = max(0, EF_A + 8 - dur_B) = max(0, 4) = 4; EF_B = 16.
        ES_A=0, ES_B=4, EF_A=8, EF_B=16,
        # Backward: LS_B = 4; implied_finish_A = LF_B - 8 = 8; LS_A = 0.
        LS_A=0, LS_B=4, LF_A=8, LF_B=16,
        project_finish=16, slack_A=0, slack_B=0,
    ),
    ("FF", -8.0): dict(
        # ES_B = max(0, EF_A - 8 - dur_B) = max(0, -12) = 0; EF_B = 12.
        # project_finish = max(8, 12) = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = LF_B - (-8) = 20;
        # LF_A = 20; LS_A = 12.
        LS_A=12, LS_B=0, LF_A=20, LF_B=12,
        project_finish=12, slack_A=12, slack_B=0,
    ),
    # --- SF ---
    ("SF", 0.0): dict(
        # ES_B = max(0, ES_A + 0 - dur_B) = max(0, -12) = 0; EF_B = 12.
        # project_finish = max(8, 12) = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = LF_B - 0 + dur_A = 12 + 8 = 20;
        # LF_A = 20; LS_A = 12.
        LS_A=12, LS_B=0, LF_A=20, LF_B=12,
        project_finish=12, slack_A=12, slack_B=0,
    ),
    ("SF", 8.0): dict(
        # ES_B = max(0, ES_A + 8 - dur_B) = max(0, -4) = 0; EF_B = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = LF_B - 8 + dur_A = 12 - 8 + 8 = 12;
        # LF_A = 12; LS_A = 4.
        LS_A=4, LS_B=0, LF_A=12, LF_B=12,
        project_finish=12, slack_A=4, slack_B=0,
    ),
    ("SF", -8.0): dict(
        # ES_B = max(0, ES_A - 8 - dur_B) = max(0, -20) = 0; EF_B = 12.
        ES_A=0, ES_B=0, EF_A=8, EF_B=12,
        # Backward: LS_B = 0; implied_finish_A = LF_B - (-8) + dur_A = 12 + 8 + 8 = 28;
        # LF_A = 28; LS_A = 20.
        LS_A=20, LS_B=0, LF_A=28, LF_B=12,
        project_finish=12, slack_A=20, slack_B=0,
    ),
}


@pytest.mark.parametrize(
    "link_type,lag",
    [
        (lt, lag)
        for lt in ("FS", "SS", "FF", "SF")
        for lag in (0.0, 8.0, -8.0)
    ],
)
def test_two_activity_link_type_matrix(link_type: str, lag: float) -> None:
    """A → B with link_type ∈ {FS, SS, FF, SF} × lag ∈ {0, +8, -8}.

    Each parametrisation reproduces ES/EF/LS/LF/project_finish/slack
    bit-exactly. Hand derivations are inline in ``_TWO_ACT_MATRIX``.
    """
    graph, durations = _make_two_activity_graph(link_type, lag)
    expected = _TWO_ACT_MATRIX[(link_type, lag)]

    result = run_batch(durations, graph, precision="float64")

    assert result["ES"][0, 0] == expected["ES_A"], "ES[A] mismatch"
    assert result["ES"][0, 1] == expected["ES_B"], "ES[B] mismatch"
    assert result["EF"][0, 0] == expected["EF_A"], "EF[A] mismatch"
    assert result["EF"][0, 1] == expected["EF_B"], "EF[B] mismatch"
    assert result["LS"][0, 0] == expected["LS_A"], "LS[A] mismatch"
    assert result["LS"][0, 1] == expected["LS_B"], "LS[B] mismatch"
    assert result["LF"][0, 0] == expected["LF_A"], "LF[A] mismatch"
    assert result["LF"][0, 1] == expected["LF_B"], "LF[B] mismatch"
    assert result["project_finish"][0] == expected["project_finish"]
    assert result["slack"][0, 0] == expected["slack_A"], "slack[A] mismatch"
    assert result["slack"][0, 1] == expected["slack_B"], "slack[B] mismatch"


@pytest.mark.parametrize(
    "link_type,lag",
    [
        (lt, lag)
        for lt in ("FS", "SS", "FF", "SF")
        for lag in (0.0, 8.0, -8.0)
    ],
)
def test_two_activity_link_type_matrix_float32_dtype(
    link_type: str, lag: float
) -> None:
    """Same parametrisation as the float64 matrix, but verifies the
    float32 default precision plumbs through on every link type / lag.

    Specifically catches the regression class identified in code review:
    ``EF[:, p] + lag`` where ``lag`` is a Python ``float`` would silently
    promote to float64 on the FF / SF / SS branches, allocating an
    undocumented ``(batch_n,)`` intermediate per candidate. This test
    fails noisily if an output array drifts off float32 OR if the
    integer-valued expected output drifts past CRITICAL_PATH_TOL.
    """
    graph, durations = _make_two_activity_graph(link_type, lag)
    expected = _TWO_ACT_MATRIX[(link_type, lag)]

    durations_f32 = durations.astype(np.float32)
    result = run_batch(durations_f32, graph, precision="float32")

    # Output dtype must be float32 across the precision-typed buffers.
    assert result["ES"].dtype == np.float32
    assert result["EF"].dtype == np.float32
    assert result["LS"].dtype == np.float32
    assert result["LF"].dtype == np.float32
    assert result["slack"].dtype == np.float32
    assert result["project_finish"].dtype == np.float32

    # Numeric correctness within CRITICAL_PATH_TOL — values are small
    # integers so float32 rounding is well below the tolerance.
    np.testing.assert_allclose(result["ES"][0, 0], expected["ES_A"], atol=1e-3)
    np.testing.assert_allclose(result["ES"][0, 1], expected["ES_B"], atol=1e-3)
    np.testing.assert_allclose(result["EF"][0, 0], expected["EF_A"], atol=1e-3)
    np.testing.assert_allclose(result["EF"][0, 1], expected["EF_B"], atol=1e-3)
    np.testing.assert_allclose(result["LS"][0, 0], expected["LS_A"], atol=1e-3)
    np.testing.assert_allclose(result["LS"][0, 1], expected["LS_B"], atol=1e-3)
    np.testing.assert_allclose(result["LF"][0, 0], expected["LF_A"], atol=1e-3)
    np.testing.assert_allclose(result["LF"][0, 1], expected["LF_B"], atol=1e-3)


# ---------------------------------------------------------------------------
# Three-activity coverage of the backward implied_finish + durations[:, j] term
# ---------------------------------------------------------------------------

class TestThreeActivityBackwardDurationTerm:
    """Three-activity graphs that exercise the ``+ durations[:, j]`` term in
    the backward implied_finish formula for Start-side outbound links.

    These tests cover the bug class the brief (§7) flags as the most
    likely failure: the duration-term sign on SS / SF in the backward
    pass.
    """

    def test_chain_A_SS_B_FS_C(self) -> None:
        """A SS B (lag=4) → B FS C. SS feeds the durations[:, j] backward path."""
        graph, durations = _make_three_activity_graph(
            links=[("A", "B", "SS", 4.0), ("B", "C", "FS", 0.0)],
            durations_by_id={"A": 8.0, "B": 12.0, "C": 6.0},
            topo_order=["A", "B", "C"],
        )
        result = run_batch(durations, graph, precision="float64")
        # Forward:
        # ES[A]=0; EF[A]=8.
        # ES[B] = max(0, ES[A]+4) = 4; EF[B] = 16.
        # ES[C] = max(0, EF[B]+0) = 16; EF[C] = 22.
        # project_finish = 22.
        np.testing.assert_array_equal(result["ES"][0], [0.0, 4.0, 16.0])
        np.testing.assert_array_equal(result["EF"][0], [8.0, 16.0, 22.0])
        # Backward:
        # LF[C]=22, LS[C]=16.
        # LF[B] = LS[C] - 0 = 16, LS[B] = 4.
        # LF[A]: A's only successor is B via SS lag=4 →
        #   implied_finish_A = LS[B] - 4 + dur_A = 4 - 4 + 8 = 8. LF[A]=8, LS[A]=0.
        np.testing.assert_array_equal(result["LS"][0], [0.0, 4.0, 16.0])
        np.testing.assert_array_equal(result["LF"][0], [8.0, 16.0, 22.0])
        np.testing.assert_array_equal(result["slack"][0], [0.0, 0.0, 0.0])

    def test_chain_A_SF_B_FS_C(self) -> None:
        """A SF B → B FS C. SF feeds the durations[:, j] backward path on A."""
        graph, durations = _make_three_activity_graph(
            links=[("A", "B", "SF", 0.0), ("B", "C", "FS", 0.0)],
            durations_by_id={"A": 8.0, "B": 12.0, "C": 6.0},
            topo_order=["A", "B", "C"],
        )
        result = run_batch(durations, graph, precision="float64")
        # Forward:
        # ES[B] from A SF lag=0: max(0, ES[A] - dur[B]) = max(0, -12) = 0; EF[B]=12.
        # ES[C] from B FS lag=0: 12; EF[C]=18.
        np.testing.assert_array_equal(result["ES"][0], [0.0, 0.0, 12.0])
        np.testing.assert_array_equal(result["EF"][0], [8.0, 12.0, 18.0])
        # Backward:
        # LF[C]=18, LS[C]=12.
        # LF[B] = LS[C] - 0 = 12, LS[B] = 0.
        # LF[A] via A SF B: implied_finish_A = LF[B] - 0 + dur_A = 12 + 8 = 20.
        # LF[A]=20, LS[A]=12. A has 12h slack from the SF link.
        np.testing.assert_array_equal(result["LS"][0], [12.0, 0.0, 12.0])
        np.testing.assert_array_equal(result["LF"][0], [20.0, 12.0, 18.0])
        np.testing.assert_array_equal(result["slack"][0], [12.0, 0.0, 0.0])

    def test_branch_A_FS_B_and_A_SS_C(self) -> None:
        """A has two successors (FS to B, SS to C). SS branch's contribution
        to A's implied_finish carries the durations[:, j] term but is NOT
        the binding constraint — FS branch wins. Verifies the min-over-
        successors comparison sees the correct duration-augmented value
        on the SS branch.
        """
        graph, durations = _make_three_activity_graph(
            links=[("A", "B", "FS", 0.0), ("A", "C", "SS", 0.0)],
            durations_by_id={"A": 8.0, "B": 10.0, "C": 4.0},
            topo_order=["A", "B", "C"],
        )
        result = run_batch(durations, graph, precision="float64")
        # Forward:
        # ES[B] = EF[A] = 8; EF[B] = 18.
        # ES[C] = ES[A] + 0 = 0; EF[C] = 4.
        # project_finish = 18.
        np.testing.assert_array_equal(result["ES"][0], [0.0, 8.0, 0.0])
        np.testing.assert_array_equal(result["EF"][0], [8.0, 18.0, 4.0])
        # Backward:
        # LF[B]=18, LS[B]=8.
        # LF[C]=18, LS[C]=14.
        # LF[A]:
        #   via B FS: implied_finish_A = LS[B] - 0 = 8.
        #   via C SS: implied_finish_A = LS[C] - 0 + dur_A = 14 + 8 = 22.
        #   min(8, 22) = 8. LF[A]=8, LS[A]=0.
        np.testing.assert_array_equal(result["LS"][0], [0.0, 8.0, 14.0])
        np.testing.assert_array_equal(result["LF"][0], [8.0, 18.0, 18.0])
        np.testing.assert_array_equal(result["slack"][0], [0.0, 0.0, 14.0])

    def test_branch_A_FF_B_and_A_SF_C(self) -> None:
        """A has FF outbound to B and SF outbound to C. SF carries the
        durations[:, j] term in implied_finish for A but the FF branch
        usually binds. Documents both candidates.
        """
        graph, durations = _make_three_activity_graph(
            links=[("A", "B", "FF", 0.0), ("A", "C", "SF", 0.0)],
            durations_by_id={"A": 8.0, "B": 10.0, "C": 4.0},
            topo_order=["A", "B", "C"],
        )
        result = run_batch(durations, graph, precision="float64")
        # Forward:
        # ES[B] via A FF lag=0: max(0, EF[A] - dur_B) = max(0, -2) = 0; EF[B]=10.
        # ES[C] via A SF lag=0: max(0, ES[A] - dur_C) = max(0, -4) = 0; EF[C]=4.
        # project_finish = max(8, 10, 4) = 10.
        np.testing.assert_array_equal(result["ES"][0], [0.0, 0.0, 0.0])
        np.testing.assert_array_equal(result["EF"][0], [8.0, 10.0, 4.0])
        # Backward:
        # LF[B]=10, LS[B]=0.
        # LF[C]=10, LS[C]=6.
        # LF[A]:
        #   via B FF: implied_finish_A = LF[B] - 0 = 10.
        #   via C SF: implied_finish_A = LF[C] - 0 + dur_A = 10 + 8 = 18.
        #   min(10, 18) = 10. LF[A]=10, LS[A]=2.
        np.testing.assert_array_equal(result["LS"][0], [2.0, 0.0, 6.0])
        np.testing.assert_array_equal(result["LF"][0], [10.0, 10.0, 10.0])
        np.testing.assert_array_equal(result["slack"][0], [2.0, 0.0, 6.0])

    def test_chain_A_FF_B_FF_C_with_lags(self) -> None:
        """FF chain with non-zero lags. Pure FF backward (no durations[:, j])."""
        graph, durations = _make_three_activity_graph(
            links=[("A", "B", "FF", 4.0), ("B", "C", "FF", 2.0)],
            durations_by_id={"A": 8.0, "B": 6.0, "C": 4.0},
            topo_order=["A", "B", "C"],
        )
        result = run_batch(durations, graph, precision="float64")
        # Forward:
        # ES[B] = max(0, EF[A] + 4 - dur_B) = max(0, 12 - 6) = 6; EF[B] = 12.
        # ES[C] = max(0, EF[B] + 2 - dur_C) = max(0, 14 - 4) = 10; EF[C] = 14.
        # project_finish = 14.
        np.testing.assert_array_equal(result["ES"][0], [0.0, 6.0, 10.0])
        np.testing.assert_array_equal(result["EF"][0], [8.0, 12.0, 14.0])
        # Backward:
        # LF[C]=14, LS[C]=10.
        # LF[B] = LF[C] - 2 = 12, LS[B] = 6.
        # LF[A] = LF[B] - 4 = 8, LS[A] = 0.
        np.testing.assert_array_equal(result["LS"][0], [0.0, 6.0, 10.0])
        np.testing.assert_array_equal(result["LF"][0], [8.0, 12.0, 14.0])
        np.testing.assert_array_equal(result["slack"][0], [0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Multi-batch consistency
# ---------------------------------------------------------------------------

def test_link_matrix_multi_iteration_consistency() -> None:
    """Each row of a multi-iteration batch matches the single-iteration result.

    Catches any cross-iteration leakage in the inner numpy operations
    (e.g., a bug that uses the wrong axis or aliases scratch buffers
    across rows).
    """
    graph, _ = _make_three_activity_graph(
        links=[("A", "B", "SS", 4.0), ("B", "C", "FS", 0.0)],
        durations_by_id={"A": 8.0, "B": 12.0, "C": 6.0},
        topo_order=["A", "B", "C"],
    )
    # Three iterations: rows 0 and 2 carry the gate fixture's durations,
    # row 1 carries doubled durations. Each row should produce the
    # arithmetic appropriate to that row in isolation.
    durations = np.array(
        [
            [8.0, 12.0, 6.0],   # iter 0
            [16.0, 24.0, 12.0], # iter 1: doubled
            [8.0, 12.0, 6.0],   # iter 2: same as iter 0
        ],
        dtype=np.float64,
    )
    result = run_batch(durations, graph, precision="float64")
    # Iter 0 and 2 must be identical (same input).
    np.testing.assert_array_equal(result["ES"][0], result["ES"][2])
    np.testing.assert_array_equal(result["EF"][0], result["EF"][2])
    np.testing.assert_array_equal(result["LS"][0], result["LS"][2])
    np.testing.assert_array_equal(result["LF"][0], result["LF"][2])
    # Iter 1 with doubled durations (lag is unchanged at 4):
    # ES[A]=0, EF[A]=16. ES[B] = max(0, ES[A]+4) = 4; EF[B] = 4+24 = 28.
    # ES[C] = EF[B]+0 = 28; EF[C] = 28+12 = 40.
    np.testing.assert_array_equal(result["ES"][1], [0.0, 4.0, 28.0])
    np.testing.assert_array_equal(result["EF"][1], [16.0, 28.0, 40.0])
