"""The manuals name no file that is absent from the tree.

`tests/test_doc_paths.py` walks the user guide, the SPEC and the playbook, where every backticked
path is written as a full repo path. The manuals are written differently - a section establishes a
directory and then names modules bare (`defaults.py` under "2.1 Top-level cost-side modules") - so
putting them through that walker produces dozens of findings that are prose working as intended.

This is the narrow check the manuals need instead. It asks one question: **does this document name
a file that exists nowhere in the tree?** A bare name resolves if any tracked file has it; a
slashed path must resolve exactly. That is enough to catch the defect class DOCPOINT-01 found -
thirty references across six documents, including a retired notebook named as the thing to run,
a pre-cut brief called "the current in-force brief", and a script deleted two increments earlier
still listed in an implementation plan - without arguing about which directory a bare name means.

Exemptions are declared with a reason, like `test_doc_paths.py`'s, and go stale loudly: a span
that starts resolving, or stops appearing, fails rather than sitting here forever.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.git_identity import git_env
from tests.input_skips import private_and_absent, private_documents_skip

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A backticked token that names a file: something with one of the extensions this repository
#: actually carries. Deliberately narrow - a dotted symbol, a glob or a shell command is not a
#: file reference, and treating it as one is what made the wider walker unusable here.
#: PUBLIC-01 widened this. The original list covered code and documents and stopped there -
#: but this product's manuals mostly name DATA: registers, schedules, strawmen, run
#: manifests. The gap let the old strawman workbook's path
#: sit in METHODOLOGY §4 after REG-01 dissolved the strawman into the register, and let two
#: documents cite a Gap Analysis `.docx` the tree has never carried. Measured before
#: widening: eleven new findings across the six manuals, of which three were stale and
#: eight are declared below.
_TOKEN = re.compile(
    r"`([A-Za-z0-9_./\-]+\."
    r"(?:py|md|ipynb|toml|bat|json|txt|cfg|ini|yml|yaml"
    r"|xlsx|xlsm|xer|csv|docx|parquet))`"
)

MANUALS = (
    "ARCHITECTURE.md",
    "CLAUDE.md",  # link-rule: the agent manual's pointers are checked when it is present, skipped when absent
    "README.md",
    "METHODOLOGY.md",
    "SCALABILITY.md",
    # The superseded ARCHITECTURE.md copy was reduced to a pointer at PUBLIC-01
    # (D-2b), so it is no longer a manual and would fail the "names files to check"
    # limb on three tokens. Its METHODOLOGY.md sibling was NOT reduced - 148 unique
    # lines including three whole sections - and METHDUP-01 stays open for it.
)


@dataclass(frozen=True)
class Absent:
    """A name the manuals may use although nothing in the tree carries it."""

    document: str
    token: str
    reason: str


_RUNTIME = "written by a run under outputs/runs/, never committed (src/final/deliverable.py)"
_VARIANT = ("a filename SUFFIX pattern, not a path - the leading ellipsis is literal, and the "
            "three name the strawman variants a project may declare")
_REPLACED = "named as what it replaced, not as something to open"

#: Every entry says which document, which name, and why it is meant not to resolve.
ABSENT_BY_DESIGN: tuple[Absent, ...] = (
    # PUBLIC-01, from widening _TOKEN to data extensions.
    Absent("ARCHITECTURE.md", "manifest.csv", _RUNTIME),
    Absent("ARCHITECTURE.md", "outputs/runs/manifest.csv", _RUNTIME),
    Absent("SCALABILITY.md", "outputs/runs/manifest.csv", _RUNTIME),
    Absent("CLAUDE.md", "..._DPReview.xlsx", _VARIANT),  # link-rule: an expected-absent pointer in the agent manual, checked only when the manual is present
    Absent("CLAUDE.md", "..._Hybrid.xlsx", _VARIANT),  # link-rule: an expected-absent pointer in the agent manual, checked only when the manual is present
    Absent("CLAUDE.md", "..._Series.xlsx", _VARIANT),  # link-rule: an expected-absent pointer in the agent manual, checked only when the manual is present
    # REPORTPAGE-01: `provenance.json` resolves now that the report page commits one beside it
    # (dashboard/public/report/), so the two RUNTIME entries for it went.
    Absent("ARCHITECTURE.md", "sr9_diagnostic.py", _REPLACED),
    Absent("METHODOLOGY.md", "sra_runner.ipynb", _REPLACED),
    Absent("CLAUDE.md", "global-CLAUDE.md",  # link-rule: an expected-absent pointer in the agent manual, checked only when the manual is present
           "machine-local vault file - CLAUDE.md never requires the vault to be executable"),  # link-rule: an expected-absent pointer in the agent manual, checked only when the manual is present
    # READABILITY-01 P2: the public README no longer names `main.py` (retired) or the
    # gitignored `tests/golden/local/CHANGELOG.local.md`, so their two entries went.
)


@pytest.fixture(scope="module")
def tracked() -> tuple[set[str], set[str]]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        env=git_env(),
    ).stdout.split("\n")
    paths = {p for p in out if p}
    return paths, {p.rsplit("/", 1)[-1] for p in paths}


def _tokens(document: str) -> list[tuple[int, str]]:
    text = (REPO_ROOT / document).read_text(encoding="utf-8")
    return [
        (i, tok)
        for i, line in enumerate(text.splitlines(), 1)
        for tok in _TOKEN.findall(line)
    ]


def _resolves(token: str, paths: set[str], names: set[str]) -> bool:
    return token in paths or ("/" not in token and token in names)


def _exempt(document: str) -> set[str]:
    return {a.token for a in ABSENT_BY_DESIGN if a.document == document}


@pytest.mark.parametrize("document", private_documents_skip(MANUALS))
def test_the_manual_names_files_to_check(document: str):
    """A walker that silently matched nothing would pass the limb below."""
    assert len(_tokens(document)) >= 10, (
        f"{document}: only {len(_tokens(document))} file references found - the pattern has "
        "stopped matching, and the check below is passing on nothing"
    )


@pytest.mark.parametrize("document", private_documents_skip(MANUALS))
def test_the_manual_names_no_absent_file(document: str, tracked):
    paths, names = tracked
    exempt = _exempt(document)
    missing = [
        f"line {i}: `{tok}`"
        for i, tok in _tokens(document)
        if tok not in exempt and not _resolves(tok, paths, names)
    ]
    assert not missing, (
        f"{document} names files that are not in the tree:\n  " + "\n  ".join(missing)
        + "\n\nEither the name is stale - say what replaced it, or that it predates the product "
        "cut - or it is absent by design, in which case add it to ABSENT_BY_DESIGN with a reason."
    )


def test_no_exemption_outlives_its_reason(tracked):
    """An exemption that starts resolving, or stops appearing, is dead weight and fails here."""
    paths, names = tracked
    stale = []
    for a in ABSENT_BY_DESIGN:
        if private_and_absent(a.document):  # a private manual, in the public snapshot
            continue
        if _resolves(a.token, paths, names):
            stale.append(f"{a.document}: `{a.token}` now resolves - drop the exemption")
        elif a.token not in {tok for _, tok in _tokens(a.document)}:
            stale.append(f"{a.document}: `{a.token}` no longer appears - drop the exemption")
    assert not stale, "stale exemptions:\n  " + "\n  ".join(stale)


def test_every_exemption_gives_a_reason():
    for a in ABSENT_BY_DESIGN:
        assert len(a.reason.split()) >= 5, f"{a.document}/{a.token}: reason too thin to act on"
