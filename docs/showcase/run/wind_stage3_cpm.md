# Tropic Ridge Wind Farm - Stage 3 CPM-Replay

CPM-replay over the 171-activity WTG schedule, 100,000 iterations, seed 42. **Pure-MC (AACE 65R-11 Mode-independent) basis: apply_mode_multipliers=False** - every Time-Impact risk injects its full sampled PERT delay and the CPM decides what reaches the finish date. Each schedule risk is auto-mapped to a single gating activity on the critical path, so the risk-driven spread (P95-P50 ~ 35 working days) reflects the additive PERT impacts, not over-binding.

> **What the CPM replay contributes on this schedule, stated plainly.** Every schedule risk here gates on an activity with **zero total float**, and each injects its delay as a discrete event at that gate. A delay at a zero-float activity extends the finish by exactly its own magnitude, so on this schedule the CPM replay is **arithmetically identical to summing the per-risk delays** - measured at 100,000 iterations, identical on every iteration. The replay is doing real work only where risks can land on float or on parallel paths, and on this schedule none do.

> **And the schedule's own shape flatters it.** This is a synthetic network: it carries no milestones and only finish-to-start logic with no lags, so it has far fewer convergence points than a real programme of the same scope. At a convergence point a successor waits for the *latest* of its predecessors, so a realistically logicked schedule would carry more merge bias than this one - which means the finish distribution above is, if anything, mildly optimistic.

## Project-finish P-bands (working days from project start)

| Metric | Project finish (working days) |
|---|---|
| MEAN | 632.7 |
| P50 | 631.3 |
| P80 | 649.1 |
| P90 | 658.7 |
| P95 | 666.7 |

## Schedule risks -> activities bound

| Risk | Activities bound |
|---|---|
| WT-001 | 11 |
| WT-002 | 1 |
| WT-008 | 11 |
| WT-009 | 1 |
| WT-020 | 10 |
| WT-021 | 1 |
| WT-026 | 1 |
| WT-027 | 1 |
| WT-031 | 11 |
| WT-032 | 10 |

## Deterministic critical path (first 20 activities)

- 1001
- 1002
- 1030
- 1044
- 1058
- 1072
- 1086
- 1100
- 1114
- 1128
- 1142
- 1156
- 1003
- 1004
- 1005
- 1006
- 1007
- 1008
- 1009
- 1010

## Top activities by criticality index

| Activity | Criticality |
|---|---|
| 1005 | 1.000 |
| 1006 | 1.000 |
| 1007 | 1.000 |
| 1008 | 1.000 |
| 1009 | 1.000 |
| 1010 | 1.000 |
| 1011 | 1.000 |
| 1012 | 1.000 |
| 1013 | 1.000 |
| 1014 | 1.000 |
| 1015 | 1.000 |
| 1016 | 1.000 |
| 1017 | 1.000 |
| 1018 | 1.000 |
| 1019 | 1.000 |
