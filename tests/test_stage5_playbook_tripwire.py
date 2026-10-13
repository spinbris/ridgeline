"""Stage 5 P-6: the playbook is kept against the tree by a test, not by memory.

The user guide went stale one sheet at a time (stage 4 F-8, F-25) because nothing compared it
with the code. This walks every command block in ``docs/PLAYBOOK.md`` and checks, in process:

* a repository path it names exists (paths under ``outputs/``, ``data/`` and ``dist/`` are what
  the reader produces, and ``<...>`` placeholders are the reader's, so those are not checked);
* ``python -m <module>`` names an importable module, and every ``--flag`` on that line is a
  literal in the module's source;
* ``python <script.py>`` names a script that exists, with the same flag rule;
* ``<NAME>.bat`` exists at the root, and its ``--flags`` are literals in the batch file;
* an environment variable the reader sets is one a batch file or the engine reads.

Static on purpose. Running ``--help`` in a subprocess would be truer and would trip the
shell-out guard into the slow lane, where a stale playbook would not be caught per stage.

Red-first: the checker is exercised on doctored snippets below, and each must name the line.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO_ROOT / "docs" / "PLAYBOOK.md"
#: The full walkthrough with its dispositions and worked inputs, which does not ship (READABILITY-01).
INSIDER_PLAYBOOK = REPO_ROOT / "docs" / "programme" / "manuals_insider" / "PLAYBOOK.md"  # link-rule: the insider playbook's stage 5 tripwire runs when it is present, skips when absent

COMMAND_LANGS = {"bat", "powershell", "bash", "cmd", ""}  # a bare fence is checked, not skipped
UNCHECKED_PREFIXES = ("outputs", "data", "dist", ".venv", "C:", "http", "%", "$",
                      "dashboard\\out", "dashboard/out")  # the app's build output is produced, not tracked
PATH_EXTENSIONS = (".py", ".bat", ".ipynb", ".md", ".xlsx", ".xer", ".txt", ".json", ".toml")
_FENCE = re.compile(r"^```(\w*)\s*$")
_FLAG = re.compile(r"(?<![\w-])(--[a-z][\w-]*)")
_ENV_SET = re.compile(r"^(?:set\s+([A-Z][A-Z0-9_]*)=|\$env:([A-Z][A-Z0-9_]*)\s*=)")
_STEP = re.compile(r"^### Step ([\w.]+)", re.M)
_FINDING = re.compile(r"\bF-(\d+)\b")


def fenced_blocks(text: str) -> list[tuple[str, str, int]]:
    """(language, body, 1-based line of the opening fence) for every fenced block."""
    out, lang, buf, start = [], None, [], 0
    for i, line in enumerate(text.splitlines(), start=1):
        m = _FENCE.match(line)
        if m and lang is None:
            lang, buf, start = m.group(1).lower(), [], i
        elif m and lang is not None:
            out.append((lang, "\n".join(buf), start))
            lang = None
        elif lang is not None:
            buf.append(line)
    return out


def _tokens(line: str) -> list[str]:
    return [t.strip("\"'`,;()") for t in line.split()]


def _looks_like_repo_path(tok: str) -> bool:
    if not tok or "<" in tok or ">" in tok or "*" in tok or tok.startswith(UNCHECKED_PREFIXES) or "://" in tok:
        return False
    if tok.startswith((".\\", "./")):
        tok = tok[2:]
    has_sep = "/" in tok or "\\" in tok
    return (has_sep and not tok.startswith("-")) or tok.endswith(PATH_EXTENSIONS)


def _flags_in_source(flags: list[str], source_text: str, *, python: bool) -> list[str]:
    """Flags NOT accepted by ``source_text``. For Python, accepted means declared to argparse
    (``add_argument("--flag"``); a mention in a docstring or comment does not count, or a flag
    removed from the parser but left in the usage text would keep the playbook green. For a batch
    file, accepted means the literal appears in it."""
    if python:
        declared = set(re.findall(r"add_argument\(\s*[\"'](--[\w-]+)[\"']", source_text))
        return [f for f in flags if f not in declared]
    return [f for f in flags if f'"{f}"' not in source_text and f"'{f}'" not in source_text
            and f"{f}=" not in source_text and f"{f} " not in source_text]


def _env_names_known(root: Path) -> str:
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in root.glob("*.bat")]
    texts += [p.read_text(encoding="utf-8", errors="replace") for p in (root / "src").rglob("*.py")]
    return "\n".join(texts)


def check_playbook(text: str, root: Path = REPO_ROOT) -> list[str]:
    """Every problem, as ``line N: <what>``. Empty means the playbook resolves against the tree."""
    problems: list[str] = []
    env_known = None
    for lang, body, start in fenced_blocks(text):
        if lang not in COMMAND_LANGS:
            continue
        for offset, raw in enumerate(body.splitlines(), start=1):
            n = start + offset
            line = raw.strip()
            if not line or line.startswith(("REM", "#", "::", "rem ")):
                continue
            toks = _tokens(line)
            flags = _FLAG.findall(line)
            if "-c" in toks[1:3]:
                continue  # a python one-liner is code, not paths

            m = _ENV_SET.match(line)
            if m:
                name = m.group(1) or m.group(2)
                env_known = env_known if env_known is not None else _env_names_known(root)
                if name not in env_known:
                    problems.append(f"line {n}: environment variable {name} is read by no batch file or engine module")
                continue

            if "python" in toks[:2] and "-m" in toks:
                mod = toks[toks.index("-m") + 1]
                if mod.startswith("<"):
                    continue
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                spec = importlib.util.find_spec(mod) if not mod.startswith("-") else None
                if spec is None or spec.origin is None:
                    problems.append(f"line {n}: python -m {mod}: no such module")
                elif flags:
                    src = Path(spec.origin).read_text(encoding="utf-8", errors="replace")
                    for f in _flags_in_source(flags, src, python=True):
                        problems.append(f"line {n}: python -m {mod}: flag {f} is not declared in {Path(spec.origin).name}")
                toks = [t for t in toks if t != mod]   # positional paths on the line are still checked below

            script = next((t for t in toks if t.endswith(".py")), None)
            if script and toks[0].startswith("python"):
                sp = root / script.replace("\\", "/")
                if not sp.is_file():
                    problems.append(f"line {n}: script {script} does not exist")
                elif flags:
                    for f in _flags_in_source(flags, sp.read_text(encoding="utf-8", errors="replace"), python=True):
                        problems.append(f"line {n}: {script}: flag {f} is not declared in its parser")
                toks = [t for t in toks if t != script]

            bat = next((t for t in toks if t.lower().endswith(".bat")), None)
            if bat:
                bp = root / bat.lstrip(".\\/").replace("\\", "/")
                if not bp.is_file():
                    problems.append(f"line {n}: {bat} does not exist at the repository root")
                elif flags:
                    # a batch file forwards what it does not parse (RUN_PERIOD.bat's %EXTRA_FLAGS%),
                    # so a flag may live in the module the batch file invokes with python -m
                    bat_text = bp.read_text(encoding="utf-8", errors="replace")
                    if str(root) not in sys.path:
                        sys.path.insert(0, str(root))
                    forwarded: set[str] = set()
                    for mod in re.findall(r"python(?:\.exe)?\s+-m\s+([\w.]+)", bat_text):
                        spec = importlib.util.find_spec(mod)
                        if spec is not None and spec.origin:
                            mod_src = Path(spec.origin).read_text(encoding="utf-8", errors="replace")
                            forwarded |= set(flags) - set(_flags_in_source(flags, mod_src, python=True))
                    for f in _flags_in_source(flags, bat_text, python=False):
                        if f not in forwarded:
                            problems.append(f"line {n}: {bat}: flag {f} is in neither the batch file nor the parser of the module it invokes")
                for t in toks[1:]:
                    if _looks_like_repo_path(t) and not (root / t.lstrip(".\\/").replace("\\", "/")).exists():
                        problems.append(f"line {n}: path {t} does not exist")
                continue

            for t in toks:
                if _looks_like_repo_path(t) and not (root / t.lstrip(".\\/").replace("\\", "/")).exists():
                    problems.append(f"line {n}: path {t} does not exist")
    return problems


# --- the playbook itself ------------------------------------------------------------------------

#: The insider copy is checked wherever it is present and skips, naming itself, in the public snapshot.
@pytest.fixture(scope="module", params=[
    pytest.param(PLAYBOOK, id="public"),
    pytest.param(INSIDER_PLAYBOOK, id="insider", marks=pytest.mark.needs_input("docs/programme/manuals_insider/PLAYBOOK.md")),  # link-rule: the insider playbook's stage 5 tripwire runs when it is present, skips when absent
])
def playbook(request) -> str:
    """The structural checks hold on both copies (READABILITY-01 P1, P4)."""
    assert request.param.is_file(), f"{request.param} is missing"
    return request.param.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def insider_playbook() -> str:
    """The stage 4 and 5b dispositions live only in the insider copy (READABILITY-01 P1)."""
    assert INSIDER_PLAYBOOK.is_file(), f"{INSIDER_PLAYBOOK} is missing"
    return INSIDER_PLAYBOOK.read_text(encoding="utf-8")


def test_every_command_in_the_playbook_resolves_against_the_tree(playbook):
    problems = check_playbook(playbook)
    assert not problems, "\n".join(problems)


def test_the_playbook_has_command_blocks_to_check(playbook):
    """The check above cannot pass vacuously."""
    assert sum(1 for lang, _, _ in fenced_blocks(playbook) if lang in COMMAND_LANGS) >= 12


def test_every_step_carries_the_four_elements(playbook):
    """P-1: precondition, command, expected result, and what a wrong state shows."""
    steps = list(_STEP.finditer(playbook))
    assert len(steps) >= 10, "Part 0, Part A (7 steps) and Part B"
    for i, m in enumerate(steps):
        body = playbook[m.end(): steps[i + 1].start() if i + 1 < len(steps) else len(playbook)]
        for label in ("**Precondition.**", "**Command.**", "**Expect.**", "**If not.**"):
            assert label in body, f"Step {m.group(1)} at offset {m.start()} lacks {label}"


@pytest.mark.needs_input("docs/programme/manuals_insider/PLAYBOOK.md")  # link-rule: the disposition table lives in the insider playbook, read when present
def test_the_disposition_table_covers_every_stage4_finding(insider_playbook):
    """P-3: F-1 to F-35, each with a disposition."""
    appendix = insider_playbook[insider_playbook.index("## Appendix A"):]
    rows = [ln for ln in appendix.splitlines() if ln.startswith("| **F-")]
    found = {int(_FINDING.search(ln).group(1)) for ln in rows}
    assert found == set(range(1, 36)), sorted(set(range(1, 36)) - found)
    for ln in rows:
        assert any(k in ln for k in ("playbook", "product", "not addressed", "open", "closed")), ln[:60]


# --- red-first: the checker names what is wrong ------------------------------------------------

def _snippet(lang: str, *lines: str) -> str:
    return "text\n```" + lang + "\n" + "\n".join(lines) + "\n```\n"


def test_red_a_renamed_flag_is_named():
    p = check_playbook(_snippet("powershell", "python -m src.am.run_period --workbok outputs\\x.xlsx"))
    assert len(p) == 1 and "--workbok" in p[0] and "line 3" in p[0]


def test_red_a_missing_module_is_named():
    p = check_playbook(_snippet("powershell", "python -m src.am.run_perod --workbook outputs\\x.xlsx"))
    assert len(p) == 1 and "no such module" in p[0]


def test_red_a_missing_script_and_a_bad_script_flag_are_named():
    p = check_playbook(_snippet("powershell", "python scripts/no_such_script.py --out x",
                                "python scripts/build_status_workbook.py --regster outputs\\r.xlsx"))
    assert len(p) == 2 and "does not exist" in p[0] and "--regster" in p[1]


def test_red_a_missing_batch_file_flag_and_path_are_named():
    p = check_playbook(_snippet("powershell", ".\\RUN_FINAL.bat --headlin both",
                                ".\\NO_SUCH.bat", ".\\RUN_PERIOD.bat tests\\fixtures\\nope.xlsx"))
    assert [("--headlin" in x, "NO_SUCH" in x, "nope.xlsx" in x) for x in p] == [
        (True, False, False), (False, True, False), (False, False, True)]


def test_a_forwarded_flag_is_accepted_and_a_misspelt_one_is_not():
    """RUN_PERIOD.bat forwards --register to src.am.run_period; --regster exists nowhere."""
    ok = check_playbook(_snippet("powershell", ".\\RUN_PERIOD.bat outputs\\p.xlsx --register outputs\\r.xlsx"))
    bad = check_playbook(_snippet("powershell", ".\\RUN_PERIOD.bat outputs\\p.xlsx --regster outputs\\r.xlsx"))
    assert ok == [] and len(bad) == 1 and "--regster" in bad[0]


def test_red_an_unknown_environment_variable_is_named():
    p = check_playbook(_snippet("powershell", '$env:QRA_PROJEKT = "synthetic_road"'))
    assert len(p) == 1 and "QRA_PROJEKT" in p[0]


def test_red_a_missing_repo_path_is_named_and_reader_paths_are_not():
    p = check_playbook(_snippet("bash", "cat docs/NO_SUCH.md", "cat outputs/anything/at_all.xlsx",
                                "cat <your register>.xlsx"))
    assert len(p) == 1 and "docs/NO_SUCH.md" in p[0]


def test_red_a_flag_that_survives_only_in_a_docstring_is_named(tmp_path):
    """Numerics review of 5a: a flag removed from the parser but left in the usage text must not
    keep the playbook green. Checked against a script under a scratch root."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "fake.py").write_text(
        '"""usage: fake.py --ghost --real"""\nimport argparse\np = argparse.ArgumentParser()\n'
        'p.add_argument("--real")\n', encoding="utf-8")
    p = check_playbook(_snippet("powershell", "python scripts/fake.py --real --ghost"), root=tmp_path)
    assert len(p) == 1 and "--ghost" in p[0] and "--real" not in p[0]


def test_a_positional_path_on_a_python_line_is_checked():
    p = check_playbook(_snippet("powershell", "python -m src.am.publish_period docs/NO_SUCH.json --project x"))
    assert len(p) == 1 and "docs/NO_SUCH.json" in p[0]


def test_a_bare_fence_is_checked_not_skipped():
    p = check_playbook(_snippet("", ".\\NO_SUCH.bat"))
    assert len(p) == 1 and "NO_SUCH" in p[0]


def test_green_a_correct_snippet_has_no_problem():
    p = check_playbook(_snippet(
        "powershell",
        '$env:QRA_PROJECT = "synthetic_road"',
        ".\\RUN_FINAL.bat --headline both",
        "python -m src.am.publish_period data\\synthetic_road\\period_20260831.json --project synthetic_road",
        "python scripts\\build_status_workbook.py --template templates\\status_workbook_template.xlsx",
    ))
    assert p == [], p


# --- FW-1: step 0.2 names no concrete tag (leg 1 of the playbook-currency run, PBFIX-02) -----------

_STEP_0_2_PRECONDITION = re.compile(
    r"^### Step 0\.2 .*?\*\*Precondition\.\*\*(.*?)\*\*Command\.\*\*", re.M | re.S)


def named_tags_in_step_0_2(text: str) -> list[str]:
    """Backticked names in step 0.2's precondition, other than ``<...>`` placeholders.

    FW-1 (21/09/2026): the precondition read *"the tag `5a`, or later"*. A reader who followed it
    checked out a tag ten days stale and finished the whole playbook green - every check passes inside
    a stale checkout - reading the Stage 2.5 comparator as the headline. Any tag written here rots at
    the next release, so the step names none and the tag comes from the brief. Reads the text only:
    no ``git``, so it needs no shell-out exemption.
    """
    m = _STEP_0_2_PRECONDITION.search(text)
    assert m, "step 0.2 has no Precondition ... Command span to check"
    return [t for t in re.findall(r"`([^`]+)`", m.group(1))
            if not (t.startswith("<") and t.endswith(">"))]


def test_step_0_2_names_no_concrete_tag(playbook):
    named = named_tags_in_step_0_2(playbook)
    assert not named, (
        f"step 0.2's precondition names {named}: a tag written there goes stale at the next release "
        "and still satisfies the step's own check (FW-1). Leave the tag to the brief.")


def test_red_an_example_tag_in_step_0_2_is_named():
    text = ("### Step 0.2 - Clone at the named tag\n\n**Precondition.** The tag named in your brief "
            "(the tag `5a`, or later).\n\n**Command.**\n")
    assert named_tags_in_step_0_2(text) == ["5a"]


def test_green_a_placeholder_in_step_0_2_is_not_a_tag():
    text = ("### Step 0.2 - Clone at the named tag\n\n**Precondition.** The tag `<tag>` named in your "
            "brief.\n\n**Command.**\n")
    assert named_tags_in_step_0_2(text) == []
