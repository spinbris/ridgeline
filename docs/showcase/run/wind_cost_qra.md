# Tropic Ridge Wind Farm - Cost QRA (Monte Carlo)

Illustrative showcase data. 29 risks, 100,000 iterations, seed 42. Contingency sits on the $50.0M Tropic Ridge Wind Farm capex (EPC $45M + grid connect $5M).

_Cost is the integrated engine's cost arm (jointly sampled with the Stage 3 schedule), so every cost figure in this showcase is consistent with the integrated headline. (Build note, not for client copy: the integrated engine does not yet model recurrence; WT-002 is therefore carried as single-occurrence in this showcase. The standalone cost engine models recurrence per AACE-style seasonal exposure and is the reference implementation; the two engines agree once WT-002 is single-occurrence. The capability gap is COST-01.)_

## Headline cost contingency (Layer-2 risk)

| Metric | Contingency | % of $50M capex |
|---|---|---|
| MEAN | $8.07M | 6.7% |
| P50 | $7.77M | 6.5% |
| P80 | $10.97M | 9.1% |
| P90 | $12.76M | 10.6% |
| P95 | $14.32M | 11.9% |

## Per-cost-group mean contribution

| CG | Mean EMV |
|---|---|
| CG01 | $1.77M |
| CG02 | $2.72M |
| CG03 | $0.71M |
| CG04 | $1.25M |
| CG05 | $0.87M |
| CG06 | $0.74M |

## Top risks by mean EMV (tornado)

| Risk | Description | CG | Mean EMV |
|---|---|---|---|
| WT-008 | WTG delivery delay (long-lead) | CG02 | $0.65M |
| WT-009 | Main crane mobilisation delay | CG02 | $0.64M |
| WT-012 | Erection weather standby | CG02 | $0.58M |
| WT-021 | Grid connection redesign | CG04 | $0.46M |
| WT-003 | Unforeseen ground conditions | CG01 | $0.45M |
| WT-031 | SCADA integration defects | CG06 | $0.40M |
| WT-011 | Tower section nonconformance | CG02 | $0.39M |
| WT-001 | Turbine foundation rework | CG01 | $0.36M |
| WT-005 | Bulk earthworks quantity overrun | CG01 | $0.34M |
| WT-032 | Turbine commissioning faults | CG06 | $0.34M |
| WT-022 | Network operator approval delay | CG04 | $0.31M |
| WT-016 | Array cable supply shortfall | CG03 | $0.30M |
