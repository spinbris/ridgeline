/**
 * Period JSON loader with zod runtime validation.
 *
 * Server-side (static export build time) and client-side both call
 * this through `fetch` against `/data/period_*.json`. The data files
 * live in `dashboard/public/data/`, copied there by
 * `scripts/copy-data.js` at build time from `../data/period_*.json`.
 *
 * The zod schemas mirror the hand-written TypeScript interfaces in
 * `types/period.ts`. They run at load time; a malformed JSON surfaces
 * a clear, field-pointing error rather than a runtime crash deeper in
 * the React tree.
 *
 * Period discovery uses the `index.json` manifest the build script
 * emits. The static export cannot list directory contents over HTTP,
 * so the manifest is the only way the dashboard knows which periods
 * exist.
 *
 * Per AM03 v1.1.1 §5.A.6.
 */

import { z } from "zod";

import type {
  ActivityItem,
  Activities,
  Audit,
  AuditConfig,
  CalibrationGate,
  Contingency,
  CpStats,
  Delta,
  DeltaEntry,
  DeltaPeriod0,
  DeltaSubsequent,
  Distribution,
  Headline,
  HistogramBin,
  InputDigest,
  Integrated,
  Meta,
  MethodologyNote,
  Mitigation,
  ModeSummary,
  PBandDerivationMethod,
  PercentileRow,
  PeriodData,
  PeriodIndex,
  Risk,
  SCurvePoint,
  Trend,
  TrendPoint,
} from "@/types/period";

// ---------------------------------------------------------------------------
// zod schemas (mirror types/period.ts; update in lock-step)
// ---------------------------------------------------------------------------

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, {
  message: "Expected YYYY-MM-DD",
});

const isoDateTime = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$/, {
    message: "Expected ISO 8601 datetime",
  });

const inputDigestSchema: z.ZodType<InputDigest> = z.object({
  method: z.enum(["git_blob_oid", "sha256_bytes"]),
  value: z.string().min(1),
});

const metaSchema: z.ZodType<Meta> = z.object({
  period_end_date: isoDate,
  previous_period_end_date: isoDate.nullable(),
  engine_run_date: isoDateTime,
  engine_run_hash: z.string().min(1),
  register_version: z.string().min(1),
  workbook_filename: z.string().min(1),
  xer_filename: z.string().min(1),
  iterations: z.number().int().positive(),
  seed: z.number().int(),
  // showcase-P5 WS5-C: optional project display name (see types/period.ts).
  project_display_name: z.string().min(1).optional(),
  // Contract 1.4, stage 7 part C (B-2). OPTIONAL by ruling, which is why the PATH is
  // authoritative and this is corroborating - see `assertProjectKeyAgrees`.
  project_key: z.string().min(1).optional(),
  // AM09 (Doc 3 v2.6): engine-provenance stamp. Optional + nullable to match
  // the soft-fail contract (null when the run's git query could not resolve).
  // z.object() is non-strict, so a pre-AM09 artefact lacking these validates.
  // Stage 7 part A (C-2): `engine_sha_pinned` and `engine_sha_matches_pin` were REMOVED
  // here. RS-A2 P-3 dropped them from the contract (`src/am/_provenance.py:6`) and the
  // writer copies only three named provenance keys (`src/am/json_writer.py:181-188`), so
  // the engine cannot emit them. A validator that accepts fields no producer can send has
  // quietly stopped describing anything - it reads as a contract while gating nothing.
  engine_sha: z.string().nullable().optional(),
  engine_tree_dirty: z.boolean().nullable().optional(),
  // 1.6, stage 2b: true when the contingency held figures are illustrative.
  contingency_illustrative: z.boolean().optional(),
  // PROVCRLF01 (schema 1.3): {method, value} records, not bare strings. A 1.2
  // artefact no longer validates here, which is intended - the served set is
  // re-stamped in the same stage, and silently accepting both shapes would put
  // the reader back to inferring the method from the value's length.
  input_sha256: z
    .object({
      register: inputDigestSchema,
      xer: inputDigestSchema,
      workbook: inputDigestSchema,
    })
    .optional(),
});

const headlineSchema: z.ZodType<Headline> = z.object({
  p10_finish: isoDate,
  p50_finish: isoDate,
  mean_finish: isoDate,
  p80_finish: isoDate,
  p90_finish: isoDate,
  p95_finish: isoDate,
  deterministic_finish: isoDate,
  p80_days_behind_plan: z.number(),
  p50_days_behind_plan: z.number(),
  p90_days_behind_plan: z.number(),
  open_risks_count: z.number().int().nonnegative(),
  fired_this_period_count: z.number().int().nonnegative(),
  closed_this_period_count: z.number().int().nonnegative(),
  near_critical_milestones_30d: z.array(z.string()),
});

const trendPointSchema: z.ZodType<TrendPoint> = z.object({
  period_end: isoDate,
  p80_finish: isoDate,
  contingency_p80_dollars: z.number().nullable(),
});

const trendSchema: z.ZodType<Trend> = z.object({
  periods: z.array(trendPointSchema),
});

// AM10 (WIND-01 A4): DORMANT. The risks[].divergence_flag field was removed
// from the contract (Doc 3 v2.5) - it was structurally constant "consistent"
// under the pure-MC AM basis. Enum retained, unused, for the deferred
// WIND-01b Mode-sensitivity run (its revival surface). z.object() is
// non-strict, so a regenerated JSON without the field validates; an older
// JSON that still carries it has the extra key stripped.
const divergenceFlagSchema = z.enum([
  "consistent",
  "mode_amplifies",
  "mode_suppresses",
]);
void divergenceFlagSchema; // referenced to keep the dormant enum from tripping no-unused

const riskSchema: z.ZodType<Risk> = z.object({
  risk_id: z.string().min(1),
  title: z.string(),
  context: z.string(),
  days_at_risk_p80: z.number(),
  owner: z.string(),
  status: z.string(),
  probability: z.number().min(0).max(1),
  impact_days_emv: z.number(),
  criticality_conditioned: z.number().min(0).max(1).nullable(),
  criticality_independent: z.number().min(0).max(1).nullable(),
  // AM10: divergence_flag removed from the contract (Doc 3 v2.5).
  ssi: z.number(),
  cruciality_proxy_p80: z.number(),
  mode: z.string(),
  cg_code: z.string().nullable(),
  tornado_sigma_days: z.number().nonnegative(),
  // AM04 / Doc 3 v2.4: nullable, and NOT constrained non-negative - small
  // negatives are legitimate MC noise at the 10k-iter precision floor; the
  // chart clamps the bar length and the tooltip shows the raw figure.
  tornado_sample_sigma_days: z.number().nullable(),
  // 1.6: masked leave-one-out dollars; null with no integrated result.
  cost_p80_contribution_dollars: z.number().nullable(),
  cost_part_dollars: z.number().nullable(),
  delay_part_dollars: z.number().nullable(),
  delay_days_saved_p80: z.number().nullable(),
});

const mitigationSchema: z.ZodType<Mitigation> = z.object({
  mitigation_id: z.string().min(1),
  risk_id: z.string().nullable(),
  description: z.string().nullable(),
  cost_aud: z.number().nullable(),
  lead_time_weeks: z.number().nullable(),
  owner: z.string().nullable(),
  status: z.string(),
  days_saved_p80: z.number(),
  p80_finish_with_mitigation: isoDate,
  dollars_saved_p80: z.number().nullable(),
  within_noise: z
    .object({
      dollars: z.boolean(),
      days: z.boolean(),
      noise_dollars: z.number().nullable(),
      noise_days: z.number().nullable(),
    })
    .nullable(),
});

const pBandMethodSchema: z.ZodType<PBandDerivationMethod> = z.enum([
  "A",
  "B",
  "C",
]);

const activityItemSchema: z.ZodType<ActivityItem> = z
  .object({
    activity_id: z.string().min(1),
    name: z.string(),
    p10_start_days: z.number().nonnegative(),
    p50_start_days: z.number().nonnegative(),
    p90_start_days: z.number().nonnegative(),
    p10_finish_days: z.number().nonnegative(),
    p50_finish_days: z.number().nonnegative(),
    p90_finish_days: z.number().nonnegative(),
    det_es_days: z.number().nullable(),
    det_ef_days: z.number().nullable(),
    criticality_index: z.number().min(0).max(1),
  })
  .refine(
    (it) =>
      it.p10_start_days <= it.p50_start_days &&
      it.p50_start_days <= it.p90_start_days,
    {
      message: "Per the period data contract: start P-band must be monotonic",
      path: ["p10_start_days"],
    },
  )
  .refine(
    (it) =>
      it.p10_finish_days <= it.p50_finish_days &&
      it.p50_finish_days <= it.p90_finish_days,
    {
      message: "Per the period data contract: finish P-band must be monotonic",
      path: ["p10_finish_days"],
    },
  );

const modeSummarySchema: z.ZodType<ModeSummary> = z.object({
  series: z.number().int().nonnegative(),
  hybrid: z.number().int().nonnegative(),
  parallel: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
});

const cpStatsSchema: z.ZodType<CpStats> = z.object({
  activities_on_det_cp: z.number().int().nonnegative(),
  activities_ci_gt_50: z.number().int().nonnegative(),
  activities_ci_gt_80: z.number().int().nonnegative(),
  stochastic_cp_additions: z.number().int().nonnegative(),
  longest_path_p80_days: z.number().nonnegative(),
  zero_float_activities: z.number().int().nonnegative(),
  mean_activity_float_days: z.number(),
  float_sigma_days: z.number().nonnegative(),
});

const activitiesSchema: z.ZodType<Activities> = z.object({
  top_n_by_ci: z.number().int().positive(),
  ci_threshold: z.number().min(0).max(1),
  p_band_derivation_method: pBandMethodSchema,
  items: z.array(activityItemSchema),
  mode_summary: modeSummarySchema,
  cp_stats: cpStatsSchema,
});

const sCurvePointSchema: z.ZodType<SCurvePoint> = z.object({
  date: isoDate,
  cumulative_prob: z.number().min(0).max(1),
});

const histogramBinSchema: z.ZodType<HistogramBin> = z.object({
  date_range_start: isoDate,
  date_range_end: isoDate,
  count: z.number().int().nonnegative(),
});

const percentileRowSchema: z.ZodType<PercentileRow> = z.object({
  percentile: z.number(),
  days_from_start: z.number(),
  date: isoDate,
  delta_vs_det: z.number(),
});

const distributionSchema: z.ZodType<Distribution> = z.object({
  s_curve_points: z.array(sCurvePointSchema),
  histogram_bins: z.array(histogramBinSchema),
  percentile_table: z.array(percentileRowSchema),
});

const deltaEntrySchema: z.ZodType<DeltaEntry> = z.object({
  risk_id: z.string().min(1),
  description: z.string(),
  change_meta: z.string(),
  delta_days: z.number(),
  delta_dollars: z.number().nullable(),
});

const deltaPeriod0Schema: z.ZodType<DeltaPeriod0> = z.object({
  period_0: z.literal(true),
  note: z.string(),
  p80_delta_dollars: z.null(),
});

const deltaSubsequentSchema: z.ZodType<DeltaSubsequent> = z.object({
  period_0: z.literal(false).optional(),
  p80_delta_days: z.number(),
  p80_delta_dollars: z.number().nullable(),
  p80_previous: isoDate,
  p80_current: isoDate,
  worse: z.array(deltaEntrySchema),
  better: z.array(deltaEntrySchema),
  new: z.array(deltaEntrySchema),
  net_movement_summary: z.string(),
});

const deltaSchema: z.ZodType<Delta> = z.union([
  deltaPeriod0Schema,
  deltaSubsequentSchema,
]);

const auditConfigSchema: z.ZodType<AuditConfig> = z.object({
  engine: z.string(),
  iterations: z.number().int().positive(),
  sampling_method: z.string(),
  seed: z.number().int(),
  cp_rule: z.string(),
  p_level_reporting: z.number(),
  cl_mode: z.string(),
});

const calibrationGateSchema: z.ZodType<CalibrationGate> = z.object({
  check: z.string(),
  target: z.string(),
  actual: z.string(),
  status: z.string(),
  note: z.string().optional(),
});

const methodologyNoteSchema: z.ZodType<MethodologyNote> = z.object({
  topic: z.string(),
  method: z.string(),
  text: z.string(),
  queued_for_v1_1: z.string().optional(),
});

const auditSchema: z.ZodType<Audit> = z.object({
  config: auditConfigSchema,
  calibration_gates: z.array(calibrationGateSchema),
  methodology_notes: z.array(methodologyNoteSchema),
  stage_brief: z.string(),
  reviewer: z.string().nullable(),
  reviewer_approved_date: z.string().nullable(),
  // Contract 1.4: why there is no `integrated` block, when there is none.
  integrated_unavailable: z.string().optional(),
});

/**
 * Contract 1.4, decision C2. Optional: a 1.3 artefact validates without it, and so does a
 * register that cannot dollarise schedule days.
 */
const integratedSchema: z.ZodType<Integrated> = z.object({
  basis: z.string(),
  day_rate: z.number(),
  deterministic_baseline_days: z.number(),
  iterations: z.number(),
  p50_dollars: z.number(),
  mean_dollars: z.number(),
  p80_dollars: z.number(),
  p90_dollars: z.number(),
  p95_dollars: z.number(),
  cost_marginal: z.object({ mean_dollars: z.number(), p80_dollars: z.number() }),
  schedule_marginal: z.object({
    mean_delay_days: z.number(),
    p80_delay_days: z.number(),
  }),
  pinning: z.object({
    risks_priced: z.number(),
    risks_removed: z.number(),
    risks_closed: z.number(),
    risks_reprobabilised: z.number(),
    removed_risk_ids: z.array(z.string()),
    closed_risk_ids: z.array(z.string()),
    reprobabilised_risk_ids: z.array(z.string()),
    priced_probabilities: z.record(z.string(), z.number()).nullable().optional(),
  }),
  // Contract 1.5, INTSCURVE-01 Part C: the integrated S-curve and the JCL.
  curve_points: z.array(z.object({ dollars: z.number(), cumulative_prob: z.number() })),
  jcl: z.object({
    basis: z.string(),
    jcl: z.number(),
    cost_target_dollars: z.number(),
    // 1.6: the report's basis (INTVIEW-01 stage 2).
    declared_base_dollars: z.number(),
    base_drawn: z.boolean(),
    cost_confidence: z.number(),
    finish_target_date: z.string(),
    finish_confidence: z.number(),
    p_level: z.number(),
    frontier_level: z.number(),
  }),
  // Contract 1.6, INTVIEW-01 stage 2: every dollar the pages show, from the engine.
  build_up: z.array(
    z.object({
      p_level: z.number(),
      event_cost_dollars: z.number(),
      delay_days: z.number(),
      delay_cost_dollars: z.number(),
      standalone_sum_dollars: z.number(),
      joint_contingency_dollars: z.number(),
      diversification_dollars: z.number(),
    }),
  ),
  what_counts_where: z.string(),
  day_rate_derivation: z.object({
    day_rate_used: z.number(),
    day_rate_stated: z.number(),
    avg_prelims_weekly: z.number().nullable(),
    schedule_duration_weeks: z.number().nullable(),
    programme_working_days: z.number(),
    day_rate_derived: z.number().nullable(),
    gap_dollars: z.number().nullable(),
    gap_flagged: z.boolean(),
    note: z.string(),
  }),
  total_cost: z
    .object({
      label: z.string(),
      declared_base_dollars: z.number(),
      mean_dollars: z.number(),
      rows: z.array(
        z.object({
          p_level: z.number(),
          total_dollars: z.number(),
          contingency_dollars: z.number(),
        }),
      ),
      excluded_base_factors: z.array(z.string()),
    })
    .nullable(),
  leave_one_out: z
    .object({
      p_level: z.number(),
      iterations: z.number(),
      replays: z.number(),
      method: z.string(),
    })
    .nullable(),
  // Contract 1.7, RISKDRV-01 stage 3: null (or absent) unless the register declares drivers.
  owner_view: z
    .object({
      label: z.string(),
      driver_ids: z.array(z.string()),
      p50_finish: isoDate,
      p80_finish: isoDate,
      p90_finish: isoDate,
      p80_days_behind_plan: z.number(),
      s_curve_points: z.array(sCurvePointSchema),
      percentile_table: z.array(percentileRowSchema),
      driver_method: z.string(),
    })
    .nullable()
    .optional(),
  shared_drivers: z
    .array(
      z.object({
        driver_id: z.string().min(1),
        name: z.string(),
        kind: z.enum(["P", "Q"]),
        wbs_codes: z.array(z.string()),
        range: z.string(),
        acts_on: z.string(),
        basis: z.string(),
        mean_duration_change: z.number(),
        p80_duration_change: z.number(),
        p_level: z.number().nullable(),
        adds_to_total_dollars: z.number().nullable(),
        adds_to_finish_days: z.number().nullable(),
      }),
    )
    .nullable()
    .optional(),
});

const bridgeStepSchema = z.object({
  key: z.enum(["closed", "new", "reassessed", "mitigations", "other"]),
  label: z.string(),
  dollars: z.number(),
  risk_ids: z.array(z.string()),
});

const bridgeSchema = z.union([
  z.object({
    available: z.literal(true),
    prior_period_end_date: isoDate.nullable(),
    prior_p80_dollars: z.number(),
    current_p80_dollars: z.number(),
    order: z.array(z.string()),
    steps: z.array(bridgeStepSchema),
    method: z.string(),
  }),
  z.object({
    available: z.literal(false),
    reason: z.string(),
    prior_period_end_date: isoDate.nullable(),
  }),
]);

/** Contract 1.6: "recommended" before commitment; "held" from it (stage 2b). */
const contingencySchema: z.ZodType<Contingency> = z.object({
  phase: z.enum(["recommended", "held"]),
  label: z.string(),
  required_p80_dollars: z.number(),
  held_dollars: z.number().nullable(),
  commitment_date: isoDate.nullable(),
  opening_held_dollars: z.number().nullable(),
  approved_draws_dollars: z.number().nullable(),
  pending_draws_dollars: z.number().nullable(),
  releases_dollars: z.number().nullable(),
  shortfall_dollars: z.number().nullable(),
  jcl_against_held: z.number().nullable(),
  cost_confidence_against_held: z.number().nullable(),
  movements: z.array(
    z.object({
      date: isoDate,
      type: z.enum(["Draw", "Release"]),
      amount_dollars: z.number(),
      status: z.enum(["Approved", "Pending"]),
      risk_id: z.string().nullable(),
      note: z.string().nullable(),
    }),
  ),
  illustrative: z.boolean(),
  bridge: bridgeSchema.nullable(),
});

/**
 * The period-JSON contract version this build of the app was written against.
 *
 * Stage 7 part B, SPEC §5.2 decision A1 (ruled 05/09/2026): the app CHECKS it. Until now
 * `schema_version` was validated as `z.string()` - any string passed - so the version was
 * load-bearing to the engine and free text to its only consumer. The 1.0 -> 1.1 bump was made
 * specifically so a consumer could detect a field removal, and no consumer could detect
 * anything. This also brings the period contract in line with the register contract, which has
 * always hard-failed on inequality (`src/register_contract.py:90-92`); one product should not
 * carry two opposite answers to the same question.
 *
 * Equality, not a floor: shape-validation does not substitute, because a widened enum or a
 * semantically changed field passes zod silently. A version-locked app must be redeployed in
 * step with the engine, which under §5.1's static export is already true.
 */
export const SUPPORTED_SCHEMA_VERSION = "1.7";

export const periodDataSchema: z.ZodType<PeriodData> = z.object({
  schema_version: z.string(),
  meta: metaSchema,
  headline: headlineSchema,
  trend: trendSchema,
  risks: z.array(riskSchema),
  mitigations: z.array(mitigationSchema),
  activities: activitiesSchema,
  distribution: distributionSchema,
  delta: deltaSchema,
  audit: auditSchema,
  integrated: integratedSchema.optional(),
  // 1.6: present whenever `integrated` is.
  contingency: contingencySchema.optional(),
});

export const projectIndexSchema = z.object({
  projects: z.array(z.string().min(1)),
  generated_at: isoDateTime,
});

/**
 * Compare the document's own key against the directory it was served from.
 *
 * §5.2 ruled `meta.project_key` OPTIONAL so that no existing period JSON was invalidated by
 * contract 1.4. That decides the relationship rather than leaving it open: the **path is
 * authoritative**, this field is **corroborating**, and the check therefore fires ONLY when the
 * field is present. An unkeyed period in a project directory is valid and belongs to that
 * directory.
 *
 * Written this way from the outset deliberately. A loader built to trust the field and tightened
 * later is the drift the options note was written to avoid - and by the time a mismatch mattered,
 * some period would already have been read as the wrong project's.
 */
export function assertProjectKeyAgrees(
  data: PeriodData,
  servedFrom: string,
  url: string,
): void {
  const declared = data.meta.project_key;
  if (declared === undefined) return;
  if (declared !== servedFrom) {
    throw new Error(
      `loadPeriod: ${url} was served from project "${servedFrom}" but declares ` +
        `meta.project_key "${declared}". The file is in the wrong project's directory, or the ` +
        `key is wrong. Refusing rather than guessing: showing one project's numbers under ` +
        `another project's name is the failure this check exists to prevent.`,
    );
  }
}

export const periodIndexSchema: z.ZodType<PeriodIndex> = z.object({
  periods: z.array(z.string().regex(/^period_\d{8}\.json$/)),
  generated_at: isoDateTime,
  showcase: z.boolean().optional(),
});

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------

/**
 * Public path prefix the static export serves from. Relative so it
 * works under any deployment base path (Vercel default subdomain or
 * future custom domain).
 */
const DATA_PATH_PREFIX = "/data";

/** Where a project's periods live. Part C (B-2): one directory per project. */
export function projectDataPath(project: string): string {
  return `${DATA_PATH_PREFIX}/${encodeURIComponent(project)}`;
}

/**
 * Which projects this build carries, from the root manifest `copy-data.js` emits.
 *
 * A static export cannot list a directory over HTTP, so without a manifest the app has
 * nothing to enumerate - the same reason the per-period `index.json` exists.
 */
export async function loadProjectIndex(): Promise<string[]> {
  const url = `${DATA_PATH_PREFIX}/projects.json`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(
      `loadProjectIndex: failed to fetch ${url} (HTTP ${res.status}). Run the dashboard ` +
        `build so scripts/copy-data.js can emit it.`,
    );
  }
  const parsed = projectIndexSchema.safeParse(await res.json());
  if (!parsed.success) {
    throw new Error(`loadProjectIndex: ${url} failed validation:
${formatZodError(parsed.error)}`);
  }
  return parsed.data.projects;
}

/**
 * Fetch the period-index manifest emitted by `scripts/copy-data.js`.
 * Throws a typed error on missing file or malformed shape.
 */
export async function loadPeriodIndex(project: string): Promise<PeriodIndex> {
  const url = `${projectDataPath(project)}/index.json`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(
      `loadPeriodIndex: failed to fetch ${url} (HTTP ${res.status}). ` +
        `The build script may not have run; ensure 'npm run prebuild' ` +
        `executed before serving.`,
    );
  }
  const raw = (await res.json()) as unknown;
  const parsed = periodIndexSchema.safeParse(raw);
  if (!parsed.success) {
    throw new Error(
      `loadPeriodIndex: ${url} failed validation:\n${formatZodError(
        parsed.error,
      )}`,
    );
  }
  return parsed.data;
}

function versionMismatchMessage(url: string, declared: string): string {
  return (
    `loadPeriod: ${url} declares period-JSON contract ${declared}, but ` +
    `this build of the dashboard was written against ${SUPPORTED_SCHEMA_VERSION}. The ` +
    `engine and the app must be deployed in step - rebuild and redeploy the dashboard ` +
    `from the same commit as the engine that produced this period.`
  );
}

/**
 * Fetch a single period JSON by filename (e.g. "period_20260528.json").
 * Returns the validated `PeriodData` shape.
 */
export async function loadPeriod(project: string, filename: string): Promise<PeriodData> {
  if (!/^period_\d{8}\.json$/.test(filename)) {
    throw new Error(
      `loadPeriod: invalid filename "${filename}"; ` +
        `must match period_YYYYMMDD.json`,
    );
  }
  const url = `${projectDataPath(project)}/${filename}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(
      `loadPeriod: failed to fetch ${url} (HTTP ${res.status})`,
    );
  }
  const raw = (await res.json()) as unknown;
  // §5.2 decision A1: refuse a period this build was not written against, rather than
  // render it and hope. A document that DECLARES another version is refused on that before
  // its shape is checked (INTVIEW-01 stage 2): a 1.5 period read by the 1.6 app lacks every
  // 1.6 field, and listing those as validation failures would report the symptom of the
  // version rather than the version. A document whose declared version matches is still
  // shape-checked first, so a malformed one reports its actual defect.
  const declared =
    raw !== null && typeof raw === "object"
      ? (raw as { schema_version?: unknown }).schema_version
      : undefined;
  if (typeof declared === "string" && declared !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error(versionMismatchMessage(url, declared));
  }
  const parsed = periodDataSchema.safeParse(raw);
  if (!parsed.success) {
    throw new Error(
      `loadPeriod: ${url} failed period data validation:\n${formatZodError(
        parsed.error,
      )}`,
    );
  }
  if (parsed.data.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error(versionMismatchMessage(url, parsed.data.schema_version));
  }
  // Part C (B-2): the document's own key must agree with the directory it came from.
  assertProjectKeyAgrees(parsed.data, project, url);
  return parsed.data;
}

/**
 * Convenience: fetch the index, identify the most recent period by
 * filename (lexicographic sort works because filenames are
 * YYYYMMDD-sortable), and return both the manifest + the latest
 * period's data.
 */
export async function loadLatestPeriod(project: string): Promise<{
  index: PeriodIndex;
  latest: PeriodData;
  latestFilename: string;
}> {
  const index = await loadPeriodIndex(project);
  if (index.periods.length === 0) {
    throw new Error(
      `loadLatestPeriod: no period files in project "${project}". ` +
        `Ensure data/${project}/period_YYYYMMDD.json exists at the repo root.`,
    );
  }
  const sorted = [...index.periods].sort();
  const latestFilename = sorted[sorted.length - 1];
  const latest = await loadPeriod(project, latestFilename);
  return { index, latest, latestFilename };
}

// ---------------------------------------------------------------------------
// Error formatting
// ---------------------------------------------------------------------------

function formatZodError(err: z.ZodError): string {
  return err.issues
    .map((issue) => {
      const path = issue.path.length > 0 ? issue.path.join(".") : "(root)";
      return `  - ${path}: ${issue.message}`;
    })
    .join("\n");
}
