"""Measure, for any project, how much the CPM replay differs from an additive sum.

SHOWCASE-02 S-3, signed 19/09/2026. This is the script behind the brief's §2.6 numbers and
behind ledger row **CPMINERT-01**, so that the finding is something a later session can
re-derive rather than a figure quoted in a document.

WHAT IT COMPARES
    * **replay** - the Stage 3 CPM project-finish delay, i.e. ``schedule_days_array``:
      per-iteration finish minus the zero-risk deterministic baseline.
    * **additive** - the sum of the per-activity delay deltas the kernel actually injected
      on that same run, converted to days.

    Both come from **one run and the same draws**, so the only thing between them is what
    the network did with those delays: float absorption, and parallel paths combining as a
    maximum rather than a sum.

TWO BASIS TRAPS, AND WHY THE OBVIOUS COMPARISON IS WRONG
    1. The tempting additive side is ``per_risk_schedule_array.sum(axis=1)`` - already
       computed (``src/qra_core.py:271``) and already called "additive". It is
       **Mode-scaled** (``qra_core.py:189``), while the Stage 3 replay runs
       ``apply_mode_multipliers=False`` -> ``mode_multiplier_override=1.0``
       (``cpm_simulation.py:1187``). Both shipped projects are mixed-Mode with two Parallel
       (x0.0) risks each, so that comparison silently drops two risks from one side and
       halves four more, and the "gap" it reports is Mode scaling, not topology. This has
       been shipped once already in this repository: STAGE3HEADLINE-01's re-based check
       "compared two additive sums and said CPM" (CPMATTRIB-01). The Mode-scaled sum is
       still computed below, but reported as its own column and never as the comparator.
    2. The invariant *additive >= replay* (a delay can extend a finish by at most its own
       magnitude) must hold per iteration. At 1e-6 it appears to fail on roughly half of
       them, by ~1e-4 days - float32 rounding, not a broken reproduction. The tolerance
       here is the engine's own: ``integrated_simulation_stage3.py:582-587`` widened an
       inversion check from 1e-6 to **1e-4 relative** for exactly this reason.

USAGE
    python scripts/measure_replay_vs_additive.py --seed 42                 # both shipped projects
    python scripts/measure_replay_vs_additive.py --seed 42 --n 100000      # production scale
    python scripts/measure_replay_vs_additive.py --seed 42 --project synthetic_road

    Exits non-zero if the invariant fails, rather than reporting a gap it cannot stand
    behind.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_N = 10_000
SHIPPED = ("synthetic_wind", "synthetic_road")

#: Standard Mode map. Passed for completeness; the override below bypasses it, because the
#: production basis applies no Mode multiplier at all.
MODE_MAP = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}


def measure(project: str, n_iter: int, seed: int) -> dict:
    """Return both bases for ``project``, plus the invariant's verdict."""
    from src.am.project_binding import resolve_project_inputs
    from src.integrated.integrated_simulation_stage3 import run_integrated_simulation_stage3
    from src.integrated.stage3_config import build_stage3_config, build_stage3_rules_from_scope
    from src.integrated.stage3_inputs import Stage3BindingConfig, resolve_float_threshold_hours
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.risk_injection import sample_risk_deltas
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    inp = resolve_project_inputs(project)
    register, xer, strawman = inp.register_path, inp.xer_path, inp.strawman_path

    xer_tables = parse_xer(str(xer))
    graph = build_schedule_graph(xer_tables)
    risk_scope = read_risk_scope(str(strawman))
    rules = build_stage3_rules_from_scope(
        risk_scope, graph,
        Stage3BindingConfig(
            register_path=register, xer_path=xer, strawman_path=strawman,
            float_threshold_hours=resolve_float_threshold_hours(project),
        ),
    )
    drivers = expand_auto_rules(rules, graph)
    risks = read_risks_v5(str(register))

    cfg = build_stage3_config(
        register_path=register, xer_path=xer, strawman_path=strawman,
        project=project, iterations=n_iter, seed=seed,
        caller_module="scripts/measure_replay_vs_additive.py",
    )
    if cfg.schedule_mc_config.apply_mode_multipliers:
        raise SystemExit(
            f"{project}: expected the post-METHFIRE pure-MC basis "
            "(apply_mode_multipliers=False); this measurement is not defined otherwise")

    res = run_integrated_simulation_stage3(
        cfg, risks=risks, risk_scope_df=risk_scope, schedule_graph=graph,
        risk_drivers=drivers, xer_tables=xer_tables,
    )

    replay = np.asarray(res.schedule_days_array, dtype=float)

    sched = res.schedule_result
    sched_ids = list(sched.risk_ids)
    deltas = sample_risk_deltas(
        res.risk_drivers, graph, n_iter, np.random.default_rng(seed),
        severity_uniform=np.stack(
            [res.severity_uniforms_by_risk_id[r] for r in sched_ids], axis=1),
        precision=cfg.schedule_mc_config.precision,
        mode_multiplier_override=1.0,
        mode_multipliers=MODE_MAP,
        fire_mask=np.asarray(sched.risk_fired_array),
    )
    hpd = float(graph.project_default_calendar.working_hours_per_day)
    additive = np.asarray(deltas, dtype=float).sum(axis=1) / hpd

    slack = additive - replay
    tol = 1e-4 * np.maximum(1.0, additive)          # the engine's own tolerance

    gates_zero_float = sum(
        1 for d in res.risk_drivers.values()
        if d.gating_activity_id
        and (a := graph.activities.get(d.gating_activity_id)) is not None
        and (a.total_float_hours or 0.0) <= 0.001
    )

    return {
        "project": project, "n_iter": n_iter, "seed": seed, "hours_per_day": hpd,
        "replay": replay, "additive": additive,
        "mode_scaled": np.asarray(
            res.cost_result["per_risk_schedule_array"], dtype=float).sum(axis=1),
        "n_drivers": len(res.risk_drivers),
        "n_gates_zero_float": gates_zero_float,
        "violations": int((slack < -tol).sum()),
        "worst_violation": float(slack.min()),
    }


def report(m: dict) -> bool:
    r, a, ms = m["replay"], m["additive"], m["mode_scaled"]
    q = lambda x, p: float(np.percentile(x, p))
    print(f"\n=== {m['project']}  n={m['n_iter']:,}  seed {m['seed']}  "
          f"{m['n_drivers']} drivers, {m['n_gates_zero_float']} gating on zero float")
    if m["violations"]:
        print(f"  !! INVALID - additive < replay on {m['violations']:,} iterations "
              f"(worst {m['worst_violation']:.4f} d). A delay cannot extend a finish by "
              f"more than itself, so the reproduction is wrong. No gap reported.")
        return False
    print(f"  {'stat':<5} {'additive':>11} {'replay':>11} {'absorbed':>11}"
          f" {'Mode-scaled':>12}")
    def stat(arr, p):
        return float(arr.mean()) if p is None else q(arr, p)

    for label, p in (("mean", None), ("P50", 50), ("P80", 80), ("P95", 95)):
        av, rv, mv = stat(a, p), stat(r, p), stat(ms, p)
        print(f"  {label:<5} {av:>11.2f} {rv:>11.2f} {av - rv:>11.2f} {mv:>12.2f}")
    absorbed = a - r
    none_absorbed = int((absorbed <= 0.01).sum())
    print(f"  the network absorbed nothing (<=0.01 d) on {none_absorbed:,} of "
          f"{m['n_iter']:,} iterations ({none_absorbed / m['n_iter'] * 100:.1f}%)")
    if none_absorbed == m["n_iter"]:
        print("  -> the replay IS the additive sum on this project (CPMINERT-01)")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", action="append", choices=SHIPPED,
                    help="repeatable; defaults to both shipped projects")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help=f"iterations (default {DEFAULT_N})")
    ap.add_argument("--seed", type=int, required=True, help="the seed to measure at")
    args = ap.parse_args(argv)

    ok = True
    for project in (args.project or list(SHIPPED)):
        ok &= report(measure(project, args.n, args.seed))
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
