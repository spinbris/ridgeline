"""PUBLICFACE-01 P7: no third-party name in what the snapshot ships.

``src/``, ``dashboard/``, ``templates/``, ``scripts/`` and ``tests/`` carry no third party's initials, in
any case, in any text file that ships (gate 3 round 1, N11: the private files under them are left to
the private repository). Where a test needs the value, it is built from parts. The
sha512 integrity hashes inside ``dashboard/package-lock.json`` are the one place the letters can
occur by chance, so that file is read with hash-shaped runs removed.

Binary files are out of this test's reach by construction: a workbook's parts are compressed, so a
text search cannot see inside one. The templates' and fixtures' creator is read from
``docProps/core.xml`` by the P5 test, which is where the property is shown.
"""
from __future__ import annotations

import re
from pathlib import Path

import scripts.release.snapshot_manifest as m

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("src", "dashboard", "templates", "scripts", "tests")
SKIP_DIRS = {"node_modules", ".next", "__pycache__", "out", "public"}
HASH_RUN = re.compile(r"sha\d+-[A-Za-z0-9+/=]{20,}")
#: Built from parts, so this file does not carry what it checks for.
THIRD_PARTY = re.compile("s" + "jp", re.I)


def third_party_hits(repo: Path) -> list[str]:
    hits: list[str] = []
    for root in ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(repo)
            if not path.is_file() or SKIP_DIRS & set(rel.parts) or m.classify(rel.as_posix()) != m.SHIP:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # a binary file; see the module note
            if path.name == "package-lock.json":
                text = HASH_RUN.sub("", text)
            for number, line in enumerate(text.splitlines(), 1):
                if THIRD_PARTY.search(line):
                    hits.append(f"{path.relative_to(repo).as_posix()}:{number}")
    return hits


def test_the_scan_can_fail(tmp_path):
    """Plant a name in each tree and one inside a lockfile hash; only the real ones are found."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1  # " + "S" + "JP theme\n", encoding="utf-8")
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "package-lock.json").write_text(
        '{"integrity": "sha512-AAAAAAAAAAAAAAAA' + "s" + 'jpAAAAAAAAAAAAAAAAAAAAA=="}\n', encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "t.txt").write_text("prepared by " + "s" + "jp_theme\n", encoding="utf-8")
    for tree in ("scripts", "tests"):
        (tmp_path / tree).mkdir()
        (tmp_path / tree / "b.py").write_text("LABEL = '" + "S" + "JP indicative'\n", encoding="utf-8")
    private = next(p for p, (cls, _) in m.MANIFEST.items()  # a private script, named by the manifest
                   if cls == m.PRIVATE and p.startswith("scripts/") and p.endswith(".py"))
    (tmp_path / private).write_text("S" + "JP\n", encoding="utf-8")  # not scanned: private
    planted = [f"{tree}/{name}:1" for tree, name in
               (("src", "a.py"), ("templates", "t.txt"), ("scripts", "b.py"), ("tests", "b.py"))]
    assert sorted(third_party_hits(tmp_path)) == sorted(planted)


def test_the_snapshot_trees_name_no_third_party():
    hits = third_party_hits(REPO)
    assert hits == [], f"a third-party name remains: {hits}"
