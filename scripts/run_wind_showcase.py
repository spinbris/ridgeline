"""Showcase-P3 WS3-D - run the engine end-to-end on the full wind dataset
and emit the clean upfront QRA + SRA + Stage 3 deliverable substrate.

Runs all three engine layers against the committed synthetic-wind fixtures
under the active ``synthetic_wind`` binding and writes readable, fully
RefProject-free summaries to ``outputs/wind_showcase/``:

- ``wind_cost_qra.md``      - Monte-Carlo cost QRA: P-bands, contingency as a
  % of the $50M Wind Farm Beta capex, per-cost-group breakdown, top-risk
  tornado (mean EMV).
- ``wind_sra_schedule.md``  - Stage 2.5 schedule MC: finish-delay P-bands,
  dollarised at the wind day rate, per-risk contribution.
- ``wind_stage3_cpm.md``    - Stage 3 CPM-replay: project-finish P-bands,
  deterministic critical path, activity criticality index.
- ``wind_integrated_headline.md`` - combined cost + schedule headline.
- ``*.csv`` companions for the tabular pieces.

These are the substrate the P5 marketing derivatives draw from - not yet the
polished marketing artefacts. Run after regenerating the fixtures:

    python scripts/build_synthetic_wind_fixture.py
    python scripts/run_wind_showcase.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from src.git_identity import git_env  # noqa: E402
from src.sra.methodology_defaults_reader import read_mode_multipliers  # noqa: E402
from src.sra.methodology_defaults_reader import read_calibration_tolerances  # noqa: E402

import numpy as np  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_wind"
WIND_REGISTER = FIXTURE_DIR / "wind_register.xlsx"
# REG-01: the strawman is dissolved into the consolidated register. The
# schedule scope + Mode read from the "Risk Register" sheet, the CPM binding
# from "Mapping", and run config from "MC_Params" - all in WIND_REGISTER.
WIND_XER = FIXTURE_DIR / "wind_schedule.xer"
OUT_DIR = REPO_ROOT / "outputs" / "wind_showcase"
#: The committed showcase's own record. A re-cut reruns at the seed it records, so the summaries it
#: is compared against came from the same draw (SEEDZERO-01 P4). ``--baseline-meta`` names another.
BASELINE_META = REPO_ROOT / "docs" / "showcase" / "run" / "wind_run_meta.json"


def baseline_seed(meta_path: Path) -> int:
    """The seed a baseline records, or a refusal: a baseline without one cannot be reproduced."""
    import json

    from src.rng_streams import parse_seed

    record = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    if "seed" not in record:
        raise SystemExit(f"{meta_path} records no seed, so no re-cut can reproduce it. "
                         f"Name a baseline that records one (--baseline-meta).")
    return parse_seed(record["seed"], where=str(meta_path))


N_ITER = int(os.environ.get("WIND_ITERATIONS", "50000"))
# WIND-02 §4: ONE showcase-wide iteration parameter feeds BOTH arms. The
# integrated engine (integrated_simulation_stage3) refuses to run if the
# cost and schedule arms' iteration counts differ, so WIND-01's separate
# STAGE3_ITERATIONS override is retired here - the schedule arm now tracks
# N_ITER exactly. Draft cheaply by setting WIND_ITERATIONS low (both arms
# drop together); a 2k run is for layout/sanity only and is NOT a subset of
# a production run. The count is stamped into every report footer + the
# run-meta JSON so no draft figure can be quoted as final.
STAGE3_ITERATIONS = N_ITER
#: Read from the baseline, never typed here. main() rereads it from --baseline-meta; the golden
#: adapter sets it from the golden registry row.
SEED = baseline_seed(BASELINE_META)
CAPEX_TOTAL = 50_000_000.0
#: The capex split the showcase text states; held to CAPEX_TOTAL in _quoted_values.
CAPEX_EPC = 45_000_000.0
CAPEX_GRID = 5_000_000.0
DAY_RATE = 35_000.0

# SHOWCASESYNC-01: --publish writes the whole set where it ships, in one run, so no hand copy can
# leave a figure behind. Anything below the production-scale floor, or over a dirty tree, refuses.
PRODUCTION_SCALE_FLOOR = 100_000
SHOWCASE_DIR = REPO_ROOT / "docs" / "showcase"
PUBLISH_RUN_DIR = SHOWCASE_DIR / "run"
PUBLISH_FIG_DIR = SHOWCASE_DIR / "figs"
SUMMARY_QMD = SHOWCASE_DIR / "tropic_ridge_wind_summary.qmd"
#: The PNG text key every chart carries, naming the run that drew it.
RUN_ID_KEY = "outturn_run_id"


# ---------------------------------------------------------------------------
# WIND-04: engine-provenance stamp (mirrors AM09's contract from home; this
# showcase's wind_run_meta.json carries the quotable $6.84M headline and must
# self-attest to the engine SHA + input identity that produced it).
# ---------------------------------------------------------------------------

def _resolve_engine_sha() -> str | None:
    """outturn HEAD SHA at run time, or None on git soft-fail."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5, env=git_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _resolve_tree_dirty() -> bool | None:
    """True if the outturn tree has uncommitted changes; None on git
    soft-fail. NB outputs/ is gitignored, so a normal showcase run does not
    dirty the tree - a True here means real source/input edits are uncommitted.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=5, env=git_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return bool(r.stdout.strip())


def _sha256_file(path: Path) -> str:
    """Streamed hex SHA-256 of a file (fixtures are small, but stream anyway)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_provenance(engine_sha: str | None, engine_tree_dirty: bool | None) -> dict:
    """WIND-04 stamp: engine SHA + dirty flag + per-file digests of the three
    wind inputs (register, xer, strawman). Per-file, not concatenated, so a
    same-filename re-issue of any single input is diagnosable."""
    return {
        "engine_sha": engine_sha,
        "engine_tree_dirty": engine_tree_dirty,
        # REG-01: the strawman is dissolved into the register, so the
        # per-input digest set drops the "strawman" key. §8: only
        # input_sha256.register moves; the engine numbers are bit-identical.
        "input_sha256": {
            "register": _sha256_file(WIND_REGISTER),
            "xer": _sha256_file(WIND_XER),
        },
    }


def _check_dirty_guard(engine_tree_dirty: bool | None, allow_dirty: bool) -> None:
    """WIND-04 §2.2, same contract as AM09: REFUSE a dirty-tree run unless
    --allow-dirty. A SHA stamped over a dirty tree is a false attestation."""
    if engine_tree_dirty and not allow_dirty:
        raise RuntimeError(
            "WIND-04 dirty-tree guard: the outturn working tree has "
            "uncommitted changes. A SHA stamped over a dirty tree is a false "
            "attestation. Commit or stash, or pass --allow-dirty to proceed "
            "(which stamps engine_tree_dirty: true - a NON-clean attestation)."
        )


#: The project this script runs. Named once, so the binding it activates and the binding its
#: Stage 3 config reads its float threshold from cannot drift apart.
PROJECT = "synthetic_wind"


def _activate_wind_binding() -> None:
    spec = importlib.util.spec_from_file_location(
        "wind_binding_showcase", FIXTURE_DIR / "wind_binding.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # self-registers 'synthetic_wind'
    os.environ["QRA_PROJECT"] = PROJECT


def _pbands(arr: np.ndarray) -> dict[str, float]:
    p50, p80, p90, p95 = np.percentile(arr, [50, 80, 90, 95])
    return {"mean": float(arr.mean()), "p50": float(p50), "p80": float(p80),
            "p90": float(p90), "p95": float(p95)}


def _m(x: float) -> str:
    return f"${x / 1e6:.2f}M"


# ---------------------------------------------------------------------------
# Layer 1 - cost QRA
# ---------------------------------------------------------------------------

def run_cost_qra(integ: dict) -> dict:
    """Cost QRA bands + tornado + CG rollup, sourced from the INTEGRATED
    engine's cost arm (WIND-02 A-with-disclosure).

    Previously this ran a separate MonteCarloEngine cost MC, which quoted a
    cost P80 that disagreed with the integrated headline by ~$0.25M. The
    decomposition traced the whole gap to ONE risk, WT-002, coded
    ``Recurrence Type = BINOMIAL``. CORRECTION (WIND-06 / COST-01, verified by
    live 100k runs): the earlier note here was INVERTED. MonteCarloEngine did
    NOT mis-dispatch - it HONOURS recurrence (n = programme_seasons occurrences
    at p=0.5), so WT-002's E[total] $370k is a legitimate SUM of up to three
    <=$500k occurrences, not an out-of-bounds single draw. The Triangular
    sampler is strictly bounded (max $500k); the "$735k conditional mean
    exceeds the $500k max, therefore impossible" argument was wrong - the
    correct E[total|fired] is $423k, and a sum of occurrences legitimately
    exceeds a single occurrence's ceiling. The real defect is the reverse:
    the INTEGRATED engine has no recurrence handling and silently collapses
    WT-002 to a single Bernoulli ($123k). WIND-06 sets WT-002 to ``Single`` so
    this showcase is internally coherent with the integrated engine that
    produces its headline; the standalone engine remains the recurrence
    reference implementation. The engine capability gap is COST-01 (open),
    NOT closed here. RefProject production is unaffected (its register carries
    zero recurring rows, so both engines agree).
    """
    risks = integ["risks"]
    total = np.asarray(integ["cost"], dtype=float)      # cost_dollars_array
    bands = _pbands(total)

    per_risk = np.asarray(integ["per_risk_cost"], dtype=float)  # (n_iter, n_risks)
    per_risk_mean = per_risk.mean(axis=0)               # mean EMV per risk
    cg_totals: dict[str, float] = {}
    for r, emv in zip(risks, per_risk_mean):
        cg_totals[r.correlation_group] = cg_totals.get(
            r.correlation_group, 0.0) + float(emv)
    ranked = sorted(
        ((r.risk_id, r.description, r.correlation_group, float(emv))
         for r, emv in zip(risks, per_risk_mean)),
        key=lambda t: t[3], reverse=True)

    return {"n_risks": len(risks), "bands": bands, "cg_totals": cg_totals,
            "ranked": ranked, "total": total}


# ---------------------------------------------------------------------------
# Layer 2 - Stage 2.5 schedule MC
# ---------------------------------------------------------------------------

def run_sra_schedule() -> dict:
    from src.sra.sra_config import SRAConfig
    from src.sra.sra_simulation import run_schedule_simulation
    from src.sra.strawman_reader import read_risk_scope

    risk_scope = read_risk_scope(str(WIND_REGISTER))
    cfg = SRAConfig(register_path=WIND_REGISTER, p6_path=WIND_XER,
                    strawman_path=WIND_REGISTER, iterations=N_ITER,
                    random_seed=SEED, day_rate=DAY_RATE, mode_multipliers=read_mode_multipliers(WIND_REGISTER))
    result = run_schedule_simulation(cfg, risk_scope)
    finish = np.asarray(result["finish_delay_days_array"])
    bands = _pbands(finish)
    contrib = np.asarray(result["contribution_array"])          # (n_iter, n_risks)
    risk_ids = result["risk_ids"]
    per_risk_days = contrib.mean(axis=0)
    ranked = sorted(zip(risk_ids, (float(d) for d in per_risk_days)),
                    key=lambda t: t[1], reverse=True)
    return {"bands": bands, "ranked": ranked, "mode_used": result["mode_used"],
            "n_sim": int((risk_scope["time_impact"] == "Yes").sum())}


# ---------------------------------------------------------------------------
# Layer 3 - Stage 3 CPM-replay
# ---------------------------------------------------------------------------

def _strawman_stage3_rules(graph) -> dict:
    """Wind's Stage 3 auto-mapper rules, from the shared builder.

    3c Part A (Director, option A): the rule construction moved to
    ``src.integrated.stage3_config.build_stage3_rules_from_scope`` so the showcase and the
    deliverable build wind's drivers with one function rather than two. WINDINJ-01 removed the
    pinned injection method that used to travel with it: the method is now the row's own, or the
    register's ``Default_Injection_Method`` where the row declares none, resolved in that same
    function and documented there.
    """
    from src.integrated.stage3_config import build_stage3_rules_from_scope
    from src.integrated.stage3_inputs import (
        Stage3BindingConfig,
        resolve_float_threshold_hours,
    )
    from src.sra.strawman_reader import read_risk_scope

    return build_stage3_rules_from_scope(
        read_risk_scope(str(WIND_REGISTER)), graph,
        Stage3BindingConfig(register_path=WIND_REGISTER, xer_path=WIND_XER,
                            strawman_path=WIND_REGISTER,
                            float_threshold_hours=resolve_float_threshold_hours()),
    )


def run_stage3_cpm() -> dict:
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.cpm_simulation import ScheduleMCConfig, run_schedule_mc
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer

    graph = build_schedule_graph(parse_xer(str(WIND_XER)))
    rules = _strawman_stage3_rules(graph)
    drivers = expand_auto_rules(rules, graph)
    bound = {rid: len(d.affected_activity_ids) for rid, d in drivers.items()}
    # WIND-01: pure-MC (Mode-independent) headline. apply_mode_multipliers
    # is set EXPLICITLY False - never relying on the ScheduleMCConfig
    # default in either direction (the default is True; relying on it was
    # the pre-WIND-01 defect). This matches the RefProject production basis:
    # SR15 retired the Mode multiplier on the full-CPM path (the CPM kernel
    # models schedule propagation directly, so a multiplier on top would
    # double-count), SR17 made Stage 3 the production headline, and
    # integrated_simulation_stage3.py hard-forces the same False. Every
    # Time-Impact risk now injects its full sampled PERT delay; the CPM
    # decides what reaches the finish date.
    #
    # criticality_measurement_mode is "mode_independent" (a SINGLE pass):
    # under apply=False the Mode-conditioned and Mode-independent indices
    # coincide, so the old "both" second pass produced an identical array
    # at ~2x cost and the dual panel it fed had nothing to show. The single
    # AACE 65R-11 index is the primary criticality_index below.
    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers,
        config=ScheduleMCConfig(
            n_iter=STAGE3_ITERATIONS, batch_size=2000, seed=SEED,
            apply_mode_multipliers=False,
            mode_multipliers=read_mode_multipliers(WIND_REGISTER),  # RS-D-3b
        ),
        criticality_measurement_mode="mode_independent")
    finish_h = np.asarray(result.project_finish_hours)
    finish_days = finish_h / 8.0
    bands = _pbands(finish_days)
    crit = sorted(result.criticality_index.items(), key=lambda t: t[1], reverse=True)
    # activity_id -> human name, for chart labels (call-only bridge to
    # compute_extended_ci_table / make_sorted_criticality_bar_chart).
    activity_titles = {aid: act.name for aid, act in graph.activities.items()}
    return {"bands": bands, "bound": bound,
            "critical_path": list(result.deterministic_critical_path),
            "criticality_top": crit[:15], "n_activities": len(result.criticality_index),
            "finish_days": finish_days, "result": result,
            "activity_titles": activity_titles, "n_iter": STAGE3_ITERATIONS}


# ---------------------------------------------------------------------------
# Integrated headline - joint cost + Stage 3 schedule (WIND-02)
# ---------------------------------------------------------------------------

def run_integrated() -> dict:
    """Route the wind headline through the RefProject Stage 3 integrated engine.

    WIND-02: replaces the naive ``cost_p80 + sched_p80`` stitch with the
    joint per-iteration sample the engine already runs for RefProject
    production. The integrated engine draws ONE severity uniform per
    dual-coded risk shared across the cost arm and the Stage 3 CPM schedule
    arm, so the integrated total's P80 reflects the true joint distribution
    rather than the sum of two marginals. No wind binding class is needed -
    every wind input is pre-loaded and the cost-side ``IntegratedConfig``
    is built by ``src.integrated.stage3_config.build_stage3_config``, which reads
    every methodology value - Mode multipliers, CG coefficients, tolerances,
    day rate - from the wind register itself (3c Part A, Director option A;
    the same construction the deliverable uses). ``apply_mode_multipliers=False``
    throughout (WIND-01 pure-MC basis); the schedule arm's delay-derivation and dollarisation
    are done INSIDE the engine (schedule_days = finish - deterministic
    baseline), which the showcase inherits rather than re-deriving.
    """
    from src.integrated.integrated_simulation_stage3 import (
        run_integrated_simulation_stage3,
    )
    from src.integrated.stage3_config import build_stage3_config
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.schedule_cross_check import (
        compute_schedule_comparators,
        evaluate_schedule_calibration,
        read_register_day_rate,
        read_register_mode_multipliers,
    )
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    # Pre-load every wind input so the RefProject-named file loaders are
    # bypassed (the binding is used only for config_summary / variant label).
    xer_tables = parse_xer(str(WIND_XER))
    graph = build_schedule_graph(xer_tables)
    risk_scope = read_risk_scope(str(WIND_REGISTER))
    drivers = _strawman_stage3_rules(graph)  # AutoMapperRule dict, wind Prefix_List
    drivers = expand_auto_rules(drivers, graph)
    risks = read_risks_v5(str(WIND_REGISTER))

    # 3c Part A (Director, option A): ONE Stage 3 config construction, shared with the
    # deliverable's Stage 3 arm, so A-5's exact reproduction holds because it is the same
    # code rather than because two hand-built configs coincide. Every methodology value
    # now comes from the wind register itself - the flat 0.5 CG map and the reference
    # project's methodology-defaults factory that stood here were both measured inert on
    # this array before they were removed (record §3.1, and the bit-identity gate in
    # tests/test_3c_a_shared_stage3_config.py).
    s3_cfg = build_stage3_config(
        register_path=WIND_REGISTER,
        xer_path=WIND_XER,
        strawman_path=WIND_REGISTER,
        iterations=N_ITER,
        seed=SEED,
        project=PROJECT,
        # No day_rate override: the register's MC_day_rate is the one source, exactly as it
        # is for the deliverable. Passing the module literal here left two sources for one
        # number - the thing option A was ruled to remove - with the headline equality
        # holding only because the two happened to agree.
        caller_module="scripts/run_wind_showcase.py",
    )
    int_cfg = s3_cfg.integrated_config
    res = run_integrated_simulation_stage3(
        s3_cfg,
        risks=risks,
        risk_scope_df=risk_scope,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
    )
    # SRA-02 S-E: the deterministic schedule cross-check. Comparator 2 is computed
    # in Python from the same consolidated frame the engine ran on, never read from
    # the register's Summary cells (P-E8) - a cached value is only as fresh as the
    # last Excel save. Tolerance comes from the config the run is already using.
    calibration = evaluate_schedule_calibration(
        float(np.mean(np.asarray(res.schedule_days_array, dtype=float))),
        compute_schedule_comparators(
            risk_scope,
            read_register_mode_multipliers(WIND_REGISTER),
            # The register's own MC_day_rate, not the module literal: the Excel
            # Summary dollars multiply by that named range, so the cross-check has
            # to dollarise off the same cell or the "one source" the reader
            # documents is only true by coincidence (review finding F-3). The two
            # agree today; nothing enforced it.
            read_register_day_rate(WIND_REGISTER),
        ),
        int_cfg.schedule_calibration_tolerance_days,
        # SCHEDCAL-01: judged on this run's own Mode basis, read from the config it ran on.
        mode_multipliers_applied=bool(s3_cfg.schedule_mc_config.apply_mode_multipliers),
        # Gate 3 round 2: Comparator 1 bounds only discrete injection, so the check needs the
        # methods of the drivers this engine ran.
        injection_methods={d.injection_method for d in drivers.values()},
    )

    cost = np.asarray(res.cost_result["cost_dollars_array"], dtype=float)
    sched_days = np.asarray(res.schedule_days_array, dtype=float)
    sched_dollars = sched_days * DAY_RATE
    integrated = cost + sched_dollars  # joint per-iteration total
    # WIND-02 A-with-disclosure: the cost QRA section sources its bands,
    # tornado and CG rollup from THIS integrated cost arm too (per_risk +
    # totals below), so the whole showcase quotes ONE cost figure. The
    # earlier standalone MonteCarloEngine cost MC over-stated risk WT-002
    # by ~$244k (it dispatched WT-002's Triangular to an unbounded sampler -
    # its conditional mean exceeded the Triangular's own max); the
    # integrated engine samples WT-002 correctly (matches the analytic
    # Triangular mean). See run_cost_qra's disclosure line + the cost QRA md.
    return {
        "cost": cost, "sched_days": sched_days, "sched_dollars": sched_dollars,
        "integrated": integrated, "n_dual": len(drivers), "n_iter": N_ITER,
        "per_risk_cost": np.asarray(
            res.cost_result["per_risk_cost_array"], dtype=float),
        "risks": risks,
        "calibration": calibration,
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    # newline="\n" is not optional here, and the idiom is the repository's own
    # (src/final/deliverable.py:748, scripts/run_diagnostic.py:98). Without it
    # Path.write_text opens with newline=None and translates every "\n" to os.linesep,
    # so on Windows these artefacts are CRLF. That was harmless while they only ever
    # landed in gitignored outputs/; SHOWCASE-02 D-2(a) commits a snapshot of them under
    # docs/showcase/wind/, where `git ls-files --eol | grep w/crlf` would list all six.
    # The wider class - 28 write_text calls across src/ and scripts/, of which only two
    # carried this argument - is WRITETEXTEOL-01, not this brief's to sweep.
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def _render_sra_schedule_md(sra: dict) -> str:
    """Render ``wind_sra_schedule.md`` from a ``run_sra_schedule()`` result.

    MODEMIX-01 (SRA-02 S-F): the header block carries the mode-mix label and
    each contribution row carries that risk's applied Mode. Both come from the
    engine's ``mode_used``, which ``run_sra_schedule`` has always returned and
    nothing read - no literal, and no second mix formatter. ``format_mode_mix``
    (``src/sra/mode_mix``, RS-D-5) is the one the report path uses too, so the two
    surfaces state the mix the same way.

    Split out of ``render`` so the surface can be asserted without an engine run.
    """
    from src.sra.mode_mix import format_mode_mix  # RS-D-5: the one formatter

    sb = sra["bands"]
    modes = sra["mode_used"]
    lines = ["# Tropic Ridge Wind Farm - Schedule Risk Analysis (Stage 2.5 MC)", "",
             f"{sra['n_sim']} Time=Yes risks simulated, {N_ITER:,} iterations, "
             f"seed {SEED}. Finish-delay dollarised at ${DAY_RATE:,.0f}/working day.",
             "",
             f"Mode mix (applied): {format_mode_mix(modes)} "
             "(S = Series, H = Hybrid, P = Parallel).", "",
             "## Finish-delay P-bands", "",
             "| Metric | Delay (days) | Dollarised |", "|---|---|---|"]
    for k in ("mean", "p50", "p80", "p90", "p95"):
        lines.append(f"| {k.upper()} | {sb[k]:.1f} | {_m(sb[k] * DAY_RATE)} |")
    lines += ["", "## Mean schedule contribution by risk", "",
              "| Risk | Mode | Mean delay (days) |", "|---|---|---|"]
    # RS-D-3 (D-15 ii): every simulated risk gets a row, including one whose Mode
    # multiplier makes its mean contribution exactly zero - so the header's mix and
    # the table agree (S-F F-3 recorded the eight-of-ten gap this filter caused).
    for rid, days in sra["ranked"]:
        lines.append(f"| {rid} | {modes[rid]} | {days:.2f} |")
    return "\n".join(lines) + "\n"


def render(cost: dict, sra: dict, s3: dict, integ: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cb = cost["bands"]
    # SHOWCASE-RENDER-01: this was missing, and the integrated-headline block
    # below referenced `sb` as though it were still in scope. It is a local of
    # _render_sra_schedule_md(), which a refactor extracted from this function
    # without moving the use with it - so this script could not finish, in this
    # repository or the one it was cut from. tests/test_showcase_smoke.py now
    # runs the entry point, and tests/test_no_undefined_names.py catches the
    # class statically for the whole tree.
    sb = sra["bands"]

    # --- Cost QRA ---
    lines = ["# Tropic Ridge Wind Farm - Cost QRA (Monte Carlo)", "",
             f"Illustrative showcase data. {cost['n_risks']} risks, "
             f"{N_ITER:,} iterations, seed {SEED}. Contingency sits on the "
             f"$50.0M Tropic Ridge Wind Farm capex (EPC $45M + grid connect $5M).", "",
             "_Cost is the integrated engine's cost arm (jointly sampled with "
             "the Stage 3 schedule), so every cost figure in this showcase is "
             "consistent with the integrated headline. (Build note, not for "
             "client copy: the integrated engine does not yet model recurrence; "
             "WT-002 is therefore carried as single-occurrence in this showcase. "
             "The standalone cost engine models recurrence per AACE-style "
             "seasonal exposure and is the reference implementation; the two "
             "engines agree once WT-002 is single-occurrence. The capability "
             "gap is COST-01.)_", "",
             "## Headline cost contingency (Layer-2 risk)", "",
             "| Metric | Contingency | % of $50M capex |", "|---|---|---|"]
    for k in ("mean", "p50", "p80", "p90", "p95"):
        lines.append(f"| {k.upper()} | {_m(cb[k])} | {cb[k] / CAPEX_TOTAL:.1%} |")
    lines += ["", "## Per-cost-group mean contribution", "",
              "| CG | Mean EMV |", "|---|---|"]
    for cg in sorted(cost["cg_totals"]):
        lines.append(f"| {cg} | {_m(cost['cg_totals'][cg])} |")
    lines += ["", "## Top risks by mean EMV (tornado)", "",
              "| Risk | Description | CG | Mean EMV |", "|---|---|---|---|"]
    for rid, desc, cg, emv in cost["ranked"][:12]:
        lines.append(f"| {rid} | {desc} | {cg} | {_m(emv)} |")
    _write(OUT_DIR / "wind_cost_qra.md", "\n".join(lines) + "\n")
    with (OUT_DIR / "wind_cost_tornado.csv").open("w", newline="", encoding="utf-8") as f:
        # lineterminator="\n": csv.writer defaults to "\r\n" per RFC 4180, which is right
        # for a CSV in the wild and wrong for one committed here. This repository's five
        # other tracked .csv files are all LF and .gitattributes carries no csv exception,
        # so a CRLF snapshot would be the only one and `git ls-files --eol` would say so.
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["risk_id", "description", "cg", "mean_emv"])
        w.writerows(cost["ranked"])

    # --- SRA schedule ---
    _write(OUT_DIR / "wind_sra_schedule.md", _render_sra_schedule_md(sra))

    # --- Stage 3 CPM ---
    tb = s3["bands"]
    spread = tb["p95"] - tb["p50"]
    lines = ["# Tropic Ridge Wind Farm - Stage 3 CPM-Replay", "",
             f"CPM-replay over the {s3['n_activities']}-activity WTG schedule, "
             f"{s3['n_iter']:,} iterations, seed {SEED}. **Pure-MC (AACE 65R-11 "
             f"Mode-independent) basis: apply_mode_multipliers=False** - every "
             f"Time-Impact risk injects its full sampled PERT delay and the CPM "
             f"decides what reaches the finish date. "
             f"Each schedule risk is auto-mapped to a single gating activity on "
             f"the critical path, so the risk-driven spread (P95-P50 ~ "
             f"{spread:.0f} working days) reflects the additive PERT impacts, "
             f"not over-binding.", "",
             # SHOWCASE-02 S-7 / CPMINERT-01. Measured, not asserted from theory: at
             # 100,000 iterations the replay and the sum of the injected delays are
             # identical on every iteration, because all ten gates carry zero float.
             # A reader told the headline rests on a CPM replay would otherwise infer
             # the network is doing something an additive model does not. Regenerate
             # this claim's evidence with scripts/measure_replay_vs_additive.py.
             "> **What the CPM replay contributes on this schedule, stated plainly.** "
             "Every schedule risk here gates on an activity with **zero total float**, "
             "and each injects its delay as a discrete event at that gate. A delay at a "
             "zero-float activity extends the finish by exactly its own magnitude, so on "
             "this schedule the CPM replay is **arithmetically identical to summing the "
             "per-risk delays** - measured at 100,000 iterations, identical on every "
             "iteration. The replay is doing real work only where risks can land on "
             "float or on parallel paths, and on this schedule none do.", "",
             "> **And the schedule's own shape flatters it.** This is a synthetic "
             "network: it carries no milestones and only finish-to-start logic with no "
             "lags, so it has far fewer convergence points than a real programme of the "
             "same scope. At a convergence point a successor waits for the *latest* of "
             "its predecessors, so a realistically logicked schedule would carry more "
             "merge bias than this one - which means the finish distribution above is, "
             "if anything, mildly optimistic.", "",
             "## Project-finish P-bands (working days from project start)", "",
             "| Metric | Project finish (working days) |", "|---|---|"]
    for k in ("mean", "p50", "p80", "p90", "p95"):
        lines.append(f"| {k.upper()} | {tb[k]:.1f} |")
    lines += ["", "## Schedule risks -> activities bound", "",
              "| Risk | Activities bound |", "|---|---|"]
    for rid, n in sorted(s3["bound"].items()):
        lines.append(f"| {rid} | {n} |")
    lines += ["", "## Deterministic critical path (first 20 activities)", ""]
    lines += [f"- {c}" for c in s3["critical_path"][:20]]
    lines += ["", "## Top activities by criticality index", "",
              "| Activity | Criticality |", "|---|---|"]
    for act, ci in s3["criticality_top"]:
        lines.append(f"| {act} | {ci:.3f} |")
    _write(OUT_DIR / "wind_stage3_cpm.md", "\n".join(lines) + "\n")

    # --- Integrated headline (WIND-02: joint cost + Stage 3 schedule) ---
    ig = integ["integrated"]; icost = integ["cost"]; isd = integ["sched_dollars"]
    isday = integ["sched_days"]
    pj = lambda a, q: float(np.percentile(a, q))
    cost_p80 = pj(icost, 80); sched_p80 = pj(isd, 80)
    integrated_p80 = pj(ig, 80)
    naive_p80 = cost_p80 + sched_p80          # sum of two marginals (wrong)
    overstate = naive_p80 - integrated_p80
    lines = ["# Tropic Ridge Wind Farm - Integrated Cost + Schedule Headline", "",
             f"Illustrative upfront contingency for the 40 MW Tropic Ridge Wind "
             f"Farm scope (~$50M capex), {integ['n_iter']:,} iterations, seed "
             f"{SEED}. **Full-CPM basis**: the schedule arm is the Stage 3 "
             f"CPM-replay (AACE 65R-11 pure-MC, apply_mode_multipliers=False), "
             f"jointly sampled with the cost arm through the integrated engine - "
             f"{integ['n_dual']} dual-coded (Time=Yes) risks share one severity "
             f"draw per iteration across cost and schedule. The integrated total "
             f"is the P80 of the joint per-iteration sum, NOT the sum of the two "
             f"arms' P80s.", "",
             "| Component | P80 | % of $50M capex |", "|---|---|---|",
             f"| Cost QRA (Layer 2) | {_m(cost_p80)} | {cost_p80 / CAPEX_TOTAL:.1%} |",
             f"| Schedule (Stage 3 CPM, dollarised @ ${DAY_RATE:,.0f}/d) | {_m(sched_p80)} | {sched_p80 / CAPEX_TOTAL:.1%} |",
             f"| **Integrated total (joint)** | **{_m(integrated_p80)}** | **{integrated_p80 / CAPEX_TOTAL:.1%}** |",
             f"| _Naive sum (cost P80 + schedule P80)_ | _{_m(naive_p80)}_ | _{naive_p80 / CAPEX_TOTAL:.1%}_ |",
             "",
             f"The naive P80-plus-P80 addition overstates the contingency by "
             f"**{_m(overstate)}** ({overstate / max(integrated_p80, 1):.1%} of the "
             f"integrated total): the P80 of a sum is not the sum of P80s unless "
             f"the arms are perfectly correlated, and the joint model prices the "
             f"diversification the naive method ignores.", "",
             "## Integrated total P-bands (joint)", "",
             "| Metric | Contingency | % of capex |", "|---|---|---|"]
    for k, q in (("Mean", None), ("P50", 50), ("P80", 80), ("P90", 90), ("P95", 95)):
        v = float(ig.mean()) if q is None else pj(ig, q)
        lines.append(f"| {k} | {_m(v)} | {v / CAPEX_TOTAL:.1%} |")
    lines += ["",
              f"Schedule arm (Stage 3 CPM): P80 finish-delay {pj(isday, 80):.1f} "
              f"working days. Stage 2.5 cross-check (retained for continuity, NOT "
              f"the headline): P80 finish-delay {sb['p80']:.1f} days / "
              f"{_m(sb['p80'] * DAY_RATE)} - the older Tier-2.5 shortcut basis."]
    # SRA-02 S-E: the deterministic schedule cross-check, the step-7 remainder.
    cal = integ["calibration"]
    lines += ["", "## Deterministic schedule cross-check", "",
              "| Quantity | Days |", "|---|---|",
              f"| Comparator 1, EMV days (no Mode weighting) | {cal['comparator_1_emv_days_pert']:.3f} |",
              f"| MC schedule mean (Stage 3 CPM) | {cal['mc_schedule_mean_days']:.3f} |",
              f"| Comparator 2, Mode-weighted EMV | {cal['comparator_2_finish_delay_days_pert']:.3f} |",
              f"| Gap tested against the tolerance ({cal['judged_against']}) | "
              f"{cal['absolute_gap_days']:.3f} |",
              f"| Tolerance | {cal['absolute_tolerance_days']:.1f} |",
              f"| Result (judged against {cal['judged_against']}) | "
              f"**{ {True: 'PASS', False: 'FAIL', None: 'NOT ASSESSED'}[cal['passes_calibration']] }** |",
              f"| _Diagnostic: gap to {cal['diagnostic_comparator']} (not part of the check)_ | "
              f"_{cal['diagnostic_gap_days']:.3f}_ |",
              "", cal["interpretation"]]
    if not cal["mode_multipliers_applied"]:
        # SCHEDCAL-01 D2 (Director, 14/10/2026): the diagnostic, stated plainly for this schedule.
        lines += ["", f"Delay that did not reach the finish (float absorbed, or risks bound to no "
                      f"activity): {cal['delay_not_reaching_finish_days']:.3f} days.",
                  "", "On this synthetic schedule every risk gates an activity with zero total "
                      "float (see wind_stage3_cpm.md), so the network absorbs none of the float the "
                      "register's Hybrid and Parallel labels expect. That is the disclosed "
                      "simplification of the synthetic network, not a defect in the model."]
    _write(OUT_DIR / "wind_integrated_headline.md", "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Charts (P5.1 WS5.1-A) - call the engine's themed chart suite on the wind
# results already in hand. Call-only: charts.py is consumed unchanged, so the
# RefProject report charts stay byte-identical. Every label/title carries the
# public name "Tropic Ridge Wind Farm" and zero RefProject identifiers.
# ---------------------------------------------------------------------------

FIG_DIR = OUT_DIR / "figs"

# Headline scenario colour for the single-curve wind S-curves (matches the
# brand navy used by the RefProject cost S-curve in composer.py).
_WIND_NAVY = "#1F4E79"
_WIND_OFFCP_GREY = "#B0B0B0"


def _make_single_panel_criticality_chart(
    *,
    criticality_index: dict,
    activity_titles: dict,
    on_cp: set,
    output_path: Path,
    top_n: int = 20,
) -> Path:
    """WIND-01 single-panel criticality bar chart (AACE 65R-11, pure-MC).

    Horizontal bars of the top-N activities by criticality index; navy for
    deterministic-critical-path activities, grey otherwise. Wind-local by
    design so the shared engine chart suite (``src/final/charts.py``,
    whose ``make_sorted_criticality_bar_chart`` renders the RefProject
    dual-panel Chart 1) is not touched - the RefProject report charts stay
    byte-identical. Replaces the removed dual Mode-conditioned/Mode-
    independent panel, which is structurally empty under ``apply=False``.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ranked = sorted(
        criticality_index.items(), key=lambda kv: (-kv[1], kv[0]),
    )[:top_n]
    labels = [activity_titles.get(aid, aid) for aid, _ in ranked]
    values = [v for _, v in ranked]
    colors = [_WIND_NAVY if aid in on_cp else _WIND_OFFCP_GREY for aid, _ in ranked]

    fig, ax = plt.subplots(figsize=(11, max(4.0, 0.34 * len(ranked) + 1.2)))
    ypos = list(range(len(ranked)))
    ax.barh(ypos, values, color=colors)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()  # highest criticality at the top
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Criticality index (AACE 65R-11, Mode-independent)")
    ax.set_title(
        f"Tropic Ridge Wind Farm - top {len(ranked)} activities by "
        f"criticality index\n(AACE 65R-11 pure-MC basis)",
        fontsize=12,
    )
    for i, v in zip(ypos, values):
        ax.text(min(v + 0.01, 0.97), i, f"{v:.0%}", va="center", fontsize=7)
    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


def _stamp_png(path: Path, run_id: str) -> None:
    """Re-save a chart with the run's id in a PNG text chunk (SHOWCASESYNC-01).

    Lossless: the pixels, the existing text chunks and the dpi are carried over. Compression level
    9 is PRERELEASE-01 P2's, which keeps chance strings out of the compressed bytes as often as any.
    """
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    with Image.open(path) as im:
        im.load()
        info = PngInfo()
        for k, v in im.text.items():
            if k != RUN_ID_KEY:
                info.add_text(k, v)
        info.add_text(RUN_ID_KEY, run_id)
        kwargs = {"pnginfo": info, "compress_level": 9}
        if "dpi" in im.info:
            kwargs["dpi"] = im.info["dpi"]
        im.save(path, format="PNG", **kwargs)


def render_charts(cost: dict, sra: dict, s3: dict, run_id: str) -> dict[str, str]:
    """Emit the themed wind chart suite to ``FIG_DIR`` (``outputs/wind_showcase/figs``, or
    ``docs/showcase/figs`` under --publish).

    Cost/schedule charts are imported from ``src.final.charts`` and
    consumed exactly as the RefProject composer consumes them (same
    signatures, unchanged); the wind-specific code is the call-site shaping
    of the in-memory wind results. The activity-criticality panel is
    wind-local (:func:`_make_single_panel_criticality_chart`) so the shared
    suite stays byte-identical (WIND-01 §2.2, §2.6).
    """
    from src.final.charts import (
        make_density_histogram,
        make_s_curve,
        make_tornado_chart,
    )

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    # --- Cost arm: outturn distribution in $M ($-array -> $M for legibility,
    #     mirroring the RefProject cost charts in composer.py). ---
    cost_total_m = np.asarray(cost["total"], dtype=float) / 1e6
    cost_pct = {int(p): float(np.percentile(cost_total_m, p)) for p in (50, 80, 90, 95)}

    cost_curve_label = "Cost contingency (Layer-2 risk)"
    p = FIG_DIR / "wind_cost_s_curve.png"
    make_s_curve(
        distributions={cost_curve_label: cost_total_m},
        percentile_markers=[50, 80, 90, 95],
        title="Tropic Ridge Wind Farm - cost contingency S-curve",
        output_path=p,
        x_axis_label="Cost contingency ($M)",
        color_map={cost_curve_label: _WIND_NAVY},
        value_label_fmt="${value:.2f}M",
    )
    paths["cost_s_curve"] = str(p)
    print(f"wrote {p}")

    p = FIG_DIR / "wind_cost_density.png"
    make_density_histogram(
        samples=cost_total_m,
        title="Tropic Ridge Wind Farm - cost contingency distribution",
        output_path=p,
        mean_value=float(cost_total_m.mean()),
        percentile_markers=cost_pct,
        x_axis_label="Cost contingency ($M)",
        color=_WIND_NAVY,
        nil_bucket_annotation=False,  # cost MC has no zero spike to surface
    )
    paths["cost_density"] = str(p)
    print(f"wrote {p}")

    # Cost tornado: ranked (rid, desc, cg, emv$) -> ranked dicts in $M.
    tornado_data = [
        {"risk_id": rid, "title": desc, "value": emv / 1e6}
        for rid, desc, _cg, emv in cost["ranked"][:12]
    ]
    p = FIG_DIR / "wind_cost_tornado.png"
    make_tornado_chart(
        ranked_risks=tornado_data,
        title="Tropic Ridge Wind Farm - top cost risks by mean EMV",
        x_axis_label="Mean EMV cost contribution ($M)",
        output_path=p,
        value_format="${:.2f}M",
    )
    paths["cost_tornado"] = str(p)
    print(f"wrote {p}")

    # --- Schedule arm: Stage 3 project-finish S-curve (working days). ---
    finish_days = np.asarray(s3["finish_days"], dtype=float)
    finish_label = "Project finish (Stage 3 CPM-replay)"
    p = FIG_DIR / "wind_schedule_finish_s_curve.png"
    make_s_curve(
        distributions={finish_label: finish_days},
        percentile_markers=[50, 80, 90, 95],
        title="Tropic Ridge Wind Farm - Stage 3 project-finish S-curve",
        output_path=p,
        x_axis_label="Project finish (working days from start)",
        color_map={finish_label: _WIND_NAVY},
        value_label_fmt="{value:.0f}d",
    )
    paths["schedule_finish_s_curve"] = str(p)
    print(f"wrote {p}")

    # --- Activity criticality top-N: SINGLE panel, AACE 65R-11 (pure-MC)
    #     basis (WIND-01 §2.2). The dual Mode-conditioned/Mode-independent
    #     panel is REMOVED - under apply_mode_multipliers=False the two
    #     indices coincide, so a dual panel would be a structurally-zero
    #     comparison (the same defect CLI found in the Stage 3 standalone
    #     deliverable, W3). Rendered wind-local so the shared chart suite
    #     (src/final/charts.py) is untouched and the RefProject report charts
    #     stay byte-identical. ---
    p = FIG_DIR / "wind_activity_criticality.png"
    _make_single_panel_criticality_chart(
        criticality_index=s3["result"].criticality_index,
        activity_titles=s3["activity_titles"],
        on_cp=set(s3["result"].deterministic_critical_path),
        output_path=p,
        top_n=20,
    )
    paths["activity_criticality"] = str(p)
    print(f"wrote {p}")

    # SHOWCASESYNC-01: every chart names the run that drew it.
    for written in paths.values():
        _stamp_png(Path(written), run_id)

    # --- Criticality density Gantt (optional, Director decision 2). The
    #     phase-mapped time-binned heatmap needs RBS Level-1 phase mapping and
    #     dated activity bindings that the wind fixture does not expose in the
    #     RefProject PROJWBS shape; deferred to a P5.1 follow-up rather than
    #     forcing a degraded render. Non-blocking per the brief. ---
    print("note: criticality density Gantt deferred (needs RBS-L1 phase map "
          "+ dated bindings; non-blocking per Director decision 2)")

    return paths


def _write_run_meta(
    cost: dict, sra: dict, s3: dict, integ: dict,
    *, provenance: dict | None = None, run_identity: dict | None = None,
) -> None:
    """WIND-01 §2.3: stamp the run parameters into a JSON meta file so no
    figure can be quoted without its iteration count and methodology basis.
    The schedule (Stage 3) arm is the pure-MC headline; its iteration count
    is the one that gates whether a figure is production-scale or draft.
    """
    import json

    import numpy as _np
    ig = integ["integrated"]
    meta = {
        "seed": SEED,
        # WIND-02: one showcase-wide iteration count feeds every arm (the
        # integrated engine requires cost/schedule parity).
        "iterations": N_ITER,
        "methodology_basis": "AACE 65R-11 pure-MC (Mode-independent)",
        "apply_mode_multipliers": False,
        "criticality_measurement_mode": "mode_independent",
        "headline_engine": "integrated_simulation_stage3 (joint cost + Stage 3 schedule)",
        "n_dual_coded_risks": integ["n_dual"],
        "integrated_total_p80": float(_np.percentile(ig, 80)),
        "naive_sum_p80": float(_np.percentile(integ["cost"], 80))
        + float(_np.percentile(integ["sched_dollars"], 80)),
        "production_scale_floor_note": (
            "Draft-scale runs are for layout/sanity only; no blog number may "
            "come from anything but a production-scale run. A low-n run is NOT "
            "a subset of a high-n run."
        ),
    }
    # WIND-04: engine-provenance stamp (meta-only; no figure changes). Added
    # as trailing keys so the old-vs-new lock diff is confined to exactly
    # these fields, with integrated_total_p80 / naive_sum_p80 byte-identical.
    if provenance is not None:
        meta["engine_sha"] = provenance["engine_sha"]
        meta["engine_tree_dirty"] = provenance["engine_tree_dirty"]
        meta["input_sha256"] = provenance["input_sha256"]
    # SHOWCASESYNC-01: the run's identity, which every chart and the quoted values carry too.
    if run_identity is not None:
        meta["run_id"] = run_identity["run_id"]
        meta["run_date"] = run_identity["run_date"]
        meta["run_timestamp"] = run_identity["run_timestamp"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "wind_run_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8", newline="\n",
    )
    print(f"wrote {OUT_DIR / 'wind_run_meta.json'}")


def _quoted_values(cost: dict, s3: dict, integ: dict) -> dict:
    """Every value the summary qmd may quote, by name (SHOWCASESYNC-01).

    All Stage 3 (Director, 14/10/2026: "everything should be the current stage 3"): the cost arm
    and the schedule arm are the integrated engine's, jointly sampled, and the finish bands are
    the CPM replay's. The Stage 2.5 schedule is not offered here, so the qmd cannot quote it.
    """
    if CAPEX_EPC + CAPEX_GRID != CAPEX_TOTAL:
        raise ValueError("the capex split does not sum to the capex total")
    v: dict = {"capex_total": CAPEX_TOTAL, "capex_epc": CAPEX_EPC, "capex_grid": CAPEX_GRID,
               "day_rate": DAY_RATE, "iterations": N_ITER, "seed": SEED}

    cb = cost["bands"]
    for k in ("mean", "p50", "p80", "p90", "p95"):
        v[f"cost.{k}"] = cb[k]
        v[f"cost.{k}_pct"] = cb[k] / CAPEX_TOTAL
    v["cost.p80_minus_p50"] = cb["p80"] - cb["p50"]

    ranked = cost["ranked"]
    mean_total = sum(emv for *_, emv in ranked)
    for i, (rid, desc, cg, emv) in enumerate(ranked[:6], 1):
        v[f"cost.rank{i}.id"] = rid
        v[f"cost.rank{i}.desc"] = desc
        v[f"cost.rank{i}.cg"] = cg
        v[f"cost.rank{i}.emv"] = emv
    v["cost.top3_share"] = sum(emv for *_, emv in ranked[:3]) / mean_total
    cg_id, cg_emv = max(cost["cg_totals"].items(), key=lambda kv: (kv[1], kv[0]))
    v["cost.cg_top.id"] = cg_id
    v["cost.cg_top.emv"] = cg_emv

    ig = np.asarray(integ["integrated"], dtype=float)
    pj = lambda a, q: float(np.percentile(a, q))
    v["sched.p80_days"] = pj(integ["sched_days"], 80)
    v["sched.p80_dollars"] = pj(integ["sched_dollars"], 80)
    v["sched.p80_dollars_pct"] = v["sched.p80_dollars"] / CAPEX_TOTAL
    v["integrated.mean"] = float(ig.mean())
    for k, q in (("p50", 50), ("p80", 80), ("p90", 90), ("p95", 95)):
        v[f"integrated.{k}"] = pj(ig, q)
    for k in ("mean", "p50", "p80", "p90", "p95"):
        v[f"integrated.{k}_pct"] = v[f"integrated.{k}"] / CAPEX_TOTAL
    v["integrated.naive_p80"] = pj(integ["cost"], 80) + v["sched.p80_dollars"]
    v["integrated.naive_p80_pct"] = v["integrated.naive_p80"] / CAPEX_TOTAL
    v["integrated.overstatement"] = v["integrated.naive_p80"] - v["integrated.p80"]

    tb = s3["bands"]
    for k in ("mean", "p50", "p80", "p90", "p95"):
        v[f"s3.finish.{k}"] = tb[k]
    v["s3.finish.p95_minus_p50"] = tb["p95"] - tb["p50"]
    v["s3.n_activities"] = s3["n_activities"]
    return v


def _write_quoted_values(values: dict, run_identity: dict) -> None:
    import json

    record = {"run_id": run_identity["run_id"], "values": values}
    p = OUT_DIR / "wind_quoted_values.json"
    p.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                 newline="\n")
    print(f"wrote {p}")


def _clear_charts_for_shipping(charts: dict[str, str]) -> None:
    """SHOWCASESYNC-01 property 7: every chart that ships clears the client gate and the shipped-
    name checks; one whose compressed bytes trip one by chance is re-encoded losslessly."""
    from scripts.release.publishable_bytes import clean_png, load_findings

    findings = load_findings()
    for path in map(Path, charts.values()):
        name = path.relative_to(REPO_ROOT).as_posix()
        data = path.read_bytes()
        cleaned = clean_png(data, name, findings)
        if cleaned is not data:
            path.write_bytes(cleaned)
            print(f"re-encoded {name} losslessly: its bytes tripped a shipped-file check")


def _publish_qmd(values: dict, run_identity: dict) -> None:
    """Rewrite the summary qmd's bound figures and date from this run."""
    from scripts.showcase_quotes import fill, unbound

    text = SUMMARY_QMD.read_text(encoding="utf-8")
    left = unbound(text)
    if left:
        raise SystemExit("the summary qmd quotes figures no run value binds:\n  "
                         + "\n  ".join(left))
    out = fill(text, values, run_identity["run_date"])
    SUMMARY_QMD.write_bytes(out.encode("utf-8"))
    print(f"wrote {SUMMARY_QMD}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the synthetic-wind showcase end-to-end.",
    )
    parser.add_argument(
        "--allow-dirty", action="store_true",
        help="WIND-04: proceed even if the outturn tree is dirty; stamps "
             "engine_tree_dirty: true (a NON-clean attestation).",
    )
    parser.add_argument(
        "--baseline-meta", type=Path, default=BASELINE_META,
        help="The run-meta whose recorded seed this run reproduces (default: the committed "
             "showcase's). A re-cut is compared against the summaries that meta came with.",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="SHOWCASESYNC-01: write the whole set where it ships - docs/showcase/run/, "
             "docs/showcase/figs/ and the summary qmd's bound figures - from this one run. "
             "Refuses below the production-scale floor and over a dirty tree.",
    )
    args = parser.parse_args(argv)
    global SEED, OUT_DIR, FIG_DIR
    SEED = baseline_seed(args.baseline_meta)

    # WIND-04: resolve engine identity ONCE, up front, so the guard and the
    # stamp see the same tree state, and the guard fails fast BEFORE the ~100k
    # compute. Mirrors AM09 (no guard/write TOCTOU).
    engine_sha = _resolve_engine_sha()
    engine_tree_dirty = _resolve_tree_dirty()
    if args.publish:
        if args.allow_dirty or engine_tree_dirty is not False:
            raise SystemExit("--publish refuses a dirty tree (and --allow-dirty): what ships must "
                             "name the commit that made it. Commit first.")
        if N_ITER < PRODUCTION_SCALE_FLOOR:
            raise SystemExit(f"--publish refuses {N_ITER:,} iterations, below the "
                             f"{PRODUCTION_SCALE_FLOOR:,} production-scale floor. "
                             f"Set WIND_ITERATIONS={PRODUCTION_SCALE_FLOOR}.")
        OUT_DIR, FIG_DIR = PUBLISH_RUN_DIR, PUBLISH_FIG_DIR
    _check_dirty_guard(engine_tree_dirty, args.allow_dirty)
    if engine_tree_dirty and args.allow_dirty:
        print("WIND-04: outturn tree is DIRTY; proceeding under "
              "--allow-dirty. engine_tree_dirty will be stamped true - this "
              "run is NOT a clean-tree attestation.")
    provenance = _build_provenance(engine_sha, engine_tree_dirty)
    import uuid
    from datetime import date, datetime, timezone
    run_identity = {
        "run_id": str(uuid.uuid4()),
        # The date is the run machine's own, as the deliverable's run_date is
        # (src/final/deliverable.py); the timestamp is UTC, so the two can differ by a day.
        "run_date": date.today().isoformat(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    _activate_wind_binding()
    # WIND-02: the integrated engine runs FIRST - it is the single source of
    # the cost arm (jointly sampled with the Stage 3 schedule). run_cost_qra
    # derives its bands/tornado/CG from that same cost arm so the whole
    # showcase quotes one, correct cost figure (A-with-disclosure).
    print("=== Integrated (joint cost + Stage 3 schedule) ===")
    integ = run_integrated()
    print("=== Cost QRA (from integrated cost arm) ===")
    cost = run_cost_qra(integ)
    print("=== SRA schedule ===")
    sra = run_sra_schedule()
    print("=== Stage 3 CPM ===")
    s3 = run_stage3_cpm()
    render(cost, sra, s3, integ)
    print("=== Charts (P5.1) ===")
    charts = render_charts(cost, sra, s3, run_identity["run_id"])
    if args.publish:
        _clear_charts_for_shipping(charts)
    _write_run_meta(cost, sra, s3, integ, provenance=provenance, run_identity=run_identity)
    values = _quoted_values(cost, s3, integ)
    _write_quoted_values(values, run_identity)
    if args.publish:
        _publish_qmd(values, run_identity)
    import numpy as _np
    ig = integ["integrated"]
    ip80 = float(_np.percentile(ig, 80))
    naive = float(_np.percentile(integ["cost"], 80)) + float(
        _np.percentile(integ["sched_dollars"], 80))
    print(f"\nHEADLINE (integrated, joint): P80 {_m(ip80)} "
          f"({ip80/CAPEX_TOTAL:.1%}) vs naive-sum {_m(naive)} "
          f"[overstatement {_m(naive - ip80)}]; "
          f"@ {integ['n_iter']:,} iters, pure-MC. "
          f"DRAFT unless production-scale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
