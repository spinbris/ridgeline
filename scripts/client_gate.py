"""Client-material gate.

Fails the build if any client term, absolute path, username, or confidential
value reaches the tree. Runs locally and in CI against the same term list, which
is never tracked.

    python scripts/client_gate.py [--root .] [--terms terms.local.txt]

Hits name a LABEL (term[i] / value[i]), never the matched literal: a red in a
CI log must not publish the material the gate protects.

Exit 0 = green, 1 = red. Red on any hit outside the allowlist, on any limb that
scanned zero files, or on a term list whose digest does not match the committed
digest (--digest).

LIMBS
  A term matches as a case-insensitive substring; a `word:` term only where it
  stands alone (WordTerm), in TERM, FILENAME and BINARY alike.
  TERM      literal client terms, text files only
  FILENAME  the same terms, plus the operator username, in path names
  BINARY    every member of every zip container, plus a raw byte scan of every
            other binary. Binaries reach this limb ONLY and never a text
            pattern (D-RSA-2c item 2)
  PATH      absolute drive paths in raw AND source-escaped form, and UNC paths.
            The operator username is NOT here: it is a term, so TERM and
            FILENAME carry it. The plant caught this gate documenting a
            username check on PATH that it did not implement.
  OUTSIDE   parent-directory references that resolve outside the repo root
  VALUE     confidential figures, expanded to every digit-separator form

WHY THE TERM LIST IS NOT IN THIS FILE
  The terms and the values are themselves the confidential material. They live
  in terms.local.txt, which .gitignore excludes, and in CI as a repository
  secret. Its digest IS committed (--digest), and the gate refuses to run if the loaded
  list does not match it -- so a truncated, stale or empty list REDS rather than
  greening, which is the failure mode that would otherwise be silent.

WHY A LIMB THAT SCANS ZERO FILES IS RED
  A limb that scans nothing reports no hits and looks identical to a clean
  tree. That is the defect this gate exists to catch, so it is checked here too.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys
import zipfile
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# DIGESTFALLBACK-01: every git call here finds its repository from the path it asks about,
# never from a GIT_DIR a hook exported. src.git_identity is standard library only.
# A wrong-repository listing here is a wrong gate verdict.
from src.git_identity import git_env  # noqa: E402

BS = chr(92)
ZIPEXT = {".zip", ".docx", ".xlsx", ".xlsm", ".pptx", ".odt", ".ods"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}

DRIVE_RAW = re.compile(r"[A-Za-z]:" + re.escape(BS) + r"Users", re.I)
DRIVE_ESC = re.compile(r"[A-Za-z]:" + re.escape(BS * 2) + r"Users", re.I)
# two components of two or more characters each (D-RSA-2c item 1)
# SELF-CONTAINMENT limb (CONSOLIDATE-01 step 7). This repository references nothing
# outside its own root. The RS-A scrub RENAMED cross-repo paths instead of cutting
# them, so eight references to a sibling that has never existed survived the cut and
# read, to anyone opening the repo, as evidence that such a sibling exists. A parent
# traversal in a tracked file is the shape that carries it.
# GATEPARENT-01: the whole run of `../` before the first segment, resolved as one. Matching a
# single `../` let `..` stand as the segment, so a three-level climb to `x` stopped after two - inside the root
# from two levels down - and the climb out beyond it was never tested. Stated blind spots (build
# review, GATEPARENT-02): backslash and mixed-separator climbs, a doubled slash (`..//`), a single
# climb from the root followed by a character outside [A-Za-z0-9._-] (`@`, `~`, `(`), URL-encoded
# separators, and a bare `..` with nothing after it. Descending segments before a climb are
# ignored, so `docs/../x` reds although it stays inside - an error on the safe side.
PARENT_REF = re.compile(r"(?<![.\w])(?:\.\./)+[A-Za-z0-9._-]+")

UNC = re.compile(re.escape(BS * 2) + r"[A-Za-z0-9._-]{2,}" + re.escape(BS)
                 + r"[A-Za-z0-9._$-]{2,}")


def outside_refs(text: str, file_path: Path, root: Path) -> list[str]:
    """Every parent traversal in ``text`` that, read from ``file_path``, resolves outside ``root``.

    The SELF-CONTAINMENT limb's rule, as a function so it can be tested without a repository.
    ``root`` must already be resolved.
    """
    found = []
    for m in PARENT_REF.finditer(text):
        target = (file_path.parent / m.group(0)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            found.append(m.group(0))
    return found


class WordTerm(str):
    """A `word:` entry: it matches only where it stands alone (PRERELEASE-01).

    A plain term is a case-insensitive substring, so a three-letter acronym hits inside ordinary
    words and, by chance, inside compressed image bytes - which the BINARY limb cannot allowlist.
    A word term matches only where no ASCII letter or digit sits immediately before or after it,
    in the TERM, FILENAME and BINARY limbs. Anything else is a boundary, a non-ASCII letter
    included, so the rule errs towards red. One exception: the limbs lower-case text first, and
    a few non-ASCII letters lower-case to ASCII ones (the Kelvin sign becomes `k`), so those
    flank as the ASCII letter they become.

    On a binary it is checked on the raw bytes, where a flank is an ASCII letter or digit BYTE
    and any other byte (punctuation, a control byte, a byte of a multi-byte character) counts as
    a boundary; and, as the other limbs read binaries, on the UTF-16-LE decoding too. It is not
    checked on the UTF-8 decoding: that drops undecodable bytes, which can join a letter to the
    term and hide a match the raw bytes show.
    """

    def __new__(cls, word: str) -> "WordTerm":
        obj = super().__new__(cls, word)
        obj.text_re = re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])",
                                 re.I | re.ASCII)
        obj.byte_re = re.compile(rb"(?<![A-Za-z0-9])" + re.escape(word.encode("utf-8"))
                                 + rb"(?![A-Za-z0-9])", re.I)
        return obj


def term_in(term: str, low: str) -> bool:
    """Does ``term`` occur in ``low`` (already lower-cased): standing alone for a WordTerm, as a
    substring otherwise - the plain behaviour every entry had before the prefix."""
    if isinstance(term, WordTerm):
        return term.text_re.search(low) is not None
    return term.lower() in low


def term_in_blob(term: str, blob: bytes, decoded: str) -> bool:
    """The BINARY limb's question for one term; ``decoded`` is ``decode_any(blob).lower()``, made once.

    See WordTerm for what a word term does on bytes.
    """
    if isinstance(term, WordTerm):
        return (term.byte_re.search(blob) is not None
                or term_in(term, blob.decode("utf-16-le", errors="ignore").lower()))
    return term_in(term, decoded)


def load_terms(path: Path, digest_file: Path) -> tuple[list[str], list[str], str]:
    """Return (literal terms, expanded value patterns, digest).

    A line beginning `word:` is a term that matches only standing alone (WordTerm).

    A line beginning `num:` is a figure: the gate expands it to the plain,
    comma-separated and underscore-separated forms, because a value limb that
    knows only one of the three scans every file and greens on the others.
    """
    raw = path.read_bytes()
    # Hash a NORMALISED form: CRLF -> LF, and trailing whitespace stripped.
    #
    # The digest has to survive the transport, not just the file. GitHub strips
    # the trailing newline when it stores a secret, so a byte-exact digest over
    # the local file reds in CI on a list that is entirely correct. That is a
    # false red, and a false red on a mandatory gate is how a gate gets turned
    # off. Normalising costs nothing in detection: every term sits on its own
    # line, so truncation, staleness and substitution all still move the digest.
    # Found by CI on the first run that had the secret.
    norm = raw.replace(b"\r\n", b"\n").rstrip()
    digest = hashlib.sha256(norm).hexdigest()
    if digest_file.exists():
        want = digest_file.read_text(encoding="utf-8").split()[0].strip()
        if want != digest:
            print(f"RED: term list digest mismatch\n"
                  f"     loaded {digest}\n     want   {want}\n"
                  f"     the list is truncated, stale, or the wrong file.")
            sys.exit(1)
    else:
        print(f"RED: {digest_file.name} is missing; the loaded list cannot be checked.")
        sys.exit(1)

    terms, values, numeric = [], [], []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("num:"):
            n = line[4:].strip()
            plain = n.replace(",", "").replace("_", "")
            values.append(plain)
            head = plain.split(".")[0]
            if len(head) > 3:
                grouped = f"{int(head):,}"
                values.append(grouped)
                values.append(grouped.replace(",", "_"))
            # DERIVED-VALUE limb. A figure computed FROM a confidential value
            # discloses it: 5% of a contract TOC, printed beside max_reward_pct,
            # gives the TOC back by one division. An exact-match limb on the
            # enumerated figures cannot see those, and one shipped at 5556b72
            # (tests/test_gain_pain.py, 5% and 10% of the TOC).
            #
            # This is a PROPERTY, not a longer list: common contract fractions of
            # each figure are generated here rather than typed. Round products are
            # dropped - a value ending in many zeros is ordinary arithmetic and
            # would fire on everything.
            numeric.append(float(plain))
        elif line.startswith("val:"):
            # a value that is only ever written one way, e.g. a $X.XXM headline.
            # Kept literal so the limb does not fire on every bare decimal.
            values.append(line[4:].strip())
        elif line.startswith("word:"):
            if not line[5:].strip():
                # An empty word matches everywhere: one label, the whole tree red, no way to see why.
                print("RED: a `word:` line in the term list is empty.")
                sys.exit(1)
            terms.append(WordTerm(line[5:].strip()))
        else:
            terms.append(line)
    # ONE generator, shared with scripts/derived_value_audit.py. Two generators
    # would drift, and the one that drifted would be the one nobody ran. If the
    # import fails the gate REDS rather than silently narrowing its own coverage.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from derived_value_audit import derived_set
    except Exception as exc:                                  # pragma: no cover
        print(f"RED: cannot load the derived-value generator ({exc}). "
              f"The gate will not run with narrower coverage than it claims.")
        sys.exit(1)
    values.extend(derived_set(numeric).keys())
    return terms, sorted(set(values)), digest


def load_allow(root: Path) -> set[str]:
    p = root / "gate_allow.txt"  # link-rule: the client gate reads its allowlist file when the repository it guards has one
    allow = {"gate_allow.txt"}  # link-rule: the client gate does not scan its own allowlist file as a finding
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                allow.add(line)
    return allow


def _git_visible(root: Path):
    """Every path git could commit: tracked, plus untracked-and-not-ignored.

    ONLY the repository's own `.gitignore` files decide "ignored". The first
    draft used `--exclude-standard`, which also honours `.git/info/exclude` and
    the operator's global `core.excludesFile` - so the scope of a governance
    control would have differed silently from machine to machine and been
    unauditable from the repo (GATESCOPE-01 review, W1). `--exclude-per-directory`
    reads `.gitignore` at every level and nothing else; the scope is now the
    same everywhere and can be read off the tree. A tracked file that also
    matches an ignore pattern IS listed (`--cached`; tracked wins) and is
    scanned, because it can be committed.

    Known edge, not exercised (review N3): `--others` stops at a directory that
    contains its own `.git`, so a repository nested inside the tree is not
    walked. The parent cannot commit its files as content, which is the
    property this scope protects, but it is narrower than the old full walk.

    Returns None when root is not a git repository or git cannot answer, and
    the caller falls back to a full filesystem walk - wider, not narrower, on
    error. That fallback is what the RS-A cut used on a copied tree before
    `git init`, and it stays.
    """
    if not (root / ".git").exists():
        return None
    import subprocess
    r = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
         "--exclude-per-directory=.gitignore"],
        capture_output=True, env=git_env(),
    )
    if r.returncode != 0:
        return None
    # surrogateescape: a path git can list but Python cannot decode still reaches
    # the read_bytes() below and fails there as OSError, not as a traceback here.
    return [root / p.decode("utf-8", errors="surrogateescape")
            for p in r.stdout.split(b"\0") if p]


def walk(root: Path, exclude: set[Path]):
    """Everything git could commit, except the gate's own input.

    SCOPE (GATESCOPE-01, Director ruling 03/09/2026: "gate respects gitignore").
    The gate protects what can be committed. It therefore scans what git could
    commit - tracked files (even where they match an ignore pattern: tracked
    wins) and untracked files that the repository's `.gitignore` does not
    exclude. An untracked file under an ignored path is not scanned. Two
    working files forced the ruling: a register
    workbook that Excel re-stamps with the operator's machine path on every
    save, and regenerated showcase figures whose compressed bytes coincide with
    a four-character term. Both live under ignored paths, neither can ever be
    committed, and both redded the gate - which is how a gate stops being read.
    An untracked file that is NOT ignored is still scanned, because it is one
    `git add` from being committed. The mode is printed on every run so a
    reader knows which scope a GREEN certifies.

    Without a `.git` the whole tree is walked, as before. That is the mode the
    RS-A cut ran in, on a copied tree before the repository existed, and a tree
    with no ignore rules has nothing to respect.

    The term list is excluded BY RESOLVED PATH, not by name: an instrument is
    not measured by itself (D-RSA-2c item 3, which named the allowlist and
    applies identically here). Excluding it by name would also let a committed
    copy under any other name go unseen. The list not being tracked is enforced
    separately, by assert_terms_untracked, so this exclusion cannot become a
    hiding place.
    """
    visible = _git_visible(root)
    if visible is None:
        print("scope: full tree (no git repository at root; nothing to respect)")
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            candidates.extend(Path(dirpath) / fn for fn in filenames)
    else:
        print("scope: git-visible files - tracked and untracked-not-ignored (GATESCOPE-01)")
        # Relative to root: a checkout that happens to live under a directory
        # named `venv` or `node_modules` must not empty the scan (review N1).
        candidates = [p for p in visible
                      if not (set(p.relative_to(root).parts) & SKIP_DIRS)]

    text, binary = [], []
    for p in candidates:
        if p.resolve() in exclude:
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if p.suffix.lower() in ZIPEXT or b"\0" in raw[:8192]:
            binary.append(p)
        else:
            text.append(p)
    return sorted(text), sorted(binary)


def decode_any(blob: bytes) -> str:
    return "\n".join(blob.decode(e, errors="ignore")
                     for e in ("utf-8", "utf-16-le"))


def assert_terms_untracked(root: Path, terms: Path) -> bool:
    """The term list must not be, and must not become, a tracked file.

    walk() skips the list so the gate does not read its own input back as a
    finding. That exclusion is only safe while the list genuinely cannot be
    committed, so the condition is checked rather than assumed: git must report
    it as ignored, and once a repository exists it must not be tracked.
    """
    import subprocess
    name = terms.name
    ok = True
    gi = root / ".gitignore"
    if not gi.exists() or name not in gi.read_text(encoding="utf-8"):
        print(f"RED: {name} is not named in .gitignore; it could be committed.")
        ok = False
    if (root / ".git").exists():
        r = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", name],
                           capture_output=True, env=git_env())
        if r.returncode == 0:
            print(f"RED: {name} is TRACKED. The confidential list is in the repository.")
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--terms", default=os.environ.get("CLIENT_GATE_TERMS", "terms.local.txt"))
    ap.add_argument("--digest", default="terms.sha256")  # link-rule: the client gate's default digest file, which the guarded repository keeps
    args = ap.parse_args()

    root = Path(args.root).resolve()
    terms, values, digest = load_terms(Path(args.terms), root / args.digest)
    allow = load_allow(root)

    print(f"client gate | root {root}")
    print(f"term list digest {digest[:16]}... matches {args.digest}: OK")
    print(f"terms loaded: {len(terms)}   value patterns loaded: {len(values)}")
    # The matched literal is NEVER printed: a red in a CI log would otherwise
    # publish the exact material this gate exists to protect. Hits name a
    # stable label instead; the operator holds the list and can map it back.
    # By position, not by term: a `word:X` entry and a plain `X` are equal as strings, and a
    # dict keyed on the term would give both one label (PRERELEASE-01 review).
    tlab = [f"term[{i}]" for i in range(len(terms))]
    vlab = {v: f"value[{i}]" for i, v in enumerate(values)}
    print("allowlist (printed on every run, per brief s3):")
    for a in sorted(allow):
        print(f"    {a}")
    print()

    terms_path = Path(args.terms).resolve()
    red_pre = not assert_terms_untracked(root, terms_path)

    text, binary = walk(root, exclude={terms_path})
    scanned = {}
    hits: list[tuple[str, str, str]] = []

    # ---- TERM, text only
    n = 0
    for p in text:
        r = p.relative_to(root).as_posix()
        if r in allow:
            continue
        n += 1
        low = p.read_text(encoding="utf-8", errors="ignore").lower()
        for i, t in enumerate(terms):
            if term_in(t, low):
                hits.append(("TERM", r, tlab[i]))
    scanned["TERM"] = n

    # ---- FILENAME, every file
    n = 0
    for p in text + binary:
        n += 1
        r = p.relative_to(root).as_posix()
        low = r.lower()
        for i, t in enumerate(terms):
            if term_in(t, low):
                hits.append(("FILENAME", r, tlab[i]))
    scanned["FILENAME"] = n

    # ---- BINARY, member walk plus raw bytes
    n = 0
    for p in binary:
        n += 1
        r = p.relative_to(root).as_posix()
        raw = p.read_bytes()
        blobs = {}
        if p.suffix.lower() in ZIPEXT and zipfile.is_zipfile(io.BytesIO(raw)):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    for m in z.namelist():
                        try:
                            blobs[m] = z.read(m)
                        except Exception:
                            continue
            except Exception:
                blobs["<unreadable container>"] = raw
        else:
            blobs["<raw bytes>"] = raw
        for member, blob in blobs.items():
            low = decode_any(blob).lower()
            for i, t in enumerate(terms):
                if term_in_blob(t, blob, low):
                    hits.append(("BINARY", f"{r}::{member}", tlab[i]))
            for v in values:
                if v.lower() in low:
                    hits.append(("BINARY", f"{r}::{member}", vlab[v]))
    scanned["BINARY"] = n

    # ---- PATH, text only
    n = 0
    for p in text:
        r = p.relative_to(root).as_posix()
        if r in allow:
            continue
        n += 1
        s = p.read_text(encoding="utf-8", errors="ignore")
        if DRIVE_RAW.search(s):
            hits.append(("PATH", r, "drive-raw"))
        if DRIVE_ESC.search(s):
            hits.append(("PATH", r, "drive-escaped"))
        if UNC.search(s):
            hits.append(("PATH", r, "unc"))
    scanned["PATH"] = n

    # ---- SELF-CONTAINMENT, text only
    n = 0
    for p in text:
        r = p.relative_to(root).as_posix()
        if r in allow:
            continue
        n += 1
        for ref in outside_refs(p.read_text(encoding="utf-8", errors="ignore"), p, root):
            hits.append(("OUTSIDE", r, ref))
    scanned["OUTSIDE"] = n

    # ---- VALUE, text only
    n = 0
    for p in text:
        r = p.relative_to(root).as_posix()
        if r in allow:
            continue
        n += 1
        s = p.read_text(encoding="utf-8", errors="ignore")
        for v in values:
            if v in s:
                hits.append(("VALUE", r, vlab[v]))
    scanned["VALUE"] = n

    red = red_pre
    print("limb        files scanned   hits")
    for limb in ("TERM", "FILENAME", "BINARY", "PATH", "OUTSIDE", "VALUE"):
        h = [x for x in hits if x[0] == limb]
        zero = scanned[limb] == 0
        print(f"  {limb:9s} {scanned[limb]:8d}   {len(h):4d}"
              f"{'   RED: limb scanned zero files' if zero else ''}")
        red |= bool(h) or zero

    if hits:
        print("\nHITS:")
        for limb, where, what in hits:
            print(f"  {limb:9s} {where}  <- {what}")

    print("\nGATE:", "RED" if red else "GREEN")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
