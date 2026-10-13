"""SNAPSHOTCUT-01, gate 3 round 1 W3: no shipped file names a private path.

READABILITY-01's link rule held nine documents and three batch files to ``EXCLUDED``. This holds
**every shipped text file** (any file that ships and decodes as UTF-8 with no NUL byte, whatever
its type) to **every private entry** of the manifest: a reference to one is red, naming the file,
the line and the entry. ``EXCLUDED`` entries are recognised by the link rule's own patterns; every
other private entry by its path - written with either slash, joined as ``"a" / "b"``, or dotted as
a module - and an exact file also by its name alone.

Two kinds of reference are allowed, each named here and nowhere else:

* a **definitional file**, whose job is to name what does not ship (the manifest, and the tests of
  the manifest and of the rules), listed in ``DEFINITIONAL`` with its reason;
* a **line marked** ``# link-rule: <why>``, for a check that reads a private document when it is
  present and skips by name when it is absent (the snapshot's case), **and for nothing else** (PM
  ruling, task -7). The reason is required: a short sentence of 20 characters and three words or
  more, and not the same text as a mark's in another file (gate 3 round 2, finding 4).

Red-first: a planted reference under each file type is named below.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest

import scripts.release.snapshot_manifest as m
from tests.test_readability01_public_docs import _REFERENCE

REPO = Path(__file__).resolve().parents[1]

#: Files whose job is to name private paths. Each must ship and actually name one.
DEFINITIONAL: dict[str, str] = {
    "scripts/release/snapshot_manifest.py": "the manifest: the list of what does not ship",
    "tests/test_readability01_public_docs.py": "the link rule: a recogniser per excluded entry, and planted references",
    "tests/test_snapshot_manifest.py": "the manifest's matcher, exercised on private paths",
    "tests/test_snapshot_links.py": "this rule: its planted references",
}
#: The line marker. Its reason must be a short sentence: at least 20 characters and three words
#: (gate 3 round 2, finding 4); a mark with less exempts nothing.
MARK = re.compile(r"#\s*link-rule:(?P<why>.*)$")
MIN_REASON = 20
#: ``"docs" / "am"`` names ``docs/am``; so do ``Path("docs", "am")`` and ``os.path.join("docs", "am")``,
#: whose arguments are joined only inside such a call (a tuple of names elsewhere is not a path).
_JOINED = re.compile(r"""["'][ \t]*/[ \t]*["']""")
_PATH_CALL = re.compile(r"""\b(?:Path|PurePath|PosixPath|WindowsPath|join)\(([^()]*)\)""")
_ARGS = re.compile(r"""["'][ \t]*,[ \t]*["']""")


def mark_reason(line: str) -> str | None:
    """The reason of a well-formed mark on ``line``, or None (no mark, or one too thin to count)."""
    found = MARK.search(line)
    why = found.group("why").strip() if found else ""
    return why if len(why) >= MIN_REASON and len(why.split()) >= 3 else None


def _recogniser(entry: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    """The entry's pattern, any case, and lower-case literal keys of which every match holds one."""
    if entry in _REFERENCE:
        pattern = _REFERENCE[entry]
        # The pattern's longest literal run: these patterns have no alternation outside a prefix.
        key = max(re.findall(r"[A-Za-z0-9_]{3,}", pattern.pattern), key=len)
        return re.compile(pattern.pattern, re.I), (key.lower(),)
    path = entry.rstrip("/")
    if entry.endswith("/"):
        dotted = path.replace("/", ".")
        # with a child, or as a dotted package with a module after it; a nested folder also bare
        # (a one-word folder such as `spikes` bare would be any use of the word)
        bare = r"|(?![\w.-])" if "/" in path else ""
        return (re.compile(rf"(?<![\w.-])(?:{re.escape(path)}(?:/{bare})|{re.escape(dotted)}\.\w)", re.I),
                (path.lower(), dotted.lower()))
    folder, _, name = entry.rpartition("/")
    stem = name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name
    forms = [re.escape(path)]
    if name not in m.MANIFEST:
        forms.append(re.escape(name))
    if folder:
        forms.append(re.escape(f"{folder}/{stem}"))  # the path without its extension
    if name.endswith(".py") and folder:
        package = folder.replace("/", ".")
        forms.append(re.escape(f"{package}.{stem}"))  # the module, dotted
        forms.append(rf"from\s+{re.escape(package)}\s+import\s+[^\n#]*?(?<![\w.]){re.escape(stem)}")
    return re.compile(rf"(?<![\w.-])(?:{'|'.join(forms)})(?![\w-])", re.I), (stem.lower(),)


#: Every private entry but a published path (``.gitignore`` ships, as the public set).
PRIVATE = {e: _recogniser(e) for e, (cls, _) in m.MANIFEST.items()
           if cls == m.PRIVATE and e not in m.SHIPPED_AS}


def _normalised(line: str) -> str:
    line = _JOINED.sub("/", line.replace("\\", "/"))
    return _PATH_CALL.sub(lambda c: c.group(0).replace(c.group(1), _ARGS.sub("/", c.group(1))), line)


def private_references(text: str) -> list[tuple[int, str]]:
    """(line, entry) for each reference to a private entry on a line without a well-formed mark."""
    whole = _normalised(text).lower()
    candidates = [(e, pattern) for e, (pattern, keys) in PRIVATE.items() if any(k in whole for k in keys)]
    if not candidates:
        return []
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        if mark_reason(line):
            continue
        line = _normalised(line)
        found += [(n, entry) for entry, pattern in candidates if pattern.search(line)]
    return found


@functools.cache
def shipped_text() -> dict[str, str]:
    """Every shipped file that is text: it decodes as UTF-8 and holds no NUL byte."""
    out = {}
    for p in m.shipped(m.tracked_files()):
        data = (REPO / m.source(p)).read_bytes()
        if b"\0" in data:
            continue
        try:
            out[p] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return out


def test_no_shipped_file_names_a_private_path():
    found = [f"{p}:{n} -> {entry}" for p, text in shipped_text().items() if p not in DEFINITIONAL
             for n, entry in private_references(text)]
    assert not found, f"{len(found)} reference(s) to what does not ship:\n  " + "\n  ".join(found)


def reasons_in_more_than_one_file(texts: dict[str, str]) -> dict[str, list[str]]:
    """Mark reasons used in two or more files: a copied reason says nothing about its own line. (One
    file may repeat a reason, e.g. on each parametrised case of one check.)"""
    files: dict[str, set[str]] = {}
    for path, text in texts.items():
        for line in text.splitlines():
            why = mark_reason(line)
            if why:
                files.setdefault(why, set()).add(path)
    return {why: sorted(ps) for why, ps in files.items() if len(ps) > 1}


def test_no_mark_reason_is_copied_between_files():
    assert reasons_in_more_than_one_file(shipped_text()) == {}


def test_red_a_reason_copied_into_a_second_file_is_named():
    mark = "x  # link-rule: read when present, skipped by name when absent\n"
    assert reasons_in_more_than_one_file({"a.py": mark, "b.py": mark, "c.py": mark.replace("absent", "gone")}) == {
        "read when present, skipped by name when absent": ["a.py", "b.py"]}


def test_each_definitional_file_ships_and_names_a_private_path():
    texts = shipped_text()
    for path in DEFINITIONAL:
        assert path in texts, f"{path} is listed as definitional but does not ship"
        assert private_references(texts[path]), f"{path} names no private path; drop it from DEFINITIONAL"


# --- red first: a planted reference under each file type is named ------------------------------

_PLANTS = {
    "a.md": "See [the notes](docs/am/01_Workflow_Design.md).",
    "a.py": 'SPIKE = REPO / "spikes" / "qraxl01_q4"',
    "a.ts": " * carries `docs/am/03_JSON_Contract_Spec_v2_6.md`",
    "a.bat": "REM see scripts\\hooks\\pre-commit",
    "a.ipynb": '"# Everything numeric happens in src/ (CLAUDE.md invariant 9)\\n",',
    "a.txt": "# Test discipline in CLAUDE.md",
    "a.toml": 'module = "spikes.qraxl01_step6a.capture_tier2"',
    "a.yml": "# the allowlist is gate_allow.txt",
    "a.j2": "{# docs/reference/aust_cegn/README.md #}",
    "a.json": '{"see": "tests/test_flow_guard.py"}',
}


@pytest.mark.parametrize("name", sorted(_PLANTS))
def test_red_a_planted_reference_is_named_in_each_file_type(name):
    assert private_references(_PLANTS[name]), name


def test_red_a_reference_by_name_alone_is_named():
    assert private_references("exempt it in gate_allow.txt") == [(1, "gate_allow.txt")]


def test_green_a_marked_line_and_shipped_paths_pass():
    assert private_references('needs_input("CLAUDE.md")  # link-rule: the private manual, read when present') == []
    assert private_references("see docs/PLAYBOOK.md, scripts/client_gate.py, .gitignore and exploratory spikes.") == []


def test_every_match_holds_one_of_its_entrys_keys():
    """The literal keys only skip the patterns; a key that a match can lack would hide a reference."""
    matched = 0
    for entry, (pattern, keys) in PRIVATE.items():
        base = entry.rstrip("/")
        for sample in (entry, base + "/x", base.replace("/", ".") + ".x", base.rsplit("/", 1)[-1]):
            hit = pattern.search(_normalised(sample))
            if hit:
                matched += 1
                assert any(k in hit.group(0).lower() for k in keys), (entry, sample, keys)
    assert matched >= len(PRIVATE)


def test_red_a_mark_without_a_reason_does_not_exempt():
    assert private_references("CLAUDE.md  # link-rule:") == [(1, "CLAUDE.md")]


@pytest.mark.parametrize("reason", ["x", "read when present", "averyveryverylongsingleword"])
def test_red_a_mark_whose_reason_is_not_a_short_sentence_does_not_exempt(reason):
    assert private_references(f"CLAUDE.md  # link-rule: {reason}") == [(1, "CLAUDE.md")]


@pytest.mark.parametrize("probe", [
    "from tests.tree_paths import x",
    "import scripts.sra_phase2_f",
    "from scripts.release import cut_snapshot",
    "SPEC = REPO / 'docs' / 'am'",
    'Path("docs", "am", "x")',
    'os.path.join("docs", "am", "x")',
    "see claude.md",
    '"tests/test_stage_log": (',
])
def test_red_each_form_gate_3_round_2_found_green(probe):
    """Gate 3 round 2, finding 3: each of these read green before; each is now named."""
    assert private_references(probe), probe


@pytest.mark.parametrize("text", [
    "fat-tail exposure (e.g. commodity price spikes).",
    '{"1.Programme", "2.Construction", "3.External"}',
])
def test_green_a_word_and_a_tuple_of_names_are_not_paths(text):
    assert private_references(text) == []
