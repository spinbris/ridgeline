"""Repository paths named in prose documents resolve against the tracked tree (REPORTDOC-01).

One walker for the user guide, the product spec and the playbook's prose. It was the guide
tripwire's alone until SPECCONTRACT-01 recurred a second time: both instances were spec prose
naming a code artefact that had moved, and both were found by someone editing the spec for
another reason. Nothing compared the spec to the tree.

What resolves, in order:

* a ``:line`` suffix is stripped first (``src/am/json_writer.py:64``). **The line number itself
  is not checked** - line citations drift with every edit above them, and a check on them would
  be red for reasons that are not errors. That is a stated blind spot, not an oversight;
* a glob resolves when it matches at least one tracked file, and ``*`` never crosses a ``/``. A
  glob with no directory (``RUN_*.bat``) matches **root-level files only**: the review of
  13/09/2026 found it matching a basename anywhere, so a retired root launcher would have stayed
  green on a fixture of the same shape elsewhere in the tree. A bare filename resolves anywhere
  because documents cite modules by name; a glob names a family, and a family needs a place;
* a path resolves when it is a tracked file, or a directory holding one;
* a bare filename (``client_gate.py``) resolves when exactly one tracked file carries it. Two
  carriers is ambiguous, and ambiguous is unresolved.

**Resolution is against ``git ls-files``, not the disk.** A disk check answers differently on a
data machine that holds the gitignored confidential tier, and a walker whose exemptions go stale
on one machine only is worse than none.

Paths a run or a build produces, or that are gitignored by design, are not checked
(:data:`RUNTIME_PREFIXES`), nor ``<...>`` placeholders, nor spans inside fenced blocks. **That last is a blind spot, stated.**
Measured 13/09/2026: only the playbook has fenced blocks, and its command blocks have their own
tripwire (``tests/test_stage5_playbook_tripwire.py``). A fenced block added to the guide or the spec
would be walked by nothing. Fences open on three or more backticks or tildes and close only on the
same character at least as long, and **an unclosed fence raises** - left open, it would silently
skip every span to the end of the document.

**Exemptions are scoped to a section, never to a span alone.** The spec names retired files on
purpose - its entry-point table exists to say which were retired - and its history names a script
that a later bump removed from the contract it described. An exemption keyed on the span alone
would pass that script reappearing in the contract. Keyed on the heading, it cannot - provided the
heading is unique, so an exemption whose heading text appears twice in its document is stale.

**An exemption cannot outlive its reason.** It is stale, and fails, when its span no longer
appears under its heading, or when its span now resolves in this tree - exactly or by its
filename. The second is how a document that says "archived repository" about a file that has
since moved into this one goes red.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from src.git_identity import git_env

CODE_SPAN = re.compile(r"`([^`\n]+)`")

#: A span that is only a file type, e.g. ``.xer`` - the documents name formats as well as files.
BARE_EXTENSION = re.compile(r"\.[a-z0-9]+$")

#: ``path:64``, ``path:153-188``, ``path:201,208,216``.
LINE_SUFFIX = re.compile(r":\d[\d,\-]*$")

#: A span is a path candidate when it carries a separator or a known extension.
PATH_EXTENSIONS = (".py", ".md", ".bat", ".xlsx", ".xer", ".json", ".ipynb", ".toml", ".tsx")

#: Produced by a run or a build, gitignored by design, or git's own: naming one is not a broken
#: pointer. ``inputs`` and ``tests/golden/local`` hold confidential material on a data machine
#: and nothing on a fresh clone, so neither can be a pointer that resolves the same everywhere.
RUNTIME_PREFIXES = ("outputs", "data", "dist", ".venv", "inputs", "tests/golden/local", ".git")
RUNTIME_FILENAMES = frozenset({"provenance.json", "metadata.json", "manifest.json"})

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class Span:
    section: str  # the nearest heading's text, without its hashes
    text: str
    line: int


@dataclass(frozen=True)
class Exemption:
    section: str
    span: str
    reason: str


def _prose_lines(text: str):
    """``(number, line, section, is_heading)`` for every line outside a fenced block."""
    section = ""
    fence, opened = "", 0
    for number, line in enumerate(text.splitlines(), start=1):
        marker = _FENCE.match(line)
        if fence:
            if (marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence)
                    and not marker.group(2).strip()):
                fence = ""
            continue
        if marker:
            fence, opened = marker.group(1), number
            continue
        heading = _HEADING.match(line)
        if heading:
            section = heading.group(2)
        yield number, line, section, bool(heading)
    if fence:
        raise ValueError(
            f"unclosed fence {fence!r} opened at line {opened}: every span after it would be skipped")


def spans(text: str) -> list[Span]:
    """Every inline code span outside fenced blocks, with the heading it sits under."""
    return [
        Span(section, m.group(1).strip(), number)
        for number, line, section, _ in _prose_lines(text)
        for m in CODE_SPAN.finditer(line)
    ]


def headings(text: str) -> Counter[str]:
    """How many times each heading's text occurs outside fenced blocks."""
    return Counter(section for _, _, section, is_heading in _prose_lines(text) if is_heading)


def is_prose(span: str) -> bool:
    """A code span that is a phrase or a file type, not a path."""
    if BARE_EXTENSION.fullmatch(span):
        return True
    if " / " in span:
        return True
    return " " in span.strip() and "/" not in span and "\\" not in span


def _normalise(span: str) -> str:
    return LINE_SUFFIX.sub("", span).replace("\\", "/").strip().rstrip("/").removeprefix("./")


def is_path_candidate(span: str) -> bool:
    if span.startswith("<") or ("<" in span and ">" in span):
        return False  # placeholder, e.g. outputs\<project>\...
    if span.startswith("/"):
        return False  # an app route, checked by the guide's own limb
    if is_prose(span):
        return False
    bare = LINE_SUFFIX.sub("", span)
    return "/" in bare or "\\" in bare or bare.endswith(PATH_EXTENSIONS)


def is_runtime(span: str) -> bool:
    path = _normalise(span)
    if path in RUNTIME_FILENAMES:
        return True
    return any(path == p or path.startswith(p + "/") for p in RUNTIME_PREFIXES)


class Tree:
    """The tracked files of a repository, indexed for the three ways a span resolves."""

    def __init__(self, files: list[str]) -> None:
        self.files = frozenset(files)
        self.dirs = frozenset(
            str(parent) for f in files for parent in PurePosixPath(f).parents if str(parent) != ".")
        by_name: dict[str, list[str]] = defaultdict(list)
        for f in files:
            by_name[PurePosixPath(f).name].append(f)
        self.by_name = dict(by_name)

    @classmethod
    def from_git(cls, root: Path) -> "Tree":
        """``git ls-files`` at ``root``. Raises rather than returning an empty tree: a walker
        with nothing to resolve against would report every span unresolved, or - worse, if a
        caller caught it - none."""
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=True,
            env=git_env(),
        ).stdout.decode("utf-8")
        files = [f for f in listing.split("\0") if f]
        if not files:
            raise RuntimeError(f"git ls-files returned nothing at {root}")
        return cls(files)

    def resolves(self, span: str) -> bool:
        path = _normalise(span)
        if any(c in path for c in "*?"):
            glob = _glob(path)
            return any(glob.fullmatch(f) for f in self.files if "/" in path or "/" not in f)
        if path in self.files or path in self.dirs:
            return True
        if "/" not in path:
            return len(self.by_name.get(path, ())) == 1
        return False

    def resolves_by_name(self, span: str) -> bool:
        """Looser than :meth:`resolves`: the span's filename is carried by a tracked file, at
        any path. This is the staleness test for an exemption - "not in this repository" is
        false the moment the file arrives, wherever it lands."""
        name = PurePosixPath(_normalise(span)).name
        if any(c in name for c in "*?"):
            # Deliberately looser than resolves()'s root-only rule for a slash-free glob: that
            # rule is right for a pointer and wrong here, where a retired family returning at
            # any path makes "retired" false (re-review, 13/09/2026).
            glob = _glob(name)
            return self.resolves(span) or any(glob.fullmatch(n) for n in self.by_name)
        return self.resolves(span) or name in self.by_name


def _glob(path: str) -> re.Pattern[str]:
    """``*`` and ``?`` within one path segment - never across a ``/``, unlike ``fnmatch``."""
    return re.compile(re.escape(path).replace(r"\*", "[^/]*").replace(r"\?", "[^/]"))


def unresolved(text: str, tree: Tree, exemptions: list[Exemption]) -> list[Span]:
    exempt = {(e.section, e.span) for e in exemptions}
    return [
        s for s in spans(text)
        if is_path_candidate(s.text)
        and not is_runtime(s.text)
        and not tree.resolves(s.text)
        and (s.section, s.text) not in exempt
    ]


def stale_exemptions(text: str, tree: Tree,
                     exemptions: list[Exemption]) -> list[tuple[Exemption, str]]:
    present = {(s.section, s.text) for s in spans(text)}
    counts = headings(text)
    stale = []
    for e in exemptions:
        if counts[e.section] > 1:
            stale.append((e, "its heading is not unique in the document"))
        elif (e.section, e.span) not in present:
            stale.append((e, "its span no longer appears under its heading"))
        elif tree.resolves_by_name(e.span):
            stale.append((e, "its span now resolves in this repository"))
    return stale


def candidate_count(text: str) -> int:
    return sum(1 for s in spans(text) if is_path_candidate(s.text) and not is_runtime(s.text))


def describe(items: list[Span]) -> str:
    return "\n  ".join(f"line {s.line}, under '{s.section}': `{s.text}`" for s in items)
