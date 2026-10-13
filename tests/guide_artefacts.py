"""The guide's §7 artefact table against the files a run writes (REPORTDOC-01 P-5).

The guide tripwire checked that what the guide **names** exists. Nothing checked that what the
product **writes** is named, so REPORT01 added two files to every run and v2.0 of the guide went
on saying there was "no diagnostic text file". This compares the two sets in both directions.

The evidence of what is written is a run's own output directory - never a list kept in a test,
which would be a third copy of the artefact set, free to drift from both of the others.

Placeholders are typed, not wildcards. ``<date>`` is a date, so the P80 executive summary's row
cannot be satisfied by the MEAN file beside it; a file that two rows both match is reported too,
because a table that cannot tell two artefacts apart is not naming either of them.

**A row can be conditional on the headline setting**, and says so in its own description:
``--headline P80``, ``--headline Mean`` and ``both`` in backticks. The review of 13/09/2026 found
the P80 row stated unconditionally while a Mean-only run does not write it, and a check that only
ever ran under ``both`` could not see it. A row's conditions are read from the row, so the table
stays the one statement of them.

**A row the parser cannot read fails**, rather than dropping out of the comparison: a row that
silently leaves the table and whose artefact also stops being written would go quiet in both
directions at once.

One row is not written by the deliverable at all: the HTML, which ``RUN_FINAL.bat``'s notebook
conversion produces. It is excluded from the run comparison by deriving it from the batch file,
not by listing it, so the exclusion is checked rather than asserted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADING = "## 7. What a run produces"
ROOT = "outputs\\"

#: The values ``FINAL_REPORT_HEADLINE_METRIC`` takes, as the guide spells them in a row.
HEADLINE_SETTINGS = ("P80", "Mean", "both")

_ROW = re.compile(r"^\|\s*`(outputs\\[^`]+)`\s*\|(.*)\|\s*$")
_HEADLINE_FLAG = re.compile(r"`--headline (P80|Mean)`")

#: ``<date>`` is ISO; a key is a binding key or project name; a variant is one strawman token.
_PLACEHOLDERS = {
    "date": r"\d{4}-\d{2}-\d{2}",
    "project": r"[A-Za-z0-9_]+",
    "binding key": r"[A-Za-z0-9_]+",
    "variant": r"[A-Za-z0-9]+",
}
_ANY_PLACEHOLDER = re.compile(r"<([^>]+)>")


@dataclass(frozen=True)
class Row:
    path: str
    headline: frozenset[str]  # empty: written under every headline setting

    def applies(self, setting: str) -> bool:
        return not self.headline or setting in self.headline


def artefact_rows(guide: str) -> list[Row]:
    """Each data row of §7's first table. Raises on a row it cannot read."""
    start = guide.index(HEADING)
    table: list[str] = []
    for line in guide[start:].splitlines()[1:]:
        if line.startswith("|"):
            table.append(line)
        elif table:
            break  # the first table only; §7's second table compares documents, not files
        elif line.startswith("#"):
            break
    rows: list[Row] = []
    for line in table[2:]:  # past the header and its separator
        m = _ROW.match(line)
        if not m:
            raise ValueError(f"§7 has a row the artefact check cannot read: {line[:120]}")
        description = m.group(2)
        conditions = set(_HEADLINE_FLAG.findall(description))
        if conditions and "`both`" in description:
            conditions.add("both")
        rows.append(Row(m.group(1), frozenset(conditions)))
    return rows


def pattern(row: str) -> re.Pattern[str]:
    """A row's path as a regex over a path relative to the output directory, ``/``-separated."""
    body = row[len(ROOT):].replace("\\", "/")
    out, pos = [], 0
    for m in _ANY_PLACEHOLDER.finditer(body):
        out.append(re.escape(body[pos:m.start()]))
        out.append(_PLACEHOLDERS.get(m.group(1), r"[^/]+"))
        pos = m.end()
    out.append(re.escape(body[pos:]))
    return re.compile("".join(out))


def html_row_from_runner(bat: str) -> str:
    """``RUN_FINAL.bat``'s ``REPORT_HTML``, in the guide's placeholder spelling."""
    m = re.search(r"^set REPORT_HTML=(.+?)\s*$", bat, re.M)
    if not m:
        raise ValueError("RUN_FINAL.bat no longer sets REPORT_HTML")
    return m.group(1).replace("%QRA_PROJECT%", "<project>").replace("%TODAY%", "<date>")


def written_files(output_dir: Path) -> list[str]:
    return sorted(p.relative_to(output_dir).as_posix() for p in output_dir.rglob("*") if p.is_file())


def disagreement(rows: list[Row], files: list[str], not_written_by_run: set[str],
                 headline: str) -> dict[str, list[str]]:
    """Under one headline setting: ``unnamed``, written and matched by no row; ``unwritten``, a
    row that applies and no file matches; ``ambiguous``, a file more than one row matches."""
    if headline not in HEADLINE_SETTINGS:
        raise ValueError(f"headline setting {headline!r} is not one of {HEADLINE_SETTINGS}")
    compiled = {r.path: pattern(r.path) for r in rows
                if r.path not in not_written_by_run and r.applies(headline)}
    unnamed, ambiguous = [], []
    matched: set[str] = set()
    for f in files:
        hits = [path for path, rx in compiled.items() if rx.fullmatch(f)]
        if not hits:
            unnamed.append(f)
        elif len(hits) > 1:
            ambiguous.append(f"{f} <- {hits}")
        matched.update(hits)
    unwritten = [path for path in compiled if path not in matched]
    return {"unnamed": unnamed, "unwritten": unwritten, "ambiguous": ambiguous}
