"""P-A1: diff two pytest runs by per-node outcome, from their ``--junitxml``.

**The property this asserts.** Two runs of the same suite at the same commit
are equivalent iff they agree on *every node's outcome*: the same set of node
IDs, each with the same verdict. It is deliberately not a count comparison.
Two runs can agree on "5 failed, 2206 passed" while failing a different five,
and that ambiguity is exactly what the standing five forced on every close-out
in this repo before TESTLANE-01 converted them to strict ``xfail``. An empty
diff from this script is the evidence that ``GATE_INCREMENT_LANE`` may carry
``-n auto --dist loadgroup``; a non-empty one names the nodes that moved, which
is the list a person can act on.

**Why it lives in the repo rather than in a scratch directory.** It is the
instrument behind a gate, and a gate whose instrument cannot be re-run is a
claim rather than a check. Anyone re-proving parallel safety after touching the
``xdist_group`` derivation in ``tests/conftest.py`` runs this, and gets the same
answer the same way.

**Its own positive control.** ``--self-check`` builds two synthetic junit
documents that differ in exactly one node's outcome and requires this script to
report exactly one difference, then requires a document diffed against itself to
report none. A diff tool that has never been shown reporting a difference is
indistinguishable from one that always prints "EMPTY" - the shape the defect
register calls a check that cannot fail. Run it before trusting a green.

Usage::

    python tests/tools/outcome_diff.py A.xml B.xml
    python tests/tools/outcome_diff.py --self-check

Exit 0 and prints ``EMPTY`` when the outcome sets are identical.
"""
from __future__ import annotations

import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


_GROUP_SUFFIX = re.compile(r"@[A-Za-z0-9_.\-]+$")

#: How pytest opens the failure message of a strict XPASS. The prefix is the
#: verdict; the same string appearing later in a message is failure text.
_XPASS_STRICT = "[XPASS(strict)]"


def normalise_nodeid(nodeid: str) -> str:
    """Strip xdist's ``@<group>`` scheduling suffix, if present.

    Under ``--dist loadgroup`` xdist rewrites ``item._nodeid`` to
    ``<nodeid>@<group>`` so the controller can schedule on it, and that rewritten
    id is what lands in the junitxml. A serial run has no suffix. Comparing the
    two raw gives 367 nodes "only in serial" and the same 367 "only in parallel"
    with every outcome identical - a pure renaming reported as a total mismatch,
    which is a defect in this tool rather than in the suite.

    Stripping it is safe because the suffix is scheduling metadata, not identity:
    the same test has the same id either side of it. It is deliberately **not**
    silent - ``diff`` reports how many ids were normalised on each side, so a
    reader can see the transformation happened rather than trusting that it did.
    ``diff`` also refuses to continue if normalising collapses two distinct ids
    into one, which is the only way this could hide a real difference.
    """
    return _GROUP_SUFFIX.sub("", nodeid)


def outcomes(path: str | Path) -> dict[str, str]:
    """Map node ID -> verdict for one junitxml document.

    junit encodes xfail as a ``<skipped type="pytest.xfail">`` child rather than
    as a verdict of its own, so an xfail read naively counts as a skip and a
    strict XPASS counts as a plain failure. Both distinctions matter here: the
    STANDING5-02 nodes are xfails, and an XPASS is the signal that one of
    them started passing.

    **The XPASS verdict is structural, not a text search (Q5).** pytest reports a
    strict XPASS as a ``<failure>`` whose ``message`` *begins* ``[XPASS(strict)]``
    - verified against real junit output, not assumed. This first read the
    substring ``XPASS`` anywhere in every child message concatenated, which is a
    text search over failure text rather than a verdict. It fails in both
    directions: a test whose assertion message merely quotes the string reads as
    xpassed, so a genuine ``failed -> XPASS(strict)`` move - one of the standing
    five starting to pass, the single most consequential thing this instrument
    exists to catch - reports EMPTY and P-A1 is declared to hold across it;
    and an ordinary failure quoting the string reads as a difference that is not
    there. Control 5 in ``--self-check`` is that pair.
    """
    root = ET.parse(path).getroot()
    out: dict[str, str] = {}
    for tc in root.iter("testcase"):
        nodeid = normalise_nodeid(f"{tc.get('classname')}::{tc.get('name')}")
        verdict = "passed"
        for child in tc:
            if child.tag == "failure":
                message = child.get("message") or ""
                verdict = "xpassed" if message.startswith(_XPASS_STRICT) else "failed"
            elif child.tag == "error":
                verdict = "error"
            elif child.tag == "skipped":
                verdict = "xfailed" if child.get("type") == "pytest.xfail" else "skipped"
        out[nodeid] = verdict
    return out


def _raw_ids(path: str | Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [f"{tc.get('classname')}::{tc.get('name')}" for tc in root.iter("testcase")]


def diff(a_path: str | Path, b_path: str | Path, stream=sys.stdout) -> int:
    a, b = outcomes(a_path), outcomes(b_path)

    p0 = lambda *args: print(*args, file=stream)
    for label, path, mapped in (("A", a_path, a), ("B", b_path, b)):
        raw = _raw_ids(path)
        n_suffixed = sum(1 for r in raw if _GROUP_SUFFIX.search(r))
        if len(mapped) != len(raw):
            p0(f"ABORT: normalising {label} collapsed {len(raw)} ids into {len(mapped)}.")
            p0("Two distinct nodes now share an id, so a real difference could be hidden.")
            return 2
        p0(f"  {label}: {n_suffixed} of {len(raw)} ids carried an xdist @group suffix (normalised away)")
    p0("")
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    moved = sorted(n for n in set(a) & set(b) if a[n] != b[n])

    p = lambda *args: print(*args, file=stream)
    p(f"A = {a_path}  ({len(a)} nodes)")
    p(f"B = {b_path}  ({len(b)} nodes)")
    p("")
    p(f"NODES ONLY IN A: {len(only_a)}")
    for n in only_a:
        p(f"  {n}  [{a[n]}]")
    p(f"NODES ONLY IN B: {len(only_b)}")
    for n in only_b:
        p(f"  {n}  [{b[n]}]")
    p(f"OUTCOME MOVED: {len(moved)}")
    for n in moved:
        p(f"  {n}  {a[n]} -> {b[n]}")
    p("")

    # Tallies are printed for the record and are never the verdict.
    for label, d in (("A", a), ("B", b)):
        tally: dict[str, int] = {}
        for v in d.values():
            tally[v] = tally.get(v, 0) + 1
        p(f"  {label} tally: {dict(sorted(tally.items()))}")
    p("")

    if only_a or only_b or moved:
        p("DIFF NON-EMPTY - P-A1 does not hold")
        return 1
    p("EMPTY - outcome sets identical, P-A1 holds")
    return 0


_SYNTHETIC = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3">
<testcase classname="tests.test_a" name="test_one" time="0.1"/>
<testcase classname="tests.test_a" name="test_two" time="0.2">{two}</testcase>
<testcase classname="tests.test_b" name="test_three" time="0.3">
  <skipped type="pytest.xfail" message="STANDING5-02"/>
</testcase>
</testsuite></testsuites>
"""


def self_check() -> int:
    """Positive control: prove this script can report a difference at all."""
    rc = 0
    with tempfile.TemporaryDirectory() as d:
        same = Path(d, "same.xml")
        moved = Path(d, "moved.xml")
        same.write_text(_SYNTHETIC.format(two=""), encoding="utf-8")
        moved.write_text(
            _SYNTHETIC.format(two='<failure message="boom">boom</failure>'),
            encoding="utf-8",
        )

        print("--- control 1: a document against itself must report EMPTY ---")
        if diff(same, same) != 0:
            print("SELF-CHECK FAILED: identical documents did not report EMPTY")
            rc = 1

        print("--- control 2: one node's outcome edited must report exactly one line ---")
        a, b = outcomes(same), outcomes(moved)
        movedn = [n for n in set(a) & set(b) if a[n] != b[n]]
        if diff(same, moved) != 1:
            print("SELF-CHECK FAILED: edited document did not report a difference")
            rc = 1
        elif movedn != ["tests.test_a::test_two"] or a[movedn[0]] != "passed" or b[movedn[0]] != "failed":
            print(f"SELF-CHECK FAILED: wrong node or verdicts reported: {movedn}")
            rc = 1

        # The xfail node must not be mistaken for a skip in either document.
        if a["tests.test_b::test_three"] != "xfailed":
            print("SELF-CHECK FAILED: xfail read as something else")
            rc = 1

        # Control 3: a parallel run's @group suffix is a renaming, not a
        # difference. Without this the tool reports every grouped test as
        # "only in B" and P-A1 can never read empty - which is exactly how it
        # first behaved on the real lane pair.
        print("--- control 3: xdist @group suffix must normalise away, not read as a difference ---")
        grouped = Path(d, "grouped.xml")
        grouped.write_text(
            _SYNTHETIC.format(two="").replace('name="test_one"', 'name="test_one@outputs"'),
            encoding="utf-8",
        )
        if diff(same, grouped) != 0:
            print("SELF-CHECK FAILED: @group suffix read as a difference")
            rc = 1

        # ...but it must still not mask a real one on a suffixed node.
        print("--- control 4: a real change on a suffixed node must still surface ---")
        grouped_moved = Path(d, "grouped_moved.xml")
        grouped_moved.write_text(
            _SYNTHETIC.format(two='<failure message="boom">boom</failure>')
            .replace('name="test_one"', 'name="test_one@outputs"'),
            encoding="utf-8",
        )
        if diff(same, grouped_moved) != 1:
            print("SELF-CHECK FAILED: real difference masked by suffix normalisation")
            rc = 1

        # Control 5: the single most consequential move this instrument exists to
        # catch - one of the standing five starting to pass - against a failure
        # whose own message quotes the string. Both messages below are verbatim
        # pytest output, not invented: a strict XPASS is a <failure> whose
        # message *begins* "[XPASS(strict)]", and an ordinary assertion failure
        # can carry "XPASS" anywhere in its text. Read as a substring search over
        # the concatenated messages, both documents classify as xpassed, the diff
        # reports EMPTY and P-A1 is declared to hold across a real change.
        # (Q5, Reviewer 26/08; Director ruling 27/08.)
        print("--- control 5: 'XPASS' inside a failure message is not an XPASS verdict ---")
        quoted = Path(d, "quoted.xml")
        real_xpass = Path(d, "real_xpass.xml")
        quoted.write_text(
            _SYNTHETIC.format(
                two="<failure message=\"AssertionError: assert 'XPASS' not in "
                    "'no XPASS here'\">boom</failure>"
            ),
            encoding="utf-8",
        )
        real_xpass.write_text(
            _SYNTHETIC.format(
                two='<failure message="[XPASS(strict)] STANDING5-02 limb 2: '
                    'reads an untracked, gitignored April workbook">x</failure>'
            ),
            encoding="utf-8",
        )
        qa, qb = outcomes(quoted), outcomes(real_xpass)
        node = "tests.test_a::test_two"
        if qa[node] != "failed":
            print(f"SELF-CHECK FAILED: a failure quoting XPASS read as {qa[node]!r}")
            rc = 1
        if qb[node] != "xpassed":
            print(f"SELF-CHECK FAILED: a strict XPASS read as {qb[node]!r}")
            rc = 1
        if diff(quoted, real_xpass) != 1:
            print("SELF-CHECK FAILED: failed -> strict-XPASS reported as no change")
            rc = 1

    print("SELF-CHECK PASSED" if rc == 0 else "SELF-CHECK FAILED")
    return rc


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-check":
        sys.exit(self_check())
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(diff(sys.argv[1], sys.argv[2]))
