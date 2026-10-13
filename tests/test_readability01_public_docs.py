"""READABILITY-01 P6 and SHIPDOCS-01 P5: nothing public points at what does not ship, and the public documents speak to the public.

E4's link rule (RELEASE-01 plan D-2, amended: E4 fails on any link in the snapshot that points at an
excluded file), made early so E4 can reuse it. Two limbs:

* **Every public document** - the four manuals plus the three shipping docs D-T names - must not
  reference a file or folder that does not ship: a link, a backticked path or a bare path, with
  either slash, and the bare word ``SPEC`` (the product spec lives in ``docs/programme/``).
* **Every public document** must also carry no register-ID shapes, no "Director", no "brief", and
  no vault reference (VAULT-REF-01's landing sites). The three shipping docs joined the four
  manuals in this limb at SHIPDOCS-01, which rewrote them.
* **The comments of the three entry-point scripts** (``REM`` and ``::`` lines) are held to the same
  insider-mark matcher. Only comment lines are scanned: an executable line is not rewritten by a
  documentation stage, so a mark on one is a register row, not this check's.

Red-first: the matchers are exercised on doctored snippets below, and each must name what it found.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

MANUALS = ("README.md", "ARCHITECTURE.md", "docs/PLAYBOOK.md", "METHODOLOGY.md")
#: D-T (Director, 01/10/2026): these ship, and are in scope for the reference limb only.
SHIPPING_DOCS = ("docs/SOFTWARE_USER_GUIDE.md", "SCALABILITY.md", "docs/RELEASE_PROCEDURE_dashboard.md",
                 # SNAPSHOTCUT-01 (Director, 09/10/2026): ships, read at run time by tools/register_polish.py
                 "docs/polish_handoff.md",
                 # SNAPSHOTCUT-01 S4: ships, rewritten as SHIPDOCS-01 rewrote the three above
                 "docs/run-recipes.md")
PUBLIC_DOCS = MANUALS + SHIPPING_DOCS
#: The scripts an operator opens. Their comment lines are public text.
ENTRY_SCRIPTS = ("RUN_FINAL.bat", "RUN_PERIOD.bat", "PUBLISH_PERIOD.bat")

#: What does not ship: the link rule's list. It lives in the snapshot manifest, the one source for
#: what ships (SNAPSHOTCUT-01), and is imported from there, never copied.
from scripts.release.snapshot_manifest import EXCLUDED  # noqa: E402

#: How each excluded entry is recognised (gate 3 round 1, W2 and W3). A reference may be a link, a
#: backticked or bare path, `./` or `../` relative, inside `href=`, or relative to `docs/` (so
#: `programme/...`, `procedures/...`, `STYLE.md`, and `flow.py` without `scripts/`). Each pattern is
#: matched on text whose backslashes are already forward slashes.
_REFERENCE: dict[str, re.Pattern[str]] = {
    "CLAUDE.md": re.compile(r"CLAUDE\.md"),
    ".claude/": re.compile(r"(?<![\w-])\.claude/"),
    "scripts/flow.py": re.compile(r"(?<![\w-])flow\.py\b"),
    "scripts/flow_evidence.py": re.compile(r"flow_evidence"),
    "docs/stage_briefs/": re.compile(r"stage_briefs"),
    "docs/running_records/": re.compile(r"running_records"),
    "docs/OPEN_THREADS.md": re.compile(r"OPEN_THREADS"),
    "docs/programme/": re.compile(r"(?<![\w-])programme/"),
    "docs/VAULT_WIKI.md": re.compile(r"VAULT_WIKI"),
    # Only the ROOT change log: `tests/golden/CHANGELOG.md` ships, so a path segment before it clears.
    "CHANGELOG.md": re.compile(r"(?<![\w/-])(?:\.\.?/)*CHANGELOG\.md"),
    "docs/Aust_GLines/": re.compile(r"Aust_GLines"),
    "docs/STAGE4_step2_fill_prompt.md": re.compile(r"STAGE4_step2_fill_prompt"),  # path-walker: plant - D-T's old path
    "docs/OPERATING_MODEL_v2.md": re.compile(r"OPERATING_MODEL"),
    "docs/PROCESS_DISCIPLINE.md": re.compile(r"PROCESS_DISCIPLINE"),
    "docs/GIT_AND_TEST_NOTES.md": re.compile(r"GIT_AND_TEST_NOTES"),
    "docs/PITFALLS.md": re.compile(r"PITFALLS\.md"),
    "docs/ARCH_DEBT.md": re.compile(r"ARCH_DEBT"),
    "docs/STYLE.md": re.compile(r"(?<![\w-])STYLE\.md"),
    "docs/INPUTS_REFERENCE.md": re.compile(r"INPUTS_REFERENCE"),
    "docs/procedures/": re.compile(r"(?<![\w-])procedures/"),
    "docs/system_description/": re.compile(r"system_description"),
}
#: The product spec lives in `docs/programme/`, so the word refers to an excluded file, in any case.
SPEC_WORD = re.compile(r"\bspecs?\b", re.I)

#: Register IDs: `READABILITY-01`, `D-21`, `F5B-4`, `FW-12`, `R-4`.
REGISTER_ID = re.compile(r"(?<![\w.-])[A-Z][A-Z0-9]*-\d+[a-z]?(?![\w-])")
#: The other insider shapes (gate 3 round 1, W4): `GOLDEN01`, a `3c` stage tag, `RS-D-2`, `SR-S3` and
#: `SR-S3-Prod`, `Beta-12`, `SP-series`, and the sprint tags `SR9`, `SR10.C`.
INSIDER_SHAPES = (
    re.compile(r"\b[A-Z]{4,}\d{2}\b"),
    re.compile(r"(?<![\w.$-])\d[a-e](?![\w-])"),
    re.compile(r"\b[A-Z]{2,}-[A-Z]-\d+\b"),
    re.compile(r"\b[A-Z]{2,}-[A-Z]\d+(?:-[A-Za-z]+)?\b"),
    re.compile(r"\b[A-Z][a-z]+-\d+\b"),
    re.compile(r"\bS[PR]-series\b", re.I),
    re.compile(r"(?<![\w.])(?:SR|SP)\d+[a-z]?(?:\.[A-Z0-9]+)?(?![\w])"),
)
#: Shapes that are not insider marks. Each with its reason; kept short.
ID_ALLOWLIST: dict[str, str] = {
    "UTF-8": "a character encoding",
    "PGD-02": "an AACE International publication number, cited as a standard",
    "SHA-256": "a hash algorithm",
}
#: Word-number shapes that are the method's own terms.
SHAPE_ALLOWLIST = re.compile(r"^(?:Top|Layer)-\d+$")  # a top-N ranking; the method's Layer 1 / 2
INSIDER_WORDS = re.compile(r"\bdirector\b|\bbriefs?\b", re.I)
#: The note app's name is built, not typed, so no shipped file carries it as one token.
_NOTE_APP = "Obsi" + "dian"
VAULT = re.compile(r"\bvault\b|\[\[|\b" + _NOTE_APP + r"\b", re.I)


def _normalised(text: str) -> str:
    return text.replace("\\", "/")


def excluded_references(text: str) -> list[tuple[int, str]]:
    """(line, entry) for each reference to something that does not ship."""
    found = []
    for n, line in enumerate(_normalised(text).splitlines(), 1):
        found += [(n, entry) for entry in EXCLUDED if _REFERENCE[entry].search(line)]
        if SPEC_WORD.search(line):
            found.append((n, "SPEC (docs/programme/SPEC_product.md)"))
    return found


def insider_marks(text: str) -> list[tuple[int, str]]:
    """(line, token) for each register ID, insider shape, insider word or vault reference."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        tokens = [m.group(0) for m in REGISTER_ID.finditer(line)]
        tokens += [m.group(0) for p in INSIDER_SHAPES for m in p.finditer(line)]
        found += [(n, t) for t in dict.fromkeys(tokens)
                  if t not in ID_ALLOWLIST and not SHAPE_ALLOWLIST.match(t)]
        found += [(n, m.group(0)) for m in INSIDER_WORDS.finditer(line)]
        found += [(n, m.group(0)) for m in VAULT.finditer(line)]
    return found


_BAT_COMMENT = re.compile(r"^\s*@?\s*(?:REM\b|::)", re.I)


def bat_comment_marks(text: str) -> list[tuple[int, str]]:
    """(line, token) for each insider mark on a ``REM`` or ``::`` comment line of a batch file."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        if _BAT_COMMENT.match(line):
            found += [(n, tok) for _, tok in insider_marks(line)]
    return found


_FENCE = re.compile(r"^\s*```(\w*)\s*$")
#: Lines that belong to one shell and not another (gate 3 round 1, W1): cmd's `set X=` and `%X%`
#: cannot run in PowerShell, and PowerShell's `$env:` and `$x =` cannot run in cmd.
_CMD_ONLY = re.compile(r"^\s*set \w+=|%\w+%", re.I)
_POWERSHELL_ONLY = re.compile(r"\$env:|^\s*\$\w+\s*=")


def fence_problems(text: str) -> list[tuple[int, str]]:
    """(line, problem) for an untagged fence, or a line written for another shell than its tag."""
    found, lang = [], None
    for n, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if m and lang is None:
            lang = m.group(1)
            if not lang:
                found.append((n, "a fence with no language tag"))
            continue
        if m:
            lang = None
            continue
        if lang in ("powershell", "ps1") and _CMD_ONLY.search(line):
            found.append((n, f"cmd syntax in a {lang} fence"))
        if lang in ("bat", "cmd", "bash", "sh") and _POWERSHELL_ONLY.search(line):
            found.append((n, f"PowerShell syntax in a {lang} fence"))
    return found


def _read(doc: str) -> str:
    return (REPO / doc).read_text(encoding="utf-8")


def _describe(doc: str, found: list[tuple[int, str]]) -> str:
    return f"{doc}: " + "; ".join(f":{n} {what}" for n, what in found[:40]) + (
        f" ... and {len(found) - 40} more" if len(found) > 40 else "")


# --- the public documents ------------------------------------------------------------------------

def test_every_excluded_entry_has_exactly_one_recogniser() -> None:
    """EXCLUDED lives in the snapshot manifest and _REFERENCE here; a drift fails by name."""
    unrecognised = [e for e in EXCLUDED if e not in _REFERENCE]
    orphaned = [k for k in _REFERENCE if k not in EXCLUDED]
    assert not unrecognised and not orphaned, (
        f"EXCLUDED entries with no pattern in _REFERENCE: {unrecognised}; "
        f"_REFERENCE patterns for no EXCLUDED entry: {orphaned}")


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_no_public_document_references_what_does_not_ship(doc: str) -> None:
    found = excluded_references(_read(doc))
    assert not found, _describe(doc, found)


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_no_public_document_carries_insider_marks(doc: str) -> None:
    found = insider_marks(_read(doc))
    assert not found, _describe(doc, found)


@pytest.mark.parametrize("script", ENTRY_SCRIPTS)
def test_no_entry_script_comment_carries_insider_marks(script: str) -> None:
    found = bat_comment_marks(_read(script))
    assert not found, _describe(script, found)


@pytest.mark.parametrize("doc", MANUALS)
def test_every_manual_fence_is_tagged_for_its_shell(doc: str) -> None:
    found = fence_problems(_read(doc))
    assert not found, _describe(doc, found)


def test_every_public_document_exists() -> None:
    """A renamed manual must not leave the checks above passing over nothing."""
    missing = [d for d in PUBLIC_DOCS + ENTRY_SCRIPTS if not (REPO / d).is_file()]
    assert not missing, missing


# --- red-first: the matchers name what they find -------------------------------------------------

@pytest.mark.parametrize("snippet, entry", [
    ("See [the spec](docs/programme/SPEC_product.md).", "docs/programme/"),
    ("Read `docs\\OPEN_THREADS.md` first.", "docs/OPEN_THREADS.md"),
    ("as the OPEN_THREADS row says", "docs/OPEN_THREADS.md"),
    ("the agent manual, CLAUDE.md, says", "CLAUDE.md"),
    ("in `docs/stage_briefs/BRIEF_X.md`", "docs/stage_briefs/"),  # path-walker: plant - a red-first fixture
    ("see `CHANGELOG.md`", "CHANGELOG.md"),
    ("see docs/PITFALLS.md", "docs/PITFALLS.md"),
    ("the `.claude/` folder", ".claude/"),
    ("`scripts/flow.py lane`", "scripts/flow.py"),
    ("as SPEC §1 rules", "SPEC (docs/programme/SPEC_product.md)"),
    # Gate 3 round 1, W2 and W3: the forms the first version missed.
    ("see [the log](./CHANGELOG.md)", "CHANGELOG.md"),
    ("see ../CHANGELOG.md", "CHANGELOG.md"),  # path-walker: plant - a red-first fixture
    ('<a href="../CLAUDE.md">the manual</a>', "CLAUDE.md"),  # path-walker: plant - a red-first fixture
    ("as the spec says", "SPEC (docs/programme/SPEC_product.md)"),
    ("relative to docs: `programme/SPEC_product.md`", "docs/programme/"),
    ("relative to docs: `procedures/PLAYBOOK_RUN_protocol_20260921.md`", "docs/procedures/"),
    ("relative to docs: `STYLE.md`", "docs/STYLE.md"),
    ("run `flow.py lane`", "scripts/flow.py"),
    ("the stale copy in `docs/system_description/METHODOLOGY.md`", "docs/system_description/"),
])
def test_red_an_excluded_reference_is_named(snippet: str, entry: str) -> None:
    assert entry in [e for _, e in excluded_references(snippet)]


@pytest.mark.parametrize("snippet", [
    "the goldens' log, `tests/golden/CHANGELOG.md`, ships",
    "see `docs/SOFTWARE_USER_GUIDE.md` and `SCALABILITY.md`",
    "a specification, specifically",
    "an overflow.py helper and a workflow",
])
def test_green_a_shipping_reference_is_not_named(snippet: str) -> None:
    assert excluded_references(snippet) == []


@pytest.mark.parametrize("snippet, token", [
    ("closed by READABILITY-01", "READABILITY-01"),
    ("ruled at D-21", "D-21"),
    ("finding F5B-4", "F5B-4"),
    ("FW-12 says", "FW-12"),
    ("the SR9 deliverable", "SR9"),
    ("SR10.C, deferred", "SR10.C"),
    ("the Director rules", "Director"),
    ("as the brief says", "brief"),
    ("see [[RefProject Process Discipline]]", "[["),
    ("in the " + _NOTE_APP + " vault", "vault"),
    # Gate 3 round 1, W4: the shapes the first version missed.
    ("the GOLDEN01 harness", "GOLDEN01"),
    ("rebuilt at 3c", "3c"),
    ("the RS-D-2 shape", "RS-D-2"),
    ("deferred to SR-S3-Prod", "SR-S3-Prod"),
    ("added at Beta-12", "Beta-12"),
    ("the legacy SP-series workbook", "SP-series"),
    ("the director signs", "director"),
    ("In Brief, the model", "Brief"),
])
def test_red_an_insider_mark_is_named(snippet: str, token: str) -> None:
    assert token in [t for _, t in insider_marks(snippet)]


@pytest.mark.parametrize("snippet, token", [
    ("REM closed by SHIPDOCS-01", "SHIPDOCS-01"),
    ("rem the SPEC section 6a says", "6a"),
    ("@REM kept for R-4", "R-4"),
    (":: deprecated at SR9 v3.5", "SR9"),
    ("  REM the Director's go", "Director"),
    ("REM ---- run token (begin) - RIDGELINE-01 round 5", "RIDGELINE-01"),
])
def test_red_a_batch_comment_mark_is_named(snippet: str, token: str) -> None:
    assert token in [t for _, t in bat_comment_marks(snippet)]


@pytest.mark.parametrize("snippet", [
    "echo ERROR: no default (QRAXL-01)",  # an executable line: a register row, not this check's
    "set QRA_PROJECT=%1",
    "REM Use the repository's own interpreter, never whatever python is first on PATH.",
    ":run",
])
def test_green_a_batch_line_that_is_not_an_insider_comment_passes(snippet: str) -> None:
    assert bat_comment_marks(snippet) == []


@pytest.mark.parametrize("snippet", [
    "files are UTF-8",
    "the `SR5_ITERATIONS` environment variable",
    "AACE 132R-23 and GN3A",
    "a P80 of $11.3m, at 100,000 iterations",
    "briefly, the model",
    "the Top-3 contributors and the Layer-1 systemic uncertainty",
    "a gap below 1e-9, the CG01 group, P80 and P90",
])
def test_green_ordinary_text_is_not_an_insider_mark(snippet: str) -> None:
    assert insider_marks(snippet) == []


@pytest.mark.parametrize("snippet, problem", [
    ("```powershell\nset QRA_PROJECT=synthetic_wind\n```", "cmd syntax in a powershell fence"),
    ("```powershell\necho %QRA_PROJECT%\n```", "cmd syntax in a powershell fence"),
    ("```bat\n$env:QRA_PROJECT = \"synthetic_wind\"\n```", "PowerShell syntax in a bat fence"),
    ("```\nplain\n```", "a fence with no language tag"),
])
def test_red_a_fence_for_the_wrong_shell_is_named(snippet: str, problem: str) -> None:
    assert problem in [p for _, p in fence_problems(snippet)]


@pytest.mark.parametrize("snippet", [
    "```powershell\n$env:QRA_PROJECT = \"synthetic_wind\"\n.\\RUN_FINAL.bat\n```",
    "```bat\nset QRA_PROJECT=synthetic_wind\nRUN_FINAL.bat\n```",  # path-walker: plant - a fixture
    "```text\nset X=1 is quoted here, not run\n```",
])
def test_green_a_fence_tagged_for_its_shell_passes(snippet: str) -> None:
    assert fence_problems(snippet) == []
