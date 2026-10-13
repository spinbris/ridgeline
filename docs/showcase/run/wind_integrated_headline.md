# Tropic Ridge Wind Farm - Integrated Cost + Schedule Headline

Illustrative upfront contingency for the 40 MW Tropic Ridge Wind Farm scope (~$50M capex), 100,000 iterations, seed 42. **Full-CPM basis**: the schedule arm is the Stage 3 CPM-replay (AACE 65R-11 pure-MC, apply_mode_multipliers=False), jointly sampled with the cost arm through the integrated engine - 10 dual-coded (Time=Yes) risks share one severity draw per iteration across cost and schedule. The integrated total is the P80 of the joint per-iteration sum, NOT the sum of the two arms' P80s.

| Component | P80 | % of $50M capex |
|---|---|---|
| Cost QRA (Layer 2) | $5.42M | 10.8% |
| Schedule (Stage 3 CPM, dollarised @ $35,000/d) | $2.13M | 4.3% |
| **Integrated total (joint)** | **$7.48M** | **15.0%** |
| _Naive sum (cost P80 + schedule P80)_ | _$7.55M_ | _15.1%_ |

The naive P80-plus-P80 addition overstates the contingency by **$0.07M** (1.0% of the integrated total): the P80 of a sum is not the sum of P80s unless the arms are perfectly correlated, and the joint model prices the diversification the naive method ignores.

## Integrated total P-bands (joint)

| Metric | Contingency | % of capex |
|---|---|---|
| Mean | $5.46M | 10.9% |
| P50 | $5.22M | 10.4% |
| P80 | $7.48M | 15.0% |
| P90 | $8.76M | 17.5% |
| P95 | $9.82M | 19.6% |

Schedule arm (Stage 3 CPM): P80 finish-delay 61.0 working days. Stage 2.5 cross-check (retained for continuity, NOT the headline): P80 finish-delay 47.0 days / $1.65M - the older Tier-2.5 shortcut basis.

## Deterministic schedule cross-check

| Quantity | Days |
|---|---|
| Comparator 1, EMV days (no Mode weighting) | 42.633 |
| MC schedule mean (Stage 3 CPM) | 42.678 |
| Comparator 2, Mode-weighted EMV | 32.046 |
| Absolute gap | 10.632 |
| Tolerance | 1.0 |
| Result | **FAIL** |

MC schedule mean = 42.678 days vs deterministic Comparator 2 = 32.046 days. Absolute gap = 10.632 days (tolerance 1.0 days) - FAIL. Comparator 2 is the register's Mode-weighted expected-value sum, a closed-form estimate of finish-date slippage; the MC mean is the same quantity derived from the CPM network. Agreement inside tolerance means the Mode classification and the network price float the same way. The MC mean sits outside the Comparator 1 (42.633 days) to Comparator 2 bracket, which the two comparators should span; treat the Mode classification or the network binding as suspect before the tolerance.
