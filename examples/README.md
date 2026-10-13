# Illustrative Schedules for Stochastic Schedule Risk Analysis

A set of six purpose-built test networks for demonstrating the key concepts of
quantitative schedule risk analysis. Each schedule isolates one effect so the
mechanism is visible without being buried in scale.

All files are MSPDI XML (Microsoft Project 2007 XML Data Interchange format).
They open natively in Microsoft Project, ProjectLibre, and via MPXJ in any
Python pipeline. Durations are in working days on a standard 5-day, 8-hour
calendar starting Monday 1 June 2026.

The MC numbers below come from 20,000 iterations with the seed-42 RNG using
the Triangular distributions noted on each task. Re-running with different
seeds or sample sizes will give slightly different point estimates but the
qualitative effects are stable.

---

## L1a - Symmetric Merge Bias (6 tasks)

**File:** `mspdi/l1a_symmetric_merge_bias.xml`
**Deterministic finish:** 20 days
**MC mean:** 20.99 days  |  **P50:** 21.00  |  **P80:** 22.22  |  **P90:** 22.82

Two parallel paths, each with two activities of 10 days planned duration,
converging on FINISH. Under CPM both paths are tied at 0 float, both are
"critical". Under MC with a symmetric Triangular(7, 10, 13) on each activity,
the project finishes 0.99 days late on average.

**What it shows:**
- The simplest demonstration of merge bias.
- Each individual activity has an unbiased mean of its planned duration,
  yet the project mean exceeds the planned 20 days.
- E[max(A, B)] > max(E[A], E[B]) by construction whenever A and B are
  not perfectly correlated.
- Criticality is 50/50 between the two paths - exactly what you would
  expect, and exactly what deterministic CPM cannot tell you.

**Why the reader cares:** This is why deterministic CPM is structurally
optimistic. Even with perfect activity estimates, the project mean
finish date is later than the CPM finish date as soon as you have
parallel paths converging.

---

## L1b - Criticality Flip (6 tasks)

**File:** `mspdi/l1b_criticality_flip.xml`
**Deterministic finish:** 26 days
**MC mean:** 31.32 days  |  **P50:** 29.87  |  **P80:** 35.87  |  **P90:** 39.10

Path A is the deterministic critical path (Site works 12d, then Foundations
14d = 26d) with low variance. Path B is shorter on planned duration (10d + 12d
= 22d) but heavily right-skewed - long-lead procurement and vendor
manufacture with credible bad-case outcomes well above plan.

**What it shows:**
- Deterministic CP: A. Stochastic criticality: B (70.4% vs A's 29.7%).
- The deterministic-critical activities A1 and A2 are not the ones to
  actively manage. B1 and B2 are. A Tornado built against the CPM critical
  path would point you at the wrong activities.
- Bias is now substantial: mean is 5.32 days above deterministic finish,
  P80 is 9.87 days above.

**Why the reader cares:** Float is a deterministic concept. Criticality
index is the stochastic generalisation, and it is what should drive risk
management priorities. An activity with low float but tight variance
matters less than one with modest float but big variance.

---

## L2 - Near-Critical Path Emergence (10 tasks)

**File:** `mspdi/l2_near_critical_path.xml`
**Deterministic finish:** 30 days
**MC mean:** 32.26 days  |  **P50:** 32.19  |  **P80:** 34.00  |  **P90:** 35.00

Three chains: A (3 x 10d, critical), B (3 x 8d, 6 days of total float),
C (2 x 5d, 20 days of total float). All Triangular(0.8mean, mean, 1.4mean).

**What it shows:**
- Criticality indices: A = 86.3%, B = 13.9%, C = 0.0%.
- B emerges as a meaningful contributor under uncertainty despite having
  6 days of deterministic float. C, with 20 days of float and low absolute
  duration, never drives the finish date.
- The "near-critical" threshold for active monitoring should be set on
  criticality index (say, anything above 5-10%), not on float.

**Why the reader cares:** PMs often draw a hard line between "critical
path" and "everything else". That bright line dissolves under uncertainty.
A schedule with three chains may have one that always matters, one that
matters a third of the time, and one that never matters - which is far
more useful guidance than a single critical-path flag.

---

## L3 - Small Construction Project (24 tasks)

**File:** `mspdi/l3_small_construction.xml`
**Deterministic finish:** 82 days
**MC mean:** 83.38 days  |  **P50:** 83.37  |  **P80:** 85.34  |  **P90:** 86.39

A small commercial fit-out with mobilisation, frame, three parallel trade
chains (electrical, mechanical, hydraulic) converging at services
commissioning, then finishes and handover. 24 activities, 30 dependencies,
three-way merge at the commissioning point.

**What it shows:**
- Mechanical chain (ductwork → plant → controls) is the 96% critical
  chain through to commissioning. Electrical is at ~4%. Hydraulic is at 0%.
- All three trade design-fix activities sit at 0% criticality because
  the frame work dominates the start of every chain.
- Once at commissioning, finish-side activities (floor finishes, joinery,
  paint, defects, PC) are all 100% critical - single-string handover
  sequence.

**Why the reader cares:**
- A realistic small network where the merge effects, near-critical paths,
  and tornado outputs all become recognisable.
- Big enough to be interesting, small enough to read in one page.
- A natural baseline for showing the active-management story (see L5).

---

## L4 - Mode Classification Demo (12 tasks)

**File:** `mspdi/l4_mode_classification_demo.xml`
**Deterministic finish:** 40 days
**MC mean:** 41.88 days  |  **P50:** 41.87  |  **P80:** 43.34  |  **P90:** 44.10

A network specifically designed so that one risk (R001) affecting three
activities can be analysed under each Mode topology in isolation:

- **Series leg:** R001 → activity #2 → downstream activity #5 (one chain).
  If R001 fires, the full impact lands on this leg's finish.
- **Parallel leg:** R001 → activities #3 and #4 in parallel → merge → #7.
  If R001 fires equally on #3 and #4, the parallel merge means the impact
  is realised once, not twice.
- **Hybrid leg:** Same R001 hits both, plus an unaffected mid-task with float.

**What it shows:**
- Series-leg activities (#2, #5) have ~41% criticality.
- Parallel-merge activities (#6, #7) have ~60% criticality - higher
  because they sit at a confluence.
- This is the cleanest controlled experiment for validating the
  RefProject mode_multiplier values. Run the same risk through each leg
  in isolation and you can directly observe the impact arithmetic.

**Why the reader cares:** Mode classification is the most contested part
of the RefProject methodology. This network gives you a defensible
demonstration case where the Series / Parallel / Hybrid impact ratios can
be measured directly per-iteration, then compared against the
mode_multiplier pass-through coefficients.

---

## L5 - Active Management: L3 at Week 10 (24 tasks)

**File:** `mspdi/l5_active_management_week_10.xml`
**Deterministic finish:** 86 days (vs L3 baseline 82, +4 day slip)

The L3 network restatused as if at week 10 of execution:
- Mobilisation, site setup, strip-out, frame, design-fix for all three
  trades, hyd design fix: **COMPLETE**.
- Strip-out ran 10 days vs planned 8.
- Frame ran 14 days vs planned 12.
- Electrical design fix ran 7 days vs planned 5.
- Ceiling grid, electrical rough-in, mechanical ductwork, hydraulic
  rough-in: **IN-PROGRESS**.
- Everything from switchboard install onwards: **FORWARD-LOOKING**.

**What it shows:**
- A 4-day deterministic slip has already been realised. The week-10
  critical path is still mechanical-dominant but the electrical chain
  has tightened (1 day of float vs original 3).
- Rerunning MC on this status snapshot gives a different criticality
  picture, different Tornado, and a different P80.
- Completed activities should be set to deterministic (zero variance);
  in-progress activities should have variance scaled to remaining
  duration only; forward-looking activities retain full distributions.

**Why the reader cares:** This is the active-management story. Baseline
SRA is useful for go/no-go and contingency-setting. SRA rerun at each
status period is what tells the PM what to act on this week. The
mechanical chain held its dominance, but the electrical chain narrowed -
which is where attention should now go.

---

## How to use these in the methodology paper

A suggested narrative arc:

1. **Open with L1a** to establish that deterministic CPM is structurally
   optimistic - a one-page demonstration with two paths.
2. **L1b and L2** in the section on criticality index vs float, showing
   why deterministic CP is the wrong list to manage.
3. **L3 baseline** as the worked example for the full MC workflow:
   inputs, MC outputs, Tornado, P50/P80, criticality table.
4. **L4** in the appendix on mode classification - a controlled
   experiment isolating Series/Parallel/Hybrid behaviour.
5. **L5** in the active-management section, demonstrating how SRA
   continues to add value through execution, not just at baseline.
6. **RefProject at scale** as the production validation - the methodology
   that works clearly on 12 activities also works on 1,959.

---

## Files

```
test_schedules/
├── build_mspdi.py             # Shared XML builder (MSPDI format)
├── illustrative_schedules.py  # Six schedule definitions, builds XML
├── cpm_solve.py               # Pure-Python CPM verification
├── mc_simulate.py             # Tiny MC simulator for verification
├── README.md                  # This file
└── mspdi/
    ├── l1a_symmetric_merge_bias.xml
    ├── l1b_criticality_flip.xml
    ├── l2_near_critical_path.xml
    ├── l3_small_construction.xml
    ├── l4_mode_classification_demo.xml
    └── l5_active_management_week_10.xml
```

All MSPDI files load directly into ProjectLibre, MS Project, or any MPXJ
pipeline. The Python files are self-contained, requiring only numpy.
