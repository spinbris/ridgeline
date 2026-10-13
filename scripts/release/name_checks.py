"""SNAPSHOTCUT-01: the names no shipped file may carry, and the matcher that finds them.

Shared by the snapshot builder (over the cut tree) and ``tests/test_shipped_names.py`` (over the
shipped files, on every lane). The checks:

* **machine name** - this machine's name, read at run time, and any the caller adds;
* **home folder** - this machine's home folder, in three spellings, read at run time;
* **note app**, **third party** (a first name) and **business name** (a registered business name,
  and its initials) - fixed, built from parts so this file does not carry them.

A word of four letters or more is found typed or disguised: any one character replaced by ``?``,
``*`` or a bracket class (gate 3 round 1, B1). A shorter word - the business initials - is found
only standing alone (no letter or digit either side, any case), so a base64 hash that happens to
hold the letters does not match.

A word that holds a separator (``-``, ``_``, a space or ``.``) is also found with any of those in
its place, or none.

A file that is a zip container (a workbook, a document) is searched member by member, and a
finding names the member: ``book.xlsx!docProps/core.xml`` (gate 3 round 2, finding 1).

**The client's identifiers** (task -9, Director 10/10/2026) are a separate set, ``client_findings``,
found without this file naming any of them: its register and P6 export names by words built from
parts, its register versions and job number by shape, and its project acronym by the hash of the
word standing alone. In a file that is neither text nor a zip, the shapes and the hash are searched
only in runs of printable characters, so compressed image bytes do not match a three-letter word.
"""
from __future__ import annotations

import hashlib
import io
import re
import socket
import zipfile
from pathlib import Path

#: Built, not typed, so this file does not carry what it checks for.
NOTE_APP = "Obsi" + "dian"
THIRD_PARTY = "Wou" + "ter"  # a third party's first name (Director, 09/10/2026)
BUSINESS = ("S" + "JP Consulting", "S" + "JP")  # a registered business name, and its initials
#: A value read at run time and shorter than this is not searched for: a two-letter host name
#: would match everywhere. The fixed names are chosen, so the floor does not apply to them.
MIN_NEEDLE = 4
#: A glob character standing in for one letter still names the word.
_STAND_IN = r"(?:\?|\*|\[[^\]\n]{1,8}\])"
#: Separators: one in a word may be any of these, or absent.
_SEPARATORS = "-_ ."
_ZIP = b"PK\x03\x04"

#: The client's register and P6 export names, as words.
CLIENT_WORDS = {
    "client register name": ["Quant" + "_Reg", "RO Reg " + "WS3"],
    "client export name": ["Issue for " + "Internal Review", "Issue for " + "Submission"],
}


class _Hashed:
    """A three-letter word found by its SHA-256 (of the word in capitals), standing alone, any case."""

    _WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}(?![A-Za-z0-9])")

    def __init__(self, digest: str) -> None:
        self.digest = digest

    def search(self, text: str) -> bool:
        return any(hashlib.sha256(w.upper().encode()).hexdigest() == self.digest
                   for w in set(self._WORD.findall(text)))


#: The client's identifiers found by shape or hash. A job number is two digits, three digits and
#: an E, separated or not, glued to what follows only by a letter that is not hex (a file name made
#: into a slug), and not after ``#`` (a colour such as ``#92400e``). A register version is a V, a
#: number and "val".
CLIENT_SHAPES = {
    "client job number": re.compile(r"(?<![A-Za-z0-9#])\d{2}[-_ .]?\d{3}[-_ .]?e(?![0-9a-f])", re.I),
    "client register version": re.compile(r"(?<![A-Za-z0-9])v\d{1,2}[-_ .]?val(?![a-z])", re.I),
    "client project acronym": _Hashed("9fc997d079e5e5786048c5acbd2d1e51"
                                      "0333caadf3a75acbb75234703bbee3f6"),
}
_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{8,}")


def needles(machines: tuple[str, ...] = ()) -> dict[str, list[str]]:
    """What no shipped file may contain, by check: this machine's values, read here, plus
    ``machines`` (other build machines' names, which the caller holds)."""
    home = str(Path.home())
    read = {
        "machine name": sorted({socket.gethostname(), *machines}),
        "home folder": sorted({home, home.replace("\\", "/"), home.replace("\\", "\\\\")}),
    }
    found = {check: [w for w in words if len(w) >= MIN_NEEDLE] for check, words in read.items()}
    return found | {"note app": [NOTE_APP], "third party": [THIRD_PARTY], "business name": list(BUSINESS)}


def _squash(text: str) -> str:
    """``text`` without separators: the space in which a word's keys are whole."""
    return text.translate({ord(c): None for c in _SEPARATORS})


def _keys(word: str) -> list[str]:
    """Literals of which every match, with its separators removed, holds one: the word itself if
    short, else the two halves of the word without separators (one stand-in leaves one half whole)."""
    if len(word) < MIN_NEEDLE:
        return [word.lower()]
    bare = _squash(word).lower()
    half = (len(bare) + 1) // 2
    return [bare[:half], bare[half:]]


def _spelled(part: str) -> str:
    return "".join("[-_ .]?" if c in _SEPARATORS else re.escape(c) for c in part)


def pattern(word: str) -> re.Pattern[str]:
    """``word`` in any case: standing alone if short, else as typed or with any one character
    replaced by ``?``, ``*`` or a bracket class such as ``[o]``, and any separator in it replaced
    or dropped."""
    if len(word) < MIN_NEEDLE:
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", re.I)
    alts = [_spelled(word)] + [_spelled(word[:i]) + _STAND_IN + _spelled(word[i + 1:])
                               for i in range(len(word))]
    return re.compile("|".join(alts), re.I)


def _members(data: bytes) -> list[tuple[str, bytes]] | None:
    """A zip container's members, or None when ``data`` is not one."""
    if not data.startswith(_ZIP):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir()]
    except zipfile.BadZipFile:
        return None


def _is_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def file_findings(path: str, data: bytes, words: dict[str, list[str]], shapes: dict | None = None) -> list[str]:
    """``"<check>: <path>:<line>"`` for each needle in ``data``, typed or disguised, and for each of
    ``shapes`` (a check's pattern or hash); inside a zip container, per member, as
    ``<path>!<member>:<line>``."""
    members = _members(data)
    if members is not None:
        return [f for name, body in members for f in file_findings(f"{path}!{name}", body, words, shapes)]
    out = []
    bare = data.lower().translate(None, _SEPARATORS.encode())
    lines = None
    for check, ws in words.items():
        for w in ws:
            keys = _keys(w)
            if not any(k.encode("utf-8") in bare for k in keys):
                continue
            if lines is None:
                lines = data.decode("utf-8", errors="replace").lower().splitlines()
            pat = pattern(w)
            line = next((i for i, ln in enumerate(lines, 1)
                         if any(k in _squash(ln) for k in keys) and pat.search(ln)), None)
            if line is not None:
                out.append(f"{check}: {path}:{line}")
    if shapes:
        text = data.decode("utf-8") if _is_text(data) else "\n".join(
            r.decode("ascii") for r in _PRINTABLE_RUN.findall(data))
        for check, shape in shapes.items():
            if shape.search(text):
                line = next(i for i, ln in enumerate(text.splitlines(), 1) if shape.search(ln))
                out.append(f"{check}: {path}:{line}")
    return list(dict.fromkeys(out))  # a name and its initials on one line are one finding


def client_findings(path: str, data: bytes) -> list[str]:
    """The client's identifiers in ``data`` (task -9): see the module's docstring."""
    return file_findings(path, data, CLIENT_WORDS, CLIENT_SHAPES)
