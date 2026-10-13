# ARCHITECTURE

Code layout and data flow for Ridgeline. This document is the engineering reference; it pairs
with `METHODOLOGY.md` (the math) and `SCALABILITY.md` (persistence, memory and archive decisions).

**The shape of it, in one paragraph.** Ridgeline has four analytical components: deterministic QRA
and deterministic SRA, which live in the project's Excel workbooks, and Monte Carlo QRA and Monte
Carlo SRA, which are Python. A run reads one project's three inputs - its risk register, its P6
schedule (`.xer`) and its schedule methodology workbook (the strawman, which may be the register
itself) - through readers that look columns up by header. The cost engine and the schedule engine
sample the same risks with one shared set of fire decisions and severity draws, so the integrated
result is one joint distribution of cost plus dollarised schedule delay. A four-check
cross-validation gate runs before anything is composed; the composer then builds the report data,
and the notebook renders it. Everything under `src/` returns data, never rendering.

**Where to look:** §1 the top-level layout; §2 the module map; §3 the data flow, with diagrams; §4
how configuration is resolved; §5 the deliverable notebook; §6 the tests; §7 the scripts; §9 the
persistence decisions; §10 the workbook contracts.

---

## 1. Top-level layout

```text
outturn/
├── README.md / METHODOLOGY.md / ARCHITECTURE.md / SCALABILITY.md
├── requirements.txt              # full stack incl. xlwings
├── requirements_client.txt       # notebook-only stack
├── RUN_FINAL.bat                 # the one deliverable entry point
├── final_runner.ipynb            # the deliverable notebook, and the only one
├── dashboard/                    # the monthly dashboard app (Next.js static export)
├── outputs/
│   ├── charts/                   # PNGs emitted by composer
│   ├── runs/<date>_<project>/    # state cache + provenance.json, one per run
│   └── *.html, *.docx            # report deliverables (no PDF)
├── src/                          # see Section 2
├── scripts/                      # diagnostics, workbook builders, P6 inspectors, release checks
├── tests/                        # pytest suite, and the two synthetic projects' fixtures
└── docs/                         # the walkthrough, the user guide, the release procedure
```

---

## 2. `src/` module map

The `src/` package is organised by analytical layer. Each subpackage is **pure-data** — it returns DataFrames, dicts, and dataclasses; rendering happens in the notebooks. This separation is enforced by tests.

### 2.1 Top-level cost-side modules

| Module | Purpose |
|---|---|
| `config.py` | Dataclasses: `SimConfig`, `WBSBucket`, `ChainConfig`, `RiskInput`, `GainPainConfig`, `SimRawResults`, `TornadoEntry`, `SingleRunBucket`, `SingleRunEvent`, `SingleRunResult` |
| `defaults.py` | Methodology constants: `HEADLESS_BUCKETS`, `HEADLESS_CG_COEFFICIENTS` (CG01-CG13 rho), `WBS_CROSS_BUCKET_RHO`, `CHAIN_RISK_IDS`, `DEFAULT_PROGRAMME_SEASONS`, gain/pain defaults |
| `simulation.py` | `MonteCarloEngine` — cost MC orchestrator. `__init__` builds the RNG and resolves overrides; `run()` returns `SimRawResults`. Vectorised numpy throughout — no Python loops over iterations |
| `distributions.py` | `pert_from_uniform`, `triangular_from_uniform`, `lognormal_from_uniform`, `binary_from_uniform`, `sample_cost` (dispatcher). One source of truth for samplers across cost and schedule |
| `correlations.py` | `build_risk_uniform_matrix` (Cholesky on CG groups), `generate_wbs_uniforms` (Cholesky on WBS buckets) |
| `analysis.py` | `build_output_table`, `compute_tornado`, `compute_party_costs`. Returns dicts and lists; no rendering |
| `gain_pain.py` | TOC contract gain/pain share — BOP/counterparty net positions, asymmetry, fair share, regret, pool drawdown |
| `charts.py` | matplotlib chart generators for the cost-side workbook |
| `reporting.py` | Pure-data dashboard panel data for cost MC |
| `single_run.py` | Single-iteration transparency for cost MC |
| `reader.py` | xlwings reader — needs Excel running; legacy path for the VBA RunMC button |
| `openpyxl_reader.py` | openpyxl reader — headless, cost-side workbook reads |
| `register_loader.py` | Legacy register loader |
| `v5_register_reader.py` | **Current canonical register reader.** Reads risks AND simulation parameters from the active project's register |
| `writer.py` / `assumptions_writer.py` | Writers back to the Excel cost workbook |

### 2.2 `src/sra/` — schedule MC layer

| Module | Purpose |
|---|---|
| `sra_config.py` | `SRAConfig` dataclass; `load_sra_config()`, which diagnostic scripts use to build one. The Mode multipliers are read from the register (`methodology_defaults_reader.read_mode_multipliers`) and the day rate from the run settings (`run_config_contract.resolve_day_rate`) |
| `sra_simulation.py` | `run_schedule_simulation` (one full run), `run_counterfactual_table` (the Mode sweep: five base scenarios plus one per Time=Yes risk), `run_single_scenario_transparency` (one iteration with full detail). `simulating_risk_ids(risk_scope_df)`, which reads the strawman rather than a hardcoded list, and the `DUMMY_REALISTIC_MODE_OVERRIDE` constant |
| `sra_analysis.py` | `compute_per_risk_criticality`, `compute_percentiles`, `compute_summary_stats`, `compute_calibration_check` (gates against strawman Comparator 2) |
| `sra_reporting.py` | Pure-data dashboard panel data for SRA |
| `strawman_reader.py` | Reads `Risk_Scope`, the run settings (`Run_Config_Preview`, or `MC_Params` in a consolidated register such as both shipped ones), `Risk_Pattern_Assignments` from the strawman. Header-driven column lookup; tolerates strawman revisions |
| `p6_reader.py` | `read_p6_schedule` — parses the P6 longest-path export into a DataFrame with `activity_id`, `total_float_days`, `critical_flag`, `primary_constraint`, `row_type` |
| `critical_path.py` | `classify_activities` — Option Z classifier producing Series/Hybrid/Parallel per activity. `COMMERCIALLY_BINDING_KEYWORDS` constant for the S3 rule |

### 2.2.1 `src/sra/cpm/` — the Stage 3 CPM-MCS kernel

The Stage 3 engine: a Monte Carlo simulation over the project's CPM schedule. Project-agnostic; every project reaches it through its binding. What it does is the rest of this document and `METHODOLOGY.md` §6.

| Module | Public surface | Role |
|---|---|---|
| `xer_reader.py` | `parse_xer(path)`, `validate_xer_tables(tables)` | Parse Primavera P6 .xer flat-file into per-table DataFrames |
| `graph.py` | `Activity`, `Link`, `ScheduleGraph` | Schedule data model |
| `graph_builder.py` | `build_schedule_graph(xer_tables)` | Construct ScheduleGraph from XER tables; topo sort; cycle detection |
| `calendar.py` | `Calendar` | Working-day arithmetic; project-default calendar fallback (a single-calendar simplification; per-activity calendar resolution is not built) |
| `cpm_kernel.py` | `forward_pass`, `backward_pass`, `compute_slack`, `run_batch`, `accumulate_batch_stats`, `CRITICAL_PATH_TOL` | Vectorised forward + backward CPM with FS/SS/FF/SF + lag; chunked batches; float32 default. `accumulate_batch_stats` is the canonical streaming aggregator for per-activity CI counts and total-float sum / sum-of-squares (float64 throughout to avoid float32 catastrophic cancellation in the variance step) |
| `risk_injection.py` | `sample_risk_deltas`, `apply_to_durations`, `build_duration_array` | Per-iteration PERT magnitude × Bernoulli firing × shared severity uniform. An optional `mode_multiplier_override` kwarg replaces the per-driver lookup in the register's Mode multipliers (`mode_multipliers[driver.mode]`, read by `read_mode_multipliers` and resolved by `src/sra/mode_multipliers.resolve_mode_multiplier`) uniformly across all risks (used by the orchestrator's `"mode_independent"` and `"both"` passes) |
| `auto_mapper.py` | `expand_single_rule`, `expand_auto_rules`, `write_audit_trail` | Substitutes for workshop-validated risk-driver assignments until a project has them; pattern-prefix + float-threshold expansion against `ScheduleGraph` |
| `cpm_simulation.py` | `run_schedule_mc`, `ScheduleMCConfig`, `ScheduleMCResult`, `CriticalityMeasurementMode` | Chunked Monte Carlo orchestrator; severity-uniform alignment contract; mode gating (beta vs prod). `ScheduleMCResult` carries `total_float_mean_hours`, `total_float_std_hours`, `deterministic_critical_path` (single zero-risk forward+backward pass — the activity *set* with `slack ≤ CRITICAL_PATH_TOL`, a superset of any single longest path under float ties). The `criticality_measurement_mode` parameter on `run_schedule_mc` accepts `"mode_conditioned"` (default — Mode multipliers honoured per-driver), `"mode_independent"` (multiplier forced to 1.0 per AACE 65R-11 §5.4), or `"both"` (two paired-seed passes); `ScheduleMCResult.mode_independent_criticality_index: dict[str, float] \| None` populated only on `"both"` runs |
| `criticality_metrics.py` | `compute_criticality_divergence`, `DIVERGENCE_BAND_SUPPRESSED`, `DIVERGENCE_BAND_CONSISTENT`, `DIVERGENCE_BAND_AMPLIFIED` | Per-activity divergence table from the two CI views with verbal banding (0.15 default threshold); sorted by abs(divergence) descending |
| `risk_driver_schema.py` | `RiskDriver`, `AutoMapperRule`, `AutoMapperConfig`, `AutoMapAuditRow`, `InjectionMethod`, `RiskMode` | Schema for both auto-mapper output and (future) workshop direct-load. `RiskDriver.mode` and `AutoMapperRule.mode` (`Literal["Series", "Hybrid", "Parallel"]`, default `"Series"`); validated at construction; multiplier read from the register's own grid by `src/sra/methodology_defaults_reader.read_mode_multipliers` |

### 2.2.2 `src/integrated/stage3_inputs.py` — the Stage 3 inputs a run declares

A project's own values live in its binding (`src/sra/cpm/bindings/<project>.py`), which is data:
filenames, directories, labels, risk-ID prefix, float threshold, CG coefficients. This module is
the behaviour every project shares. **Nothing in it has a project default**: a project's paths,
CG map and float threshold come from its own binding, never from another project's.

| Symbol | Role |
|---|---|
| `Stage3BindingConfig` | One run's inputs and knobs: register / schedule / strawman paths and the float threshold, all required; CG coefficients, injection-method pin and Mode flags optional |
| `build_joint_severity_uniforms(*, risk_ids, n_iter, rng, precision)` | The joint per-risk U(0,1) draws both arms consume, on the severity stream (`src.rng_streams`) |
| `resolve_default_injection_method(config)` | The register's `Default_Injection_Method` unless the caller pins one. No code default |
| `resolve_float_threshold_hours(project=None, *, binding=None)` | The active (or named) project's Filter B threshold; a binding that declares none is refused by name |

### 2.3 `src/integrated/` — joint cost+schedule MC layer

| Module | Purpose |
|---|---|
| `integrated_simulation.py` | `IntegratedConfig` dataclass; `run_integrated_simulation` (joint sampler with shared severity uniform for dual-coded risks); `apply_chain_logic` (post-iteration chain replay using cost engine's resample-with-elevated-probability mechanism); `load_integrated_config` |
| `joint_sampler.py` | Per-iteration joint draw helper |
| `cost_dispatcher.py` | `sample_cost` vectorised dispatcher; `_get_attr` safe attribute fetch |
| `integrated_analysis.py` | `compute_marginal_calibration` (cost and schedule gates), `compute_diversification_benefit` (P80 across Mode scenarios), `compute_joint_percentiles`, `compute_correlation_metrics` (per-risk pre/post-mode rho, aggregate Pearson/Spearman) |
| `integrated_reporting.py` | Pure-data dashboard panel data for integrated runner |

### 2.4 `src/final/` — the composed deliverable

| Module | Purpose |
|---|---|
| `composer.py` | `compose_final_report_data` — single nested-dict producer. Builds page1-page8 data, drilldown data, appendix data, callouts. Mode-aware (`dev` / `prod`) — empties prod-restricted bodies via the same code path |
| `cross_validator.py` | `cross_validate_reports` — four-check hard gate (cost calibration, schedule calibration, top-3 cost contributor consistency, top-3 schedule contributor consistency). Returns `all_pass` bool plus per-check details |
| `word_generator.py` | `generate_word_summary` — produces the docx executive summary side-effect from composed data |
| `charts.py` | `make_s_curve`, `make_density_histogram`, `make_tornado_chart`, `make_risk_matrix`, `make_confidence_waterfall` — report-quality matplotlib helpers. `SCENARIO_COLORS` and `MODE_COLORS` palettes |
| `executive_summary.py` | `get_top_n_risk_drivers`, `get_headline_contingency_range`, `get_diversification_summary`, `INDICATIVE_SCENARIO_*` resolvers |
| `commentary_text.py` | Methodology narrative constants (paragraph templates with paired `_PROD` twins for prod mode) |
| `callout_text.py` | "Why MC matters", "How this analysis ages well" callout text |
| `disclaimer_text.py` | Disclaimer paragraphs (mode-aware) |
| `final_reporting.py` | Pure-data panel helpers consumed by the notebook |
| `_pre_flight.py` | `assert_strawman_unlocked` — fails if the strawman has an Excel lock file (~$ prefix) |

---

## 3. Data flow

The codebase carries two parallel schedule-data paths. **Stage 3 is the headline** (since 11/09/2026). **Stage 2.5** is retained beside it as a labelled comparator: it reads the longest-path xlsx via `src/sra/p6_reader.py` and `src/sra/critical_path.py` (Option Z classifier), produces finish-delay days via Mode multiplier on the longest-path subset, and joint-samples with the cost engine via shared severity uniform. **Stage 3** reads the .xer via `src/sra/cpm/xer_reader.py` + `src/sra/cpm/graph_builder.py`, runs full forward+backward CPM per iteration via `cpm_kernel.run_batch`, injects risks via `risk_injection.build_duration_array`, orchestrates chunked iteration via `cpm_simulation.run_schedule_mc`, and is driven for any project by `src/integrated/integrated_simulation_stage3.run_integrated_simulation_stage3`. Joint sampling is preserved across both arms via the shared per-risk severity uniform, constructed once by `src/integrated/stage3_inputs.build_joint_severity_uniforms` and consumed via the surgical refactor of `run_integrated_simulation` (precomputed_severity_uniforms keyword-only param). The Stage 3 path flags its outputs as BETA across HTML, Word body, custom doc property, and output filename prefix, because its risk-to-activity bindings are auto-mapped rather than workshop-validated.

```text
                  ┌───────────────────────────────┐
                  │  the project's register.xlsx  │
                  │  - Identification + scoring   │
                  │  - Quantitative section       │
                  │  - MC bridge fields           │
                  └──────────────┬────────────────┘
                                 │
       ┌─────────────────────────┼──────────────────────────────┐
       │                         │                               │
       ▼                         ▼                               ▼
┌─────────────┐           ┌─────────────┐               ┌──────────────────┐
│ Excel native │           │ v5_register_│               │ strawman_reader  │
│ formulas →   │           │  reader →   │               │  reads from      │
│ EMV Summary  │           │  list[Risk  │               │  the project's   │
│ EMV Tornado  │           │  Input]     │               │  strawman        │
│ Risk Matrix  │           │             │               │                  │
│ Top 20       │           │             │               │ Risk_Scope:      │
│ Pareto       │           │             │               │  Mode_Aggregated │
│ Risk Analysis│           │             │               │  Probability_Time│
│              │           │             │               │  Opt/ML/Pess days│
│ DETERMINISTIC│           │             │               │ Run_Config_      │
│  QRA OUTPUTS │           │             │               │  Preview         │
└──────────────┘           └──────┬──────┘               └────────┬─────────┘
                                  │                               │
                                  │                               │
                                  ▼                               ▼
                         ┌─────────────────┐             ┌─────────────────┐
                         │ MonteCarloEngine│             │ run_schedule_   │
                         │   Layer 1 + L2  │             │  simulation     │
                         │   chains, CG    │             │  PERT × Mode    │
                         │   correlation   │             │  multiplier     │
                         │                 │             │                 │
                         │   MC QRA        │             │   MC SRA        │
                         └────────┬────────┘             └────────┬────────┘
                                  │                               │
   ┌──────────────────────────────┼─────────────────────┐         │
   │                              │                     │         │
   │   Stage 2.5 schedule input:  │                     │         │
   │   ┌─────────────────┐        │                     │         │
   │   │ P6 longest-path │        │                     │         │
   │   │ xlsx → p6_      │        │                     │         │
   │   │ reader →        │────────┘                     │         │
   │   │ classify_       │                              │         │
   │   │ activities      │                              │         │
   │   │ (Option Z)      │                              │         │
   │   └─────────────────┘                              │         │
   │                                                    │         │
   │   Stage 3 schedule input:                          │         │
   │   ┌──────────────────────────────────┐             │         │
   │   │ the project's .xer               │             │         │
   │   │  - TASK (activities; 171 on      │             │         │
   │   │    Tropic Ridge)                 │             │         │
   │   │  - TASKPRED (logic links,        │             │         │
   │   │    FS/SS/FF/SF + lag in hours)   │             │         │
   │   │  - CALENDAR                      │             │         │
   │   │  - PROJWBS, ACTVCODE, NONWORK    │             │         │
   │   │           ↓                      │             │         │
   │   │  src/sra/cpm/xer_reader.py       │             │         │
   │   │           ↓                      │             │         │
   │   │  graph_builder → ScheduleGraph   │             │         │
   │   │           ↓                      │             │         │
   │   │  cpm_kernel (forward/backward,   │             │         │
   │   │   chunked, float32) →            │             │         │
   │   │   project_finish + criticality   │             │         │
   │   └──────────────────────────────────┘             │         │
   └────────────────────────────────────────────────────┘         │
                                  │                               │
                                  ▼                               ▼
                              ┌──────────────────────────────────────┐
                              │  run_integrated_simulation            │
                              │  Joint severity uniform (dual-coded)  │
                              │  Independent uniform (cost-only)      │
                              │  CG correlation on firing             │
                              │  Stage 2.5: Mode multiplier on sched. │
                              │  Stage 3: per-activity duration       │
                              │           injection + CPM re-level    │
                              └──────────────────┬────────────────────┘
                                                 │
                                                 ▼
                              ┌──────────────────────────────────────┐
                              │  cross_validate_reports               │
                              │   1. Cost marginal (register tol.)   │
                              │   2. Schedule marginal (register)    │
                              │   3. Top-3 cost consistency          │
                              │   4. Top-3 schedule consistency      │
                              └──────────────────┬────────────────────┘
                                                 │
                              FAIL ◄─────────────┴─────────────► PASS
                                │                                 │
                                ▼                                 ▼
                       FAIL banner injected             compose_final_report_data
                       across HTML + Word;              → executive_summary
                       notebook raises                  → page1..page8
                       RuntimeError                     → drilldowns
                                                        → appendices
                                                        → state cache pickle
                                                                  │
                                                                  ▼
                                          ┌────────────────────────────────────┐
                                          │ outputs/                           │
                                          │   <project>_deliverable_<date>.html│
                                          │   the Word executive summary       │
                                          │   runs/<date>_<project>/ (cache)   │
                                          │   charts/*.png                     │
                                          └────────────────────────────────────┘
```

```text
The Stage 3 path:

   ┌─────────────────────────────────────┐
   │  the project's .xer                 │
   │  (its P6 baseline export)           │
   └────────────────┬────────────────────┘
                    │
   ┌────────────────▼────────────────────┐
   │  src/sra/cpm/xer_reader.py          │
   │  → per-table DataFrames             │
   └────────────────┬────────────────────┘
                    │
   ┌────────────────▼────────────────────┐
   │  src/sra/cpm/graph_builder.py       │
   │  → ScheduleGraph (topo + cycle      │
   │     detection) + project_default    │
   │     Calendar                        │
   └────────────────┬────────────────────┘
                    │
   ┌────────────────▼────────────────────┐         ┌─────────────────────────┐
   │  stage3_config.build_stage3_      │◄────────│  the project's register │
   │    rules_from_scope() + expand    │         │  and strawman           │
   │  → dict[risk_id, RiskDriver]        │         └─────────────────────────┘
   │  stage3_inputs.build_joint_        │
   │    severity_uniforms()            │
   │  → dict[risk_id, ndarray (n_iter,)] │
   └────────────────┬────────────────────┘
                    │
                    ├──────► run_integrated_simulation (cost arm)
                    │        with precomputed_severity_uniforms
                    │        (joint sampling preserved)
                    │
                    └──────► run_schedule_mc (schedule arm)
                              ├─ risk_injection.build_duration_array
                              │  (per-batch; chunked)
                              └─ cpm_kernel.run_batch
                                 (per-batch; forward+backward; criticality)
                                       │
                                       ▼
   ┌─────────────────────────────────────┐
   │  ScheduleMCResult                   │
   │  + auto_mapper_audit_path           │
   │  + beta_flag = True                 │
   └────────────────┬────────────────────┘
                    │
   ┌────────────────▼────────────────────┐
   │  src/final/composer.py              │
   │  compose_final_report(              │
   │    ..., stage3_beta_result=...)     │
   │  → composed["beta_flag"] = True     │
   │  → composed["path_crossover_delta"] │
   └────────────────┬────────────────────┘
                    │
   ┌────────────────▼────────────────────┐
   │  src/final/word_generator.py        │
   │  + _inject_beta_banner              │
   │  + _apply_beta_filename_prefix      │
   │  + CUSTOM_PROPERTY_BETA_FLAG        │
   │  → BETA_<deliverable>.docx          │
   └─────────────────────────────────────┘
```

The 171 in the first diagram is Tropic Ridge's activity count: the TASK table of `tests/fixtures/synthetic_wind/wind_schedule.xer`.

The strawman acts as the SRA methodology shim between the register and the schedule engines. It exists because the SRA methodology has its own decisions (Mode classification per risk, day rate derivation, programme dates, Comparator 1/2 calibration targets) that are not properties of the risks themselves but of the project's schedule context. Keeping these in a separate xlsx makes them auditable and revisable independently of the register.

---

## 4. Configuration resolution

What to set, and where run settings live.

- **The deliverable** reads four environment variables: `QRA_PROJECT` names the project's binding,
  and `REGISTER_FILE`, `P6_FILE` and `STRAWMAN_FILE` name its three inputs. It refuses to start if
  a path is missing.
- **The period run** (`RUN_PERIOD.bat`) takes the inputs as flags: `--register`, `--xer` and
  `--strawman`.
- **Run settings** - iterations, the reporting P-level, the day rate, seasons and the hybrid float
  threshold - live in the register's `MC_Params` sheet when the strawman is part of the register, as in both shipped projects, or a separate strawman's `Run_Config_Preview`. `strawman_reader.read_run_config` reads whichever the
  workbook has.
- **Overrides:** `SR9_ITERATIONS` sets the deliverable's iteration count and `SR9_SEED` its seed
  (unset, blank or 0: one seed is drawn for every arm and recorded in the provenance);
  the period run takes `--main-iter`, and `--seed` to override its binding's `period_seed`.
- **The day rate** is the project's own, from the run settings. The deliverable needs it.

The legacy cost-model workbook (`.xlsm`) has its own MC_Params parameter sheet that the xlwings reader (`reader.py`) consumes — but the register's MC_Params sheet shadows it for the canonical register flow.

---

## 5. Notebook architecture

**One notebook, and it is the only report path.**
`final_runner.ipynb` lives at the repository root and is thin: it calls
`src/final/deliverable`, which runs the deliverable sequence and returns it, and the notebook
renders. The three earlier runners (`sra_runner`, `integrated_runner`, `outputs/client_runner`)
are retired - the standalone schedule and integrated runs are cells of this one.

| Engines run | Output |
|---|---|
| Cost MC standalone, the Stage 2.5 schedule MC per Mode scenario, integrated per Mode scenario, Stage 3 CPM-replay - then `cross_validate_reports`, `compose_final_report_data`, `generate_word_summary`, `emit_stage3_standalone_artefacts`, `write_state_cache` | HTML (nbconvert) + Word per headline metric + the Stage 3 standalone pair + `outputs/runs/<date>_<project>/` (state cache + `provenance.json`). **No PDF** |

Inputs come from the environment (§4): `QRA_PROJECT` selects the binding, `REGISTER_FILE` /
`P6_FILE` / `STRAWMAN_FILE` the inputs, and `SR9_ITERATIONS`, `SR9_SEED` and
`FINAL_REPORT_HEADLINE_METRIC` set the iteration count, the seed and the headline metric. It
refuses to start if a path is missing.
The deliverable runs **prod only** - `FINAL_REPORT_MODE=dev` is refused rather than honoured.

**Halt behaviour: write, then fail.** On a cross-validation failure every artefact is
still written and carries the FAIL banner, and the notebook's LAST cell raises. `RUN_FINAL.bat`
runs nbconvert with `--allow-errors` for that reason - without it the raising cell aborts the
conversion and no HTML is written at all - and takes the run's verdict from the provenance
manifest the run wrote, keyed by a per-invocation token so a stale same-day manifest cannot
supply a pass.

The notebook renders via `display(Markdown())` and `display(Image())`. No engine logic in the
notebook layer; no rendering in the engine layer.

---

## 6. Test layout

`tests/` contains the pytest suite. Tests are organised to mirror the `src/` module structure where practical, with cross-cutting tests grouped under their feature.

Indicative slices:

- `test_distributions.py` — PERT/Triangular/Lognormal samplers
- `test_correlations.py` — Cholesky on CG groups, WBS bucket correlation
- `test_simulation.py` — `MonteCarloEngine` end-to-end at small iteration counts
- `test_recurrence.py` — BINOMIAL/POISSON recurrence
- `test_cascade.py` — Chain 1 / Chain 2 logic
- `test_gain_pain.py` — TOC gain/pain
- `test_charts.py`, `test_pool_charts.py`, `test_chart_improvements.py` — chart generators
- `test_reader_columns.py`, `test_cont_share_reader.py`, `test_pool_keys.py` — register reader column resolution
- `test_l2_only.py` — L2-only path used by integrated calibration
- `test_lognormal_l2.py`, `test_binary_pert.py`, `test_max_occ.py`, `test_programme_seasons.py` — distribution-specific corner cases
- `test_dashboard_layout.py`, `test_view_override.py`, `test_shared_view_pvalues.py` — dashboard logic
- `test_single_run_shared.py` — single-run transparency
- `test_cg_analysis.py`, `test_stage3_analysis.py` — cost-side analysis layer
- `tests/sra/` and `tests/integrated/` and `tests/final/` (where present) — SRA, integrated, and deliverable-layer tests

The `slow` pytest marker partitions out tests that run full simulations at reduced iteration counts; default `pytest -m "not slow"` skips them for fast feedback.

`tests/fixtures/` holds golden artefacts (docx, HTML, JSON, pickle) that snapshot tests compare against.

---

## 7. Scripts

`scripts/` holds operational helpers — diagnostics and one-off Excel-builders, not part of the engine.

| Script | Purpose |
|---|---|
| `run_diagnostic.py` | Re-renders a run's one-page diagnostic from its state cache. Replaced `sr9_diagnostic.py`, whose cache path, artefact names and headline had all drifted. A normal run does not need it: `src.final.deliverable` writes `run_diagnostic_<date>.txt` itself, on every run |

Run from the project root with `python scripts/<name>.py`.

---

## 8. How changes are made

How changes to this codebase are planned and reviewed is internal process, not part of the
product. One design rule from it belongs here: the strawman's `Risk_Scope.Mode_Aggregated` is the
canonical Mode source for production deliverables, and `DUMMY_REALISTIC_MODE_OVERRIDE` is a Python
override layer still read by the deliverable, marked for absorption into the strawman.

---

## 9. Persistence — architecture decisions

These decisions are recorded so future sessions don't re-litigate them. The fuller rationale, sizing data, and migration plan are in `SCALABILITY.md`; this section is the executive summary.

| Layer | Format | Rationale |
|---|---|---|
| Inputs (register, P6, strawman) | xlsx | Canonical interchange format with external parties (Contractor planning, register owner). Not negotiable; readers tolerate column reordering via header-driven lookup |
| Per-run state cache | **parquet for arrays + JSON for metadata** (replacing pickle) | Pickle is fragile across Python and library versions. Parquet is schema-stable, columnar, 3-5× smaller for typical MC payloads, and language-portable. JSON beside it for the small metadata dict is text-diffable. Migration is ~2 days, scoped to `composer.py` writer + the diagnostic reader + test fixtures |
| Per-run intermediate arrays (in RAM during a run) | numpy float32, **chunked iteration** | Stage 3's naive single-batch peak is 4.8 GB; chunking at `batch_size=10_000` brings per-batch peak to ~0.48 GB. Float32 is the default precision; float64 is opt-in for diagnostics. Chunked design is mandatory in `cpm_kernel.py` from day one, a constraint of the Stage 3 design |
| Cross-run archive | flat parquet directory tree + `manifest.csv` | `outputs/runs/<YYYY-MM-DD>/{*.parquet, metadata.json}` plus `outputs/runs/manifest.csv` with one row per run. ~20 historical runs ≈ 250-500 MB. Pandas reads the manifest in one line and joins to per-run parquets |
| Cross-run analytical queries (if and only if needed) | **DuckDB** as a query layer over existing parquet | Embedded, no server, reads parquet in place. Adopted only if cross-run questions become routine; the parquet archive is already DuckDB-readable so introducing it later is non-disruptive |
| HTML / Word deliverables | files in `outputs/` | Unchanged |

**Decisions explicitly out of scope:**

- **No Postgres / MySQL / SQL Server.** Single-analyst project, no concurrent writes, no transactional needs. Operational burden of a server-based DB has no offsetting benefit at any foreseeable project scale
- **No client-server schedule risk tooling.** The CPM kernel is in-house Python. Third-party CPM-MCS tools are not available to the project
- **No real-time / streaming compute.** Each release cycle is a sequential produce-and-archive; batch numpy is the right tool

**Migration sequence:**

1. Before Stage 3: pickle → parquet+JSON for the state cache. Adds `pyarrow>=15` to `requirements_client.txt`
2. During Stage 3: chunked iteration baked into `cpm_kernel.py` from the start
3. At Stage 3 sign-off: `outputs/runs/manifest.csv` updater wired into the notebook close-out
4. On demand only: DuckDB if cross-run queries become routine

---

## 10. Interface contracts

Three reference contracts: the legacy cost workbook's Python-Excel API, that workbook's sheet
structure, and the SRA strawman.

### 10.1 Cost MC Excel integration contract (legacy cost workbook)

API between cost MC Python engine and the legacy cost-model workbook (`.xlsm`), used by VBA RunMC button. Notebook stack does not use this; the register reader reads the project's register directly.

Python writes key-value pairs to `MC_Engine` starting at the `mc_results` named range (currently `MC_Engine!$C$6`). XLOOKUP formulas on `MC_Dashboard` and `MC_Outputs` read from that range.

**DO NOT change the key names — they are the API between Python and Excel.**

Key prefixes: `p10/p50/p80/p90/mean/std` (primary view), `l1_*` (Layer 1), `bop_*` / `cse_*` / `shared_*` (sub-views), `t0_*`-`t9_*` (tornado top 10), `sc_total_*` / `sc_l1_*` (S-curve percentiles 1-99), `conv_*` (convergence), `gp_*` (gain/pain: P-values, asymmetry, fair share, regret, cap utilisation, pool drawdown), plus `view_label`, `view`, `adequacy`, `overrun`, `n_risks`, `risk_premium`, `shared_pool_p80`, `shared_pool_p90`.

Named ranges used by `reader.py` (workbook scope):
`mc_n_iter`, `mc_seed`, `mc_view`, `mc_bop_contract`, `mc_bop_cont`, `mc_cse_cont`, `mc_tic`, `mc_contingency`, `mc_wbs_labels`, `mc_wbs_base`, `mc_wbs_lo`, `mc_wbs_hi`, `mc_wbs_dist`, `mc_c1_trigger`, `mc_c1_amp`, `mc_c2_trigger`, `mc_c2_factor`, `mc_cascade_on`, `mc_cascade_slip`, `mc_cascade_cap`, `mc_cascade_cost`, `mc_cg_coeffs`, `mc_party_a`, `mc_party_b`, `mc_shared_label`, `mc_results`.

Gain/pain share (`MC_Params` section G, rows 74-80):
`mc_gp_enabled`, `mc_gp_toc`, `mc_gp_share_split`, `mc_gp_max_reward`, `mc_gp_max_risk`.

Not yet created (reader falls back to defaults):
`mc_programme_seasons`, `mc_wbs_rho`, `mc_pool_budget`, `mc_register_path`.

### 10.2 Cost MC workbook sheet structure (legacy cost workbook)

| Sheet | Purpose | Audience |
|---|---|---|
| `MC_Dashboard` | One-page summary: P-values, adequacy, sanity check, S-curve chart | Project leadership, client, lender |
| `MC_Inputs` | Risk rows with probability, ranges, CG. Blue cells editable | Estimator, workshop |
| `RR_Snapshot` | Copy of risk register data feeding `MC_Inputs` via formulas | Reference |
| `Cont_Share_rev` | Client-provided gain/pain sharing calculation | Commercial / contract |
| `Contingency_Share` | Older gain/pain parameter sheet (superseded by `Cont_Share_rev`) | — |
| `Pricing Summary` | BOP pricing breakdown by WBS line item | Commercial |
| `MC_Outputs` | Detailed results: P-value table by view, tornado, layer split, convergence | Cost / risk manager |
| `MC_Params` | Global parameters: iterations, TIC, chains, CG coefficients, party config | Risk manager |
| `MC_Engine` | Key-value results range written by Python; XLOOKUP source for Dashboard/Outputs | Technical / audit |
| `MC_SingleRun` | One random scenario in full detail — transparency tool for leadership meetings | Project leadership, sceptics |
| `Methodology Note` | Methodology description for workbook users | All |
| `xlwings.conf` | xlwings configuration | — |

### 10.3 SRA strawman contract

The SRA pipeline reads only; does not write back to the strawman.

| Sheet | Consumer | Purpose |
|---|---|---|
| `Risk_Scope` | `strawman_reader.read_risk_scope` | One row per Open risk; `Mode_Aggregated` is canonical Mode source: this column is the single source of truth for DP Review baseline Modes |
| `Risk_Pattern_Assignments` | `strawman_reader.read_risk_pattern_assignments` | Maps each risk to a pattern_id |
| `Risk_Activity_Patterns` | `strawman_reader.read_risk_activity_patterns` | Pattern-level metadata |
| `Run_Config_Preview` (in a consolidated register, such as both shipped ones, `MC_Params` carries iterations, the reporting P-level, the day rate, programme seasons, the hybrid float threshold, the schedule duration and the expected Time=Yes count; the other rows are not read from a consolidated register) | `strawman_reader.read_run_config` | Iterations, p_level, day_rate_default, schedule duration, LD parameters |
| `Methodology` (grid-native registers; legacy registers carry the `meth_*` named ranges instead) | `methodology_defaults_reader.read_mode_multipliers`, `read_calibration_tolerances`, `read_default_injection_method`; `qra_register_parse.resolve_methodology_from_grid` | Label/value rows: `CGnn` coefficients; `Series`/`Hybrid`/`Parallel` multipliers; `Cost_Calibration_Tolerance_Dollars`, `Cost_Calibration_Tolerance_Pct`, `Schedule_Calibration_Tolerance_Days`, `Schedule_Calibration_Tolerance_Pct` (cost passes on dollars OR percent, schedule on days OR percent); `Default_Injection_Method` (one of `additive_pert_days`, `discrete_event_additive_days`, `productivity_multiplicative_factor`). **These are register values with no code default; a register carrying none refuses.** |
| `Mapping` (consolidated registers) | `strawman_reader._read_mapping_sheet`, joined into the scope frame | Per-risk CPM binding: `Pattern_ID`, `Prefix_List`, `Activity_Count`, `Gating_Activity_ID`, and `Injection_Method` (optional; blank takes the register's `Default_Injection_Method`). |
| `Summary` | `strawman_reader.get_strawman_calibration_target` | Comparator 1 (EMV) and Comparator 2 (Mode-weighted aggregate) calibration targets |
| `Mapping`, `Mapping_ARCHIVE`, `P6_Processed`, `CP_Classifier_QA` | (not read by engine) | Audit-trail / strawman-build artefacts. **`Mapping_ARCHIVE` not referenced by any engine code path** |

Pre-flight: `RUN_FINAL.bat` checks for the strawman's Excel lock file (the `~$` sibling of whatever the binding declares) and fail fast if Excel has the workbook open.
