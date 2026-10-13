"""Bless (regenerate) golden-number manifests. Approval-gated.

The ONLY legitimate way a golden headline number moves.

    # diff mode (default): compute current vs blessed, print, change NOTHING,
    # exit non-zero if anything differs (or is unblessed). Safe to run anytime.
    python scripts/bless_goldens.py
    python scripts/bless_goldens.py --project wind_synth

    # approve mode: regenerate manifests. REQUIRES --reason and the approver's sign-off.
    python scripts/bless_goldens.py --approve --reason "initial baseline"
    python scripts/bless_goldens.py --approve --project refproject --reason "..."

Rules:
- Builder must NEVER run ``--approve`` unprompted, including to "fix" a red test.
- ``--approve`` writes to the committed ``manifests/`` tier for public projects
  and the gitignored ``local/`` tier for confidential projects - per the
  registry ``confidential`` flag, never a named code branch.
- Audit trail: PUBLIC movements are logged with numbers to
  ``tests/golden/CHANGELOG.md`` (committed). CONFIDENTIAL movements are logged
  with NO numbers to ``tests/golden/CHANGELOG.md`` and WITH numbers to the
  gitignored ``tests/golden/local/CHANGELOG.local.md``. Confidential percentiles
  never enter a committed file.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.golden import golden_harness as gh  # noqa: E402

_GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
_PUBLIC_CHANGELOG = REPO_ROOT / "tests" / "golden" / "CHANGELOG.md"
_LOCAL_CHANGELOG = _GOLDEN_DIR / "local" / "CHANGELOG.local.md"


def _m(v: float) -> str:
    return f"${v / 1e6:.3f}M"


def _selected_rows(project: str | None) -> dict[str, gh.ProjectRow]:
    rows = gh.load_registry()
    if project is None:
        return rows
    if project not in rows:
        raise SystemExit(
            f"error: project {project!r} not in registry (have: {sorted(rows)})"
        )
    return {project: rows[project]}


def _old_headline(mpath: Path) -> dict[str, float] | None:
    if not mpath.exists():
        return None
    return gh.headline_floats(gh.load_manifest(mpath))


# ---------------------------------------------------------------------------
# diff mode
# ---------------------------------------------------------------------------


def run_diff(rows: dict[str, gh.ProjectRow], n_iter: int) -> int:
    """Print current vs blessed for every selected project/scenario. Writes
    nothing. Exit non-zero if anything differs or is unblessed."""
    any_diff = False
    for row in rows.values():
        for scenario in row.scenarios:
            mpath = gh.manifest_path(row, scenario)
            old = _old_headline(mpath)
            print(f"\n=== {row.project}::{scenario} "
                  f"({'confidential->local' if row.confidential else 'public->committed'}) ===")
            print(f"    running adapter {row.adapter!r} @ seed {row.seed}, "
                  f"n={n_iter:,} ...")
            stats = gh.run(row.project, row.seed, n_iter)
            for k in gh.HEADLINE_KEYS:
                new = stats[k]
                if old is None:
                    any_diff = True
                    print(f"    {k:>4}: (unblessed) -> {_m(new)}  [{new.hex()}]")
                elif new != old[k]:
                    any_diff = True
                    print(f"    {k:>4}: {_m(old[k])} -> {_m(new)}  CHANGED "
                          f"[{old[k].hex()} -> {new.hex()}]")
                else:
                    print(f"    {k:>4}: {_m(new)}  (unchanged)")
    if any_diff:
        print("\nDIFF: goldens differ or are unblessed. This run changed "
              "NOTHING. To move the goldens, re-run with --approve --reason "
              "\"...\" and Director sign-off.")
        return 1
    print("\nOK: all selected goldens match the blessed manifests. Nothing to do.")
    return 0


# ---------------------------------------------------------------------------
# approve mode
# ---------------------------------------------------------------------------


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if path.exists() else _changelog_header(path)
    # newline="\n" for the same reason the manifest write below carries it, and found the same
    # way: this append left the changelog CRLF in the worktree under `eol=lf`, so every bless
    # dirtied a file it had only added a line to. The manifest writer was fixed and this one,
    # one function over, was not.
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(header + text)


def _changelog_header(path: Path) -> str:
    if path.name == "CHANGELOG.local.md":
        return ("# Golden movements - LOCAL (confidential)\n\n"
                "GITIGNORED. Confidential old->new headline numbers live here "
                "ONLY. Never commit this file.\n\n")
    return ("# Golden number movements\n\n"
            "Audit trail of blessed golden-headline movements. PUBLIC projects "
            "record numbers here; CONFIDENTIAL projects record a no-number line "
            "here and the numbers in the gitignored local/CHANGELOG.local.md.\n\n")


def _log_movement(
    row: gh.ProjectRow,
    scenario: str,
    old: dict[str, float] | None,
    new_stats: dict[str, float],
    reason: str,
    by: str,
    date: str,
) -> None:
    old_p80 = "(none)" if old is None else _m(old["p80"])
    new_p80 = _m(new_stats["p80"])
    if row.confidential:
        # committed: NO numbers.
        _append(
            _PUBLIC_CHANGELOG,
            f"- {date} {row.project}::{scenario} headline moved - reason: "
            f"{reason} (blessed by {by}; numbers in local/CHANGELOG.local.md)\n",
        )
        # gitignored: the actual numbers.
        detail = "  ".join(
            f"{k}: {'(none)' if old is None else _m(old[k])} -> {_m(new_stats[k])}"
            for k in gh.HEADLINE_KEYS
        )
        _append(
            _LOCAL_CHANGELOG,
            f"- {date} {row.project}::{scenario} - reason: {reason} "
            f"(by {by})\n    {detail}\n",
        )
    else:
        detail = "  ".join(
            f"{k}: {'(none)' if old is None else _m(old[k])} -> {_m(new_stats[k])}"
            for k in gh.HEADLINE_KEYS
        )
        _append(
            _PUBLIC_CHANGELOG,
            f"- {date} {row.project}::{scenario} P80 {old_p80} -> {new_p80} "
            f"- reason: {reason} (by {by})\n    {detail}\n",
        )


def run_approve(
    rows: dict[str, gh.ProjectRow], n_iter: int, reason: str, by: str, date: str,
) -> int:
    if not reason.strip():
        raise SystemExit("error: --approve requires a non-empty --reason")
    # One ref for the whole bless, taken BEFORE the first manifest is written. Read per
    # manifest instead, every project after the first is stamped -dirty by the sibling this
    # same loop just wrote, and the stamp names a tree that exists in no history - which is
    # what a second machine is later asked to reproduce against. Same reason `date` is owned
    # here rather than read in the harness.
    ref = gh.engine_ref()
    print(f"BLESS (approve): reason={reason!r} by={by} date={date} n={n_iter:,} ref={ref}")
    for row in rows.values():
        for scenario in row.scenarios:
            mpath = gh.manifest_path(row, scenario)
            old = _old_headline(mpath)
            print(f"  blessing {row.project}::{scenario} -> "
                  f"{mpath.relative_to(REPO_ROOT).as_posix()} ...")
            manifest = gh.build_manifest(
                row, scenario, n_iter=n_iter, reason=reason, by=by, date=date, ref=ref,
            )
            mpath.parent.mkdir(parents=True, exist_ok=True)
            # newline="\n" explicitly. The default translates to CRLF on Windows, and
            # `git ls-files --eol` must report no w/crlf (the line-ending rule). The
            # capture scripts fixed this for the fixtures they write and recorded that "these
            # two older scripts never did"; the bless writer is the one they missed, so every
            # bless left the manifest CRLF in the worktree while git stored LF.
            mpath.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
            new_stats = {k: gh.hex_to_float(manifest["headline"][k])
                         for k in gh.HEADLINE_KEYS}
            _log_movement(row, scenario, old, new_stats, reason, by, date)
            tier = "local (gitignored)" if row.confidential else "committed"
            print(f"    wrote manifest [{tier}]; movement logged.")
    print("\nBlessed. Review the manifest(s) and changelog before merge.")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bless / diff golden-number manifests.")
    ap.add_argument("--approve", action="store_true",
                    help="regenerate manifests (Director-gated; requires --reason). "
                         "Without this, runs in diff mode and changes nothing.")
    ap.add_argument("--reason", default="",
                    help="why the goldens move (required with --approve).")
    ap.add_argument("--project", default=None,
                    help="single project id (default: all registry rows).")
    ap.add_argument("--by", default="Steve", help="who approved the bless.")
    ap.add_argument("--n-iter", type=int, default=gh.GOLDEN_N_ITER,
                    help=f"iterations (default {gh.GOLDEN_N_ITER}).")
    args = ap.parse_args(argv)

    rows = _selected_rows(args.project)
    if not args.approve:
        return run_diff(rows, args.n_iter)
    # The harness never reads the wall clock; the CLI owns the timestamp.
    date = datetime.date.today().isoformat()
    return run_approve(rows, args.n_iter, args.reason, args.by, date)


if __name__ == "__main__":
    raise SystemExit(main())
