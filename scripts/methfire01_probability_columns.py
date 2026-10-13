"""METHFIRE-01 evidence: is `Probability (Time)` equal to `Probability` on every Time Impact = Yes row?

SPEC R-10 (17/09/2026) retired `Probability (Time)` as a firing probability on the condition
that it carries no information `Probability` does not. This script is that condition, re-runnable.

Each register is read twice: raw from the `Risk Register` sheet (cached values, and whether the
column holds formulas), and through the engine's own reader (`strawman_reader.read_risk_scope`),
because the engine fires on what the reader returns, not on the sheet.

Exit 0 only if every Time Impact = Yes row agrees on both reads AND at least one such row was
compared in every register - an empty comparison is not a pass. Exit 1 otherwise.

    .venv\\Scripts\\python.exe scripts\\methfire01_probability_columns.py
    .venv\\Scripts\\python.exe scripts\\methfire01_probability_columns.py synthetic_road=path\\to\\register.xlsx
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: The shipped registers, each with the binding its reader needs.
SHIPPED = (
    ("synthetic_road", "tests/fixtures/synthetic_road/road_register.xlsx"),
    ("synthetic_wind", "tests/fixtures/synthetic_wind/wind_register.xlsx"),
    ("synthetic_wind", "tests/golden/wind_register_polished.xlsx"),
)


def _norm(v) -> str:
    return str(v).strip() if v is not None else ""


def _raw_rows(path: Path, *, data_only: bool) -> list[dict[str, object]]:
    wb = openpyxl.load_workbook(path, data_only=data_only, read_only=True)
    try:
        rows = list(wb["Risk Register"].iter_rows(values_only=True))
    finally:
        wb.close()
    hi = next(i for i, r in enumerate(rows) if r and "Probability (Time)" in [_norm(c) for c in r])
    header = [_norm(c) for c in rows[hi]]
    out = []
    for r in rows[hi + 1:]:
        row = dict(zip(header, r))
        if _norm(row.get("Risk ID")):
            out.append(row)
    return out


def check(project: str, register: Path) -> bool:
    raw = _raw_rows(register, data_only=True)
    formulas = sum(1 for r in _raw_rows(register, data_only=False)
                   if isinstance(r.get("Probability (Time)"), str) and r["Probability (Time)"].startswith("="))
    prob = {_norm(r["Risk ID"]): r["Probability"] for r in raw}
    time_yes = [r for r in raw if _norm(r.get("Time Impact")).lower() == "yes"]
    raw_diff = [(_norm(r["Risk ID"]), r["Probability"], r["Probability (Time)"])
                for r in time_yes if r["Probability"] != r["Probability (Time)"]]

    os.environ["QRA_PROJECT"] = project
    from src.sra import strawman_reader
    # Since METHFIRE-01 the reader itself refuses an unequal row (SPEC R-10), so on such a
    # register the engine limb's evidence is the refusal, reported here rather than raised.
    try:
        scope = strawman_reader.read_risk_scope(str(register))
        refused = ""
    except ValueError as exc:
        scope, refused = None, str(exc)
    if scope is None:
        scope_yes, engine_diff = [], []
    else:
        scope_yes = scope[scope["time_impact"].astype(str).str.strip() == "Yes"]
        engine_diff = [(rid, prob.get(rid), float(pt))
                       for rid, pt in zip(scope_yes["risk_id"], scope_yes["probability_time"])
                       if prob.get(rid) is None or float(prob[rid]) != float(pt)]

    compared = len(time_yes) > 0 and len(scope_yes) > 0
    ok = compared and not raw_diff and not engine_diff and not refused
    shown = register.relative_to(REPO).as_posix() if register.is_relative_to(REPO) else register.name
    print(f"{'PASS' if ok else 'FAIL'}  {shown}  (binding {project})")
    print(f"      rows {len(raw)}; Time Impact = Yes: raw {len(time_yes)}, engine reader {len(scope_yes)}; "
          f"formulas in Probability (Time): {formulas}")
    if refused:
        print(f"      engine reader refused the register: {refused[:300]}")
    elif not compared:
        print("      no Time Impact = Yes row compared - an empty comparison is not a pass")
    for rid, p, pt in raw_diff:
        print(f"      raw differs:    {rid}  Probability={p!r}  Probability (Time)={pt!r}")
    for rid, p, pt in engine_diff:
        print(f"      engine differs: {rid}  Probability={p!r}  probability_time={pt!r}")
    return ok


def main(argv: list[str]) -> int:
    targets = ([tuple(a.split("=", 1)) for a in argv] if argv else list(SHIPPED))
    results = [check(project, (REPO / path) if not Path(path).is_absolute() else Path(path))
               for project, path in targets]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
