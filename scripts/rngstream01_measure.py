"""RNGSTREAM-01 evidence: do the fire draw and the severity draws share a random stream, and what
would separating them move?

The RNGSTREAM-01 brief, §2. Four
measurements, each re-runnable, each seeded:

* ``coupling`` - on each shipped register, build the fire uniforms exactly as the cost arm does
  (``build_risk_uniform_matrix`` on ``default_rng(seed)``) and the severity uniforms as the Stage 3
  orchestrator did **before RNGSTREAM-01** (``build_joint_severity_uniforms`` on another
  ``default_rng(seed)``; since the fix every route uses ``src.rng_streams.severity_generator``,
  and the beta route that still built them this way retired at REFRETIRE-01),
  then report the correlation groups, any fire column equal to any severity column, and the largest
  absolute correlation over every fire x severity pair.
* ``singleton`` - the same on a three-risk synthetic register whose first risk is a single-member
  group: the case the brief says couples exactly.
* ``spawn`` - whether child 0 of ``default_rng(seed).spawn()``, the kernel's batch-0 generator, is the
  same stream as ``default_rng(SeedSequence(seed).spawn()[0])``: the trap in brief §2.3.
* ``estimate`` - the Stage 3 headline with severity on a stand-in independent stream, against the
  current headline, with a bootstrap standard error on P80. Slow (two engine runs per project).
  **Before RNGSTREAM-01 merged** the current headline was the coupled one, so this was old against
  a stand-in fix, the brief's §2.4. **After**, the current headline already uses the new stream, so it
  compares two independent streams: a noise check, not the change.

    .venv\\Scripts\\python.exe scripts\\rngstream01_measure.py --seed 42              # coupling, singleton, spawn
    .venv\\Scripts\\python.exe scripts\\rngstream01_measure.py --seed 42 --estimate   # and the estimate
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PROJECTS = (
    ("synthetic_road", REPO / "tests/fixtures/synthetic_road/road_register.xlsx"),
    ("synthetic_wind", REPO / "tests/fixtures/synthetic_wind/wind_register.xlsx"),
)
N_ITER = 10_000
#: Set by main() from --seed. The RNGSTREAM-01 record's measurements were taken at 42.
SEED: int | None = None


def coupling(risks, cg, label: str) -> None:
    from src.correlations import build_risk_uniform_matrix
    from src.integrated.stage3_inputs import build_joint_severity_uniforms

    ids = [str(r.risk_id) for r in risks]
    fire = build_risk_uniform_matrix(N_ITER, risks, cg, np.random.default_rng(SEED))
    sev = build_joint_severity_uniforms(risk_ids=tuple(ids), n_iter=N_ITER,
                                             rng=np.random.default_rng(SEED), precision="float64")
    groups: dict[str, int] = {}
    for r in risks:
        groups[r.correlation_group] = groups.get(r.correlation_group, 0) + 1
    equal = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(len(ids))
             if np.array_equal(fire[:, i], sev[ids[j]])]
    corr = np.array([[abs(np.corrcoef(fire[:, i], sev[ids[j]])[0, 1]) for j in range(len(ids))]
                     for i in range(len(ids))])
    print(f"{label}: groups {groups}")
    print(f"  fire column == severity column: {equal if equal else 'none'}")
    print(f"  max |corr| over {corr.size} fire x severity pairs: {corr.max():.4f} "
          f"(per-pair noise scale ~{1 / np.sqrt(N_ITER):.4f}, n={N_ITER:,}, seed {SEED})")
    if equal:
        i = ids.index(equal[0][0])
        p = float(risks[i].probability)
        fired = fire[:, i] < p
        print(f"  {ids[i]} at p={p}: max severity uniform on a fired iteration "
              f"{sev[ids[i]][fired].max():.4f}")


def spawn_collision() -> None:
    kernel_batch0 = np.random.default_rng(SEED).spawn(1)[0].random(1_000)
    naive_child0 = np.random.default_rng(np.random.SeedSequence(SEED).spawn(1)[0]).random(1_000)
    print(f"spawn: kernel batch-0 generator == default_rng(SeedSequence({SEED}).spawn()[0]): "
          f"{np.array_equal(kernel_batch0, naive_child0)}")


def estimate(project: str, register: Path) -> None:
    from src.am.project_binding import resolve_project_inputs
    from src.integrated.integrated_simulation_stage3 import run_integrated_simulation_stage3
    from src.integrated.stage3_config import build_stage3_config, build_stage3_rules_from_scope
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.integrated.stage3_inputs import (Stage3BindingConfig,
                                              build_joint_severity_uniforms,
                                              resolve_float_threshold_hours)
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.schedule_cross_check import read_register_day_rate
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    xer = resolve_project_inputs(project).xer_path
    tables = parse_xer(str(xer))
    graph = build_schedule_graph(tables)
    scope = read_risk_scope(str(register))
    drivers = expand_auto_rules(build_stage3_rules_from_scope(
        scope, graph, Stage3BindingConfig(
            register_path=register, xer_path=xer, strawman_path=register,
            float_threshold_hours=resolve_float_threshold_hours(project))), graph)
    risks = read_risks_v5(str(register))
    rate = read_register_day_rate(register)

    def run(severity):
        cfg = build_stage3_config(register_path=register, xer_path=xer, strawman_path=register,
                                  iterations=N_ITER, seed=SEED,
                                  caller_module="scripts/rngstream01_measure.py")
        res = run_integrated_simulation_stage3(cfg, risks=risks, risk_scope_df=scope,
                                               schedule_graph=graph, risk_drivers=drivers,
                                               xer_tables=tables,
                                               severity_uniforms_by_risk_id=severity)
        total = (np.asarray(res.cost_result["cost_dollars_array"])
                 + np.asarray(res.schedule_days_array) * rate)
        return total, res

    current, res = run(None)
    # The stand-in independent stream for the estimate. Distinct entropy, so it is not a spawn
    # child of the run seed (brief §2.3). Not the stream the build will choose.
    stand_in = build_joint_severity_uniforms(
        risk_ids=tuple(str(r.risk_id) for r in risks), n_iter=N_ITER,
        rng=np.random.default_rng(np.random.SeedSequence([SEED, 0x5E7])),
        precision=res.config_summary["schedule_mc"]["precision"])
    moved, _ = run(stand_in)
    boot = np.random.default_rng(1)
    se = float(np.std([np.percentile(current[boot.integers(0, N_ITER, N_ITER)], 80)
                       for _ in range(300)]))
    p_cur, p_new = np.percentile(current, 80), np.percentile(moved, 80)
    print(f"{project}: integrated P80 {p_cur / 1e6:.4f} -> {p_new / 1e6:.4f} $M "
          f"({(p_new - p_cur) / 1e6:+.4f}, {(p_new - p_cur) / se:+.2f} bootstrap SE of "
          f"{se / 1e6:.4f}); mean {current.mean() / 1e6:.4f} -> {moved.mean() / 1e6:.4f}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--estimate", action="store_true", help="also run the movement estimate")
    parser.add_argument("--seed", type=int, required=True,
                        help="the seed to measure at (the RNGSTREAM-01 record's is 42)")
    args = parser.parse_args(argv)
    global SEED
    SEED = args.seed

    from src.sra.methodology_defaults_reader import read_cg_coefficients
    from src.v5_register_reader import read_risks_v5

    for project, register in PROJECTS:
        os.environ["QRA_PROJECT"] = project
        coupling(read_risks_v5(str(register)),
                 read_cg_coefficients(register, caller_module="scripts/rngstream01_measure.py"),
                 register.name)

    synthetic = [SimpleNamespace(risk_id="A", correlation_group="S-A", probability=0.3),
                 SimpleNamespace(risk_id="B", correlation_group="CG01", probability=0.3),
                 SimpleNamespace(risk_id="C", correlation_group="CG01", probability=0.3)]
    coupling(synthetic, {"CG01": 0.5}, "synthetic, singleton group first")
    spawn_collision()

    if args.estimate:
        for project, register in PROJECTS:
            os.environ["QRA_PROJECT"] = project
            estimate(project, register)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
