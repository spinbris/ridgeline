/**
 * TypeScript interfaces for the AM02.1 / Doc 3 v2.3 JSON contract.
 *
 * Hand-written from the archived repository's v2.3 spec (the authority is
 * `src/am/json_writer.py`) and the actual
 * `period_20260528.json` artefact. Doc 3 v2.3 is a markdown spec, not
 * a machine-readable JSON Schema; auto-generation is a v1.1 conversation
 * if/when an upstream schema lands (see AM03 brief §4 Type generation).
 *
 * Paired with zod schemas in `lib/loadPeriod.ts` for runtime validation
 * at load time. Whenever this file changes, the zod schemas must change
 * in lock-step.
 *
 * No `any`. No fields that the contract doesn't carry. If the dashboard
 * needs a value the JSON doesn't provide, raise an engine-side brief
 * (AM02.x / AM03.1) rather than computing it client-side
 * (per AM03 §3 standing SOP).
 */

// ---------------------------------------------------------------------------
// `meta`
// ---------------------------------------------------------------------------

export interface Meta {
  period_end_date: string; // YYYY-MM-DD
  previous_period_end_date: string | null; // YYYY-MM-DD or null on period 0
  engine_run_date: string; // ISO 8601 datetime
  engine_run_hash: string; // UUID v4
  register_version: string; // e.g. "Tropic Ridge Wind Farm"
  workbook_filename: string;
  xer_filename: string;
  iterations: number;
  seed: number;
  // Optional project display name for the dashboard chrome (showcase-P5
  // WS5-C). Resolved from the period data, not hardcoded. Optional so the
  // pre-P5 field-less the engagement artefact still validates; absent -> the
  // chrome falls back to the archived default.
  project_display_name?: string;
  // Contract 1.4, stage 7 part C (B-2): which project this period belongs to. OPTIONAL by
  // ruling, so the PATH is authoritative and this corroborates it - a period without it,
  // sitting in a project directory, belongs to that directory.
  project_key?: string;
  // AM09 engine-provenance stamp (Doc 3 v2.6). All optional so a pre-AM09
  // ("1.1") artefact that lacks them still validates; a stamped ("1.2")
  // artefact is traceable to the engine code + inputs that produced it.
  // Nullable where the run's git query can soft-fail.
  engine_sha?: string | null;
  // Stage 7 part A (C-2): the two pin fields are gone. RS-A2 P-3 dropped them from the
  // contract and nothing has emitted them since; the note here used to say "kept optional
  // until contract 1.4 removes them", and part A removes them ahead of the 1.4 bump
  // because keeping a dead field costs a reader more than the sequencing saves.
  engine_tree_dirty?: boolean | null;
  // PROVCRLF01 (schema 1.3): each digest carries the method that produced it.
  // A tracked input is identified by its git blob OID, which is normalised for
  // line endings and therefore identical on every machine at the same commit;
  // anything untracked or outside a repo falls back to a byte hash. The method
  // is a recorded field rather than something the reader infers from the value,
  // because a provenance record that silently switches method is the defect the
  // stamp exists to rule out.
  input_sha256?: {
    register: InputDigest;
    xer: InputDigest;
    workbook: InputDigest;
  };
}

export type InputDigestMethod = "git_blob_oid" | "sha256_bytes";

export interface InputDigest {
  method: InputDigestMethod;
  value: string;
}

// ---------------------------------------------------------------------------
// `headline`
// ---------------------------------------------------------------------------

export interface Headline {
  p10_finish: string; // YYYY-MM-DD
  p50_finish: string;
  mean_finish: string;
  p80_finish: string;
  p90_finish: string;
  p95_finish: string;
  deterministic_finish: string;
  p80_days_behind_plan: number;
  p50_days_behind_plan: number;
  p90_days_behind_plan: number;
  open_risks_count: number;
  fired_this_period_count: number;
  closed_this_period_count: number;
  near_critical_milestones_30d: string[];
}

// ---------------------------------------------------------------------------
// `trend`
// ---------------------------------------------------------------------------

export interface TrendPoint {
  period_end: string; // YYYY-MM-DD
  p80_finish: string; // YYYY-MM-DD
}

export interface Trend {
  periods: TrendPoint[];
}

// ---------------------------------------------------------------------------
// `risks`
// ---------------------------------------------------------------------------

export type RiskStatus =
  | "open"
  | "actioned"
  | "monitor"
  | "fired"
  | "closed";

export type RiskMode = "Series" | "Hybrid" | "Parallel";

// AM10 (WIND-01 A4): DORMANT - no longer used on the Risk type (the
// divergence_flag field was removed, Doc 3 v2.5). Retained for the deferred
// WIND-01b Mode-sensitivity run, mirroring DivergenceBadge.tsx.
export type DivergenceFlag =
  | "consistent"
  | "mode_amplifies"
  | "mode_suppresses";

export interface Risk {
  risk_id: string;
  title: string;
  context: string;
  days_at_risk_p80: number;
  owner: string;
  status: RiskStatus | string; // lowercased; permissive to absorb workbook drift
  probability: number;
  impact_days_emv: number;
  criticality_conditioned: number | null;
  criticality_independent: number | null;
  // AM10 (WIND-01 A4): divergence_flag removed from the contract (Doc 3
  // v2.5) - structurally constant under the pure-MC AM basis. The
  // DivergenceFlag type alias is retained (dormant) for WIND-01b.
  ssi: number;
  cruciality_proxy_p80: number;
  mode: RiskMode | string; // permissive
  cg_code: string | null;
  tornado_sigma_days: number; // PERT proxy (fallback)
  // AM04 / Doc 3 v2.4: sample-based per-risk tornado sigma (working days)
  // via leave-one-out variance reduction. Preferred over the PERT proxy
  // when non-null; null for risks outside the evaluated set or with a
  // skipped re-run (the chart falls back to tornado_sigma_days).
  tornado_sample_sigma_days: number | null;
}

// ---------------------------------------------------------------------------
// `mitigations`
// ---------------------------------------------------------------------------

export type MitigationStatus =
  | "proposed"
  | "approved"
  | "in progress"
  | "completed"
  | "rejected";

export interface Mitigation {
  mitigation_id: string;
  risk_id: string | null;
  description: string | null;
  cost_aud: number | null;
  lead_time_weeks: number | null;
  owner: string | null;
  status: MitigationStatus | string;
  days_saved_p80: number;
  p80_finish_with_mitigation: string; // YYYY-MM-DD
}

// ---------------------------------------------------------------------------
// `activities`
// ---------------------------------------------------------------------------

export type PBandDerivationMethod = "A" | "B" | "C";

export interface ActivityItem {
  activity_id: string;
  name: string;
  p10_start_days: number;
  p50_start_days: number;
  p90_start_days: number;
  p10_finish_days: number;
  p50_finish_days: number;
  p90_finish_days: number;
  det_es_days: number | null;
  det_ef_days: number | null;
  criticality_index: number;
  // AM02.1 §4.B.1 / Doc 3 v2.3: per-activity `mode` removed
  // (category error). Per-risk Mode lives on Risk; activities
  // don't carry one.
}

export interface ModeSummary {
  series: number;
  hybrid: number;
  parallel: number;
  total: number;
}

export interface CpStats {
  activities_on_det_cp: number;
  activities_ci_gt_50: number;
  activities_ci_gt_80: number;
  stochastic_cp_additions: number;
  longest_path_p80_days: number;
  zero_float_activities: number;
  mean_activity_float_days: number;
  float_sigma_days: number;
}

export interface Activities {
  top_n_by_ci: number;
  ci_threshold: number;
  p_band_derivation_method: PBandDerivationMethod;
  items: ActivityItem[];
  mode_summary: ModeSummary;
  cp_stats: CpStats;
}

// ---------------------------------------------------------------------------
// `distribution`
// ---------------------------------------------------------------------------

export interface SCurvePoint {
  date: string; // YYYY-MM-DD
  cumulative_prob: number;
}

export interface HistogramBin {
  date_range_start: string;
  date_range_end: string;
  count: number;
}

export interface PercentileRow {
  percentile: number;
  days_from_start: number;
  date: string;
  delta_vs_det: number;
}

export interface Distribution {
  s_curve_points: SCurvePoint[];
  histogram_bins: HistogramBin[];
  percentile_table: PercentileRow[];
}

// ---------------------------------------------------------------------------
// `delta`
// ---------------------------------------------------------------------------

export interface DeltaEntry {
  risk_id: string;
  description: string;
  change_meta: string;
  delta_days: number;
}

/**
 * Period-0 shape vs subsequent-period shape are slightly different
 * (period 0 has `period_0: true` + `note`; subsequent periods have
 * P80 deltas + worse/better/new lists). Modeled as a discriminated
 * union via the optional `period_0` flag.
 */
export interface DeltaPeriod0 {
  period_0: true;
  note: string;
}

export interface DeltaSubsequent {
  period_0?: false;
  p80_delta_days: number;
  p80_previous: string;
  p80_current: string;
  worse: DeltaEntry[];
  better: DeltaEntry[];
  new: DeltaEntry[];
  net_movement_summary: string;
}

export type Delta = DeltaPeriod0 | DeltaSubsequent;

// ---------------------------------------------------------------------------
// `audit`
// ---------------------------------------------------------------------------

export interface AuditConfig {
  engine: string;
  iterations: number;
  sampling_method: string;
  seed: number;
  cp_rule: string;
  p_level_reporting: number;
  cl_mode: string;
}

export interface CalibrationGate {
  check: string;
  target: string;
  actual: string;
  status: string;
  note?: string;
}

export interface MethodologyNote {
  topic: string;
  method: string;
  text: string;
  queued_for_v1_1?: string;
}

export interface Audit {
  config: AuditConfig;
  calibration_gates: CalibrationGate[];
  methodology_notes: MethodologyNote[];
  stage_brief: string;
  reviewer: string | null;
  reviewer_approved_date: string | null;
  // Contract 1.4: why no `integrated` block, when there is none. Present only then.
  integrated_unavailable?: string;
}

// ---------------------------------------------------------------------------
// Top-level
// ---------------------------------------------------------------------------

/**
 * Contract 1.4 (stage 7 part B, SPEC §5.2 decision C2): the integrated
 * cost-plus-schedule result. A NEW top-level block, never folded into
 * `headline` - `headline` is dates and `trend` reads it back across periods,
 * so adding dollars there would make one block mean different things in
 * different periods.
 *
 * OPTIONAL, so a 1.3 artefact and a register that cannot dollarise days both
 * still validate. When the arm could not run, `audit.integrated_unavailable`
 * carries the reason - absence is explained rather than merely absent.
 */
export interface IntegratedPinning {
  risks_priced: number;
  risks_removed: number;
  // Closed is distinct from removed: the schedule arm zeroes a Closed risk rather than
  // dropping it, so the audit can still show it, and the cost arm matches.
  risks_closed: number;
  risks_reprobabilised: number;
  removed_risk_ids: string[];
  closed_risk_ids: string[];
  reprobabilised_risk_ids: string[];
}

export interface Integrated {
  basis: string;
  day_rate: number;
  deterministic_baseline_days: number;
  iterations: number;
  p50_dollars: number;
  mean_dollars: number;
  p80_dollars: number;
  p90_dollars: number;
  p95_dollars: number;
  cost_marginal: { mean_dollars: number; p80_dollars: number };
  schedule_marginal: { mean_delay_days: number; p80_delay_days: number };
  pinning: IntegratedPinning;
}

export interface PeriodData {
  schema_version: string;
  meta: Meta;
  headline: Headline;
  trend: Trend;
  risks: Risk[];
  mitigations: Mitigation[];
  activities: Activities;
  distribution: Distribution;
  delta: Delta;
  audit: Audit;
  integrated?: Integrated;
}

/**
 * The `index.json` manifest written by `scripts/copy-data.js` so the
 * loader can discover available periods without listing the directory
 * at runtime (static export can't list dir contents over HTTP).
 */
export interface PeriodIndex {
  periods: string[]; // filenames, sorted ascending (oldest first)
  generated_at: string; // ISO 8601 datetime
}
