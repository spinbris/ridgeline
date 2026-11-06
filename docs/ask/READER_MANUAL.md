# outturn reader manual

contract_version: 1.7

This manual is the reference for the Ask box on the outturn risk dashboard. It says what every
figure in a period's data means, how each page and chart is read, and the caveats that travel
with the numbers. The Ask box answers from this manual and from the one period's data the reader
is looking at, and nothing else.

ASKSVC-01 stage B. The stamp above must equal the period data's `schema_version`; a test in the
repository fails when it does not, or when the data carries a field this manual does not describe.

---

## 1. What the dashboard is

The dashboard shows a quantitative cost and schedule risk analysis for one capital project, and
how that analysis moves month by month. Each month is a "period". A period is one run of the
analysis on that month's risk status, written as one data file and shown as one view of the
dashboard. The period picker in the header chooses which period is on screen.

The analysis is a Monte Carlo simulation. The project's risk events are simulated thousands of
times. Each run (an "iteration") decides which risks happen and how badly, replays the schedule
network to find the finish date, and adds up the cost. The results are distributions of cost and
finish date, read at confidence levels called P-levels.

What it presents is the **event-risk contingency**: the allowance for the register's risk events,
including what their delay costs. The base estimate is an input, not something the dashboard
produces. Base plus contingency is shown as an owner's view on the analyst pages.

The full technical report, linked from the top of the first page, holds the certified figures.
The dashboard and the Ask box explain them.

### Who it is for

There are two views, chosen by the PM / Analyst toggle in the header.

- **PM view**: four pages written for a project manager, sponsor or finance reader.
- **Analyst view**: the distributions, drivers, activity detail and audit behind the PM pages.

The toggle is a view, not a permission. Anyone with the link can switch.

### Stage framing

Every period shown is a **Delivery** period: the project is being tracked month by month against
its risk position. Before the budget is committed, the contingency is shown as "Recommended at
P80"; from the commitment date it is shown as "held against required" (section 5, Contingency
position). A separate Assessment view, for a project before commitment, is planned but not part
of this version.

### The showcase project

The published example is a synthetic 40 MW wind farm, Tropic Ridge, with a $120M illustrative base
estimate and a plan of about fourteen months. Its data is made up to demonstrate the method. Where
the data marks a figure as illustrative (`contingency.illustrative`, `meta.contingency_illustrative`),
say so.

---

## 2. P-levels and the standing caveats

**P-levels.** P80 is the value that 80% of simulated outcomes fall at or below: enough in eight
outcomes out of ten. P50 is the median. The dashboard's convention:

- P80 is the primary figure, the one contingency is sized on.
- P90 is secondary.
- P50 and P95 are supporting context.
- P99, where it appears in the report, is driven by single long-tail risks and is never used to
  size contingency.
- The mean is shown beside the P-levels for context. For a right-skewed distribution it sits near
  the P50, well below the P80.

**Standing caveats.** State these whenever a question turns on them.

1. **The headline finish is event risks only.** `headline.p80_finish` comes from the risk events
   alone. The owner-view finish (`integrated.owner_view.p80_finish`) adds the shared drivers,
   which are uncertainty on the estimate itself (productivity, quantities), and is later. The
   total cost and the joint confidence read the owner-view finish.
2. **Joint confidence is lower than 80% by design.** It is the chance of meeting the budget AND
   the P80 finish in the same simulated outcome. Two 80% targets met together is always less
   likely than either alone.
3. **The cost axis of the joint confidence includes delay cost**, as the budget funds it, and the
   base estimate drawn as uncertain. Its basis is stated in `integrated.jcl.basis`.
4. **Mode does not act on the headline.** Each risk carries a Mode (Series, Hybrid, Parallel),
   which describes how its delay would combine with others under an older approximation. The
   headline uses a full replay of the schedule network instead, so Mode is recorded for
   reference only and does not change any headline figure.
5. **Contributions do not add up.** Each risk's dollar and day contribution is measured by taking
   that one risk out and re-running. Risks overlap on the critical path, so the per-risk figures
   do not sum to the total, and the cost/delay split of each is a stated convention, not unique.
6. **Diversification.** The joint P80 is below the sum of a cost-only P80 and a delay-only P80,
   because cost and delay do not peak in the same outcomes.
7. **Simulation noise.** Figures move slightly between runs. Small differences, such as a
   mitigation saving flagged as within noise, should not be read as real.
8. **Risk-to-activity links are auto-mapped**, not yet confirmed in a workshop, and one project
   calendar is used for the whole schedule. The report states both on its face.
9. **Out of scope**: liquidated damages, escalation, interest during construction, time-phased
   cash flow, and identifying risks. The register is an input; the analysis quantifies it.

---

## 3. Units and how figures are written

- Dollars are Australian dollars. The data holds them to the cent; the pages show them in
  millions to two decimals (14,410,870.17 shows as $14.41M). Quote either.
- Probabilities, confidences and indices are fractions from 0 to 1 in the data and percentages
  on the page (0.3265 shows as 32.7% or 33%).
- Dates are ISO (2026-11-18) in the data and "18 Nov 2026" on the page.
- **Two kinds of days.** "Days behind plan", every `delta_vs_det` and the movement in the P80
  finish (`delta.p80_delta_days`) are calendar days between two dates. Everything measured on the schedule network (risk days at risk, delay days, activity
  start and finish days, sigma) is in working days. Do not mix them in one sentence without saying
  which is which.
- The day rate is dollars per working day of delay.

---

## 4. The pages

### PM page 1: How much and when (`/`)

Four tiles across the top, then the explanation beneath.

- **Risk contingency (P80)**: `integrated.p80_dollars`, with P50 and P90 beneath. Captioned
  "Allowance for risk events plus delay, enough in 8 of 10 outcomes. Excludes the base estimate."
- **Finish (P80)**: `headline.p80_finish`, and `headline.p80_days_behind_plan` calendar days after
  the plan finish `headline.deterministic_finish`. A line beneath gives the owner-view P80
  finish with shared drivers (`integrated.owner_view.p80_finish`).
- **Since last period**: the movement in the P80 contingency (`delta.p80_delta_dollars`) and in
  the P80 finish (`delta.p80_delta_days`). A first period says there is nothing to compare yet.
- **On budget and on time**: the joint confidence `integrated.jcl.jcl`, the chance of finishing
  within the cost target `integrated.jcl.cost_target_dollars` and by
  `integrated.jcl.finish_target_date` together. "How this is worked out" opens the basis.

Beneath the tiles:

- **How the contingency is made up**: the build-up for P50, P80 and P90 (`integrated.build_up`):
  event cost, delay days, delay cost at the day rate, their standalone sum, the joint contingency,
  and the diversification between them.
- **P80 forecast trend**: the P80 finish and P80 contingency for up to the last five periods and
  this one (`trend.periods`).
- **Contingency position**: recommended at P80 before commitment, then held against required
  (section 5).
- **Open, fired and closed counts** (`headline.open_risks_count`, `headline.fired_this_period_count`,
  `headline.closed_this_period_count`).
- **Near-critical milestones (next 30 days)**: `headline.near_critical_milestones_30d`.
- **Shared drivers** card: the estimate uncertainties and what each adds (section 5).

### PM page 2: What's driving risk (`/risks/`)

The risk table, sorted by days at risk at P80, most first. Each row opens to its detail. The
columns are the per-risk fields in section 5: status, probability, owner, days at risk, the P80
dollar contribution split into cost and delay, and criticality. A risk the period closed or
removed shows zero contribution.

### PM page 3: What we could do (`/mitigations/`)

The P80 finish without and with each proposed mitigation, and a card per mitigation: its cost,
lead time, owner, status, the days and dollars it saves at P80, and whether the saving is within
simulation noise. A period with no mitigation log shows none.

### PM page 4: What changed (`/changes/`)

The P80 finish and contingency against last period, a one-paragraph summary
(`delta.net_movement_summary`), and three lists: worse this period, better this period, and new
this period. Each entry names the risk, what changed (`change_meta`), and its movement in days at
risk and in P80 dollars. A first period carries only a note.

### Analyst: Distributions (`/analyst/`)

- **S-curve: cumulative probability of project finish** (`distribution.s_curve_points`): read
  across from a probability to a date.
- **Histogram: project finish distribution** (`distribution.histogram_bins`): how many simulated
  outcomes finish in each date band.
- **Percentile table** (`distribution.percentile_table`): finish date and days behind plan at
  each percentile.
- **S-curve: integrated event-risk cost** (`integrated.curve_points`): the contingency at each
  probability.
- **Joint confidence: cost and finish together**: the JCL detail (`integrated.jcl`).
- **Total cost**: base drawn plus event-risk cost plus delay cost at P50, P80 and P90
  (`integrated.total_cost`), shown on the analyst side only.
- **Day rate derivation**: how the day rate compares with prelims (`integrated.day_rate_derivation`).

### Analyst: Drivers and sensitivity (`/analyst/drivers/`)

- **Tornado: per-risk sigma days**: how much each live risk widens the finish distribution, in
  working days. Sample-based where available (`tornado_sample_sigma_days`), else a PERT proxy
  (`tornado_sigma_days`). Not additive. Values under about 0.3 days are noise.
- **Schedule Sensitivity Index per risk** (`ssi`): a combined measure of how much a risk's
  activities vary and how often they sit on the critical path.
- **Shared drivers: uncertainty on the estimate, not events** (`integrated.shared_drivers`).
- **Metric definitions** card.

### Analyst: Activity-level detail (`/analyst/activities/`)

- **Stochastic Gantt, top activities by criticality** (`activities.items`): each activity's P10,
  P50 and P90 start and finish against its planned dates.
- **Critical-path statistics** (`activities.cp_stats`).

### Analyst: Methodology audit (`/analyst/audit/`)

Engine configuration (`audit.config`), calibration gates (`audit.calibration_gates`),
methodology notes (`audit.methodology_notes`), and the reviewer.

### Header, banners and footer

The header carries the project name, the period picker and the PM / Analyst toggle. A banner
appears when the latest period is overdue; for the synthetic showcase a neutral line says it is an
example project instead. The footer carries the engine version and flags a period produced from
uncommitted code.

---

## 5. Field reference

Every field the period data carries. `[]` marks a list; `<risk_id>` stands for a risk identifier
such as WT-021. "Null" means the field is present but empty because it does not apply this
period.

### Top level

- `schema_version`: the data contract version. Must equal this manual's stamp.

### meta: where the period came from

- `meta.period_end_date`: the last day of the period. The date the figures are as at.
- `meta.previous_period_end_date`: the prior period's end date; null for a first period.
- `meta.project_display_name`: the project's name as shown in the header.
- `meta.project_key`: the project's identifier in the system.
- `meta.register_version`: the version label of the risk register the period read.
- `meta.workbook_filename`, `meta.xer_filename`: the status workbook and schedule file used.
- `meta.iterations`: simulation iterations in the main run.
- `meta.seed`, `meta.seed_source`: the random seed and where it came from. The same seed and
  inputs reproduce the same numbers.
- `meta.engine_run_date`, `meta.engine_run_hash`: when the run happened and a unique run id.
- `meta.engine_sha`, `meta.engine_tree_dirty`: the code version, and whether it had uncommitted
  changes. A dirty run is not evidence.
- `meta.input_sha256.register.method`, `meta.input_sha256.register.value`,
  `meta.input_sha256.workbook.method`, `meta.input_sha256.workbook.value`,
  `meta.input_sha256.xer.method`, `meta.input_sha256.xer.value`: fingerprints of the three
  inputs, and how each was taken. Provenance only.
- `meta.contingency_illustrative`: present and true when the contingency held figures are
  illustrative, not a real ledger.

### headline: the schedule headline (event risks only)

- `headline.deterministic_finish`: the plan finish with no risks, from the schedule.
- `headline.p10_finish`, `headline.p50_finish`, `headline.mean_finish`, `headline.p80_finish`,
  `headline.p90_finish`, `headline.p95_finish`: forecast finish dates at each level. P80 is the
  headline. Event risks only; see the owner view for shared drivers.
- `headline.p50_days_behind_plan`, `headline.p80_days_behind_plan`, `headline.p90_days_behind_plan`:
  calendar days from the plan finish to that finish date.
- `headline.open_risks_count`: risks open (including actioned and monitor) this period.
- `headline.fired_this_period_count`, `headline.closed_this_period_count`: risks that occurred, or
  were closed, this period.
- `headline.near_critical_milestones_30d[]`: milestones within 30 days that are near-critical.
  Not populated in this version; an empty list means not assessed, not "none at risk".

### trend: the movement across periods

- `trend.periods[].period_end`: each period's end date, oldest first, this period last.
- `trend.periods[].p80_finish`: that period's P80 finish.
- `trend.periods[].contingency_p80_dollars`: that period's P80 risk contingency; null for a period
  that carried none.

### risks: one row per tracked risk

- `risks[].risk_id`, `risks[].title`, `risks[].context`: the register's identifier, title and any
  context note.
- `risks[].owner`: who manages it.
- `risks[].status`: open, actioned, monitor, fired or closed, this period.
- `risks[].probability`: the chance it occurs, as run this period (after any override).
- `risks[].impact_days_emv`: probability times most-likely delay, in working days. A quick
  expected-value measure, not a simulation output.
- `risks[].days_at_risk_p80`: how many working days later the P80 finish is with this risk than
  without it. The table's sort key.
- `risks[].cost_p80_contribution_dollars`: how much lower the P80 contingency is with this risk
  taken out. Split into `risks[].cost_part_dollars` (its own cost) and
  `risks[].delay_part_dollars` (the delay it causes, at the day rate). Null when the period has no
  integrated result; zero for a risk the period removed.
- `risks[].delay_days_saved_p80`: working days the integrated P80 delay falls with the risk out.
- `risks[].criticality_conditioned`, `risks[].criticality_independent`: how often the risk's
  activities sit on the critical path, measured two ways; fractions 0 to 1.
- `risks[].ssi`: Schedule Sensitivity Index, a combined measure of variance and criticality.
- `risks[].cruciality_proxy_p80`: days at risk normalised to a 0 to 1 scale, for ranking.
- `risks[].tornado_sample_sigma_days`: working days the risk adds to the spread of the finish,
  by leave-one-out; null when not evaluated.
- `risks[].tornado_sigma_days`: the PERT-proxy fallback for the same, status-blind.
- `risks[].mode`: Series, Hybrid or Parallel. Recorded only; does not act on the headline.
- `risks[].cg_code`: the correlation group, if any: risks whose outcomes move together.

### mitigations: one row per logged mitigation

- `mitigations[].mitigation_id`, `mitigations[].risk_id`, `mitigations[].description`: what it is
  and which risk it treats.
- `mitigations[].cost_aud`: its estimated cost; `mitigations[].lead_time_weeks`: time to put in
  place; `mitigations[].owner`; `mitigations[].status` (proposed, approved, in progress,
  completed, rejected).
- `mitigations[].days_saved_p80`: working days the P80 finish moves earlier with it in place.
- `mitigations[].p80_finish_with_mitigation`: the P80 finish with it in place.
- `mitigations[].dollars_saved_p80`: how much the P80 contingency falls with it; proposed rows only,
  else null.
- `mitigations[].within_noise.dollars`, `mitigations[].within_noise.days`: true when that saving is
  smaller than twice the run's own noise, so it should not be relied on.
  `mitigations[].within_noise.noise_dollars`, `mitigations[].within_noise.noise_days`: the noise
  level used.

A mitigation's cost against its dollar saving is for the reader to compare; the dashboard does
not net them.

### activities: the schedule network detail

- `activities.items[].activity_id`, `activities.items[].name`: the schedule activity.
- `activities.items[].p10_start_days`, `activities.items[].p50_start_days`,
  `activities.items[].p90_start_days`, `activities.items[].p10_finish_days`,
  `activities.items[].p50_finish_days`, `activities.items[].p90_finish_days`: simulated start and
  finish, in working days from project start.
- `activities.items[].det_es_days`, `activities.items[].det_ef_days`: planned early start and finish
  in working days from project start.
- `activities.items[].criticality_index`: share of iterations the activity is on the critical
  path.
- `activities.top_n_by_ci`: how many activities the Gantt shows; `activities.ci_threshold`: the
  criticality cut-off used.
- `activities.p_band_derivation_method`: how the activity bands were derived (A, B or C); see
  the methodology notes.
- `activities.mode_summary.series`, `activities.mode_summary.hybrid`,
  `activities.mode_summary.parallel`, `activities.mode_summary.total`: count of risks by Mode.
  Reference only.
- `activities.cp_stats.activities_on_det_cp`: activities on the planned critical path.
- `activities.cp_stats.activities_ci_gt_50`, `activities.cp_stats.activities_ci_gt_80`:
  activities critical in over half, or over 80%, of iterations.
- `activities.cp_stats.stochastic_cp_additions`: activities that become critical under risk but
  are not on the planned critical path.
- `activities.cp_stats.longest_path_p80_days`: P80 length of the longest path, working days.
- `activities.cp_stats.zero_float_activities`, `activities.cp_stats.mean_activity_float_days`,
  `activities.cp_stats.float_sigma_days`: float statistics, working days.

### distribution: the finish-date distribution (event risks only)

- `distribution.s_curve_points[].date`, `distribution.s_curve_points[].cumulative_prob`: points on
  the finish S-curve.
- `distribution.histogram_bins[].date_range_start`, `distribution.histogram_bins[].date_range_end`,
  `distribution.histogram_bins[].count`: the histogram bands and how many iterations fall in each.
- `distribution.percentile_table[].percentile`, `distribution.percentile_table[].date`,
  `distribution.percentile_table[].days_from_start` (working days),
  `distribution.percentile_table[].delta_vs_det` (calendar days behind the plan finish).

### delta: what changed since last period

- `delta.period_0`, `delta.note`: true, with a note, on a first period.
- `delta.p80_delta_days`: change in the P80 finish against last period, calendar days.
- `delta.p80_previous`, `delta.p80_current`: last period's and this period's P80 finish.
- `delta.p80_delta_dollars`: change in the P80 contingency; null when last period carried none.
- `delta.worse[]`, `delta.better[]`, `delta.new[]`: risks that moved, each with
  `delta.worse[].risk_id`, `delta.worse[].description`, `delta.worse[].change_meta` (what changed:
  status, probability or days at risk), `delta.worse[].delta_days` (movement in days at risk) and
  `delta.worse[].delta_dollars` (movement in P80 contribution; null when either period lacks it).
  The better and new lists carry the same fields: `delta.better[].risk_id`,
  `delta.better[].description`, `delta.better[].change_meta`, `delta.better[].delta_days`,
  `delta.better[].delta_dollars`, `delta.new[].risk_id`, `delta.new[].description`,
  `delta.new[].change_meta`, `delta.new[].delta_days`, `delta.new[].delta_dollars`.
- `delta.net_movement_summary`: the engine's one-paragraph account of the movement.

### audit: how the run was configured and checked

- `audit.config.engine`, `audit.config.iterations`, `audit.config.sampling_method`,
  `audit.config.seed`, `audit.config.cp_rule`, `audit.config.p_level_reporting`,
  `audit.config.cl_mode`: the engine settings.
- `audit.calibration_gates[]`: each check with `audit.calibration_gates[].check`,
  `audit.calibration_gates[].target`, `audit.calibration_gates[].actual`,
  `audit.calibration_gates[].status` and `audit.calibration_gates[].note`. An empty list means no
  gate was run in the period route.
- `audit.methodology_notes[].topic`, `audit.methodology_notes[].method`,
  `audit.methodology_notes[].text`, `audit.methodology_notes[].queued_for_v1_1`: the method used
  for each derived metric, in words.
- `audit.stage_brief`, `audit.reviewer`, `audit.reviewer_approved_date`: the governing brief and
  the reviewer's sign-off, where recorded.
- `audit.integrated_unavailable`: present only when the integrated result could not be produced,
  with the reason.

### integrated: the cost-plus-schedule result

The integrated distribution is event-risk cost plus delay days at the day rate, simulated jointly:
a risk that delays and costs fires once and carries both. Risk states are pinned from the month's
status workbook.

- `integrated.basis`: the basis in words.
- `integrated.p50_dollars`, `integrated.mean_dollars`, `integrated.p80_dollars`,
  `integrated.p90_dollars`, `integrated.p95_dollars`: the risk contingency at each level.
  `integrated.p80_dollars` is the headline.
- `integrated.curve_points[].dollars`, `integrated.curve_points[].cumulative_prob`: points on its
  S-curve.
- `integrated.cost_marginal.mean_dollars`, `integrated.cost_marginal.p80_dollars`: event cost alone.
- `integrated.schedule_marginal.mean_delay_days`, `integrated.schedule_marginal.p80_delay_days`:
  delay alone, working days.
- `integrated.day_rate`: dollars per working day of delay.
- `integrated.deterministic_baseline_days`: the plan duration, working days.
- `integrated.iterations`: iterations in the integrated run.
- `integrated.what_counts_where`: which costs sit in risk events and which on the delay line, so
  nothing is counted twice.
- `integrated.build_up[]`: one row per P-level, with `integrated.build_up[].p_level`,
  `integrated.build_up[].event_cost_dollars`, `integrated.build_up[].delay_days`,
  `integrated.build_up[].delay_cost_dollars`, `integrated.build_up[].standalone_sum_dollars` (event
  plus delay cost, each at that level on its own), `integrated.build_up[].joint_contingency_dollars`
  (the joint figure, which is the contingency), and `integrated.build_up[].diversification_dollars`
  (standalone sum less joint).
- `integrated.pinning.risks_priced`, `integrated.pinning.risks_removed`,
  `integrated.pinning.risks_closed`, `integrated.pinning.risks_reprobabilised`: how the month's
  status changed the risk set. `integrated.pinning.removed_risk_ids[]`,
  `integrated.pinning.closed_risk_ids[]`, `integrated.pinning.reprobabilised_risk_ids[]` list them.
  `integrated.pinning.priced_probabilities.<risk_id>`: the probability each priced risk ran at.
- `integrated.leave_one_out.p_level`, `integrated.leave_one_out.iterations`,
  `integrated.leave_one_out.replays`, `integrated.leave_one_out.method`: how the per-risk dollar
  contributions were measured.

**Joint confidence** (`integrated.jcl`):

- `integrated.jcl.jcl`: the share of iterations meeting the cost target and the finish target
  together.
- `integrated.jcl.cost_target_dollars`: the budget tested, declared base plus P80 contingency.
- `integrated.jcl.declared_base_dollars`: the declared base estimate; `integrated.jcl.base_drawn`:
  true when the base is simulated as uncertain rather than fixed.
- `integrated.jcl.cost_confidence`: chance of meeting the cost target alone.
- `integrated.jcl.finish_target_date`: the finish tested (the owner-view P80 finish when shared
  drivers exist); `integrated.jcl.finish_confidence`: chance of meeting it alone.
- `integrated.jcl.p_level`: the level the targets are set at.
- `integrated.jcl.frontier_level`: a reference level for the joint confidence frontier on the
  chart.
- `integrated.jcl.basis`: the basis in words, including the cost-finish correlation.

**Total cost** (`integrated.total_cost`, analyst view only):

- `integrated.total_cost.label`: what it is.
- `integrated.total_cost.declared_base_dollars`, `integrated.total_cost.mean_dollars`.
- `integrated.total_cost.rows[].p_level`, `integrated.total_cost.rows[].total_dollars`,
  `integrated.total_cost.rows[].contingency_dollars` (total less the declared base). This is larger
  than the event-risk contingency because it also carries the base estimate's own uncertainty
  and the shared drivers. It is not the headline.
- `integrated.total_cost.excluded_base_factors[]`: base uncertainty factors left out, to avoid
  counting them twice.

**Day rate derivation** (`integrated.day_rate_derivation`):

- `integrated.day_rate_derivation.day_rate_used`, `integrated.day_rate_derivation.day_rate_stated`,
  `integrated.day_rate_derivation.day_rate_derived`: the rate used, as stated in the register, and
  as derived from prelims.
- `integrated.day_rate_derivation.avg_prelims_weekly`,
  `integrated.day_rate_derivation.schedule_duration_weeks`,
  `integrated.day_rate_derivation.programme_working_days`: the inputs to the derivation.
- `integrated.day_rate_derivation.gap_dollars`, `integrated.day_rate_derivation.gap_flagged`,
  `integrated.day_rate_derivation.note`: the difference, whether it is flagged, and a note.

**Owner view** (`integrated.owner_view`): the finish with shared drivers on as well as event risks.

- `integrated.owner_view.label`: what it is.
- `integrated.owner_view.driver_ids[]`: the shared drivers included.
- `integrated.owner_view.p50_finish`, `integrated.owner_view.p80_finish`,
  `integrated.owner_view.p90_finish`, `integrated.owner_view.p80_days_behind_plan` (calendar days).
- `integrated.owner_view.s_curve_points[].date`, `integrated.owner_view.s_curve_points[].cumulative_prob`,
  `integrated.owner_view.percentile_table[].percentile`, `integrated.owner_view.percentile_table[].date`,
  `integrated.owner_view.percentile_table[].days_from_start`,
  `integrated.owner_view.percentile_table[].delta_vs_det`: its curve and table, as for the headline.
- `integrated.owner_view.driver_method`: how the drivers were applied.

**Shared drivers** (`integrated.shared_drivers[]`): uncertainties on the estimate itself, not
events. They act on every iteration rather than firing or not.

- `integrated.shared_drivers[].driver_id`, `integrated.shared_drivers[].name`.
- `integrated.shared_drivers[].kind`: P for productivity (acts on duration and the cost that scales
  with it), Q for quantity.
- `integrated.shared_drivers[].wbs_codes[]`: the parts of the work it acts on.
- `integrated.shared_drivers[].range`: its low / most likely / high range as a percentage.
- `integrated.shared_drivers[].acts_on`, `integrated.shared_drivers[].basis`: what it acts on and
  why, in words.
- `integrated.shared_drivers[].mean_duration_change`, `integrated.shared_drivers[].p80_duration_change`:
  the change it makes to affected durations, as a fraction (0.146 is 14.6% longer).
- `integrated.shared_drivers[].adds_to_total_dollars`, `integrated.shared_drivers[].adds_to_finish_days`,
  `integrated.shared_drivers[].p_level`: what it adds to the total cost and the finish at that
  level, by leave-one-out. Not additive.

### contingency: the contingency position

- `contingency.phase`: "recommended" before the budget is committed, "held" from the commitment
  date.
- `contingency.label`: the label shown, for example "Recommended at P80".
- `contingency.required_p80_dollars`: the P80 risk contingency required this period.
- `contingency.illustrative`: true when the held figures are illustrative (the showcase).
- `contingency.commitment_date`, `contingency.opening_held_dollars`: when the budget was committed
  and the contingency held at that date. Null before commitment.
- `contingency.held_dollars`: contingency held now: opening, less approved draws, plus approved
  releases.
- `contingency.approved_draws_dollars`, `contingency.releases_dollars`: approved draws and releases
  to date.
- `contingency.pending_draws_dollars`: draws requested but not yet approved, shown apart and not
  taken off held.
- `contingency.shortfall_dollars`: required less held. Positive is a shortfall; negative is
  headroom.
- `contingency.jcl_against_held`, `contingency.cost_confidence_against_held`: joint and cost
  confidence with the budget set at base plus the contingency actually held.
- `contingency.movements[]`: the ledger, with `contingency.movements[].date`,
  `contingency.movements[].type` (Draw or Release), `contingency.movements[].amount_dollars`,
  `contingency.movements[].status` (Approved or Pending), `contingency.movements[].risk_id` and
  `contingency.movements[].note`.
- `contingency.bridge`: last period's P80 contingency to this one's, step by step. Null on a first
  period. When it could not be built, `contingency.bridge.available` is false and
  `contingency.bridge.reason` says why. Otherwise: `contingency.bridge.prior_period_end_date`,
  `contingency.bridge.prior_p80_dollars`, `contingency.bridge.current_p80_dollars`,
  `contingency.bridge.order` (the step order: closed risks, new risks, reassessed risks,
  mitigations, other), `contingency.bridge.method`, and `contingency.bridge.steps[]` with
  `contingency.bridge.steps[].key`, `contingency.bridge.steps[].label`,
  `contingency.bridge.steps[].dollars` and `contingency.bridge.steps[].risk_ids`. "Other" is what
  the replay could not attribute, including simulation noise.

---

## 6. Glossary

- **Base estimate**: the project cost before contingency. An input.
- **Contingency (event-risk)**: the allowance for risk events and the delay they cause.
- **Critical path**: the chain of activities that sets the finish date.
- **Criticality index**: the share of simulated outcomes in which an activity is on the critical
  path.
- **Day rate**: the cost of one working day of delay, mainly site running costs.
- **Delay cost**: delay days times the day rate.
- **Diversification**: how much lower the joint figure is than adding cost and delay separately.
- **Fired**: a risk that has occurred.
- **Float**: how far an activity can slip without moving the finish.
- **JCL (joint confidence level)**: the chance of meeting the cost and finish targets together.
- **Leave-one-out**: measuring a risk's effect by re-running without it.
- **Monte Carlo simulation**: running the project many times with random outcomes to get a range.
- **Owner view**: the finish or total cost with shared drivers included.
- **P-level (P50, P80, P90)**: the value that share of simulated outcomes falls at or below.
- **Period**: one month's run and its data.
- **Shared driver**: uncertainty on the estimate itself, such as productivity, that affects many
  activities at once.
- **S-curve**: cumulative probability against cost or date.

---

## 7. Answer rules for the Ask box

- Answer from this manual and the period's data only. If the answer is not there, say so and
  point the reader to the page or the full technical report that would show it.
- Write plain text for a project manager or finance reader. No markdown formatting, no headings,
  no tables. Short paragraphs; a short list only when the question asks for several items.
- Use the page and tile names readers see ("the Risk contingency (P80) tile", "the What changed
  page"), never the data field names.
- Do not mention this manual. Say "the dashboard" or "the report".
- Quote figures as they appear, in dollars-in-millions to two decimals or to the dollar, as
  percentages, and as dates. Never calculate a difference, sum or ratio: name both figures and,
  where the dashboard already shows the comparison (the Since last period tile, the build-up,
  the bridge, the delta lists, the shortfall), point the reader there.
- When a question compares the headline finish with the total cost or the joint confidence, say
  which finish each uses (caveat 1).
- Do not advise what contingency to hold or what decision to make. Explain what the analysis
  shows. The report holds the certified figures.
