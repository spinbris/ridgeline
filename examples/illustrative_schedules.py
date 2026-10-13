"""
Build six illustrative schedules for stochastic schedule risk analysis training.

Each schedule isolates one effect. Run this script to emit MSPDI XML files
into ./mspdi/. Companion markdown notes describe the expected MC behaviour.

Numbering:
  L1a - Symmetric merge bias (5 activities)
  L1b - Asymmetric merge bias / criticality flip (6 activities)
  L2  - Near-critical path emergence (10 activities)
  L3  - Small construction project, parallel trades (24 activities)
  L4  - Mode classification demo, parallel/series/hybrid (12 activities)
  L5  - Active management - same network with status update midway (24 activities)
"""

from datetime import datetime
from pathlib import Path
from build_mspdi import Task, Schedule, write_schedule


START = datetime(2026, 6, 1)  # arbitrary Monday
OUT = Path(__file__).parent / "mspdi"


# -----------------------------------------------------------------------------
# L1a - Symmetric merge bias
# -----------------------------------------------------------------------------
# Two parallel paths of identical deterministic duration (20 days each), both
# converging on FINISH. Under CPM both are critical. Under MC with symmetric
# variance, E[max(A, B)] > max(E[A], E[B]) - the finish date pushes right,
# neither path is reliably critical, and a Tornado built against either single
# path mislabels the other path's activities as "not critical".
#
# Teaching point: merge bias is the simplest reason deterministic CPM is
# optimistic. Even with unbiased activity estimates, the project finishes late
# on average.

L1a = Schedule(
    name="L1a Symmetric Merge Bias",
    start_date=START,
    description="Two parallel paths, equal duration. Demonstrates merge bias.",
    tasks=[
        Task(uid=1, name="START", duration_days=0, predecessors=[]),
        Task(uid=2, name="A1 (path A, part 1)", duration_days=10, predecessors=[1],
             notes="Triangular(7, 10, 13)"),
        Task(uid=3, name="A2 (path A, part 2)", duration_days=10, predecessors=[2],
             notes="Triangular(7, 10, 13)"),
        Task(uid=4, name="B1 (path B, part 1)", duration_days=10, predecessors=[1],
             notes="Triangular(7, 10, 13)"),
        Task(uid=5, name="B2 (path B, part 2)", duration_days=10, predecessors=[4],
             notes="Triangular(7, 10, 13)"),
        Task(uid=6, name="FINISH", duration_days=0, predecessors=[3, 5]),
    ],
)


# -----------------------------------------------------------------------------
# L1b - Asymmetric merge bias - criticality flip
# -----------------------------------------------------------------------------
# Path A is longer but low-variance (e.g. well-understood site works).
# Path B is shorter but high-variance (e.g. long-lead procurement with
# vendor risk). Deterministic critical path is A. Under MC, B becomes
# critical a meaningful fraction of the time.
#
# Teaching point: criticality index is what matters for risk management,
# not float. A near-zero-float path can dominate when its variance is high.

L1b = Schedule(
    name="L1b Criticality Flip",
    start_date=START,
    description="One long-low-variance path, one short-high-variance path. "
                "Deterministic CP differs from stochastic dominant path.",
    tasks=[
        Task(uid=1, name="START", duration_days=0),
        Task(uid=2, name="A1 Site works (low variance)", duration_days=12, predecessors=[1],
             notes="Suggest Triangular(10, 12, 14) - tight range"),
        Task(uid=3, name="A2 Foundations (low variance)", duration_days=14, predecessors=[2],
             notes="Suggest Triangular(12, 14, 17) - tight range"),
        Task(uid=4, name="B1 Long-lead procurement (high variance)",
             duration_days=10, predecessors=[1],
             notes="Suggest Triangular(6, 10, 30) - heavily right-skewed"),
        Task(uid=5, name="B2 Vendor manufacture (high variance)",
             duration_days=12, predecessors=[4],
             notes="Suggest Triangular(8, 12, 25) - heavily right-skewed"),
        Task(uid=6, name="FINISH", duration_days=0, predecessors=[3, 5]),
    ],
)


# -----------------------------------------------------------------------------
# L2 - Near-critical path emerges
# -----------------------------------------------------------------------------
# Deterministic critical path is A1-A2-A3 (30 days). Path B (B1-B2-B3, 24 days)
# has 6 days of total float. Under deterministic analysis you ignore B.
# Under MC with modest variance, B's criticality index can climb to 30-50%,
# meaning a third to a half of the time B drives the finish date.
#
# Teaching point: float is a deterministic concept. Use criticality index
# from MC to identify what to actively manage.

L2 = Schedule(
    name="L2 Near Critical Path",
    start_date=START,
    description="One critical path, one near-critical path with float. "
                "Demonstrates criticality index vs deterministic float.",
    tasks=[
        Task(uid=1, name="START", duration_days=0),
        Task(uid=2, name="A1 Design (critical)", duration_days=10, predecessors=[1],
             notes="Triangular(8, 10, 14)"),
        Task(uid=3, name="A2 Procurement (critical)", duration_days=10, predecessors=[2],
             notes="Triangular(8, 10, 14)"),
        Task(uid=4, name="A3 Install (critical)", duration_days=10, predecessors=[3],
             notes="Triangular(8, 10, 14)"),
        Task(uid=5, name="B1 Permit (float 6d)", duration_days=8, predecessors=[1],
             notes="Triangular(6, 8, 14) - higher variance than A"),
        Task(uid=6, name="B2 Sitework (float 6d)", duration_days=8, predecessors=[5],
             notes="Triangular(6, 8, 14)"),
        Task(uid=7, name="B3 Fence and signage (float 6d)", duration_days=8, predecessors=[6],
             notes="Triangular(6, 8, 14)"),
        Task(uid=8, name="C1 Documentation", duration_days=5, predecessors=[1],
             notes="Triangular(4, 5, 7) - large float, low variance, ignore"),
        Task(uid=9, name="C2 Reporting", duration_days=5, predecessors=[8],
             notes="Triangular(4, 5, 7)"),
        Task(uid=10, name="FINISH", duration_days=0, predecessors=[4, 7, 9]),
    ],
)


# -----------------------------------------------------------------------------
# L3 - Small construction project (24 activities, multi-trade parallel)
# -----------------------------------------------------------------------------
# Modelled on a small commercial fit-out. Three parallel trades (electrical,
# mechanical, hydraulic) running through frame and pre-fit-out, then merging
# at services commissioning. Then fit-out, then handover.
#
# Teaching points:
#   - Realistic merge bias at "services commissioning" (3-way merge)
#   - Tornado chart can be built against MC results, not deterministic CP
#   - Criticality concentrates in the long-lead trade typically
#   - Good case for showing baseline P50/P80 then re-running mid-project

L3 = Schedule(
    name="L3 Small Construction",
    start_date=START,
    description="24-activity small commercial fit-out with three parallel "
                "trade chains converging at commissioning.",
    tasks=[
        # Mobilisation
        Task(uid=1, name="START", duration_days=0),
        Task(uid=2, name="Mobilisation", duration_days=5, predecessors=[1]),
        Task(uid=3, name="Site setup and hoarding", duration_days=4, predecessors=[2]),
        # Frame
        Task(uid=4, name="Strip-out existing", duration_days=8, predecessors=[3]),
        Task(uid=5, name="Frame and partitions", duration_days=12, predecessors=[4]),
        Task(uid=6, name="Ceiling grid", duration_days=6, predecessors=[5]),
        # Electrical chain
        Task(uid=10, name="Elec design fix", duration_days=5, predecessors=[3]),
        Task(uid=11, name="Elec rough-in", duration_days=10, predecessors=[5, 10]),
        Task(uid=12, name="Elec switchboard install", duration_days=6, predecessors=[11]),
        Task(uid=13, name="Elec terminations", duration_days=5, predecessors=[12]),
        # Mechanical chain
        Task(uid=20, name="Mech design fix", duration_days=5, predecessors=[3]),
        Task(uid=21, name="Mech ductwork", duration_days=12, predecessors=[5, 20]),
        Task(uid=22, name="Mech plant install", duration_days=8, predecessors=[21]),
        Task(uid=23, name="Mech controls", duration_days=4, predecessors=[22]),
        # Hydraulic chain
        Task(uid=30, name="Hyd design fix", duration_days=4, predecessors=[3]),
        Task(uid=31, name="Hyd rough-in", duration_days=8, predecessors=[5, 30]),
        Task(uid=32, name="Hyd fixtures", duration_days=5, predecessors=[31]),
        # Commissioning (3-way merge)
        Task(uid=40, name="Services commissioning", duration_days=6,
             predecessors=[13, 23, 32]),
        # Fit-out
        Task(uid=50, name="Ceiling install", duration_days=4, predecessors=[6, 40]),
        Task(uid=51, name="Floor finishes", duration_days=6, predecessors=[40]),
        Task(uid=52, name="Joinery and fittings", duration_days=8, predecessors=[50, 51]),
        Task(uid=53, name="Paint and finishes", duration_days=5, predecessors=[52]),
        # Handover
        Task(uid=60, name="Defects and clean", duration_days=4, predecessors=[53]),
        Task(uid=61, name="Handover and PC", duration_days=0, predecessors=[60]),
    ],
)


# -----------------------------------------------------------------------------
# L4 - Mode classification demo (Series / Parallel / Hybrid)
# -----------------------------------------------------------------------------
# Crafted to expose how a single risk's impact differs based on whether the
# affected activities are on a single chain (Series), parallel chains (Parallel)
# with the longest dominating, or a mix (Hybrid). One risk affects three
# activities; the network topology determines the schedule effect.
#
# Teaching point: the RefProject mode_multiplier (Series=1.0, Hybrid=~0.6,
# Parallel=~0.3) is a topology-aware proxy for the actual schedule arithmetic.
# This case lets you compare against full per-iteration computation.

L4 = Schedule(
    name="L4 Mode Classification Demo",
    start_date=START,
    description="Network designed to expose Series vs Parallel vs Hybrid "
                "mode effects when one risk hits three activities.",
    tasks=[
        Task(uid=1, name="START", duration_days=0),
        # Three activities the same risk affects
        Task(uid=2, name="RISK-AFFECTED-1 (procurement A)", duration_days=10,
             predecessors=[1], notes="Affected by Risk R001"),
        Task(uid=3, name="RISK-AFFECTED-2 (procurement B)", duration_days=10,
             predecessors=[1], notes="Affected by Risk R001"),
        Task(uid=4, name="RISK-AFFECTED-3 (procurement C)", duration_days=10,
             predecessors=[1], notes="Affected by Risk R001"),
        # Series leg - one risk-affected activity in line
        Task(uid=5, name="Series leg downstream of #2", duration_days=15, predecessors=[2]),
        # Parallel leg - two risk-affected, longest wins
        Task(uid=6, name="Parallel merge after #3 and #4", duration_days=0,
             predecessors=[3, 4]),
        Task(uid=7, name="Downstream of parallel merge", duration_days=15,
             predecessors=[6]),
        # Hybrid leg - extra unaffected activity
        Task(uid=8, name="Unaffected mid-task", duration_days=8, predecessors=[1]),
        Task(uid=9, name="Hybrid merge", duration_days=0, predecessors=[5, 7, 8]),
        Task(uid=10, name="Common downstream", duration_days=10, predecessors=[9]),
        Task(uid=11, name="Final task", duration_days=5, predecessors=[10]),
        Task(uid=12, name="FINISH", duration_days=0, predecessors=[11]),
    ],
)


# -----------------------------------------------------------------------------
# L5 - Active management - L3 with mid-project status update
# -----------------------------------------------------------------------------
# Same network as L3, but with %-complete and actual durations populated as
# if it were week 10 of the project. Some activities done, some in-progress,
# one delay realised on the electrical chain.
#
# Teaching point: rerun the MC with these as fixed/in-progress and the
# criticality picture changes. The Tornado at week 10 looks different to
# week 0. This is how SRA supports active management, not just baseline-day
# decisions.

L5 = Schedule(
    name="L5 Active Management Week 10",
    start_date=START,
    description="L3 network re-statused at week 10. Frame complete, "
                "electrical delayed, mechanical on track. Re-run MC to "
                "see updated criticality.",
    tasks=[
        # Completed activities (notes record actuals - the engine would
        # treat these as fixed-zero-variance in a re-baselined MC)
        Task(uid=1, name="START", duration_days=0,
             notes="ACTUAL FINISH: day 0"),
        Task(uid=2, name="Mobilisation [DONE]", duration_days=5, predecessors=[1],
             notes="ACTUAL: 5 days. Treat as deterministic."),
        Task(uid=3, name="Site setup and hoarding [DONE]", duration_days=4, predecessors=[2],
             notes="ACTUAL: 4 days. Treat as deterministic."),
        Task(uid=4, name="Strip-out existing [DONE]", duration_days=10, predecessors=[3],
             notes="ACTUAL: 10 days (planned 8, +2d slip). Deterministic."),
        Task(uid=5, name="Frame and partitions [DONE]", duration_days=14, predecessors=[4],
             notes="ACTUAL: 14 days (planned 12, +2d slip). Deterministic."),
        Task(uid=6, name="Ceiling grid [IN-PROG 50%]", duration_days=6, predecessors=[5],
             notes="Remaining duration ~3 days. Reduce variance accordingly."),
        # Electrical chain - delayed
        Task(uid=10, name="Elec design fix [DONE]", duration_days=7, predecessors=[3],
             notes="ACTUAL: 7 days (planned 5, +2d slip)."),
        Task(uid=11, name="Elec rough-in [IN-PROG 70%]", duration_days=12, predecessors=[5, 10],
             notes="Planned 10, now 12 estimated. Remaining ~4 days."),
        Task(uid=12, name="Elec switchboard install", duration_days=6, predecessors=[11],
             notes="Forward-looking. Triangular(5, 6, 9)."),
        Task(uid=13, name="Elec terminations", duration_days=5, predecessors=[12],
             notes="Triangular(4, 5, 7)."),
        # Mechanical - on track
        Task(uid=20, name="Mech design fix [DONE]", duration_days=5, predecessors=[3],
             notes="ACTUAL: 5 days."),
        Task(uid=21, name="Mech ductwork [IN-PROG 60%]", duration_days=12, predecessors=[5, 20],
             notes="On track. Remaining ~5 days."),
        Task(uid=22, name="Mech plant install", duration_days=8, predecessors=[21],
             notes="Triangular(6, 8, 11)."),
        Task(uid=23, name="Mech controls", duration_days=4, predecessors=[22],
             notes="Triangular(3, 4, 6)."),
        # Hydraulic - on track
        Task(uid=30, name="Hyd design fix [DONE]", duration_days=4, predecessors=[3],
             notes="ACTUAL: 4 days."),
        Task(uid=31, name="Hyd rough-in [IN-PROG 80%]", duration_days=8, predecessors=[5, 30],
             notes="Remaining ~2 days."),
        Task(uid=32, name="Hyd fixtures", duration_days=5, predecessors=[31],
             notes="Triangular(4, 5, 7)."),
        # Forward-looking remainder
        Task(uid=40, name="Services commissioning", duration_days=6,
             predecessors=[13, 23, 32], notes="Triangular(5, 6, 10)."),
        Task(uid=50, name="Ceiling install", duration_days=4, predecessors=[6, 40]),
        Task(uid=51, name="Floor finishes", duration_days=6, predecessors=[40]),
        Task(uid=52, name="Joinery and fittings", duration_days=8, predecessors=[50, 51]),
        Task(uid=53, name="Paint and finishes", duration_days=5, predecessors=[52]),
        Task(uid=60, name="Defects and clean", duration_days=4, predecessors=[53]),
        Task(uid=61, name="Handover and PC", duration_days=0, predecessors=[60]),
    ],
)


if __name__ == "__main__":
    for sched in [L1a, L1b, L2, L3, L4, L5]:
        path = write_schedule(sched, OUT)
        print(f"Wrote {path} ({len(sched.tasks)} tasks)")
