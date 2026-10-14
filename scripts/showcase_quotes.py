"""SHOWCASESYNC-01: every figure the showcase summary quotes is bound to a named value of one run.

The summary qmd is prose a person writes, but its figures are not typed. Each one is a pandoc
bracketed span naming the run value it shows and how it is formatted:

    [$5.42M]{.run v="cost.p80" f="M"}

``scripts/run_wind_showcase.py --publish`` writes the run's values to
``docs/showcase/run/wind_quoted_values.json`` and rewrites every span's text from them, so a re-cut
cannot leave a figure behind. ``tests/test_showcase_sync.py`` holds the committed qmd to the
committed values, so a hand edit, or a re-cut that skipped the qmd, reds CI.

A figure that is merely found somewhere in the number files proves nothing (the 14/10 qmd quoted
$3.97M as the P50, and $3.97M is in the files - as the mean). So the binding is by name, and
:func:`unbound` refuses any figure-shaped text left outside a span.
"""
from __future__ import annotations

import re
from typing import Callable

#: How a value is shown. One formatter per code, shared by the writer and the test.
FORMATS: dict[str, Callable[[object], str]] = {
    "M": lambda x: f"${float(x) / 1e6:.2f}M",       # dollars, as $ millions to 2 dp
    "M0": lambda x: f"${float(x) / 1e6:.0f}M",      # dollars, as whole $ millions
    "M1": lambda x: f"${float(x) / 1e6:.1f}M",      # dollars, as $ millions to 1 dp
    "k": lambda x: f"${float(x) / 1e3:.0f}k",       # dollars, as whole $ thousands
    "pct": lambda x: f"{float(x):.1%}",             # a fraction, as a percentage to 1 dp
    "pct0": lambda x: f"{float(x):.0%}",            # a fraction, as a whole percentage
    "d0": lambda x: f"{float(x):.0f}",              # a count of days, whole
    "d1": lambda x: f"{float(x):.1f}",              # a count of days, to 1 dp
    "int": lambda x: f"{int(x)}",
    "s": lambda x: str(x),                          # text: a risk id, a description, a date
}

#: ``[text]{.run v="key" f="fmt"}``. The text may not contain a bracket.
SPAN = re.compile(r'\[([^\[\]]*)\]\{\.run v="([^"]+)" f="([^"]+)"\}')

#: Figure-shaped text that must not appear outside a span: a dollar amount, a percentage, a
#: decimal, a count of working days, and an activity count.
FIGURE = re.compile(r"\$\d|\d%|\d\.\d|\d+ working days|\d+-activity")

#: The front matter's ``date:`` line, which is the run's date.
DATE_LINE = re.compile(r"^date: .*$", re.MULTILINE)


def render(values: dict, key: str, fmt: str) -> str:
    if key not in values:
        raise KeyError(f"the qmd quotes {key!r}, which the run does not record")
    if fmt not in FORMATS:
        raise KeyError(f"the qmd formats {key!r} as {fmt!r}, which is not a format")
    return FORMATS[fmt](values[key])


def spans(text: str) -> list[tuple[str, str, str]]:
    """Every bound figure, as (text shown, value key, format)."""
    return SPAN.findall(text)


def mismatches(text: str, values: dict) -> list[str]:
    """Every span whose text is not its value, rendered. Empty is in sync."""
    out = []
    for shown, key, fmt in spans(text):
        try:
            want = render(values, key, fmt)
        except KeyError as exc:
            out.append(str(exc))
            continue
        if shown != want:
            out.append(f"{key}: the qmd shows {shown!r}, the run says {want!r}")
    return out


def unbound(text: str) -> list[str]:
    """Every figure-shaped line outside a span and outside the comment block. Empty is bound."""
    # The comment is blanked line for line, so the line numbers reported are the file's own.
    body = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    out = []
    for n, line in enumerate(body.splitlines(), 1):
        if line.startswith("date: "):
            continue  # the run date, held by its own check
        stripped = SPAN.sub("", line)
        if FIGURE.search(stripped):
            out.append(f"line {n}: {line.strip()[:100]}")
    return out


def fill(text: str, values: dict, run_date: str) -> str:
    """The qmd with every span's text, and the front matter date, rewritten from the run."""
    text = SPAN.sub(lambda m: f'[{render(values, m.group(2), m.group(3))}]'
                              f'{{.run v="{m.group(2)}" f="{m.group(3)}"}}', text)
    text, n = DATE_LINE.subn(f"date: {run_date}", text, count=1)
    if n != 1:
        raise ValueError("the qmd has no front matter date: line to stamp")
    return text
