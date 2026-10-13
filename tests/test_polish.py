"""POLISH-01 - presentation layer regression suite.

Four stages, cheapest first (handoff brief Step 3):
  1 smoke        polish() completes on a freshly scaffolded register
  2 idempotency  a second run changes nothing
  3 fidelity     module output == the workbook that was actually approved
  4 invariants   the eight non-negotiables, as assertions

data_only stays FALSE throughout. openpyxl writes formulas with no cached result, so
data_only=True would read None on both sides of every comparison and the suite would go
green while proving nothing.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.register_polish import polish  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "wind_register_polished.xlsx"
# "scaffold structure + synthetic data fill" - provably the workbook the golden was
# hand-polished from (zero value diffs on Risk Register / Simulation / EMV / MC_Params).
SCAFFOLDED = ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"

# Sheets the polish layer cannot yet rebuild - Build Log steps 54 and 55 were built by
# hand in Excel and carry no op: payload. Excluded from the fidelity comparison so the
# rest of it stays meaningful; test_known_gap_dashboard_diagnostics is the live alarm.
#   TOC & Instructions - its tab inventory is not regenerated (spec step 61) and two of
#     its descriptions are scaffold changes the polish layer is forbidden to make
#     (steps 57/58). The rows below the inventory shift as tabs are added, so a
#     cell-by-cell comparison is meaningless until step 61 lands.
NOT_REPRODUCIBLE = {"Dashboard", "Diagnostics", "TOC & Instructions"}

# The four meta tabs are RENDERS of files that live in the repo and are expected to
# evolve. Comparing them to a frozen snapshot would fail on every legitimate edit to the
# spec, the driver or the brief. test_meta_tabs_regenerate is their gate instead.
RENDERED = {"Reference (polish)", "Handoff Prompt", "Build Log", "Polish Inbox"}

# POLISH-01a. The engine write-back region on Simulation, derived from the workbook's own
# names rather than hardcoded, so it follows the contract if the region ever moves.
#
# The golden was snapshotted from a workbook that had been run in Excel, so it carries a
# run's output: 321 cells, all of them here. A freshly scaffolded register has none, and
# it should have none - simulation output is not presentation, and a committed input
# fixture must not depend on a run having happened. Comparing the two therefore compares
# a run against no run, which is what made this fail once the 29/07 in-Excel save was
# reverted (the rule: "Never run the model in Excel against a tests/fixtures/
# workbook"). Excluded so the rest of the fidelity comparison stays meaningful.
#
# Corr_flag is the one write-back cell without the Out_ prefix; register_scaffold.py:739
# names it and :1238 lists it alongside the Out_* ranges as one region.
def _writeback_cells(path):
    from openpyxl.utils import range_boundaries
    wb = load_workbook(path)
    out = set()
    for name, defn in wb.defined_names.items():
        if not (name.startswith("Out_") or name == "Corr_flag"):
            continue
        sheet, ref = defn.value.split("!")
        sheet = sheet.strip("'")
        c1, r1, c2, r2 = range_boundaries(ref.replace("$", ""))
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                out.add((sheet, wb[sheet].cell(r, c).coordinate))
    return out


ENGINE_WRITEBACK = _writeback_cells(GOLDEN)

# Deliberate, recorded departures from the golden. Each one is a decision, not a bug.
KNOWN_DEVIATIONS = {
    # Charts!A1 is a formula on Set_ProjectName / Set_ProjectNumber instead of the
    # literal "... Tropic Ridge Wind Farm (TR-BOP-001)". The polish layer is shared
    # across projects; a hardcoded project identifier here breaks that (PORTABILITY.md).
    ("Charts", "A1"),
}


def _chart_titles(ws):
    """Plain-text chart titles. str(ch.title) is a multi-kilobyte object repr - useless
    in a diff and not stable across openpyxl versions."""
    out = []
    for ch in ws._charts:
        try:
            out.append("".join(r.t or "" for p in ch.title.tx.rich.p for r in (p.r or [])))
        except AttributeError:
            out.append("(untitled)")
    return sorted(out)


def _fmt(number_format):
    """Excel rewrites number formats on save, escaping literals it chose to quote:
    $#,##0;($#,##0);- comes back as "$"#,##0;\\("$"#,##0\\);\\-. Same format, different
    string. Strip the quoting so an openpyxl-written file and an Excel-written one can
    be compared at all."""
    return re.sub(r'[\\"]', "", number_format or "")


def _rgb(colour):
    """openpyxl 3.1.5 writes solid fills with a 00 alpha byte; Excel normalises the same
    fill to FF on save. 00DDEBF7 and FFDDEBF7 are the same colour, and the golden was last
    saved by Excel while the polished file is openpyxl-written, so every shaded cell
    differs on that byte alone - 14 of them, and nothing else (POLISH-01a). Same class as
    _fmt and _val above: an Excel-save normalisation, not a difference the polish layer
    caused. REG05-A1 fixed the writer side for the same reason; this is the compare side.
    """
    rgb = getattr(colour, "rgb", None)
    return "FF" + rgb[2:] if isinstance(rgb, str) and len(rgb) == 8 else rgb


def _val(value):
    """Excel truncates stored float literals to 17 significant figures on save, so
    50898938.022560574 reads back as 50898938.02256057. Round to the cent - well below
    anything the polish layer could affect, and far above the repr difference."""
    return round(value, 2) if isinstance(value, float) else str(value)


def dump(path, skip_sheets=frozenset()):
    """Normalised comparable view - values, formats, fills, bold, charts."""
    wb = load_workbook(path)
    out = []
    for ws in wb.worksheets:
        if ws.title in skip_sheets:
            continue
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None or c.number_format != "General":
                    out.append((ws.title, c.coordinate, _val(c.value), _fmt(c.number_format),
                                _rgb(c.fill.fgColor), c.font.b))
        out.append((ws.title, "_charts", str(_chart_titles(ws))))
    return out


def widths(path):
    wb = load_workbook(path)
    return {(ws.title, k): round(v.width or 0)
            for ws in wb.worksheets for k, v in ws.column_dimensions.items()}


@pytest.fixture
def polished(tmp_path):
    target = tmp_path / "reg.xlsx"
    shutil.copyfile(SCAFFOLDED, target)
    polish(str(target))
    return str(target)


@pytest.mark.integration
def test_smoke(polished):
    assert load_workbook(polished)["Charts"]._charts


@pytest.mark.integration
def test_idempotent(polished):
    before = dump(polished)
    polish(polished)
    assert dump(polished) == before


@pytest.mark.integration
def test_fidelity(polished):
    skip = NOT_REPRODUCIBLE | RENDERED
    excluded = KNOWN_DEVIATIONS | ENGINE_WRITEBACK
    got = [r for r in dump(polished, skip) if (r[0], r[1]) not in excluded]
    want = [r for r in dump(GOLDEN, skip) if (r[0], r[1]) not in excluded]
    assert got == want


@pytest.mark.integration
@pytest.mark.xfail(reason="autofit is a character-count approximation, not Excel's renderer",
                   strict=False)
def test_widths_match_golden(polished):
    assert widths(polished) == widths(GOLDEN)


@pytest.mark.integration
def test_invariants(polished):
    wb = load_workbook(polished)

    # 4 - P-level categories must be TEXT or they chart as a data series
    assert str(wb["Charts"]["AA3"].value).startswith('="P"&')
    assert str(wb["Charts"]["AD3"].value).startswith('="P"&')

    # 3 - Lists column headers are in ROW 2; row 1 is the cascade note
    assert (wb["Lists"]["A2"].fill.fgColor.rgb or "").endswith("1F4E79")
    assert not (wb["Lists"]["A1"].fill.fgColor.rgb or "").endswith("1F4E79")

    # 6 - tornado: largest risk at the TOP
    t = next(c for c in wb["Charts"]._charts
             if "tornado" in "".join(_chart_titles(wb["Charts"])).lower()
             or c.y_axis.scaling.orientation == "maxMin")
    assert t.y_axis.scaling.orientation == "maxMin"

    # 7 - Charts unprotected (protection kills the column-outline toggle)
    assert not wb["Charts"].protection.sheet
    assert wb["Build Log"].protection.sheet

    # 2 - the polish pass writes NO font colour on data cells. Asserted as "unchanged
    # from the scaffolded input", not as "black": Risk Register!P5 is an INPUT cell and
    # is legitimately blue (#0000CC) before polish ever runs. The brief's version of this
    # assertion tested for black and would have passed only by accident.
    before = load_workbook(SCAFFOLDED)
    for sheet, ref in (("Risk Register", "P5"), ("Mapping", "A2"), ("Lists", "A3")):
        was = getattr(before[sheet][ref].font.color, "rgb", None)
        now = getattr(wb[sheet][ref].font.color, "rgb", None)
        assert now == was, f"{sheet}!{ref} font colour moved {was} -> {now}"

    # 5 charts present
    assert len(wb["Charts"]._charts) == 5

    # TOC is excluded from fidelity (see NOT_REPRODUCIBLE) - assert what polish owns
    toc = wb["TOC & Instructions"]
    banded = [r for r in range(1, toc.max_row + 1)
              if (toc.cell(r, 1).fill.fgColor.rgb or "").endswith("1F4E79")]
    assert len(banded) == 6, f"expected 6 TOC section bands, found {banded}"
    assert all((toc.cell(r, 2).fill.fgColor.rgb or "").endswith("1F4E79") for r in banded),         "a band on column A alone clips at the column edge - bands must span A:B"
    assert not toc.sheet_view.showGridLines

    # 5 - scatter takes X (cost) from the LEFT column of the helper block
    assert str(wb["Charts"]["X3"].value).startswith("=Simulation!E")
    assert str(wb["Charts"]["Y3"].value).startswith("=Simulation!D")


@pytest.mark.integration
def test_toc_inventory_and_legend(polished):
    """Spec step 61. The inventory lists every tab, and the cell-type legend is intact.

    The legend was destroyed in the delivered register because the inventory was extended
    by hand with overwrites instead of inserts - taking 'Cell-type legend', 'input' and
    'calc' with it, so rule 2's "the TOC legend depends on it" pointed at a legend that no
    longer explained blue or black font.
    """
    wb = load_workbook(polished)
    toc = wb["TOC & Instructions"]
    listed = {str(toc.cell(r, 1).value) for r in range(1, toc.max_row + 1)}

    missing = [s for s in wb.sheetnames if s != toc.title and s not in listed]
    assert not missing, f"tabs absent from the TOC inventory: {missing}"

    for entry in ("Cell-type legend", "input", "calc", "model", "model-read"):
        assert entry in listed, f"cell-type legend entry {entry!r} missing"

    # Build Log 58 - the description that made deleting MC_Params look safe
    desc = next(toc.cell(r, 2).value for r in range(1, toc.max_row + 1)
                if toc.cell(r, 1).value == "MC_Params")
    # The corrected text deliberately contains "NOT legacy", so test the forbidden
    # phrase from Build Log 58, not the bare word.
    assert "legacy vba config surface" not in str(desc).lower(),         f"MC_Params still carries the description that made deletion look safe: {desc}"


@pytest.mark.integration
def test_toc_regeneration_preserves_the_range_contract(polished):
    """Step 61 inserts rows, and openpyxl does NOT follow defined names across a shift.

    Set_ProjectName..Set_IssueDate sit below the inventory. If they are not re-pointed
    they silently address the wrong cells and Validate Contract breaks.
    """
    before = load_workbook(SCAFFOLDED)
    after = load_workbook(polished)
    assert len(after.defined_names) == len(before.defined_names)

    for name, dn in after.defined_names.items():
        for sheet, ref in dn.destinations:
            if sheet != "TOC & Instructions":
                continue
            was = before.defined_names[name]
            (_s, old_ref), = was.destinations
            assert after[sheet][ref.replace("$", "")].value == \
                   before[_s][old_ref.replace("$", "")].value, \
                f"{name} moved to a different value after the TOC row shift"


@pytest.mark.integration
def test_toc_regeneration_is_stable(polished):
    """Re-running must not keep inserting rows - the classic regenerate-in-place bug."""
    first = load_workbook(polished)["TOC & Instructions"].max_row
    polish(polished)
    polish(polished)
    assert load_workbook(polished)["TOC & Instructions"].max_row == first


@pytest.mark.integration
def test_no_excel_repair_on_open(polished):
    """Guards the whole 'Excel repaired your file' class, which nothing else here can see.

    Two real defects shipped past a fully green suite and were only caught by a human
    opening the workbook:

      Removed Part: /xl/drawings/drawing2.xml part. (Drawing shape)
      Removed Records: Formula from /xl/worksheets/sheet18.xml part

    1. DrawingML srgbClr@val is ST_HexColorRGB - exactly six hex digits. The 8-digit ARGB
       that cell fills need is schema-invalid there, so Excel rejected four of the five
       charts and dropped the entire drawing part.
    2. openpyxl types a cell as a formula from a leading '=' alone, and number_format='@'
       does not override it. The meta tabs render prose full of '=' banner rules, so 31
       cells became unparseable formulas.
    """
    import zipfile
    z = zipfile.ZipFile(polished)

    bad_colour = {}
    for part in (n for n in z.namelist() if "charts/chart" in n and n.endswith(".xml")):
        hits = re.findall(r'srgbClr val="([0-9A-Fa-f]{8})"', z.read(part).decode("utf-8"))
        if hits:
            bad_colour[part.split("/")[-1]] = sorted(set(hits))
    assert not bad_colour, f"8-digit ARGB in chart DrawingML (must be 6): {bad_colour}"

    # Scoped to the tabs polish renders as TEXT. Elsewhere formulas are the whole point -
    # the scaffold's Risk Register and EMV columns, and Charts!A1's project-name formula,
    # are all legitimate.
    wb = load_workbook(polished)
    stray = {name: [c.coordinate for row in wb[name].iter_rows() for c in row
                    if c.data_type == "f"]
             for name in RENDERED if name in wb.sheetnames}
    stray = {k: v for k, v in stray.items() if v}
    assert not stray, (
        f"prose stored as formulas on a rendered text tab - Excel strips these on "
        f"open: { {k: v[:4] for k, v in stray.items()} }")


@pytest.mark.integration
def test_meta_tabs_regenerate(polished):
    """Step 4 acceptance: delete all five generated tabs, re-run, all five return."""
    generated = ["Charts", "Build Log", "Polish Inbox",
                 "Reference (polish)", "Handoff Prompt"]
    wb = load_workbook(polished)
    for name in generated:
        del wb[name]
    wb.save(polished)

    polish(polished)
    wb = load_workbook(polished)
    assert all(name in wb.sheetnames for name in generated)


@pytest.mark.integration
def test_inbox_merge(polished, tmp_path, monkeypatch):
    """Flip the shipped example row to pending; it must merge exactly once."""
    import tools.register_polish as rp

    # merge_inbox rewrites the spec on disk. Point it at a copy so a test run cannot
    # mutate the committed config/polish_spec.yaml.
    spec_copy = tmp_path / "polish_spec.yaml"
    shutil.copyfile(rp.SPEC, spec_copy)
    monkeypatch.setattr(rp, "SPEC", spec_copy)

    wb = load_workbook(polished)
    wb["Polish Inbox"]["G12"] = "pending"
    wb.save(polished)

    polish(polished)
    wb = load_workbook(polished)
    assert wb["Polish Inbox"]["G12"].value == "merged"
    assert str(wb["Polish Inbox"]["H12"].value).startswith("polish-v")

    before = len(wb["Charts"]._charts)
    polish(polished)                       # merge must not duplicate
    assert len(load_workbook(polished)["Charts"]._charts) == before


@pytest.mark.slow  # TESTLANE-01 A sweep: shells out (see tests/conftest.py guard)
@pytest.mark.integration
def test_runs_as_a_script(tmp_path):
    """`python tools/register_polish.py <wb>` - the invocation the build docs specify.

    Every other test IMPORTS the module, which puts the repo root on sys.path for free.
    Run as a script Python puts tools/ there instead, and `from tools.polish_charts
    import build_chart` fails at the first chart op. The documented entry point was
    broken while the whole suite was green.
    """
    import subprocess
    target = tmp_path / "reg.xlsx"
    shutil.copyfile(SCAFFOLDED, target)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "register_polish.py"),
                        str(target)],
                       capture_output=True, text=True, cwd=tmp_path)  # cwd != repo root
    assert r.returncode == 0, f"script invocation failed:\n{r.stdout}\n{r.stderr}"
    assert len(load_workbook(target)["Charts"]._charts) == 5


@pytest.mark.unit
def test_op_schema_matches_handlers():
    """OP_SCHEMA drives both inbox validation and the rendered vocabulary tab. If it can
    drift from the handlers, a new op ships undocumented (CiE can never use it) or a
    documented op does not exist (CiE uses it and the build breaks)."""
    import tools.register_polish as rp
    handlers = {n[3:] for n in dir(rp.Polisher) if n.startswith("op_")}
    assert handlers == set(rp.OP_SCHEMA), (
        f"undocumented handlers: {sorted(handlers - set(rp.OP_SCHEMA))} / "
        f"documented non-ops: {sorted(set(rp.OP_SCHEMA) - handlers)}")


@pytest.mark.unit
@pytest.mark.parametrize("payload, expect", [
    ({"kind": "set_column_width", "col": "S"}, "unknown op kind"),
    ({"kind": "numfmt"},                       "missing required field"),
    ({"kind": "header", "ref": "A1", "colour": "navy"}, "does not take colour"),
    ({"kind": "composite", "ops": [{"kind": "nope"}]},  "sub-op 0"),
    ("not a mapping",                          "must be a YAML mapping"),
    ({"ref": "A1"},                            "no kind"),
])
def test_validate_op_rejects(payload, expect):
    from tools.register_polish import validate_op
    reason = validate_op(payload)
    assert reason and expect in reason, f"expected {expect!r}, got {reason!r}"


@pytest.mark.unit
def test_validate_op_accepts_every_shipped_op():
    """Every op in the committed spec must pass its own validator."""
    import yaml
    import tools.register_polish as rp
    spec = yaml.safe_load(rp.SPEC.read_text(encoding="utf-8"))

    def check(op, where):
        if not op:
            return
        reason = rp.validate_op(op)
        assert reason is None, f"{where}: {reason}"

    for rec in spec["steps"]:
        check(rec.get("op"), f"step {rec['id']}")


@pytest.mark.integration
def test_bad_inbox_row_cannot_corrupt_the_spec(polished, tmp_path, monkeypatch):
    """The regression that motivated all of this.

    An unknown op kind used to be appended to polish_spec.yaml, marked merged, and only
    fail later in dispatch() - leaving the canonical spec corrupted, the row still
    'pending', and the next run merging the same bad payload again. Version and step
    count grew on every run and the build stayed broken until someone hand-edited the
    YAML, which the design explicitly forbids.
    """
    import yaml
    import tools.register_polish as rp

    spec_copy = tmp_path / "polish_spec.yaml"
    shutil.copyfile(rp.SPEC, spec_copy)
    monkeypatch.setattr(rp, "SPEC", spec_copy)
    original = spec_copy.read_text(encoding="utf-8")

    wb = load_workbook(polished)
    ib = wb["Polish Inbox"]
    ib["A13"], ib["D13"] = "INB-002", "Charts"
    ib["E13"] = "Widen column S so risk names are not truncated"
    ib["F13"] = "kind: set_column_width\nsheet: Charts\ncol: S\nwidth: 44"
    ib["G13"] = "pending"
    wb.save(polished)

    for _ in range(2):                              # must not compound across runs
        polish(polished)                            # build still succeeds
        assert spec_copy.read_text(encoding="utf-8") == original, \
            "a rejected payload reached the canonical spec"

    ib = load_workbook(polished)["Polish Inbox"]
    assert ib["G13"].value == "rejected"
    assert "unknown op kind" in str(ib["H13"].value)
    assert "set_column_width" in str(ib["H13"].value)


@pytest.mark.integration
def test_reference_tab_is_generated_vocabulary(polished):
    """Reference (polish) must describe every op kind, and carry no source dump."""
    import tools.register_polish as rp
    ws = load_workbook(polished)["Reference (polish)"]
    text = "\n".join(str(c.value or "") for c in ws["A"])
    for kind in rp.OP_SCHEMA:
        assert kind in text, f"{kind} missing from the rendered vocabulary"
    assert "import yaml" not in text and "def polish" not in text, \
        "the tab is dumping source again instead of the vocabulary"
    assert ws.max_row < 120, f"vocabulary tab has grown to {ws.max_row} rows"


@pytest.mark.integration
@pytest.mark.xfail(reason="Build Log 54/55: Dashboard and Diagnostics have no op: payload "
                          "and are lost on regeneration. Awaiting a Director decision on "
                          "whether to author them.",
                   strict=True)
def test_known_gap_dashboard_diagnostics(polished):
    wb = load_workbook(polished)
    assert "Dashboard" in wb.sheetnames and "Diagnostics" in wb.sheetnames
