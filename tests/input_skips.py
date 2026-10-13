"""Skip reasons name the input, never the machine's path (TESTLANE-01 B, P-B7).

Measured at G0 on a fresh clone: 193 skips, 21 distinct reasons, **17 of them
carrying an absolute ``<drive>:\\Users\\<name>\\...`` path** and not one naming a register
row. Every one of those lines is published into a CI log, so the path is both the
least useful half of the message and the half that leaks a username.

A path answers "where did this machine look", which the reader already knows and
cannot act on. A label plus a register ID answers "which input, and what is the
standing decision about it", which is the thing a CI log is read for.

So the reason is built here, in one place, rather than formatted at 72 call sites:

    from tests.input_skips import skip_missing

    skip_missing(strawman_path)
    -> SKIPPED: SRA strawman workbook not available (GOLDCOLL-01)

The label comes from the registry below when the input is one the repo knows, and
from the file stem otherwise - an unknown input still gets a path-free reason
rather than falling back to the shape this module exists to remove.

``tests/test_input_skips_static.py`` is the close check: it greps for call sites
that format their own reason, so a new bare ``pytest.skip(f"...{path}")`` fails
naming itself rather than quietly reintroducing the class.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

#: Known inputs: (distinctive substring, label, register row or None).
#:
#: Ordered - the first match wins, so the more specific pattern precedes the more
#: general one (the `.xer` export before the full-report title, below). SNAPSHOTCUT-01 retired the
#: register and workbook entries with the last tests that read them (Director, 11/10/2026).
_KNOWN: tuple[tuple[str, str, str | None], ...] = (
    ("Longest Path", "P6 longest-path export", "GOLDCOLL-01"),
    # `.xer` precedes "Full Report" deliberately. The Stage-3 XER export is named
    # "...<issue status> - Full Report.xer", so the more general needle would
    # otherwise claim it and every _needs("xer") skip would point a CI-log reader at the
    # P6 spreadsheet instead. Extension before title: the extension is the stronger
    # evidence of which artefact this is.
    (".xer", "P6 .xer export", "GOLDCOLL-01"),
    ("Full Report", "P6 full-report export", "GOLDCOLL-01"),
    ("sr9_state_cache_v31_baseline.pkl", "v31 legacy state-cache pickle", None),
    ("runs/v31_baseline", "v31 parquet state-cache fixture", None),
    ("outputs/charts", "chart output directory", "CHARTSDEP-01"),
    # Notebooks. The repository split cut every *.ipynb by rule, so these are
    # absent in the product tree and present in the source one. Tests that read
    # them must skip rather than raise - RS-B step 3.
    ("final_runner.ipynb", "final runner notebook", "REPOSPLIT-01"),
    ("client_runner.ipynb", "client runner notebook", "REPOSPLIT-01"),
    ("client_appendices.ipynb", "client appendices notebook", "REPOSPLIT-01"),
    (".ipynb", "notebook", "REPOSPLIT-01"),
    # Documents that do not ship in the public snapshot (scripts/release/snapshot_manifest.py).
    # A test of a shipped surface that reads one of these among others skips it there.
    ("CLAUDE.md", "private agent operating manual", "SNAPSHOTCUT-01"),  # link-rule: the skip label for a private document absent from the snapshot
    ("docs/programme/", "private programme document", "SNAPSHOTCUT-01"),  # link-rule: the skip label for a private document absent from the snapshot
    ("docs/system_description/", "private superseded method copy",  # link-rule: the skip label for a private document absent from the snapshot
     "SNAPSHOTCUT-01"),
    ("docs/reference/aust_cegn/", "held government reference text", "SNAPSHOTCUT-01"),  # link-rule: the skip label for a private document absent from the snapshot
)


def describe(path: Path | str) -> tuple[str, str | None]:
    """Return ``(label, register_id)`` for an input, without touching the filesystem.

    A ``bool`` is rejected rather than described. The natural typo at a call site is to
    pass the guard expression instead of the thing it guarded -
    ``skip_reason(p.exists())`` rather than ``skip_reason(p)`` - and ``str(True)``
    describes cleanly as the label "True", so the reason renders "True not available"
    and names nothing. That is the exact shape this module exists to remove, arriving
    through the module itself, and it was found in review at one site.
    """
    if isinstance(path, bool):
        raise TypeError(
            "skip reason built from a bool - pass the path, not the guard expression "
            "(skip_reason(p), not skip_reason(p.exists()))"
        )
    text = str(path).replace("\\", "/")
    for needle, label, register in _KNOWN:
        if needle.replace("\\", "/") in text:
            return label, register
    return Path(text).stem or "input", None


def skip_reason(
    path: Path | str,
    *,
    state: str = "not available",
    label: str | None = None,
    register: str | None = None,
    detail: str | None = None,
) -> str:
    """Build a skip reason: ``<label> <state> (<register>)``, never a path.

    ``label`` and ``register`` override the registry lookup for a caller that already
    holds a more specific name or row. ``detail`` appends an actionable clause - use it
    for something the reader can act on ("close Excel and re-run"), never for a path.
    """
    known_label, known_rid = describe(path)
    rid = register or known_rid
    text = f"{label or known_label} {state}"
    if rid:
        text += f" ({rid})"
    if detail:
        text += f". {detail}"
    return text


def skip_reason_all(paths, *, state: str = "not available", register: str | None = None) -> str:
    """Reason for a set of inputs at once, for the ``missing = [...]`` call sites.

    Labels are de-duplicated and ordered, so two absent registers read as one clause
    rather than two lines of near-identical path. An empty collection is still given a
    reason, because a skip with no reason is the thing this module exists to remove.
    """
    seen: dict[str, None] = {}
    rid = register
    for p in paths:
        lbl, known = describe(p)
        seen.setdefault(lbl, None)
        rid = rid or known
    if not seen:
        return f"required inputs {state}"
    text = ", ".join(seen) + f" {state}"
    if rid:
        text += f" ({rid})"
    return text


def skip_missing(path: Path | str, **kwargs) -> NoReturn:
    """Skip because a required input is absent on this machine."""
    pytest.skip(skip_reason(path, **kwargs))


def skip_missing_all(paths, **kwargs) -> NoReturn:
    """Skip because several required inputs are absent."""
    pytest.skip(skip_reason_all(paths, **kwargs))


def skip_locked(path: Path | str, **kwargs) -> NoReturn:
    """Skip because Excel holds the workbook open, which is not the same as absent."""
    kwargs.setdefault("state", "locked by Excel")
    kwargs.setdefault("detail", "Close Excel and re-run.")
    pytest.skip(skip_reason(path, **kwargs))


def private_documents_skip(documents):
    """Parametrize over ``documents``, marking each private one ``needs_input``.

    A private document (by the snapshot manifest, the one source) is checked wherever it is
    present and skips, naming itself, where it is not - the public snapshot. A shipped document
    is never marked, so a shipped one that goes missing still fails.
    """
    from scripts.release.snapshot_manifest import PRIVATE, classify

    return [pytest.param(d, marks=pytest.mark.needs_input(d)) if classify(d) == PRIVATE else d
            for d in documents]


def private_and_absent(path: Path | str) -> bool:
    """True when ``path`` is private by the snapshot manifest and not in this tree."""
    from scripts.release.snapshot_manifest import PRIVATE, classify

    rel = str(path).replace("\\", "/")
    return classify(rel) == PRIVATE and not (Path(__file__).resolve().parents[1] / rel).exists()


def skip_if_private_and_absent(path: Path | str) -> None:
    """Skip, naming the document, when it is private and absent; otherwise return."""
    if private_and_absent(path):
        skip_missing(path)
