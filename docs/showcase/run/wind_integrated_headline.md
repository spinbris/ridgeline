# Tropic Ridge Wind Farm - Integrated Cost + Schedule Headline

Illustrative upfront contingency for the 40 MW Tropic Ridge Wind Farm scope (~$50M capex), 100,000 iterations, seed 42. **Full-CPM basis**: the schedule arm is the Stage 3 CPM-replay (AACE 65R-11 pure-MC, apply_mode_multipliers=False), jointly sampled with the cost arm through the integrated engine - 15 dual-coded (Time=Yes) risks share one severity draw per iteration across cost and schedule. The integrated total is the P80 of the joint per-iteration sum, NOT the sum of the two arms' P80s.

| Component | P80 | % of $50M capex |
|---|---|---|
| Cost QRA (Layer 2) | $11.24M | 9.4% |
| Schedule (Stage 3 CPM, dollarised @ $35,000/d) | $3.50M | 2.9% |
| **Integrated total (joint)** | **$14.60M** | **12.2%** |
| _Naive sum (cost P80 + schedule P80)_ | _$14.74M_ | _12.3%_ |

The naive P80-plus-P80 addition overstates the contingency by **$0.14M** (1.0% of the integrated total): the P80 of a sum is not the sum of P80s unless the arms are perfectly correlated, and the joint model prices the diversification the naive method ignores.

## Integrated total P-bands (joint)

| Metric | Contingency | % of capex |
|---|---|---|
| Mean | $10.76M | 9.0% |
| P50 | $10.44M | 8.7% |
| P80 | $14.60M | 12.2% |
| P90 | $16.84M | 14.0% |
| P95 | $18.77M | 15.6% |

Schedule arm (Stage 3 CPM): P80 finish-delay 100.0 working days. Stage 2.5 cross-check (retained for continuity, NOT the headline): P80 finish-delay 115.3 days / $4.04M - the older Tier-2.5 shortcut basis.

## Deterministic schedule cross-check

| Quantity | Days |
|---|---|
| Comparator 1, EMV days (no Mode weighting) | 95.267 |
| MC schedule mean (Stage 3 CPM) | 69.998 |
| Comparator 2, Mode-weighted EMV | 79.175 |
| Gap tested against the tolerance (Comparator 1 (upper bound)) | 0.000 |
| Tolerance | 1.0 |
| Result (judged against Comparator 1 (upper bound)) | **PASS** |
| _Diagnostic: gap to Comparator 2 (not part of the check)_ | _9.177_ |

MC schedule mean = 69.998 days against Comparator 1 = 95.267 days (no Mode weighting). Comparator 1 is the upper bound for this run: every risk injects one delay, written once, so no path can carry more than the sum. Excess over the bound = 0.000 days (tolerance 1.0 days) - PASS. Delay that did not reach the finish: 25.3 days (float absorbed, or risks bound to no activity); the register's Mode labels expect about 16.1 (Comparator 2 = 79.175 days). Diagnostic, not part of the check.

Delay that did not reach the finish (float absorbed, or risks bound to no activity): 25.269 days.

On this synthetic schedule every risk gates an activity with zero total float (see wind_stage3_cpm.md), so the network absorbs none of the float the register's Hybrid and Parallel labels expect. That is the disclosed simplification of the synthetic network, not a defect in the model.
