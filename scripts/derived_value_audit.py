"""Derived-value audit. CONSOLIDATE-01 step 2.

THE PROPERTY
    No figure in the tracked tree is computable from a confidential figure by
    arithmetic the product itself performs.

WHY THIS EXISTS AND WHY IT IS NOT A LIST
    RS-A shipped a derived figure: 5% of a contract total, printed four lines
    from the 5% rate that produced it, so the total came back by one division.
    It was found because a test happened to fail on it, not because anything
    looked. The gate's VALUE limb is exact-match on the enumerated figures, and
    arithmetic on those figures escapes it completely.

    client_gate.py now generates simple fractions of each figure. That closes the
    multiplicative sub-class only. This audit covers the operations the ENGINE
    actually performs, which is a wider and differently-shaped set:

      - fractions and percentage points of a contract total   (cap, share, band)
      - a rate multiplied by a duration                        (dollarised days)
      - sums and differences between confidential figures      (residuals)

    Anything it finds is scrubbed and its generator folded into the gate, so the
    class stays closed rather than being closed once.

WHY ROUND PRODUCTS ARE DROPPED
    A derived value ending in many zeros is ordinary arithmetic and appears
    everywhere. Keeping them would make the audit fire on every file and be
    switched off, which is how a check dies.

    python scripts/derived_value_audit.py [--root .] [--terms terms.local.txt]

Exit 0 = clean, 1 = a derived figure is present. Hits name a LABEL and the
operation that produced it, never the figure itself: this output must be safe to
paste into a record.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}
TEXT_EXT = {".py", ".md", ".txt", ".toml", ".json", ".yml", ".yaml", ".bat", ".cfg",
            ".ini", ".bas", ".ipynb", ".csv", ".in", ""}

#: Fractions and percentage points a contract actually uses.
FRACTIONS = (0.01, 0.02, 0.025, 0.05, 0.075, 0.1, 0.125, 0.15, 0.2, 0.25,
             0.3, 0.333, 0.4, 0.5, 0.6, 0.667, 0.75, 0.8, 0.9, 1.25, 1.5, 2.0, 3.0)

#: Programme durations the day rate is multiplied by. Working days and weeks.
DURATIONS = (1, 5, 7, 10, 20, 21, 30, 50, 60, 90, 100, 120, 180, 200,
             250, 260, 300, 365, 400, 500, 502, 600, 750, 1000)


def load_figures(terms: Path) -> list[float]:
    out = []
    for line in terms.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("num:"):
            out.append(float(line[4:].strip().replace(",", "").replace("_", "")))
    return out


def too_round(n: int) -> bool:
    """Ordinary arithmetic, not a derived confidential figure."""
    return str(abs(n)).endswith("0000") or abs(n) < 1000


def derived_set(figs: list[float]) -> dict[str, str]:
    """{numeric string: operation that produced it}. Operation, never the source."""
    out: dict[str, str] = {}

    def add(v: float, how: str) -> None:
        if v != int(v):
            return
        n = int(v)
        if too_round(n):
            return
        for form in (str(n), f"{n:,}", f"{n:,}".replace(",", "_")):
            out.setdefault(form, how)

    for i, f in enumerate(figs):
        for fr in FRACTIONS:
            add(f * fr, f"figure[{i}] x {fr}")
        for d in DURATIONS:
            add(f * d, f"figure[{i}] x {d} periods")
    for i, a in enumerate(figs):
        for j, b in enumerate(figs):
            if i >= j:
                continue
            add(a + b, f"figure[{i}] + figure[{j}]")
            add(abs(a - b), f"figure[{i}] - figure[{j}]")
    return out


def load_allow(root: Path) -> set[str]:
    p = root / "gate_allow.txt"  # link-rule: the derived-value audit reads the gate's allowlist when present
    allow = {"gate_allow.txt"}  # link-rule: the derived-value audit does not scan the gate's allowlist itself
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                allow.add(line)
    return allow


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--terms", default=os.environ.get("CLIENT_GATE_TERMS", "terms.local.txt"))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    terms_path = Path(args.terms).resolve()
    figs = load_figures(terms_path)
    derived = derived_set(figs)
    allow = load_allow(root)

    print(f"derived-value audit | root {root}")
    print(f"confidential figures loaded : {len(figs)}")
    print(f"derived forms generated     : {len(derived)}")
    print("(the forms themselves are not printed; hits name the operation)\n")

    scanned, hits = 0, []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() not in TEXT_EXT or p.resolve() == terms_path:
                continue
            rel = p.relative_to(root).as_posix()
            if rel in allow:
                continue
            scanned += 1
            try:
                s = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for form, how in derived.items():
                if form in s:
                    hits.append((rel, how))

    print(f"files scanned : {scanned}")
    print(f"hits          : {len(hits)}")
    if scanned == 0:
        print("RED: scanned zero files")
        return 1
    for rel, how in sorted(set(hits)):
        print(f"  {rel}  <- {how}")
    print("\nAUDIT:", "RED" if hits else "CLEAN")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
