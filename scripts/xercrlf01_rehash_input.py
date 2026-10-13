"""XERCRLF-01: re-record one input's sha256 in a baseline fixture. No numbers move.

The two 10k baselines recorded the CRLF form of `tests/fixtures/synthetic_wind/
wind_schedule.xer`, because they were captured while the working copy was CRLF and the file
was re-checked-out LF in the same minute. Under this repository's `.gitattributes`
(`text=auto eol=lf`) git yields LF bytes, which hash differently, so the input-hash limb has
been red on master since.

The capture scripts cannot fix this: both re-run the engine end to end, and a re-run cannot
be told apart afterwards from a content change. This corrects the recorded digest and
nothing else, so the diff itself is the evidence that no simulated number moved.

**It refuses to record a digest that differs from the bytes git yields.** That guard is the
whole point: the original defect was recording a working copy whose line endings the
repository does not use, and a tool that can repeat that defect has not fixed it.

Run:  python scripts/xercrlf01_rehash_input.py --input xer
      python scripts/xercrlf01_rehash_input.py --input xer --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# DIGESTFALLBACK-01: every git call here finds its repository from the path it asks about,
# never from a GIT_DIR a hook exported. src.git_identity is standard library only.
from src.git_identity import git_env  # noqa: E402

#: The fixtures XERCRLF-01 names. Each records inputs under a single top-level block.
FIXTURES = (
    Path("tests/fixtures/qraxl01_0_baseline_10k.json"),
    Path("tests/fixtures/sra02_schedule_baseline_10k.json"),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(rel: str) -> bytes:
    """The bytes a fresh clone gets: the blob as `.gitattributes` renders it on checkout."""
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel}"],
        capture_output=True, check=True, env=git_env(),
    )
    return out.stdout


def _input_blocks(doc: dict) -> list[tuple[str, dict]]:
    """Every ``inputs`` mapping in the document, with the path that reaches it."""
    found: list[tuple[str, dict]] = []

    def walk(node, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "inputs" and isinstance(value, dict):
                    found.append((f"{trail}/inputs", value))
                else:
                    walk(value, f"{trail}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{trail}[{i}]")

    walk(doc, "")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True,
                    help="the input's key inside the fixture's `inputs` block, e.g. 'xer'")
    ap.add_argument("--check", action="store_true",
                    help="report and exit non-zero on a mismatch; write nothing")
    args = ap.parse_args()

    exit_code = 0
    for fixture in FIXTURES:
        path = REPO_ROOT / fixture
        doc = json.loads(path.read_text(encoding="utf-8"))
        blocks = [(trail, blk) for trail, blk in _input_blocks(doc) if args.input in blk]
        if not blocks:
            print(f"FAIL {fixture.as_posix()}: no `inputs` block carries {args.input!r}")
            return 2
        if len(blocks) > 1:
            print(f"FAIL {fixture.as_posix()}: {args.input!r} appears in {len(blocks)} blocks; "
                  "this script corrects one recorded digest, not several at once")
            return 2

        trail, block = blocks[0]
        spec = block[args.input]
        rel = spec["path"]
        on_disk = (REPO_ROOT / rel).read_bytes()
        from_git = _git_bytes(rel)
        if on_disk != from_git:
            print(f"REFUSING {fixture.as_posix()}: the working copy of {rel} is not the bytes "
                  f"git yields ({len(on_disk)} vs {len(from_git)} bytes; working copy carries "
                  f"{on_disk.count(chr(13).encode())} CR). Recording it would repeat XERCRLF-01. "
                  "Re-checkout the file and run again.")
            return 2

        was, now = spec["sha256"], _sha256(from_git)
        if was == now:
            print(f"OK   {fixture.as_posix()} {trail}/{args.input}: {now} (unchanged)")
            continue
        exit_code = 1
        print(f"{'DIFF' if args.check else 'WROTE'} {fixture.as_posix()} {trail}/{args.input}\n"
              f"       was {was}\n       now {now}")
        if not args.check:
            spec["sha256"] = now
            # newline="\n" - the fixture is a committed text file under `eol=lf`, and writing
            # it CRLF here is the same class of defect this script exists to correct.
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
            exit_code = 0

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
