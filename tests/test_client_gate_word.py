"""PRERELEASE-01 P2: a `word:` term matches only where it stands alone.

A three-letter client acronym entered as a plain term hits inside ordinary words and, by chance,
inside the compressed bytes of shipped PNGs, which the BINARY limb cannot allowlist. The `word:`
prefix makes such a term match only when no letter or digit flanks it on either side, in the
TERM, FILENAME and BINARY limbs. A plain entry keeps its substring behaviour.

Each test runs the gate's own `main()` on a tree with no `.git`, which walks the tree in full and
shells out to nothing. The term is made up; the real one is never written here.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import client_gate  # noqa: E402

TERM = "qzx"


def _gate(tmp_path: Path, monkeypatch, capsys, entry: str, text: str, name: str, blob: bytes):
    """Build a tree with one text file and one binary, run the gate, return (exit, hit limbs)."""
    root = tmp_path / "tree"
    root.mkdir()
    (root / ".gitignore").write_bytes(b"terms.local.txt\n")
    (root / name).write_bytes(text.encode("utf-8"))
    (root / "fig.bin").write_bytes(b"\0\0" + blob + b"\0")
    terms = tmp_path / "terms.local.txt"
    terms.write_bytes(f"{entry}\n".encode("utf-8"))
    digest = tmp_path / "list.digest"
    # The gate hashes the list with trailing whitespace stripped (client_gate.load_terms).
    digest.write_bytes(hashlib.sha256(entry.encode("utf-8")).hexdigest().encode() + b"\n")
    monkeypatch.setattr(sys, "argv", ["client_gate.py", "--root", str(root),
                                      "--terms", str(terms), "--digest", str(digest)])
    code = client_gate.main()
    out = capsys.readouterr().out
    hits = out.split("\nHITS:", 1)[1].split("\nGATE:", 1)[0] if "\nHITS:" in out else ""
    limbs = {line.split()[0] for line in hits.splitlines() if line.strip()}
    return code, limbs


@pytest.mark.parametrize("limb, text, name, blob", [
    ("TERM", f"the {TERM} export", "notes.txt", b"nothing"),
    ("FILENAME", "nothing", f"{TERM}_notes.txt", b"nothing"),
    ("BINARY", "nothing", "notes.txt", f"\x01{TERM}\x02".encode()),
])
def test_a_word_term_standing_alone_reds_its_limb(tmp_path, monkeypatch, capsys, limb, text, name, blob):
    code, limbs = _gate(tmp_path, monkeypatch, capsys, f"word:{TERM}", text, name, blob)
    assert code == 1 and limbs == {limb}, (code, limbs)


@pytest.mark.parametrize("text, name, blob", [
    (f"the a{TERM}b export", "notes.txt", b"nothing"),
    ("nothing", f"a{TERM}9.txt", b"nothing"),
    ("nothing", "notes.txt", f"\x01Z{TERM}7\x02".encode()),
])
def test_a_word_term_inside_a_word_stays_green(tmp_path, monkeypatch, capsys, text, name, blob):
    code, limbs = _gate(tmp_path, monkeypatch, capsys, f"word:{TERM}", text, name, blob)
    assert code == 0 and limbs == set(), (code, limbs)


def test_a_word_term_matches_any_case(tmp_path, monkeypatch, capsys):
    code, limbs = _gate(tmp_path, monkeypatch, capsys, f"word:{TERM}", f"the {TERM.upper()} export",
                        "notes.txt", b"nothing")
    assert code == 1 and limbs == {"TERM"}, (code, limbs)


def test_a_plain_term_still_matches_as_a_substring(tmp_path, monkeypatch, capsys):
    """Every existing entry is plain; its behaviour must not change with the prefix's arrival."""
    code, limbs = _gate(tmp_path, monkeypatch, capsys, TERM, f"the a{TERM}b export",
                        f"a{TERM}9.txt", f"\x01Z{TERM}7\x02".encode())
    assert code == 1 and limbs == {"TERM", "FILENAME", "BINARY"}, (code, limbs)


def test_a_word_entry_and_an_equal_plain_entry_keep_their_own_labels(tmp_path, monkeypatch, capsys):
    """WordTerm is a str: keyed by term, `word:X` and plain `X` shared one label (review WARN)."""
    root = tmp_path / "tree"
    root.mkdir()
    (root / ".gitignore").write_bytes(b"terms.local.txt\n")
    (root / "notes.txt").write_bytes(f"the {TERM} export".encode())
    (root / "fig.bin").write_bytes(b"\0\0nothing\0")
    entries = f"word:{TERM}\n{TERM}"
    terms = tmp_path / "terms.local.txt"
    terms.write_bytes(entries.encode())
    digest = tmp_path / "list.digest"
    digest.write_bytes(hashlib.sha256(entries.encode()).hexdigest().encode() + b"\n")
    monkeypatch.setattr(sys, "argv", ["client_gate.py", "--root", str(root),
                                      "--terms", str(terms), "--digest", str(digest)])
    assert client_gate.main() == 1
    out = capsys.readouterr().out
    assert "<- term[0]" in out and "<- term[1]" in out


def test_a_non_ascii_letter_is_a_boundary(tmp_path, monkeypatch, capsys):
    """Under re.I a Unicode pattern folds LATIN SMALL LETTER LONG S into [A-Za-z]; the gate
    promises a non-ASCII letter is a boundary, so the rule errs towards red (review NOTE)."""
    code, limbs = _gate(tmp_path, monkeypatch, capsys, f"word:{TERM}", f"the \u017f{TERM} export",
                        "notes.txt", b"nothing")
    assert code == 1 and limbs == {"TERM"}, (code, limbs)
