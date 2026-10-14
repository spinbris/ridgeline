# METHODOLOGY

Quantitative risk analysis for capital projects. This document describes the methodology of each of the four analytical components and how they combine into the integrated solution. It is the methodology reference for the codebase; for the run-time how-to see `README.md` and `docs/PLAYBOOK.md`, and for the module layout see `ARCHITECTURE.md`.

The methodology framework is anchored in two aligned industry references: **AACE International 132R-23 — *Schedule Risk Analysis Maturity Model*** (May 2024) and the Australian Department of Infrastructure *Cost Estimation Guidance Notes* v2.0 (November 2023), particularly **Guidance Note 3A — Probabilistic Contingency Estimation** and its supplementary guidance. The two frameworks describe the same progression of analytical sophistication using different shorthand (AACE 132R-23 maturity Levels 0-5 ↔ GN3A Risk Factor Models 1-4); under either reading, the headline runs at **Stage 3**: a Monte Carlo simulation of the project's CPM schedule, re-levelled every iteration - the Level 3 / Risk Factor Model 3 engine - with three stated gaps that keep the method short of full Level 3 / Model 3: risk-to-activity bindings are auto-mapped rather than workshop-validated, a single project-default calendar is used, and the schedule's duration distribution does not feed the cost model (cost and schedule are joint-sampled marginals, with the schedule dollarised at the project's day rate). An earlier, simpler approximation, **Stage 2.5**, is retained beside it as a labelled comparator. Section 7 below sets out the framework alignment in detail.

GN3A sets non-negotiables for probabilistic contingency: Monte Carlo simulation, P50/P90 confidence levels, correlation between risks modelled, ≥5,000-10,000 iterations, and the S-curve and tornado as primary outputs. Sections 3 and 6 describe how each is carried.

**Scope, stated once so no reader has to infer it.** Australian Government cost-estimation
guidance is built on `base estimate + contingency + escalation`. **The base estimate is an
input**: this is not an estimating tool. **The owner view's distribution of base plus contingency
is an output** - Layer-1 systemic uncertainty sampled on the input base. **The deliverable
presents the event-risk contingency**: its P-values are risk-driven cost *above* the base
estimate, in real terms at the estimator's base date, and are never called an outturn.
Escalation is a documented hand-off. Where a headline is labelled, it is labelled as contingency
for that reason.

---

## 1. Inputs and the single-source-of-truth principle

All four components consume from three locked input files. No layer maintains its own copy of probabilities, durations, costs, or distributions. Drift between layers is prevented by construction.

| Source | Path | Layers that read it |
|---|---|---|
| Risk register (`.xlsx`) | The active project's, from its binding | All four |
| P6 schedule export (`.xer`, with a longest-path `.xlsx` subset for Stage 2.5) | The active project's, from its binding | Deterministic SRA, MC SRA, Integrated |
| SRA strawman (`.xlsx`) | The active project's, from its binding | Deterministic SRA, MC SRA, Integrated |

The register sheets relevant to each layer are:

- *Risk Register* — every risk's identity, scoring, treatment, and quantitative parameters. Its row and column counts are the project's own; the readers look every column up by its header, never by position
- *EMV Summary*, *EMV Tornado*, *Risk Matrix*, *Top 20*, *Pareto Analysis*, *Risk Analysis* — deterministic QRA output sheets
- *Variables* — commercial parameters (day rate basis, weekly prelims, programme dates, LD parameters)
- *MC_Params* — legacy header sheet retained for compatibility with the legacy cost workbook tooling

Filter discipline applied at every read:

1. **Status = Open** (eliminates Closed and Closed-Mitigated rows)
2. For SRA layers, additionally **Time Impact = Yes** — the dual-coded risks, whichever they are

**Which risks those are is a property of the project, not of this document.** Both shipped projects happen to carry ten; the number and the ids differ per register and neither is fixed anywhere in code.

There is no such list in code. The strawman's `Risk_Scope.Time_Impact` is the single source of truth for which risks simulate, and `src/sra/sra_simulation.simulating_risk_ids` reads it; the run settings carry an expected Time=Yes count (`Expected_Time_Yes_Count`, on `MC_Params` or `Run_Config_Preview`), against which `src/sra/_pre_flight.assert_strawman_shape` can check the row count, though no production route runs that check today.

---

## 2. Component 1 — Deterministic QRA (Excel)

**Lives in**: the active project's register, Risk Register sheet plus the dependent analysis sheets.

The register's Quantitative Assessment section spans columns Z to BP and is structured as four sub-sections.

### 2.1 Inherent assessment (cols Z-AL)

For each risk: assumptions, optimistic / likely / pessimistic scenarios, an Inherent Risk Cost dollar set (Optimistic %, Most Likely %, Pessimistic $), and the **Inherent EMV** computed assuming the risk is unmitigated. This is the baseline against which the value of controls is measured.

### 2.2 Contingent (residual) cost assessment (cols AN-AY)

For each Open risk with cost impact:

- **Probability** (cell P) — point probability the risk fires
- **Optimistic / Most Likely / Pessimistic** cost impact ($)
- **Basis of Estimate** — free text naming where the three-point estimate came from. No vocabulary is enforced and none is assumed: the shipped projects write descriptive text. Printed per risk on the driver tables
- **Expected Value (EV) simple** = (Opt + ML + Pess) / 3
- **Contingent EMV simple** = P x EV simple
- **EV PERT** = (Opt + 4 x ML + Pess) / 6
- **EMV PERT** = P x EV PERT

The simple and PERT EMVs are reported side by side. The simple EMV is the textbook three-point average; the PERT EMV is the Beta-PERT mean implied by the same three points and is the standard for contingency analysis where the most-likely value carries more weight than the extremes.

### 2.3 Time impact assessment (cols BA-BG)

For each Open risk with time impact (the dual-coded risks):

- **Probability_Time** — not a firing probability. A risk has one probability, `Probability`, and both arms fire on it; a Time=Yes row whose `Probability_Time` differs from `Probability` is refused by the reader. The column is kept only until it is retired
- **Optimistic / Most Likely / Pessimistic** duration in working days
- **Basis of Estimate** — the Time section's own, distinct from the cost section's.
  Reaches `RiskInput.time_basis` and the schedule drivers table

These flow into the SRA layers. The deterministic SRA EMV-day calculation reuses the PERT formulation from Section 2.2 in days rather than dollars.

### 2.4 MC bridge fields (cols BH-BO)

Six fields drive the Monte Carlo layers:

- **MC Include** — gate flag; risks with MC Include = No are excluded from MC runs (e.g. risks with no quantitative parameters yet)
- **Distribution** — `PERT`, `Triangular`, `Lognormal`, or `Binary`. Determines the cost sampler in `src/distributions.py`
- **Correlation Group** — `CG01` through `CG13` or singleton; determines which CG-correlated uniform stream the risk's firing decision uses (per `src/correlations.py`)
- **Recurrence Type** — empty, `BINOMIAL` (with Max Occ parameter), or `POISSON` (with lambda parameter). Empty means single-occurrence
- **Corr. Factor** — per-risk correlation override

These fields are the contract between the deterministic register and the MC engines. Adding a risk to the register without populating the MC bridge fields excludes it from the MC layers; that is intentional.

### 2.5 Deterministic outputs

The register's deterministic QRA output sheets present the contingent EMVs in five aggregations:

- **EMV Summary** — totals by RBS Level 1 (Total EMV Simple, Total EMV PERT, count of Open risks)
- **EMV Tornado** — risks ranked by EMV PERT contribution
- **Risk Matrix** — Current and Residual P x C scoring grid, with risk IDs placed by their Likelihood / Consequence cells
- **Top 20** — twenty highest-EMV risks
- **Pareto Analysis** — cumulative EMV percentage by rank

These are the deterministic answer. They size contingency under the textbook EMV PERT method but understate tail exposure compared with the MC layers because they collapse each risk's distribution to its mean and ignore correlation between risks.

---

## 3. Component 2 — Monte Carlo QRA (Python cost engine)

**Lives in**: `src/simulation.py` (`MonteCarloEngine`), driven through `final_runner.ipynb`. Reads the register via `src/v5_register_reader.py`.

The cost MC is a two-layer model with explicit chains.

### 3.1 Layer 1 — WBS price/volume variation

Continuous uncertainty within the base estimate. Eight WBS cost buckets are sampled from triangular, lognormal, or PERT distributions parameterised by low/high variance percentages. The eight buckets are correlated via a Cholesky-decomposed covariance matrix with cross-bucket correlation `WBS_CROSS_BUCKET_RHO` (default 0.4 per `src/defaults.py`).

For iteration *i*, bucket *j*:

```text
u_j        ~ U(0, 1)            # correlated via Cholesky
draw_j     = sampler_j(u_j, base_j, low_var_j, high_var_j)
variation  = draw_j - base_j
L1_total_i = TIC + Σ variation_j
```

This layer answers: even with no event risks, how much could the base estimate vary? It is OFF (empty bucket list) in the integrated engine because the integrated engine is L2-only by design (its calibration target is the cost engine's L2-only standalone).

### 3.2 Layer 2 — Event risks

Discrete events from the register. For each Open MC-Include risk and iteration *i*:

```text
u_fire_i ~ U(0, 1)              # CG-correlated via Cholesky on CG groups
fired    = (u_fire_i < probability)
u_sev_i  ~ U(0, 1)              # independent severity uniform
cost_i   = sample_cost(u_sev_i, opt, ml, pess, distribution)
event_cost_i = cost_i if fired else 0
```

`sample_cost` dispatches on the Distribution column to PERT, Triangular, Lognormal, or Binary. PERT is the calibrated default (`src/distributions.pert_from_uniform`).

The CG correlation matrix is built from per-CG rho coefficients. The deliverable, the Stage 3 integrated run and the period run all take them from the project's register, read by `src/sra/methodology_defaults_reader.read_cg_coefficients`, with no code default. The project binding's own coefficients (`src/defaults.HEADLESS_CG_COEFFICIENTS`) are read only on two non-production paths: the legacy V5 register reader (`src/v5_register_reader.read_params_v5`), when the register carries no CG rows; and the CG drivers table (`src/final/sections/cost_drivers.build_cg_drivers_table`) when it is called without coefficients, which the deliverable never does. Risks in the same CG fire together more often than chance; risks across CGs fire independently. This captures common-driver relationships such as "tight construction market" elevating multiple downstream risks simultaneously.

### 3.3 Recurrence (BINOMIAL, POISSON)

Some risks recur across the programme (e.g. wet-season events). Recurrence is modelled by drawing the number of occurrences in an iteration from a BINOMIAL(n_seasons, probability) or POISSON(lambda) distribution and summing per-occurrence cost draws. Implemented inside `MonteCarloEngine.run`'s per-risk loop in `src/simulation.py`, which reads each risk's `recurrence_type` and `recurrence_param`; see the seasonal-firing tests in `tests/test_recurrence.py`.

### 3.4 Chains

Two conditional dependencies are applied post-iteration via `_apply_chain1` / `_apply_chain2`:

- **Chain 1** — planning delay → wet-season amplification. If the planning-delay risk fires with duration ≥ `c1_trigger_months`, the wet-season risk's probability is multiplied by `c1_amplification` and resampled
- **Chain 2** — site-establishment cascade. If site-establishment delay fires with delay ≥ `c2_trigger_weeks`, downstream critical-path risks have their probabilities multiplied by `c2_cascade_factor` and are resampled

Where a register's declared chain risk ids do not match its Open set, the chain logic is dormant but ready for future register revisions. This is documented in `src/integrated/integrated_simulation.py` module docstring.

### 3.5 Stakeholder views

The cost MC produces three views from the same input table, filtered by Risk Owner:

- **BOP Contractor view** — BOP-owned risks plus Shared risks. Used for contingency-pool and management-fee sizing
- **Counterparty view** — counterparty-owned risks plus Shared risks. Used for owner's-reserve sizing
- **Whole-project view** — all risks. Used for lender and board reporting

The three views are *not additive*. Shared risks appear in both party views but only once in the whole-project view. Adding the two party P90s double-counts Shared risks; the whole-project P90 is the correct funding total.

### 3.6 Outputs

`MonteCarloEngine.run()` returns a `SimRawResults` dataclass containing per-iteration L1 totals, per-bucket variations, and per-risk L2 costs as numpy arrays. Downstream analytics (`src/analysis.py`) compute:

- **S-curve** — empirical CDF of total cost, real terms at the base date (Layer 1 only, Layer 1 + Layer 2 integrated = base plus contingency, blue band = event-risk contingency); never called an outturn
- **Tornado** — variance-attribution decomposition by risk and by Layer 1 bucket
- **Party costs** — BOP, CSE, Shared per-iteration arrays
- **Output table** — P10 / P50 / P80 / P90 / P95 / P99 across views

P80 is the primary reporting convention (per the run settings' reporting P-level, on `MC_Params` or a separate strawman's `Run_Config_Preview`); P90 is secondary. P50 is shown for context.

### 3.7 What the correlation contributes

Two measures, answering different questions. Stated here once; the report renders them
and restates no arithmetic.

**Does correlation matter at all — the GN3A §4.1 bounding.** AU GN3A v2.0 §4.1,
*Accounting for correlation using sensitivity analysis*, sets correlation to zero, then
to 100%, and compares the resulting curves. The measure is the dollar gap between them
at the confidence level used to fix contingency:

```text
gap(P) = F_one^-1(P) - F_zero^-1(P)
```

reported at P50, P80 and P90 (GN3A names P50 and P90 for Commonwealth-funded projects;
P80 is this product's primary level). The guidance attaches a decision rule: a negligible
gap means correlation can be ignored, otherwise the level of correlation is examined,
discussed and documented by the project team and then carried in the model. **What counts
as negligible is the project team's judgement**, not a threshold this product sets.

The three modes run on the same seed and the same joint severity uniforms, varying only
the CG coefficients, so the gap carries the correlation effect and not sampling noise.
The elicited mode is asserted to reproduce the run's own cost arm on exact bytes; if it
does not, the table is withheld and the artefact says so.

Scope: this engine's correlation acts on the **firing** draws within a CG group (§3.2);
severity draws are independent. That is narrower than GN3A's "each model input", and the
report says so on the page.

**Which group drives the spread — leave-one-out variance share.** Each correlation
group's risks are removed **together** and the variance the portfolio total loses is
attributed to the group:

```text
share(g) = [Var(T) - Var(T - sum of g's per-risk columns)] / Var(T)
```

Shares need not sum to 100%: correlated risks contribute jointly, so the parts overlap.
A group whose removal *raises* the variance is reported as such rather than rounded to
zero. Dropping members singly would measure each risk against a portfolio still holding
its correlated siblings, which misses what the group expresses.

---

## 4. Component 3 — Deterministic SRA (Excel strawman)

**Lives in**: the active project's strawman, declared by its binding. "Strawman" names the SRA methodology surface — the sheets below — rather than a particular file: **it can be consolidated into the register**, and both shipped projects resolve their strawman path to their own register. A project may still declare a separate workbook, and the three variants (`..._DPReview`, `..._Hybrid`, `..._Series`) select the SRA workflow.

### 4.1 Sheet roles

| Sheet | Role |
|---|---|
| Methodology | Written methodology |
| Run_Config_Preview (in a consolidated register, as in both shipped projects, `MC_Params` carries iterations, the reporting P-level, the day rate, programme seasons, the hybrid float threshold, the schedule duration and the expected Time=Yes count; the other rows are not read from a consolidated register) | Global parameters: programme_seasons, iterations, P-level_reporting, day_rate, CP_rule, Avg prelims/wk, Schedule duration weeks, Schedule start/finish, TOC for LDs, LD burn rate, LD cap |
| Risk_Register | Mirror of the register's Open set (one-time seed; canonical truth remains the register itself) |
| Risk_Activity_Patterns | Named patterns linking risks to P6 activity prefixes |
| Risk_Pattern_Assignments | Per-risk pattern assignment (one row per Open risk) |
| Risk_Scope | The central deterministic SRA artefact — the Time=Yes risks with Mode_Aggregated, Probability_Time, Opt/ML/Pess days, EMV days, finish-delay contribution |
| P6_Processed | Cleaned P6 data |
| CP_Classifier_QA | Output of the critical-path classifier across all P6 rows |
| Mapping | Risk-to-activity mapping for each dual-coded risk |
| DayRate_Reconciliation | Derivation of the day rate from the register's prelims and programme weeks |
| Workshop_Questions | Open methodology questions to be resolved with the PM |

### 4.2 Mode classification (Series / Hybrid / Parallel)

Each dual-coded risk is classified by **Mode** based on whether its impact lands on the longest path:

| Mode | Multiplier | Meaning |
|---|---:|---|
| Series | 1.0 | Risk's drawn duration contributes 100% to finish-date slippage |
| Hybrid | 0.5 | Near-critical; partial contribution as float is consumed |
| Parallel | 0.0 | Off the longest path; zero contribution to finish date regardless of how often it fires |

The multipliers are **register values**, read by `src/sra/methodology_defaults_reader.read_mode_multipliers`; there is no code default. Series 1.0 and Parallel 0.0 follow from what the two Modes mean. Hybrid's 0.5 is the value both shipped registers carry, and a project may set its own.

The classification is produced by the **Option Z classifier** (`src/sra/critical_path.classify_activities`) which applies a five-rule cascade against the P6 longest-path subset:

- S1 — `critical_flag = Yes` → Series. Total float is not read for this rule: a P6-critical row is Series whatever its float
- S2 — primary constraint hard-bound → Series
- S3 — commercially-binding milestone (COD, Practical Completion, Takeover, Ready for First Fire/Hot Commissioning) → Series
- H1 — `0 < total_float_days ≤ 20` → Hybrid. The 20 working days is fixed in the classifier (`src/sra/critical_path.py`); the register's float-threshold row is not used by the classification
- H2 — secondary float-bound conditions → Hybrid
- default → Parallel

Per-risk Mode is then aggregated across the activities each risk maps to via `Mode_Aggregated` in `Risk_Scope`. The classification a strawman ships with is a **starting position for the PM workshop, not a final answer**, and PM review revises it. The mix differs per project and is read from the strawman at run time, never from this document.

### 4.3 Deterministic finish-delay calculation

For each Time=Yes risk the strawman computes:

```text
EMV_days_Simple = Probability_Time x (Opt_Days + ML_Days + Pess_Days) / 3
EMV_days_PERT   = Probability_Time x (Opt_Days + 4 x ML_Days + Pess_Days) / 6
Finish_delay_days = EMV_days_PERT x Mode_Multiplier
Finish_delay_dollars = Finish_delay_days x Day_Rate
```

The workbook's formulas still read `Probability_Time`. The Python twin (`src/sra/schedule_cross_check.py`) reads `Probability`, and the two agree because the reader refuses any Time=Yes row where the columns differ.

Two **comparator targets** drive calibration of the MC layer:

- **Comparator 1** — naive EMV-days sum (no Mode multiplier applied; treats every risk as if it were Series). The "if everything went wrong on the critical path" upper bound
- **Comparator 2** — Mode-weighted EMV-days sum (applies the Mode multiplier). The deterministic central estimate

The calibration target is the comparator that matches the run's Mode basis:

- **Mode multipliers applied** (Stage 2.5): **Comparator 2**. The schedule arm scales each risk by its Mode multiplier, so its mean estimates the Mode-weighted sum.
- **Mode multipliers off** (Stage 3, the production headline), every risk injected by `discrete_event_additive_days`: **Comparator 1, as an upper bound**. Each risk's sampled delay is written once, to its gating activity, and the finish is the longest path, so no network can push the mean above Comparator 1. The check is one-sided: it fails only on a mean above Comparator 1 by more than the tolerance.
- **Mode multipliers off, any other injection method**: **not assessed**. `additive_pert_days` writes one delay to every activity a risk binds, so a serial cohort moves the finish by a multiple of it; the multiplicative methods scale a factor by each activity's duration, which Comparator 1 sums as if it were days. Comparator 1 bounds neither, so the comparators and the gap are reported and nothing is passed or failed.

The tolerance is the register's absolute schedule tolerance, in days (there is no code default): either side of Comparator 2 on the Mode-on basis, above Comparator 1 on the Mode-off basis. A gap exceeding it triggers investigation, not a tolerance adjustment. On the Mode-off basis the delay that did not reach the finish (Comparator 1 less the mean: float absorbed, or a risk bound to no activity) is always reported, beside the absorption the register's Mode labels expect (Comparator 1 less Comparator 2); it is a diagnostic and never decides the result. The run states its Mode basis and its drivers' injection methods from what it ran; the check refuses a call that does not, and refuses a missing or non-finite mean rather than reading it as zero (`src/sra/schedule_cross_check.py`).

### 4.4 Day rate

Day rate is the schedule-to-cost converter, and **it is each project's own**. Where a project derives it from its preliminaries, the derivation is:

```text
Avg prelims per week ($)          = <weekly_prelims>
Schedule duration (weeks)         = <programme_weeks>
Working days per week             = 5             [standard construction working week]
Day rate ($/wd) = <weekly_prelims> x <programme_weeks> / <programme_days>
```

The day rate is read from the project's run settings (the register's `MC_Params` sheet when the strawman is part of the register, as in both shipped projects, or a separate strawman's `Run_Config_Preview`) by `src/integrated/run_config_contract.resolve_day_rate`, and the deliverable needs it. To change it, change the run settings, not the code.

---

## 5. Component 4 — Monte Carlo SRA (Python schedule engine)

**Lives in**: `src/sra/sra_simulation.py` (`run_schedule_simulation`, `run_counterfactual_table`, `run_single_scenario_transparency`), driven through `final_runner.ipynb`, which replaced the retired `sra_runner.ipynb`. Reads the strawman via `src/sra/strawman_reader.py` and the register via `src/v5_register_reader.py`.

### 5.1 Per-iteration mechanics

For each Time=Yes risk and iteration *i*:

```text
u_fire_i ~ U(0, 1)
fired    = (u_fire_i < Probability)          # the risk's one probability
u_dur_i  ~ U(0, 1)
duration = pert_from_uniform(u_dur_i, Opt_Days, ML_Days, Pess_Days)
contribution_i = (duration if fired else 0) x Mode_Multiplier
```

The PERT sampler is shared with the cost engine (`src/distributions.pert_from_uniform`) — one calibrated source of truth for PERT across cost and schedule. The Bernoulli draw is independent per risk in standalone mode (no CG correlation in the SRA standalone — this is a Stage 2.5 simplification that the integrated engine relaxes).

### 5.2 Outputs

`run_schedule_simulation` returns:

- `finish_delay_days_array` — `(n_iter,)` total finish-delay per iteration
- `fired_array` — `(n_iter, n_risks)` boolean
- `duration_array` — `(n_iter, n_risks)` per-risk duration draws
- `contribution_array` — `(n_iter, n_risks)` post-Mode contribution
- `mode_used` — `{risk_id: applied_mode}` dict for audit
- `risk_ids`, `config`, `seed_used`

Distribution shape is typically **bimodal**: a large mass at zero, on the iterations where no Time=Yes risk fires, and a hump in the right tail where one does. The bimodality is methodology-correct, not a bug - it is what a small set of discrete, low-probability events looks like. How pronounced it is depends on the project's firing probabilities.

### 5.3 The counterfactual Mode sweep

The central artefact of the schedule arm. `run_counterfactual_table` runs the simulation once per scenario, with different Mode classifications applied, to make the Mode question concrete for the PM workshop. The sweep is **five base scenarios plus one per Time=Yes risk** (`src/sra/sra_simulation.BASE_COUNTERFACTUAL_SCENARIOS` and `build_counterfactual_scenarios`): 5 + N, so 15 for each shipped project, whose registers carry ten Time=Yes risks.

| # | Scenario |
|---|---|
| 1 | Baseline (DP Review) — strawman as-is |
| 2 | All Series — every Time=Yes risk Series |
| 3 | All Hybrid — every Time=Yes risk Hybrid |
| 4 | Dummy realistic — an indicative mix held as a Python override, keyed by risk ID; a risk it does not name takes Parallel, so on a register it does not cover this scenario equals All Parallel |
| 5 | All Parallel — every Time=Yes risk Parallel, the lower bound beside All Series |
| 6 to 5 + N | One risk at a time → Series, others at strawman state |

Each scenario reports MC Mean, P50, P80, P90, and delta from baseline. Deltas > 5 days are highlighted as high-leverage Mode decisions.

### 5.4 The long-tail risk callout

A project often carries one risk with a low probability and a very long tail - a 12-month equipment replacement, say, at a few percent. Such a risk behaves in two quite different ways depending on its Mode: classified Parallel it contributes **zero** days to finish-date slippage however often it fires, while classified Series its tail dominates P95-P99 and approaches its own pessimistic duration whenever it fires.

**This is why P80 is the primary metric and P99 is reported but never used for sizing.** Where such a risk exists, the deliverable names it and states its effect on every layer it reaches - which one it is, is the project's fact and comes from the run, not from this document.

### 5.5 Single-iteration transparency

`run_single_scenario_transparency(seed=...)` runs one iteration with full per-risk detail (probability, fire decision, drawn duration, Mode multiplier, contribution). This is the methodology audit tool. It has no seed of its own: it takes the seed of the run that asks for it, so the walkthrough reproduces from that run's record, and whatever the seed produces is reported honestly. The walkthrough makes the methodology concrete for non-technical reviewers.

---

## 6. The integrated solution

**Lives in**: `src/integrated/integrated_simulation.py` (`run_integrated_simulation`, `IntegratedConfig`), exposed through `final_runner.ipynb`, the only report path. The composer is `src/final/composer.py`. The hard gate is `src/final/cross_validator.py`.

### 6.1 Joint sampling — the integration mechanic

A dual-coded (Time=Yes) risk is **one event with two consequences**. Each iteration it gets *one* fire decision, against its register `Probability`, and *one* severity uniform `u_sev_i`; both arms use both. So in any iteration a dual-coded risk carries its cost and its delay together, or neither, and when it fires large on cost it fires large on schedule — a tight construction market that drives the cost high simultaneously drives the duration long.

**The fire decision is correlated across risks, on both arms.** It is drawn once per run by `src.qra_core.draw_fire_matrix`: uniforms correlated within each correlation group (Cholesky, the register's CG coefficients), compared against `Probability`. The cost arm (`run_cost_layer`) consumes that matrix as its first draw. The Stage 3 schedule replay — the arm behind the headline — does not draw at all: the orchestrator hands the CPM kernel the cost arm's final fire record, after chain resamples, as `fire_mask` (`src/integrated/integrated_simulation_stage3.py`, `cost_arm_fire_mask`). The period route cannot run the cost arm first, so `src/am/conditional_runner.period_fire_mask` reproduces the same draw from the same seed, pinned risk set and coefficients, and refuses a register whose event-chain target is a schedule driver, since that draw is pre-chain.

**The two draws are on independent streams.** `src/rng_streams.py` makes every generator the Stage 3 routes use from the one run seed: the fire draw and the cost arm's other draws on the seed's own stream, the severity uniforms on a stream of their own (entropy `[seed, SEVERITY_STREAM]`), and the kernel's per-batch generators spawned from the seed. So a risk's fire uniform is never its severity uniform, and a fired risk samples the whole of its range.

A risk that only delays is still one event with one probability: it carries `Probability` and zero dollar estimates, and fires on the same draw as everything else. The Stage 2.5 comparator below shares the same fire array across its cost and schedule columns by construction.


The pseudo-code below is the **Stage 2.5** integrated engine (`run_integrated_simulation`), which is the comparator and the Stage 3 cost arm. The Stage 3 schedule arm replaces its `sched_i` line with a CPM replay that fires on the same `fired`.

```python
for risk i in dual-coded set:
    u_fire_i  ~ U(0, 1)                      # CG-correlated
    fired     = (u_fire_i < probability)
    u_sev_i   ~ U(0, 1)                      # SHARED across cost and schedule
    cost_i    = sample_cost(u_sev_i, opt_c, ml_c, pess_c, distribution)
    sched_i   = pert_from_uniform(u_sev_i, opt_d, ml_d, pess_d) x Mode_Multiplier
    iteration_cost  += (cost_i if fired else 0)
    iteration_sched += (sched_i if fired else 0)

for risk j in cost-only set:
    u_fire_j  ~ U(0, 1)                      # CG-correlated
    fired     = (u_fire_j < probability)
    u_sev_j   ~ U(0, 1)                      # INDEPENDENT (no schedule arm)
    cost_j    = sample_cost(u_sev_j, opt_c, ml_c, pess_c, distribution)
    iteration_cost  += (cost_j if fired else 0)
```

The shared severity uniform is the methodological core of the integrated engine. Without it, cost and schedule would be sampled independently and the engine would understate joint-tail exposure at exactly the contingency-relevant probability levels.

### 6.2 Marginal calibration

The integrated engine must reconcile to its standalone counterparts. Two gates are checked by `compute_marginal_calibration` and re-asserted by `cross_validate_reports`:

| Gate | Tolerance | Source |
|---|---|---|
| Cost marginal — integrated cost mean ≈ L2-only standalone cost mean | the register's dollars OR percent (whichever is looser) | `IntegratedConfig.cost_calibration_tolerance_dollars` / `_pct`, read from the register |
| Schedule marginal — integrated schedule mean ≈ standalone schedule mean | the register's days OR percent | `IntegratedConfig.schedule_calibration_tolerance_days` / `_pct`, read from the register |

The tolerances are register values with no code default (`src/sra/methodology_defaults_reader.read_calibration_tolerances`): a register that carries none stops the run, and a failing run is never made to pass by relaxing them.

Failure of either gate means the integrated engine has drifted from one of its inputs and the deliverable is not fit for distribution. The `final_runner.ipynb` notebook halts in that case and FAIL banners are injected into both the HTML and Word deliverables.

### 6.3 Diversification benefit at P80

Cost and schedule do not peak in the same iterations because the cost-only risks add cost mass that does not move schedule. The integrated P80 (in dollars, with schedule converted at the day rate) sits *below* the naive sum of cost-only P80 + schedule-only P80 dollarised:

```text
Diversification ($) = (Cost-only_P80 + Schedule-only_P80 x Day_Rate) - Integrated_P80
Diversification (%) = Diversification ($) / Naive_sum_P80
```

This is reported across the Mode-classification scenarios the run carries:

- **DP Review baseline** (informational)
- **All Series** (strict gate: diversification must be > 0)

The All Series gate is the formal acceptance criterion — if diversification is not positive under All Series, the joint-sampling mechanism is broken.

### 6.4 Cross-validation — the four-check hard gate

`src/final/cross_validator.cross_validate_reports` runs four checks before the final deliverable is allowed to ship:

1. **Cost marginal calibration** (Section 6.2 gate 1)
2. **The cross-surface Stage 3 comparison**: the deliverable's Stage 3 P80 delay against the
   app's period engine's Stage 3 P80 delay on the same register, `.xer`, seed and iteration
   count, within the register's schedule tolerance (days OR percent). Coverage stated on the
   gate's own output: both surfaces share the CPM kernel, so this check catches divergence in how
   the two surfaces assemble a Stage 3 run (drivers, pinning, configuration) and not a defect
   inside the kernel.
3. **Top-3 cost contributors consistent** between cost-only standalone and integrated (at P80, identical risk IDs)
4. **Top-3 schedule contributors consistent** between the standalone schedule run and the
   integrated arm's per-risk schedule draws (probability-weighted mean impact, register tie
   band). The Stage 3 result's per-risk schedule array is the cost arm's additive, Mode-scaled
   draw, and the CPM kernel attributes nothing per risk - it reports the project finish and each
   activity's criticality. So both sides of this check are additive whichever arm supplies them,
   the check cannot fail on the headline engine, and the gate says so on its face. Ranking
   drivers by a CPM attribution instead - for example by leaving each risk out, as the app's
   days-at-risk measure does - is a methodology choice not yet made.

All four must pass. The `final_runner.ipynb` notebook raises `RuntimeError` on any failure; FAIL banners are present in the HTML rendered up to that cell and in the Word doc, and the deliverable carries unmissable warning text.

#### Iteration-aware tolerance scaling

The absolute clauses of the cost gate and of the standalone schedule marginal (the register's cost dollars and schedule days) are calibrated for the canonical 100,000-iteration production run. At lower iteration counts the standard error of the mean grows as 1/√N, so the realised gap between two independent-RNG runs grows as √2/√N. Without compensation, smoke runs at sub-canonical iteration (e.g. `SR9_ITERATIONS=1000`) cannot pass the gate even when the engines are correct — the gap is dominated by Monte Carlo sampling variance, not by any methodological difference.

`src/final/cross_validator.py` (`compute_iteration_scaling_factor`) therefore scales those two absolute tolerances by **√(canonical_iter / actual_iter)**, capped at **5.0×** to prevent unbounded loosening at very low iteration counts. **Check 2, the cross-surface Stage 3 comparison, is not scaled:** it takes the register's schedule tolerance as written (`src/final/deliverable.py` passes it in; `cross_validator.py` compares against it directly), because its two sides run at the same iteration count and seed.

| Iter (actual) | Scaling factor (multiplies the register's absolute tolerances) |
|---:|:---:|
| 100,000 (canonical) | 1.00 |
| 25,000 | 2.00 |
| 10,000 | 3.16 |
| 5,000 | 4.47 |
| ≤ 4,000 (cap binds) | 5.00 |

At 100,000 iterations, the canonical count, the scaling factor is 1.0 and the register's tolerances apply as written. The relative (percent) clauses are **not** scaled, because relative measures are invariant to iteration count. Check 4's top-3 **tie band is** scaled by the same factor, and capped at 100% of the cut (`min(tie_band x factor, 1.0)`). The scaling instrumentation is surfaced in the cross-validator return dict (keys `tolerance_scaling_factor`, `cost_tolerance_dollars_effective`, `schedule_tolerance_days_effective`, `n_iter_used_for_scaling`) and is preserved in the state cache.

The factor depends only on the run's own iteration count n: √(100,000 / n), capped at 5.0. A smoke run at a low count (`SR9_ITERATIONS=1000`, say) is judged against wider tolerances. Both modes produce identical engine outputs; only the validator threshold differs.

#### A calibration gate that passes only on its percent clause

Each calibration gate passes on its absolute clause OR its percent clause (`abs_gap <= tol_abs OR rel_gap <= tol_rel`). A cost gate that passes **only** on the percent clause is visually a PASS but a different regime, so the validator logs a warning (`Cost calibration passes via relative-clause only ...`) whenever it happens, at any iteration count (`tests/test_sr9_v36_cross_val_passes.py::test_relative_clause_warn_when_only_clause_passing`). On the live deliverable path the caller hands the gate the current run's own engine results, not a cached state; that is the caller's discipline, not something the gate checks.

### 6.5 Reporting conventions

- **P80** — primary report metric (per the run settings' reporting P-level)
- **P90** — secondary
- **P50, P95, P99** — supporting context. P99 is documented as outlier-driven wherever one risk carries a long tail, and not relied upon for contingency sizing
- **Mean** — reported with each P-level table for context
- **Day rate** — the project's own (Section 4.4), applied to convert schedule days to dollars throughout

**Headline basis: the Stage 3 distribution** (since 11/09/2026).
The headline contingency is the P80 of one integrated distribution, cost plus dollarised
schedule delay from the Stage 3 CPM replay, presented as a P50 / P80 / P95 range with its
basis stated on the page: the spread of one modelled outcome, not a spread between Mode
assumptions. Stage 3 has no Mode family. The Stage 2.5 Mode-scenario range is retained beside
the reconciliation as a labelled comparator; it is not the headline and no shipping gate
depends on it. The app's period cycle and the deliverable dollarise through one function,
`src/final/headline.py`.

**Footnote — Mean as a supplementary metric.** P80 is the methodology-standard contingency level for engineering and construction projects per the AU Department of Infrastructure GN3A v2.0 and AACE recommended practices 18R-97 / 41R-08 / 65R-11; it covers approximately four in five simulated outcomes and is the value embedded in the prod report's headline recommendation. Both summary tables (Page 1 component breakdown and Page 2 confidence curve) also surface the **integrated Mean** alongside the P80 figures, and a run can produce a parallel Mean-headline Word summary (`--headline Mean` or `both`) for audiences that prefer Mean framing. Mean reflects the expected value across simulated outcomes and reconciles with EMV; for a right-skewed integrated distribution it covers approximately one in two simulated outcomes. Mean is therefore a supplementary metric, not a replacement for P80 — the methodology-standard contingency framing is unchanged. The Mean / P80 footnote on Page 1 makes this stance explicit in both prod outputs.

---

## 7. Industry framing — AACE Schedule Risk Analysis Maturity Model and AU Guidance Note 3A

Two industry frameworks describe the same progression of cost-and-schedule risk analysis sophistication. This build's position is identical under either reading; they are aligned.

### 7.1 AACE 132R-23 — Schedule Risk Analysis Maturity Model (May 2024)

The international reference for SRA practice maturity. Per AACE 132R-23:

| AACE level | Approach |
|---|---|
| 0, 1 | Qualitative risk awareness; no quantitative analysis |
| **2** | **Risk register identifies risks with probability and impact on the finish date, WITHOUT the benefit of a schedule. Risk analysis is qualitative; no detailed schedule required** |
| 3 | Quantitative Monte Carlo simulation. Activity durations represented by three-point estimates (Opt/ML/Pess) and a Monte Carlo simulation is run on a CPM schedule imported from scheduling software. Critical path is recomputed per iteration. References AACE Recommended Practices 57R-09 (Risk Drivers + MCS of CPM) and 117R-21 |
| 4-5 | Higher-maturity additions including risk-driver decomposition, calibration, integrated cost+schedule and analytics |

The leap from Level 2 to Level 3 is the introduction of MCS over a CPM schedule with per-iteration re-levelling. AACE 57R-09 is the canonical RP for this.

### 7.2 AU Guidance Note 3A — worked-example Risk Factor Models

The Australian counterpart, in the *Supplementary Guidance Note 3A* (Department of Infrastructure, v2.0 Nov 2023). Four worked examples of increasing sophistication:

| GN3A model | Description |
|---|---|
| Risk Factor Model 1 | Quantity uncertainty per area + rate uncertainty + duration uncertainty (overhead running rate) + one event risk. Cost-only. Simplest worked example |
| Risk Factor Model 2 | Same base estimate as Model 1, but quantity uncertainty assessed by **separate disciplines**. Cost-only with finer-grained discipline-level uncertainty |
| Risk Factor Model 3 | Same as Model 2 but the duration distribution is **imported from a separate schedule risk analysis** (originally Primavera Risk Analysis / Pertmaster) and feeds into the cost model as a duration-driven cost uncertainty |
| Risk Factor Model 4 | Rail-project equivalent of Model 3, with quantity and rate uncertainties plus an imported schedule duration distribution |

GN3A Models 2 → 3 describes the same transition as AACE Level 2 → Level 3: at Model 3 / Level 3, a schedule duration distribution from a CPM-based MCS is consumed by the cost model.

### 7.3 This build's position — Stage 3, with Stage 2.5 as the comparator

Both frameworks place this build at the same point. Its headline engine, **Stage 3**, is a full MCS over the CPM schedule with per-iteration re-levelling - the Level 3 / Model 3 engine - and the method stays short of full Level 3 / Model 3 for three stated reasons: risk-to-activity bindings are auto-mapped rather than workshop-validated; a single project-default calendar is used; and the schedule's duration distribution does not feed the cost model - cost and schedule are joint-sampled marginals, the schedule dollarised at the project's day rate (Section 6.1: the Stage 3 cost arm is the Stage 2.5 engine). **Stage 2.5**, retained as the comparator, sits between Level 2 and Level 3. The stages map consistently across both frameworks:

| Stage | Approach | AACE 132R-23 | AU GN3A | Alignment |
|---|---|---|---|---|
| Stage 1 | Deterministic point estimates / line-item ranging | Levels 0-1 | Pre-Model 1 | Deterministic QRA in the register (Component 1) — EMV simple and EMV PERT |
| Stage 2 | Cost MC with discipline-level / WBS uncertainty + correlation; risk register with P x C scoring | Level 2 (qualitative on schedule side) plus cost MC | Risk Factor Model 2 | MC QRA (Component 2): Layer 1 + Layer 2 cost engine, CG correlation groups, party views |
| **Stage 2.5** | **Stage 2 plus a parallel schedule MC engine. Three-point PERT durations × Bernoulli firing × Mode multiplier on the longest-path subset, joint-sampled with cost via shared severity uniform. Schedule MC is *not yet* a per-iteration MCS of a re-levelled CPM schedule** | **Beyond Level 2 (MC has been added) but not yet Level 3 (no MCS-of-CPM with re-levelling)** | **Beyond Model 2 (cost MC done) but not yet Model 3 (no imported MCS schedule duration distribution)** | **The labelled comparator.** Cost MC + schedule MC + integrated MC via shared severity uniform. Mode-aggregator approach (the register's Mode multipliers, Section 4.2) used in lieu of CPM re-levelling |
| Stage 3 | Full MCS over CPM schedule. Risks injected as duration uncertainties on individual P6 activities; schedule re-levelled per iteration; critical path may change between iterations. Schedule duration distribution feeds the cost model as a duration-driven cost uncertainty input on time-driven components | Level 3 (per AACE 57R-09 / 117R-21) | Risk Factor Model 3 | **The headline (this build).** In-house Python CPM-MCS kernel at `src/sra/cpm/`; per-project bindings at `src/sra/cpm/bindings/`; auto-mapped risk drivers substitute for workshop validation, and a single project-default calendar is used; outputs carry a BETA flag for that reason. Workshop-validated risk drivers and full per-activity calendar handling are not built. **Unlike the full Model 3 pattern, the schedule's duration distribution does not feed the cost model:** cost and schedule are joint-sampled marginals, the schedule dollarised at the day rate |

Higher-maturity additions (AACE Level 4-5; full FPRA per Engineers Australia RES Contingency Guideline) are reserved as later upgrades and are not built.

### 7.4 What the Stage 2.5 comparator captures, and what it leaves on the table

Stage 2.5 captures much of the contingency-sizing value of a Level 3 / Model 3 analysis, which is why it is kept beside the headline as a comparator:

- **Probability distributions on cost and schedule** — full S-curves, P50/P80/P90, tornado decomposition
- **Joint sampling for the dual-coded risks** — correlated cost and schedule severities for the same risk in the same iteration; diversification at P80 is correctly captured
- **Calibration to deterministic comparators** — Comparator 1 (naive EMV-days sum) and Comparator 2 (Mode-weighted) anchor the MC results
- **Mode aggregator** — captures the first-order critical-path filtering effect (the register's Mode multipliers, Section 4.2)

Its known limitations relative to Stage 3. The Stage 3 headline removes the first two; it **shares the third**:

- **No path crossover modelling** — the Mode-aggregator cannot represent a risk converting a near-critical activity to critical and shifting the longest path. The counterfactual Mode sweep (Section 5.3) bounds this by re-running the analysis with each Time=Yes risk reclassified to Series in turn
- **No per-activity injection** — risks impact the schedule via the Mode multiplier on aggregated finish-date contribution, not via explicit duration uncertainty on individual P6 activities
- **Schedule MC duration distribution not imported into the cost model** — schedule and cost are produced as separate marginals (joint-sampled) rather than the Model 3 pattern of schedule duration feeding time-driven cost components

Stage 2.5 remains in the build as the labelled comparator (Section 6.5) and as the cost arm's calibration comparator (Section 6.4, checks 1 and 3).

**The Stage 3 headline's own caveats.** The kernel runs against the project's `.xer` with auto-mapped risk drivers (substituting for workshop-validated assignments) and a single project-default calendar (substituting for full per-activity resolution). Its outputs are flagged BETA across HTML, Word body, custom document property `stage3_beta_present`, and output filename prefix `BETA_`, and the deliverable states both caveats on its own face. The method has a third gap, which is structural rather than printed as a caveat: the schedule's duration distribution does not feed the cost model; cost and schedule are joint-sampled, and the schedule is dollarised at the project's day rate (Section 6.1). The steps from here to a full Level 3 / Model 3 methodology are therefore three: replace the auto-mapper with workshop-validated risk drivers; replace the single calendar with per-activity calendars; and feed the schedule's duration distribution into the cost model.

**Activity-level criticality** is produced against the inputs as provided. The kernel records per-iteration on-critical-path counts and total-float streaming statistics; `ScheduleMCResult` carries `criticality_index` (probability that each activity sits on the critical path across the simulated futures), `total_float_mean_hours` / `total_float_std_hours` (per-activity float distribution), and `deterministic_critical_path` (the activity set with `slack ≤ CRITICAL_PATH_TOL` after a single zero-risk forward+backward pass). The composer aggregates these into an "Activity-level criticality" section in the deliverable (between Page 4 and Page 5) — a CI distribution chart plus a near-critical activities table, with a risk-to-activity bridge connecting the top-3 schedule risk drivers to the activities each one's auto-mapper expansion lands on. The accompanying caveat positions the output as deterministic-given-inputs and names three input categories that drive ranking accuracy (risk-driver-to-activity assignments, schedule logic in the .xer, and calendar handling); workshop-validated risk drivers and full per-activity calendar handling are not built.

> **Terminology note.** Both AACE 132R-23 (Levels 0-5) and AU GN3A (Risk Factor Models 1-4) describe the same progression with different shorthand. "Stage 2.5" and "Stage 3" are this product's own shorthand, consistent with both: the leap to Stage 3 in either framework is the introduction of MCS over a CPM schedule with per-iteration re-levelling. This build's Stage 3 sits in that transition zone — at Level 3 in the engine layer (CPM-MCS is built and runs against the .xer), still short of Level 3 in the methodology layer (auto-mapped risk drivers, the single-calendar simplification, and a schedule duration distribution that does not feed the cost model).

---

## 8. Reproducibility

The full deliverable is reproducible from three inputs and one seed.

| Element | Value |
|---|---|
| Register | The active project's (SHA-256 audited in deliverable Page 8) |
| P6 export | The active project's `.xer`, with the longest-path `.xlsx` subset for Stage 2.5 |
| Strawman | The active project's |
| Iterations | From the run settings (`MC_Params`, or a separate strawman's `Run_Config_Preview`); `SR9_ITERATIONS` sets the deliverable's count. 100,000 is the canonical production count |
| Random seed | No seed is a code default. `SR9_SEED` sets the deliverable's seed (unset, blank or 0: drawn once and recorded in the run's provenance). The period run uses the project binding's `period_seed`, the same every period, so period-on-period movement is the register's; `--seed` overrides it for one run, and `meta.seed_source` records which. Tier 1 reads `Set_seed`: blank or 0 is drawn and written back. A fractional seed is refused, never truncated |

Input file SHA-256 hashes are computed by the composer and printed on the audit-trail page of the final deliverable, alongside the run date, iteration count, seed, day rate, and engine versions. The state cache (parquet arrays and JSON metadata, in `outputs/runs/<date>_<project>/`) preserves the composed report data and the cross-validation result so the diagnostic can re-render without re-running the engines.

---

## 9. Out of scope

Items intentionally excluded from the current build:

- **LD layer** — deferred until LD rate confirmation, EOT grounds list, and per-risk Considered LD Impact flag are available
- **Probabilistic escalation** (AACE 68R-11) — not modelled
- **First-principles risk analysis at the activity level** (Engineers Australia RES Contingency Guideline / FPRA) — see Section 7. A future option beyond the current method, not built
- **Layer 1 in the integrated engine** — the integrated engine is L2-only by design; its calibration target is the cost-only L2-only standalone
- **Time-phased S-curve** — the cost MC produces a probability distribution of total cost in real terms, not a phased spend curve. The latter requires a schedule-phased estimate, which is not an input today

---

## Changes to the method

The method has changed in these ways since the analysis first ran. Each says whether the
committed reference numbers moved with it.

- **11/09/2026 - the headline became the Stage 3 distribution.** The deliverable's headline
  contingency moved from the Stage 2.5 Mode-scenario range to the Stage 3 distribution, presented
  as P50 / P80 / P95 with its basis stated; Stage 2.5 stays as the labelled comparator. The same
  day, the Stage 3 delay's baseline became the kernel's zero-risk forward pass
  (`src/sra/cpm/deterministic.py`) rather than the minimum finish across iterations. The committed
  reference numbers were already Stage 3, so none moved.
- **11/09/2026 - cross-validation check 2 became the cross-surface Stage 3 comparison** (Section
  6.4), because the comparison it replaced could not fail on the engine behind the headline.
- **12/09/2026 - the report gained its correlation and validation measures:** the GN3A §4.1
  bounding and the leave-one-out variance share (Section 3.7), and the Time section's own basis of
  estimate on the schedule drivers table. Reporting only: no reference number moved.
- **17/09/2026 - one risk, one probability.** Both arms fire every risk on its one `Probability`,
  from one fire decision correlated within each correlation group (Section 6.1). Before, the
  schedule replay fired on its own `Probability (Time)` draw. The schedule arm's upper tail
  widened, and the reference numbers moved with it.
- **17/09/2026 - independent random streams for fire and severity** (Section 6.1). The headlines
  moved by resampling noise only.
