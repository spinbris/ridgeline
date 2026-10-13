"""PROCDIET-01 output pack: the audit lane's headline diff, and the artefacts the Director audits.

Three parts, each against the last approved baseline it already has, at that baseline's own
recorded seed and iteration count (SEEDZERO-01 P4):

1. Every public golden (``tests/golden/projects.toml``) rerun through the golden harness and
   compared exactly with its committed manifest: P50, P80, P90 and mean.
2. The wind period run at the period golden's parameters, compared with the committed period
   golden: the schedule P-levels and days behind plan, the integrated dollar P-levels, and then
   every number through ``scripts/ws4a_repro_gate.py``, which masks provenance only.
3. ``run_deliverable`` for every shipped binding at the golden seed and a small n. Its
   cross-validation verdict is reported, and its artefacts are what CI uploads.

Provenance (``engine_sha``, branch, input digests) is never compared here: a headline that did
not move is not a finding (brief §1 item 4).

Writes ``<out>/headline_diff.md`` (the PR summary) and ``<out>/headline_diff.json``. Exit 0 when
nothing moved and both deliverables pass cross-validation, 1 otherwise.

Usage:
    python scripts/output_pack.py [--out outputs/pack] [--deliverable-iterations 2000]
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.golden import golden_harness as gh  # noqa: E402
from tests.test_7a_period_json_golden import GOLDEN, GOLDEN_RUN, WORKBOOK  # noqa: E402

#: The period golden's headline figures shown in the summary; the repro gate checks every other.
PERIOD_KEYS = {
    "headline": ("p50_finish", "p80_finish", "p90_finish",
                 "p50_days_behind_plan", "p80_days_behind_plan", "p90_days_behind_plan"),
    "integrated": ("p50_dollars", "p80_dollars", "p90_dollars", "mean_dollars"),
}

#: One deliverable per shipped binding, on its committed fixture.
DELIVERABLES = {
    "synthetic_wind": ("tests/fixtures/synthetic_wind/wind_register.xlsx",
                       "tests/fixtures/synthetic_wind/wind_schedule.xer"),
    "synthetic_road": ("tests/fixtures/synthetic_road/road_register.xlsx",
                       "tests/fixtures/synthetic_road/road_schedule.xer"),
}


def deliverable_seed(project: str) -> int:
    """The seed a project's deliverable runs at here: its golden registry row's (SEEDZERO-01 P4),
    so the pack's seed is data, matched by the register the row hashes."""
    register = DELIVERABLES[project][0]
    rows = [row for row in gh.load_registry().values() if register in row.inputs]
    if len(rows) != 1:
        raise SystemExit(f"output pack: {project}'s register {register} is in {len(rows)} golden "
                         f"registry rows, not one, so its seed has no single source.")
    return rows[0].seed


def golden_rows() -> list[dict]:
    """Every committed manifest, rerun. Driven by the manifests on disk, not the registry's
    confidential flag, so flipping that flag cannot drop a public golden from the pack; and a
    public registry row with no committed manifest, or no manifest at all, stops the pack."""
    committed = sorted((gh.REPO_ROOT / "tests" / "golden" / "manifests").glob("*/*.json"))
    covered = {(m["project"], m["scenario"]) for m in map(gh.load_manifest, committed)}
    public = {(p, s) for p, s, confidential in gh.iter_project_scenarios() if not confidential}
    if not committed or public - covered:
        raise SystemExit(f"output pack: golden coverage is short. Committed manifests: "
                         f"{sorted(covered)}; public registry rows without one: "
                         f"{sorted(public - covered)}")
    rows = []
    for path in committed:
        manifest = gh.load_manifest(path)
        project, scenario = manifest["project"], manifest["scenario"]
        stats = gh.run(project, manifest["seed"], manifest["n_iterations"])
        want = gh.headline_floats(manifest)
        for key in gh.HEADLINE_KEYS:
            rows.append({"source": f"golden {project}::{scenario}", "figure": key,
                         "seed": manifest["seed"], "n": manifest["n_iterations"],
                         "baseline": want[key], "current": stats[key],
                         "moved": stats[key] != want[key]})
    return rows


def period_rows(out: Path) -> tuple[list[dict], bool]:
    from src.am.run_period import run_period

    baseline = json.loads(GOLDEN.read_bytes().decode("utf-8"))
    candidate_path = run_period(workbook_path=WORKBOOK, output_dir=out / "period",
                                allow_dirty=True, **GOLDEN_RUN)
    candidate = json.loads(Path(candidate_path).read_bytes().decode("utf-8"))
    rows = []
    for block, keys in PERIOD_KEYS.items():
        for key in keys:
            want, got = baseline[block][key], candidate[block][key]
            rows.append({"source": "period golden (wind)", "figure": f"{block}.{key}",
                         "seed": GOLDEN_RUN["seed"], "n": GOLDEN_RUN["main_iterations"],
                         "baseline": want, "current": got, "moved": got != want})

    spec = importlib.util.spec_from_file_location("ws4a_repro_gate",
                                                  REPO / "scripts" / "ws4a_repro_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = gate.main(["ws4a_repro_gate.py", str(GOLDEN), str(candidate_path)])
    return rows, rc == 0


def run_deliverables(out: Path, iterations: int) -> list[dict]:
    import importlib

    from src.final.deliverable import run_deliverable

    results = []
    saved = os.environ.get("QRA_PROJECT")
    try:
        for project, (register, xer) in DELIVERABLES.items():
            importlib.import_module(f"src.sra.cpm.bindings.{project}")
            os.environ["QRA_PROJECT"] = project
            env = {**os.environ, "REGISTER_FILE": register, "STRAWMAN_FILE": register,
                   "P6_FILE": xer, "SR9_ITERATIONS": str(iterations),
                   "SR9_SEED": str(deliverable_seed(project))}
            run = run_deliverable(env=env, output_dir=out / project)
            results.append({"project": project, "all_pass": run.all_pass,
                            "artefacts": [Path(a).relative_to(out).as_posix()
                                          for a in run.artefacts
                                          if Path(a).is_relative_to(out)]})
    finally:
        if saved is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = saved
    return results


def render(rows: list[dict], period_ok: bool, deliverables: list[dict]) -> str:
    moved = [r for r in rows if r["moved"]]
    lines = ["## Headline diff against the last approved baseline", ""]
    lines.append("**No headline moved.**" if not moved and period_ok
                 else "**A HEADLINE MOVED.** This change is Track N whatever its path.")
    lines += ["", "| Source | Figure | Seed | n | Baseline | Current | |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['source']} | {r['figure']} | {r['seed']} | {r['n']} | "
                     f"{r['baseline']} | {r['current']} | {'MOVED' if r['moved'] else 'same'} |")
    lines += ["", f"Period golden, every number under the provenance mask: "
                  f"**{'identical' if period_ok else 'MOVED'}**.", "",
              "## Deliverables (cross-validation)", ""]
    for d in deliverables:
        lines.append(f"- {d['project']}: **{'PASS' if d['all_pass'] else 'FAIL'}**, "
                     f"{len(d['artefacts'])} artefacts")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO / "outputs" / "pack")
    ap.add_argument("--deliverable-iterations", type=int, default=2000)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows = golden_rows()
    p_rows, period_ok = period_rows(out)
    rows += p_rows
    deliverables = run_deliverables(out, args.deliverable_iterations)

    moved = any(r["moved"] for r in rows) or not period_ok
    failed = [d["project"] for d in deliverables if not d["all_pass"]]
    (out / "headline_diff.json").write_bytes(json.dumps(
        {"headline_moved": moved, "period_identical": period_ok,
         "cross_validation_failed": failed, "rows": rows, "deliverables": deliverables},
        indent=2).encode("utf-8"))
    summary = render(rows, period_ok, deliverables)
    (out / "headline_diff.md").write_bytes(summary.encode("utf-8"))
    print(summary)
    return 1 if moved or failed else 0


if __name__ == "__main__":
    sys.exit(main())
