"""REPORTCOH-01: checks a rendered report's words against its own numbers and sections.

The report drifted because each method change added text and none retired the old: the
Stage 2.5 Mode basis left a comparator table, an empty appendix and "n/a" columns behind
after Stage 3 replaced it, and fixed sentences went on claiming agreements the tables beside
them no longer showed. Review section 10 asked for three mechanical guards, and this module
holds them so the tests and the release read-through run the same code:

1. **Retired terms.** Words that belong only to a retired basis must not reach the reader.
2. **Claims follow numbers.** Every days-to-dollars sentence must multiply out.
3. **No orphan references.** Every "the X appendix" / "under X in the appendices" must name
   a heading or label the page carries.

Pure functions over text (hard invariant 9). Run against a rendered page with
``python -m src.final.report_guard <report.html>``; exit 1 lists each problem.
"""

from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

#: Terms that belong only to the retired Stage 2.5 Mode-scenario basis, or to text the review
#: found false, matched case-insensitively. A phrase, not a bare word: "Series, Hybrid and
#: Parallel" is the register's own field and may be named, so bare "Series" is not here.
RETIRED_TERMS: tuple[str, ...] = (
    r"stage 2\.5",
    r"\bstage 3\b",
    r"\bdp review\b",
    r"\ball series\b",
    r"counterfactual",
    r"comparator",
    r"mode[- ]scaled",
    r"mode[- ]multiplied",
    r"mode[- ]scenario",
    r"mode[- ]classification",
    r"mode assumptions",
    r"additive draws",
    r"within mc noise",
    r"bracket the mc result",
    r"wind farm beta",
    r"strawman",
    r"workshop input",
    r"(?<![\w/])n/a(?![\w/])",
    r"\bnan\b",
)

_DAYS_TO_DOLLARS = re.compile(
    r"(?P<days>\d[\d,]*(?:\.\d+)?) (?:working )?days?\b[^.]*?"
    r"\$(?P<dollars>\d[\d,]*(?:\.\d+)?)M[^.]*?"
    r"\$(?P<rate>\d[\d,]*(?:\.\d+)?) per working day",
    re.IGNORECASE,
)

_REFERENCE = re.compile(
    r"\b(?:in|to|see) the (?P<a>[A-Za-z][A-Za-z -]{1,40}?) appendix\b"
    r"|\bunder (?P<b>[A-Z][A-Za-z -]{1,40}?) in the appendices\b"
)


def page_text(html_source: str) -> str:
    """Reader-visible text of a rendered page, one block per line; scripts and styles dropped."""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_source, flags=re.S | re.I)
    s = re.sub(r"<img[^>]*>", "\n", s)
    s = re.sub(r"</(p|h\d|tr|li|div|th|td|strong|b|caption)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s).replace("¶", "")
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines())
    return "\n".join(ln for ln in lines if ln)


def retired_terms(text: str) -> list[str]:
    """Each retired term the text still carries, with the line it sits on."""
    out: list[str] = []
    for line in text.splitlines():
        for pat in RETIRED_TERMS:
            if re.search(pat, line, re.IGNORECASE):
                out.append(f"retired term /{pat}/: {line[:160]}")
    return out


def _f(num: str) -> float:
    return float(num.replace(",", ""))


def unpriced_days(text: str, tol_m: float = 0.006) -> list[str]:
    """Each "N days ... $XM ... at $R per working day" sentence whose arithmetic fails.

    ``tol_m`` allows for the days and dollars each being rounded for display.
    """
    out: list[str] = []
    for m in _DAYS_TO_DOLLARS.finditer(text):
        days, dollars, rate = _f(m["days"]), _f(m["dollars"]), _f(m["rate"])
        implied = days * rate / 1e6
        # Days shown to 1 dp can carry 0.05 of rounding: allow its dollar value too.
        allow = tol_m + 0.05 * rate / 1e6
        if abs(implied - dollars) > allow:
            out.append(f"{days:g} days at ${rate:,.0f} is ${implied:.2f}M, not "
                       f"${dollars:.2f}M: {m.group(0)[:160]}")
    return out


def orphan_references(text: str) -> list[str]:
    """Each "the X appendix" whose X is not a heading or label line on the page."""
    lines = {ln.strip().lower() for ln in text.splitlines()}
    out: list[str] = []
    for m in _REFERENCE.finditer(text):
        name = (m["a"] or m["b"]).strip().lower()
        if name not in lines:
            out.append(f"reference to '{name}' has no heading or label on the page: "
                       f"{m.group(0)}")
    return out


def check_page(html_source: str) -> list[str]:
    """All three guards over one rendered page. Empty means it passes."""
    text = page_text(html_source)
    return retired_terms(text) + unpriced_days(text) + orphan_references(text)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m src.final.report_guard <report.html>")
        return 2
    problems = check_page(Path(argv[0]).read_text(encoding="utf-8"))
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s) in {argv[0]}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
