"""Project-agnostic integrated headline run - ROAD-01 §5.2, closing GOLDENADPT-01.

`tests/golden/projects.toml` claimed that adding a project needed "a row here + a bless. No code
change". That was untrue: neither golden adapter took a project. `_adapter_wind` imported
`scripts/run_wind_showcase.py`, which hardcodes its own register and `.xer` paths, capex and day
rate, so **reusing `adapter = "wind"` for another project would re-run the wind fixture and return
wind's numbers under the new project's name** - a golden that passes while measuring nothing.

This module is the fix the Director ruled (§5.2 option (b)): one runner, any project. Inputs are
resolved from the project's **binding** rather than from module constants, which is only possible
because GENERIC-01 made `resolve_project_inputs` binding-driven.

**The day rate is read from the register, not passed in.** `run_wind_showcase` carries a module
literal beside the register's `MC_day_rate` and its own comment notes the two "agree today;
nothing enforced it". A generic runner cannot carry a per-project literal at all, so the register
is the single source by construction.

**Why the wind showcase script is not simply deleted.** Its output is byte-identity gated and it
does more than this - cost-QRA sections, narrative, disclosure blocks. This is the headline path
only, which is what a golden needs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_integrated_for_project(
    project: str, *, n_iter: int, seed: int,
) -> dict[str, Any]:
    """Return the integrated cost-plus-schedule headline for ``project``.

    The joint per-iteration total: one severity uniform per dual-coded risk shared across the cost
    arm and the Stage-3 CPM schedule arm, so the result reflects the joint distribution rather
    than the sum of two marginals.
    """
    from src.am.project_binding import resolve_project_inputs
    from src.integrated.integrated_simulation_stage3 import (
        run_integrated_simulation_stage3,
    )
    from src.integrated.stage3_config import (
        build_stage3_config,
        build_stage3_rules_from_scope,
    )
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.integrated.stage3_inputs import (
        Stage3BindingConfig,
        resolve_float_threshold_hours,
    )
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.schedule_cross_check import read_register_day_rate
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    inputs = resolve_project_inputs(project)
    register, xer, strawman = (
        inputs.register_path, inputs.xer_path, inputs.strawman_path,
    )

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

    s3_cfg = build_stage3_config(
        register_path=register,
        xer_path=xer,
        strawman_path=strawman,
        project=project,
        iterations=n_iter,
        seed=seed,
        caller_module="scripts/run_project_showcase.py",
    )
    res = run_integrated_simulation_stage3(
        s3_cfg,
        risks=risks,
        risk_scope_df=risk_scope,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
    )

    cost = np.asarray(res.cost_result["cost_dollars_array"], dtype=float)
    sched_days = np.asarray(res.schedule_days_array, dtype=float)
    day_rate = read_register_day_rate(register)
    integrated = cost + sched_days * day_rate

    return {
        "project": project,
        "integrated": integrated,
        "cost": cost,
        "schedule_days": sched_days,
        "day_rate": day_rate,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", help="registry key, e.g. synthetic_road")
    parser.add_argument("--iterations", type=int, default=50_000)
    parser.add_argument("--seed", type=int, required=True,
                        help="the seed to run at; a golden passes its registry row's")
    args = parser.parse_args(argv)

    out = run_integrated_for_project(
        args.project, n_iter=args.iterations, seed=args.seed,
    )
    arr = out["integrated"]
    print(f"{out['project']}: n={arr.size:,} day_rate=${out['day_rate']:,.0f}")
    for p in (50, 80, 90):
        print(f"  P{p}: ${np.percentile(arr, p):,.0f}")
    print(f"  mean: ${arr.mean():,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
