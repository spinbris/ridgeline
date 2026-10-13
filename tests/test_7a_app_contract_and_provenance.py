"""Stage 7 part A: C-2 (the app's schema catches up) and D-3 (it displays what it receives).

**What these tests can and cannot do, stated plainly.** The dashboard has no test harness at all -
`dashboard/package.json` declares no test script and there is no test directory. Standing one up
is D-2, in part D, and it is most of part D's cost. Until then the only assertions available from
this side are over the app's *source text* and over its *built output* when a build exists.

Source-text assertions are weak: they prove a field is not declared, not that the running app
behaves. They are here because the alternative for the whole of part A is nothing, and because
both properties are about a declaration rather than a behaviour - C-2 removes a schema field, D-3
adds three reads. The real render gate is D-2's, and when it lands these should be revisited
rather than kept alongside it out of habit.

The last test carries the finding that came out of trying to do better: an assertion over the
built static export **cannot** see the footer, because the footer is a client component gated on
the period context. D-2 will need a DOM-level harness, not HTML matching. Part A's own
behavioural verification was done by loading the built export in a browser and reading the live
DOM - recorded in the running record, not automatable from here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
LOADER = REPO / "dashboard" / "lib" / "loadPeriod.ts"
TYPES = REPO / "dashboard" / "types" / "period.ts"
FOOTER = REPO / "dashboard" / "components" / "AppFooter.tsx"

#: RS-A2 P-3 dropped these from the contract; `src/am/_provenance.py:6` records the removal.
DROPPED_PIN_FIELDS = ("engine_sha_pinned", "engine_sha_matches_pin")

#: AM09's stamp: what a period JSON has been carrying, and what D-3 makes visible.
PROVENANCE_FIELDS = ("engine_sha", "engine_tree_dirty", "input_sha256")


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --- C-2: the validator stops accepting what no producer can send -----------------------------

@pytest.mark.parametrize("field", DROPPED_PIN_FIELDS)
@pytest.mark.parametrize("source", [LOADER, TYPES], ids=["zod_schema", "ts_type"])
def test_the_dropped_pin_fields_are_no_longer_declared(source: Path, field: str) -> None:
    """A validator that accepts a field its producer cannot emit has quietly stopped describing
    anything: it reads as a contract while gating nothing, and the next reader has to go to the
    engine to find out which half is true.

    Matched as a DECLARATION (`field:` at the start of a line), not as the bare word - both files
    now carry a comment explaining the removal, and a bare-word match would hit that comment and
    make this test unable to pass. That is the same self-reference trap the 3d weasyprint guard
    had to split a literal to avoid.
    """
    declaration = re.compile(rf"^\s*{re.escape(field)}\s*[?:]", re.M)
    hit = declaration.search(_text(source))
    assert hit is None, (
        f"{source.relative_to(REPO).as_posix()} still declares {field}, which RS-A2 P-3 dropped "
        f"from the contract")


@pytest.mark.parametrize("field", DROPPED_PIN_FIELDS)
def test_the_engine_could_not_emit_them_anyway(field: str) -> None:
    """The other half of C-2, and the reason removing them is safe rather than merely tidy: the
    writer copies a fixed tuple of provenance keys into meta, and these are not in it. Without
    this, C-2 would rest on a claim in a comment."""
    writer = _text(REPO / "src" / "am" / "json_writer.py")
    copied = re.search(
        r"if engine_provenance is not None:\s*\n\s*for key in \((?P<keys>.*?)\):",
        writer, re.S)
    assert copied, "the provenance copy loop in json_writer.py has moved; re-read it"
    assert field not in copied.group("keys"), (
        f"json_writer now copies {field} into meta, so removing it from the app schema would "
        f"reject a document the engine can produce")


# --- D-3: the app displays the provenance it already receives ---------------------------------

@pytest.mark.parametrize("field", PROVENANCE_FIELDS)
def test_the_footer_reads_every_provenance_field(field: str) -> None:
    """Before part A the footer showed `engine_run_hash` alone - a `uuid.uuid4()` minted per run
    (`src/am/json_writer.py:163`), which identifies an execution and nothing reproducible - while
    these three arrived in every period JSON and were rendered nowhere."""
    assert field in _text(FOOTER), f"AppFooter does not read meta.{field}"


def test_the_dirty_tree_flag_is_rendered_as_a_warning_not_a_value() -> None:
    """`engine_tree_dirty` is the one that mattered: a number produced by uncommitted code cannot
    be reproduced from the SHA displayed beside it. Printing `true` next to a label is not a
    warning - the reader has to already know what it means. This asserts the footer carries
    prose explaining the consequence, which is the part a reader can act on."""
    footer = _text(FOOTER)
    assert "uncommitted changes" in footer, "the dirty-tree flag has no reader-facing label"
    assert "cannot be" in footer and "reproduced" in footer, (
        "the dirty-tree warning does not say what it means for the figures")


def test_the_golden_actually_carries_what_the_footer_reads() -> None:
    """Guards the pairing rather than each side alone. A footer reading fields no artefact
    carries would render nothing and pass every source-text test above."""
    golden = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"
    meta = json.loads(golden.read_bytes().decode("utf-8"))["meta"]
    missing = [f for f in PROVENANCE_FIELDS if f not in meta]
    assert missing == [], f"the golden period JSON lacks {missing}"
    assert set(meta["input_sha256"]) == {"register", "xer", "workbook"}
    for name, digest in meta["input_sha256"].items():
        assert set(digest) == {"method", "value"}, f"{name} digest is not a {{method, value}} record"


# --- what a static-export assertion CANNOT reach, found while trying ------------------------

def test_the_footer_is_client_rendered_which_is_why_D2_needs_a_dom_harness() -> None:
    """A finding from part A, kept as a test so part D cannot be planned without it.

    The first version of this module tried to assert the provenance text in `dashboard/out/
    index.html` - the strongest check available without a JS harness. **It cannot work.** The
    footer is a client component that returns `null` until the period context reaches "ready"
    (`AppFooter.tsx`), so the exported HTML carries none of its text; the strings live only in a
    JS chunk (`out/_next/static/chunks/app/layout-*.js`), where matching them proves the source
    compiled and nothing about what renders.

    D-2's app-render gate therefore needs a **DOM-level harness that runs the client** - jsdom,
    or a headless browser - not HTML string matching over the export. That is a real cost in part
    D's estimate, and finding it here is cheaper than finding it there.

    Verified 05/09/2026 by loading the built export and reading the live DOM: the footer renders
    `engine 44a3d1b6`, an `uncommitted changes` warning, and `3 inputs digested` with the full
    digests and methods in its tooltips.
    """
    footer = _text(FOOTER)
    assert '"use client"' in footer, (
        "AppFooter is no longer a client component - if it now server-renders, the export CAN be "
        "asserted directly and D-2's harness may be cheaper than this test assumed")
    assert 'status.kind !== "ready"' in footer, (
        "the footer no longer gates on the period context; re-check whether its text reaches the "
        "static export before planning D-2's harness")

    built = REPO / "dashboard" / "out" / "index.html"
    if built.is_file():
        assert "inputs digested" not in _text(built), (
            "the provenance text now IS in the exported HTML, which contradicts the reasoning "
            "above - re-open D-2's harness decision")
