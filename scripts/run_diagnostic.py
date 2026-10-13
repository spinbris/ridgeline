"""Render a run's one-page diagnostic from its state cache.

Replaces ``scripts/sr9_diagnostic.py``, which wrote this artefact in this format and had
drifted from every contract it depended on: it named ``RUN_FINAL.bat`` as its caller and
``RUN_FINAL.bat`` did not invoke it; it read ``outputs/runs/<date>{_PROD}`` while the
deliverable writes ``outputs/runs/<date>_<project>``; it globbed for the HTML of three
standalone drivers since retired; it named ``sra_executive_summary_<date>.docx`` where
the deliverable writes ``executive_summary_<date>.docx``; and it had no Stage 3
awareness at all, so it printed the Stage 2.5 comparator as the headline. Its
re-execution fallback ran ``DUMMY_REALISTIC_MODE_OVERRIDE``, a Stage 2.5 Mode scenario.

**A normal run does not need this script.** ``src.final.deliverable`` writes
``run_diagnostic_<date>.txt`` beside the provenance on every run, pass or fail, from the
state it already holds. This is for re-rendering an earlier run's diagnostic from its
cache - after the file is deleted, or when the formatter changes and an old run wants
re-reading.

There is no re-execution fallback. The old one silently ran a superseded engine set when
the cache was missing, so a missing cache produced a plausible page of wrong numbers. A
missing cache now says so and exits non-zero.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.final.run_diagnostic import format_run_diagnostic  # noqa: E402
from src.final.state_cache import read_state_cache  # noqa: E402


def cache_dir_for(output_dir: Path, run_date: str, project: str) -> Path:
    """Where ``src.final.deliverable.write_artefacts`` puts a run's state cache.

    One construction, shared by intent with the deliverable's. The predecessor computed
    a *different* path and fell through to re-execution when it missed - a cache-path
    divergence that presented as a slow run rather than as an error.
    """
    return output_dir / "runs" / f"{run_date}_{project}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Re-render a run's one-page diagnostic from its state cache.")
    p.add_argument(
        "--project", required=True,
        help="Project key the run was executed for, e.g. synthetic_wind.")
    p.add_argument(
        "--run-date", default=date.today().isoformat(),
        help="Run date the cache is filed under (YYYY-MM-DD). Defaults to today.")
    p.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "outputs",
        help="Deliverable output directory. Defaults to ./outputs.")
    p.add_argument(
        "--out", type=Path, default=None,
        help="Write here instead of stdout.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache = cache_dir_for(args.output_dir, args.run_date, args.project)
    if not cache.is_dir():
        print(
            f"No state cache at {cache}.\n"
            f"This script re-renders an existing run; it does not re-run the engines. "
            f"Check --project and --run-date, or run the deliverable, which writes "
            f"run_diagnostic_{args.run_date}.txt itself.",
            file=sys.stderr,
        )
        return 2

    state = read_state_cache(cache)
    manifest = cache / "provenance.json"
    provenance: dict = {}
    if manifest.is_file():
        import json
        provenance = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        # The cache carries enough to identify the run even when the manifest is gone.
        provenance = {
            "project": state.get("project", args.project),
            "run_date": state.get("run_date", args.run_date),
            "artefacts": [],
        }

    text = format_run_diagnostic(
        composed=state["composed"],
        cross_validation=state.get("cv_result", {}),
        provenance=provenance,
    )
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
