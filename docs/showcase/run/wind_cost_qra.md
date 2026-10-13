# Tropic Ridge Wind Farm - Cost QRA (Monte Carlo)

Illustrative showcase data. 35 risks, 100,000 iterations, seed 42. Contingency sits on the $50.0M Tropic Ridge Wind Farm capex (EPC $45M + grid connect $5M).

_Cost is the integrated engine's cost arm (jointly sampled with the Stage 3 schedule), so every cost figure in this showcase is consistent with the integrated headline. (Build note, not for client copy: the integrated engine does not yet model recurrence; WT-002 is therefore carried as single-occurrence in this showcase. The standalone cost engine models recurrence per AACE-style seasonal exposure and is the reference implementation; the two engines agree once WT-002 is single-occurrence. The capability gap is COST-01.)_

## Headline cost contingency (Layer-2 risk)

| Metric | Contingency | % of $50M capex |
|---|---|---|
| MEAN | $3.97M | 7.9% |
| P50 | $3.73M | 7.5% |
| P80 | $5.42M | 10.8% |
| P90 | $6.44M | 12.9% |
| P95 | $7.32M | 14.6% |

## Per-cost-group mean contribution

| CG | Mean EMV |
|---|---|
| CG01 | $0.74M |
| CG02 | $1.47M |
| CG03 | $0.39M |
| CG04 | $0.52M |
| CG05 | $0.37M |
| CG06 | $0.48M |

## Top risks by mean EMV (tornado)

| Risk | Description | CG | Mean EMV |
|---|---|---|---|
| WT-008 | WTG delivery delay (long-lead) | CG02 | $0.27M |
| WT-009 | Main crane mobilisation delay | CG02 | $0.27M |
| WT-012 | Erection weather standby | CG02 | $0.24M |
| WT-021 | Grid connection redesign | CG04 | $0.19M |
| WT-003 | Unforeseen ground conditions | CG01 | $0.19M |
| WT-014 | Major component warranty defect | CG02 | $0.17M |
| WT-031 | SCADA integration defects | CG06 | $0.17M |
| WT-011 | Tower section nonconformance | CG02 | $0.16M |
| WT-015 | Gearbox / main-bearing replacement | CG02 | $0.16M |
| WT-001 | Turbine foundation rework | CG01 | $0.15M |
| WT-005 | Bulk earthworks quantity overrun | CG01 | $0.14M |
| WT-032 | Turbine commissioning faults | CG06 | $0.14M |
