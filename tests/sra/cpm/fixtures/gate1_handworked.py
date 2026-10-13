"""Validation Gate 1 — hand-worked CPM fixture (referee-able).

This file is the **single source of truth** for the SR-S3-Beta-03
Validation Gate 1 example. The expected ES / EF / LS / LF / slack
values below are derived **by hand**, with the working shown in this
docstring; the kernel must reproduce them bit-exactly under
``precision='float64'``. A reviewer can step through this docstring
without ever running the kernel and recompute every number.

Why this gate exists
--------------------
Stage 3 has no third-party CPM tool to cross-check against
(``STAGE3_ROADMAP.md`` §8). The hand-worked example is the only
independent verification of the forward + backward arithmetic for the
beta phase. Any silent off-by-one in any of the four link types
would propagate undetected through every Stage 3 simulation, so this
gate is treated as load-bearing.

Graph (7 activities, three of the four link types: FS / SS / FF;
mixed lag; two non-critical activities)
-----------------------------------------------------------------

SF coverage lives in :mod:`tests.sra.cpm.test_cpm_kernel_links`
(brief §6 acceptance criterion 5: all four link types covered with at
least three lag values each). SF rarely binds anything in a forward
CPM scenario — engineering it into the Gate-1 walkthrough adds
distraction without adding cover, so the per-link-type matrix tests
exercise it instead.

::

    Activity | Dur (h) | Predecessors                           | Notes
    ---------+---------+----------------------------------------+-----------------------
    A        |   8     | (none)                                 | root
    B        |  12     | A FS lag=0                             | non-critical (slack=2)
    C        |  20     | A FS lag=4                             | critical (FS+lag)
    D        |  16     | B FS lag=0, C SS lag=10                | critical (SS+lag binds)
    E        |  10     | C FF lag=0                             | non-critical (slack=6)
    F        |   8     | D FS lag=0, E FS lag=0                 | critical (D binds)
    G        |   6     | F FS lag=0                             | critical (sink)

Topological order: ``[A, B, C, D, E, F, G]``. Within ties, alphabetical
order is fine — the kernel only requires *a* valid topological order.

Forward pass (project_start = 0)
--------------------------------

Walk forward through the topo order. For each activity ``j`` and each
predecessor link, compute the implied start under that link's
constraint, take the max across links (and floor at 0), then
``EF = ES + duration``::

    A: no preds → ES = 0; EF = 0 + 8 = 8
    B: A FS lag=0 → implied_start = EF[A] + 0 = 8 → ES = 8; EF = 8 + 12 = 20
    C: A FS lag=4 → implied_start = EF[A] + 4 = 12 → ES = 12; EF = 12 + 20 = 32
    D: B FS lag=0  → implied_start = EF[B] + 0 = 20
       C SS lag=10 → implied_start = ES[C] + 10 = 12 + 10 = 22
       max(20, 22) = 22 → ES = 22; EF = 22 + 16 = 38
    E: C FF lag=0 → implied_start = EF[C] + 0 - dur[E] = 32 - 10 = 22
       → ES = 22; EF = 22 + 10 = 32
    F: D FS lag=0 → implied_start = EF[D] + 0 = 38
       E FS lag=0 → implied_start = EF[E] + 0 = 32
       max(38, 32) = 38 → ES = 38; EF = 38 + 8 = 46
    G: F FS lag=0 → implied_start = EF[F] + 0 = 46 → ES = 46; EF = 46 + 6 = 52

Project finish = max(EF) = 52.

Backward pass (project_finish = 52)
-----------------------------------

Walk backward through reversed(topo_order). For each activity ``j``
and each successor link, compute the implied finish under that
link's constraint, take the min across links (or anchor at
project_finish for sinks), then ``LS = LF - duration``::

    G: no successors → LF = 52; LS = 52 - 6 = 46
    F: G via FS lag=0 → implied_finish = LS[G] - 0 = 46 → LF = 46; LS = 46 - 8 = 38
    E: F via FS lag=0 → implied_finish = LS[F] - 0 = 38 → LF = 38; LS = 38 - 10 = 28
    D: F via FS lag=0 → implied_finish = LS[F] - 0 = 38 → LF = 38; LS = 38 - 16 = 22
    C: D via SS lag=10 → implied_finish = LS[D] - 10 + dur[C] = 22 - 10 + 20 = 32
       E via FF lag=0 → implied_finish = LF[E] - 0 = 38
       min(32, 38) = 32 → LF = 32; LS = 32 - 20 = 12
    B: D via FS lag=0 → implied_finish = LS[D] - 0 = 22 → LF = 22; LS = 22 - 12 = 10
    A: B via FS lag=0 → implied_finish = LS[B] - 0 = 10
       C via FS lag=4 → implied_finish = LS[C] - 4 = 12 - 4 = 8
       min(10, 8) = 8 → LF = 8; LS = 8 - 8 = 0

Slack = LS - ES (== LF - EF)
----------------------------

::

    A: 0  - 0  = 0   critical
    B: 10 - 8  = 2   non-critical (B's FS to D is non-binding because C SS lag=10 dominates)
    C: 12 - 12 = 0   critical
    D: 22 - 22 = 0   critical
    E: 28 - 22 = 6   non-critical (E's branch through C FF doesn't reach the F bottleneck)
    F: 38 - 38 = 0   critical
    G: 46 - 46 = 0   critical

Critical path: ``A → C → D → F → G``.
Non-critical: ``B`` (slack=2), ``E`` (slack=6).

Constants below are organised in topological order so reviewers can
read them in the same order the kernel processes them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Topological order — the kernel column convention follows this list,
# so any duration / expected-value array is indexed in this order.
TOPO_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G")


@dataclass(frozen=True)
class _LinkSpec:
    """Lightweight link descriptor for fixture-only use."""

    pred_id: str
    succ_id: str
    link_type: str
    lag_hours: float


# Per-activity duration in working hours, in topo order.
DURATIONS_HOURS: tuple[float, ...] = (
    8.0,   # A
    12.0,  # B
    20.0,  # C
    16.0,  # D
    10.0,  # E
    8.0,   # F
    6.0,   # G
)

# Precedence links. Each tuple is the predecessor activity's links
# *out* (i.e., this is just an enumeration of the seven directed edges
# in the network). The graph builder will distribute these across the
# corresponding Activity.predecessor_links and successor_links lists.
LINK_SPECS: tuple[_LinkSpec, ...] = (
    _LinkSpec("A", "B", "FS", 0.0),
    _LinkSpec("A", "C", "FS", 4.0),
    _LinkSpec("B", "D", "FS", 0.0),
    _LinkSpec("C", "D", "SS", 10.0),
    _LinkSpec("C", "E", "FF", 0.0),
    _LinkSpec("D", "F", "FS", 0.0),
    _LinkSpec("E", "F", "FS", 0.0),
    _LinkSpec("F", "G", "FS", 0.0),
)

# Hand-derived expected values, in topo order. See module docstring for
# the working-out. These must reproduce bit-exactly under
# precision='float64'.
EXPECTED_ES: tuple[float, ...] = (0.0, 8.0, 12.0, 22.0, 22.0, 38.0, 46.0)
EXPECTED_EF: tuple[float, ...] = (8.0, 20.0, 32.0, 38.0, 32.0, 46.0, 52.0)
EXPECTED_LS: tuple[float, ...] = (0.0, 10.0, 12.0, 22.0, 28.0, 38.0, 46.0)
EXPECTED_LF: tuple[float, ...] = (8.0, 22.0, 32.0, 38.0, 38.0, 46.0, 52.0)
EXPECTED_SLACK: tuple[float, ...] = (0.0, 2.0, 0.0, 0.0, 6.0, 0.0, 0.0)
EXPECTED_PROJECT_FINISH: float = 52.0
EXPECTED_ON_CRITICAL_PATH: tuple[bool, ...] = (
    True,   # A
    False,  # B (slack=2)
    True,   # C
    True,   # D
    False,  # E (slack=6)
    True,   # F
    True,   # G
)
