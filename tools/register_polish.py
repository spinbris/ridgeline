"""Spec-driven presentation layer. Reads config/polish_spec.yaml, APPLIES the op:
payloads and REGENERATES the Build Log tab from the same records. Run LAST in the
build. Touches no model logic, named ranges or contract cells."""
from __future__ import annotations
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # repo root - NOT the cwd. Portable on all OSes.
if str(ROOT) not in sys.path:
    # Run as a script (python tools/register_polish.py), Python puts tools/ on sys.path,
    # not the repo root, so `from tools.polish_charts import ...` fails at the first
    # chart op. Importing the module works either way, which is why the test suite never
    # saw it - and the script form is the one the build documentation tells you to use.
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill, Alignment  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

SPEC = ROOT / "config" / "polish_spec.yaml"
SRC_ROOT = ROOT                              # source files resolved relative to this
DEFAULT_WORKBOOK = ROOT / "dist" / "wind_register.xlsx"
HANDOFF_MD = ROOT / "docs" / "polish_handoff.md"
LOG_COLS = ["id", "step", "sheet", "target", "action", "detail", "why"]


def _split(ref):
    col = "".join(c for c in ref if c.isalpha())
    return col, int("".join(c for c in ref if c.isdigit()))


def _idx(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _tpl(tpl, i):
    """Expand {12+i} style row offsets inside a formula template."""
    return re.sub(r"\{(\d+)\+i\}", lambda m: str(int(m.group(1)) + i), tpl)


def _text(cell, value):
    """Write value as TEXT, never as a formula.

    openpyxl decides a cell is a formula purely from a leading '=' in the string, and
    number_format='@' does not override it. The meta tabs render prose: the '=' banner
    rules, and Build Log detail fields quoting formulas like
    ="EMV & Mode Analysis"!B12-ROW()/1000000, all became formula cells. Excel then cannot
    parse them and strips them on open - "Removed Records: Formula from
    /xl/worksheets/sheetN.xml part" - which is a repair prompt on a client deliverable."""
    cell.value = value
    if cell.data_type == "f":
        cell.data_type = "s"
    return cell


def autofit(ws, min_w=7, max_w=34, pad=1.6, ignore_rows=(), only_cols=None):
    """Approximate Excel autofit from content length.

    openpyxl cannot measure rendered text, so character count is the proxy - fine for
    tabular data, wrong for prose. ignore_rows EXCLUDES note/footnote rows that sit
    inside a data column; without it a single sentence stretches the whole column.
    Known offenders: Layer1_Base!B12, Lists!A1, Layer1_Correlation!C1."""
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        if only_cols and letter not in only_cols:
            continue
        longest = 0
        for cell in col:
            if cell.row in ignore_rows or cell.value is None:
                continue
            numeric = isinstance(cell.value, (int, float))
            grouped = "#,##" in (cell.number_format or "")
            text = f"{cell.value:,.0f}" if numeric and grouped else str(cell.value)
            longest = max(longest, len(text))
        if longest:
            ws.column_dimensions[letter].width = min(max(longest + pad, min_w), max_w)


class Polisher:
    def __init__(self, wb, spec):
        self.wb, self.spec = wb, spec
        self.pal, self.fmt = spec["palette"], spec["formats"]
        self.applied, self.docs = [], []

    def _c(self, key):
        """Palette lookup for CELL FILLS - 8-digit ARGB.

        Excel writes 8-digit ARGB; openpyxl left-pads a 6-digit value with 00 (fully
        transparent), which reads back as a different colour than the same fill set in
        Excel. Normalise so a polished file and a hand-formatted one compare equal.

        NOT for charts - see _c6()."""
        hexcode = self.pal.get(key, key)
        return f"FF{hexcode}" if len(hexcode) == 6 else hexcode

    def _c6(self, key):
        """Palette lookup for CHARTS - 6-digit RGB.

        DrawingML's srgbClr@val is ST_HexColorRGB: exactly six hex digits. Feeding it the
        8-digit ARGB that cell fills need produces <a:srgbClr val="FF1F4E79"/>, which is
        schema-invalid - Excel rejects the chart and then drops the whole drawing part
        with "Removed Part: /xl/drawings/drawingN.xml (Drawing shape)". Two consumers,
        two formats, one palette."""
        hexcode = self.pal.get(key, key)
        return hexcode[-6:] if len(hexcode) == 8 else hexcode

    def _f(self, key):          # format lookup, passthrough for literals
        return self.fmt.get(key, key)

    def _hdr(self):
        return (PatternFill("solid", fgColor=self._c("navy")),
                Font(bold=True, color="FFFFFFFF"),
                Alignment(horizontal="center", vertical="center", wrap_text=True))

    # ---- op handlers ---------------------------------------------------------
    def op_unprotect_workbook(self, o):
        self.wb.security.lockStructure = False

    def op_protect_workbook(self, o):
        self.wb.security.lockStructure = True

    def op_assert_convention(self, o):
        pass                    # enforced in _guard(), this row is the audit trail

    def op_composite(self, o):
        for sub in o["ops"]:
            self.dispatch(sub, sub.get("sheet"))

    def op_create_sheet(self, o):
        if o["name"] in self.wb.sheetnames:
            del self.wb[o["name"]]
        ws = self.wb.create_sheet(o["name"], o["index"])
        ws.sheet_properties.tabColor = self._c(o.get("tab_color", "navy"))
        ws.sheet_view.showGridLines = o.get("gridlines", True)

    def op_protect_sheet(self, o):
        self.wb[o["name"]].protection.sheet = True

    def op_set(self, o, ws):
        ws[o["ref"]] = o["value"]

    def op_freeze(self, o, ws):
        ws.freeze_panes = o["ref"]

    def op_gridlines(self, o, ws):
        ws.sheet_view.showGridLines = o["show"]

    def op_group_columns(self, o, ws):
        ws.column_dimensions.group(o["first"], o["last"], outline_level=1, hidden=False)

    def op_formula_fill(self, o, ws):
        col, row = _split(o["anchor"])
        for i in range(o["count"]):
            ws[f"{col}{row + i}"] = _tpl(o["template"], i)

    def _fill_n(self, o, ws):
        col, row = _split(o["anchor"])
        fmts = o.get("formats") or [None] * len(o["templates"])
        for i in range(o["count"]):
            for j, tpl in enumerate(o["templates"]):
                cell = ws.cell(row + i, _idx(col) + j, _tpl(tpl, i))
                if fmts[j]:
                    cell.number_format = self._f(fmts[j])

    op_formula_fill_2col = _fill_n
    op_formula_fill_4col = _fill_n
    op_formula_fill_n = _fill_n         # width taken from len(templates)

    def op_numfmt(self, o, ws):
        for key, refs in o["map"].items():
            for ref in refs:
                cells = ws[ref] if ":" in ref else ((ws[ref],),)
                for row in cells:
                    for cell in row:
                        cell.number_format = self._f(key)

    def op_header(self, o, ws):
        fill, font, align = self._hdr()
        ref = o["ref"]
        rows = ws[ref] if ":" in ref else ((ws[ref],),)
        for row in rows:
            for cell in row:
                cell.fill, cell.font, cell.alignment = fill, font, align
        if o.get("height"):
            ws.row_dimensions[_split(ref.split(":")[0])[1]].height = o["height"]

    def op_title(self, o, ws):
        ws[o["ref"]].font = Font(bold=True, color=self._c("navy"), size=o.get("size", 11))

    def op_note(self, o, ws):
        """Small provenance / caption line - the counterpart to op_title."""
        ws[o["ref"]].font = Font(size=o.get("size", 9),
                                 italic=o.get("italic", True),
                                 bold=o.get("bold", False),
                                 color=self._c(o["color"]) if o.get("color") else None)

    def op_bold(self, o, ws):
        for row in ws[o["ref"]]:
            for cell in row:
                cell.font = Font(bold=True)

    def op_fill_rows(self, o, ws):
        """Fill only - no font touched. For highlight rows that must keep dark text."""
        fill = PatternFill("solid", fgColor=self._c(o["fill"]))
        for r in self._rows(o, ws):
            for col in o["cols"]:
                ws[f"{col}{r}"].fill = fill

    @staticmethod
    def _rows(o, ws):
        """Row targets, either literal rows: or labels: matched against column A.

        Prefer labels:. Row numbers on the TOC are not stable - the tab inventory grows
        by one row per generated sheet, so a list like [4, 22, 28] banded the right
        sections on the workbook it was written against and the wrong ones on the next."""
        if "rows" in o:
            return list(o["rows"])
        wanted = {str(v).strip() for v in o["labels"]}
        found = {str(ws.cell(r, 1).value).strip(): r
                 for r in range(1, ws.max_row + 1)
                 if str(ws.cell(r, 1).value).strip() in wanted}
        missing = wanted - set(found)
        if o.get("optional") or not missing:
            return sorted(found.values())
        if not found:
            # Nothing matched at all - the label list or the sheet is wrong, not the data.
            raise ValueError(f"{ws.title}: no row found for ANY of {sorted(wanted)}")
        # Some matched. A register whose TOC has been edited can legitimately be missing a
        # section; banding the rest is right, and failing the whole build over a cosmetic
        # band is not. Warn so the drift is visible rather than silent.
        print(f"WARNING: {ws.title}: no row for {sorted(missing)} - "
              f"section(s) absent from this register, band skipped")
        return sorted(found.values())

    def op_toc_inventory(self, o, ws):
        """Rebuild the tab inventory + cell-type legend from the ACTUAL sheet list.

        The inventory was hand-extended when the generated tabs were added, and because
        rows were overwritten rather than inserted it consumed the cell-type legend -
        'Cell-type legend', 'input' and 'calc' were destroyed. Rule 2 ("never write font
        colour - the TOC legend depends on it") then pointed at a legend that no longer
        explained blue or black. Regenerating is the only fix that does not repeat the
        hand-edit that caused it.

        Rows are inserted or deleted to fit, so anything below moves. openpyxl does NOT
        follow defined names across a row shift, so they are re-pointed here and the op
        refuses to complete unless every one still resolves to the value it did before."""
        head = self._rows({"labels": [o["header"]]}, ws)[0]
        stop = self._rows({"labels": [o["ends_before"]]}, ws)[0]

        described = {}                       # keep whatever text is already there
        for r in range(head + 1, stop):
            name = str(ws.cell(r, 1).value or "").strip()
            if name and ws.cell(r, 2).value:
                described[name] = ws.cell(r, 2).value
        described.update({k: v for k, v in (o.get("descriptions") or {}).items()
                          if k not in described})
        # overrides: always win. Reserved for descriptions that are actively wrong -
        # see the Build Log 58 note in the step record.
        described.update(o.get("overrides") or {})

        block = [(s, described.get(s, "")) for s in self.wb.sheetnames if s != ws.title]
        block.append((None, None))                       # separator
        block.append((o["legend_header"], None))
        block += [(k, v) for k, v in o["legend"].items()]

        available, needed = stop - head - 1, len(block)
        delta = needed - available
        before = {n: self.wb[sh][ref.replace("$", "")].value
                  for n, dn in self.wb.defined_names.items()
                  for sh, ref in dn.destinations if sh == ws.title}
        if delta > 0:
            ws.insert_rows(stop, delta)
        elif delta < 0:
            ws.delete_rows(stop + delta, -delta)
        if delta:
            for name, dn in self.wb.defined_names.items():
                for sh, ref in list(dn.destinations):
                    if sh != ws.title:
                        continue
                    col, row = _split(ref.replace("$", ""))
                    if row >= stop:
                        dn.attr_text = f"'{ws.title}'!${col}${row + delta}"

        for i, (name, desc) in enumerate(block):
            # Assign .value explicitly - ws.cell(r, c, None) is a no-op that LEAVES the
            # previous content, so the blank separator and the legend header's empty
            # column B silently kept whatever the old layout had in them.
            ws.cell(head + 1 + i, 1).value = name
            ws.cell(head + 1 + i, 2).value = desc
        for name, dn in self.wb.defined_names.items():
            for sh, ref in dn.destinations:
                if sh == ws.title and self.wb[sh][ref.replace("$", "")].value != before[name]:
                    raise ValueError(
                        f"{name} no longer resolves to its original value after the "
                        f"{delta:+d}-row TOC shift - the range contract would be broken")

    def op_sheet_order(self, o):
        """Reorder tabs to the spec's list. Sheets not named keep their relative order
        and sit where the list says 'others' - anything unnamed goes to the tail."""
        named = [n for n in o["order"] if n in self.wb.sheetnames]
        rest = [n for n in self.wb.sheetnames if n not in named]
        self.wb._sheets = [self.wb[n] for n in named + rest]

    def op_align(self, o, ws):
        for row in ws[o["ref"]]:
            for cell in row:
                cell.alignment = Alignment(horizontal=o.get("horizontal", "general"),
                                           vertical=o.get("vertical", "bottom"),
                                           wrap_text=o.get("wrap", False))

    def op_band_headers(self, o, ws):
        for b in o["bands"]:
            ref = b["ref"]
            cells = ws[ref][0] if ":" in ref else [ws[ref]]
            for cell in cells:
                cell.fill = PatternFill("solid", fgColor=self._c(b["fill"]))
                cell.font = Font(bold=True, color="FFFFFF")
            cells[0].alignment = Alignment(horizontal="centerContinuous")

    def op_band_rows(self, o, ws):
        fill = PatternFill("solid", fgColor=self._c(o["fill"]))
        for r in self._rows(o, ws):
            for col in o["cols"]:          # MUST span A:B or the band clips
                ws[f"{col}{r}"].fill = fill
                ws[f"{col}{r}"].font = Font(bold=True, color="FFFFFF")

    def op_autofit_all(self, o):
        cfg = self.spec.get("autofit", {})
        base = cfg.get("defaults", {})
        for ws in self.wb.worksheets:
            over = cfg.get("sheets", {}).get(ws.title, {})
            autofit(ws, **{**base, **over})
        for name, spec in self.spec.get("widths", {}).items():   # explicit wins
            if name not in self.wb.sheetnames:
                continue
            ws = self.wb[name]
            if "_span" in spec:
                a, b, w = spec["_span"]
                for i in range(ord(a), ord(b) + 1):
                    ws.column_dimensions[chr(i)].width = w
            for col, w in spec.items():
                if not col.startswith("_"):
                    ws.column_dimensions[col].width = w

    def op_chart(self, o, ws):
        from tools.polish_charts import build_chart
        ws.add_chart(build_chart(self.wb, o, self._c6), o["anchor"])

    # ---- guard ---------------------------------------------------------------
    def _guard(self, op):
        """Step 27 as a test, not a comment: no op may set a font colour."""
        if "font_color" in set(self.spec["conventions"]["never_touch"]):
            if "font_color" in yaml.safe_dump(op):
                raise ValueError(f"op violates the colour convention: {op}")

    def dispatch(self, op, sheet=None):
        if not op:
            return
        self._guard(op)
        fn = getattr(self, f"op_{op['kind']}", None)
        if fn is None:
            raise ValueError(f"unknown op kind: {op['kind']}")
        wants_ws = fn.__code__.co_argcount == 3
        if wants_ws:
            target = op.get("sheet", sheet)
            fn(op, self.wb[target])
        else:
            fn(op)

    # ---- main ----------------------------------------------------------------
    # Ops that must see the finished workbook, so they run after the meta tabs are built
    # rather than in step order. Four of the tabs a reorder names do not exist yet when
    # the step loop reaches step 56.
    DEFERRED = {"sheet_order", "toc_inventory"}

    def _defer_rank(self, rec):
        """0 = run in step order. Higher = run after the meta tabs, in rank order.

        Some steps cannot run in spec order at all. toc_inventory needs the final sheet
        list, which only exists once the run() tail has created the meta tabs; and the
        TOC's START HERE highlight targets a row that toc_inventory creates, so it has to
        follow it. Ordering by rank rather than by file position keeps the Build Log
        readable while letting the dependencies be explicit."""
        op = rec.get("op") or {}
        return rec.get("defer") or (1 if op.get("kind") in self.DEFERRED else 0)

    def run(self):
        deferred = []
        for rec in self.spec["steps"]:
            op = rec.get("op")
            if op and self._defer_rank(rec):
                deferred.append(rec)
                self.applied.append(rec["id"])
                continue
            try:
                self.dispatch(op, rec.get("sheet"))
            except Exception as exc:
                raise RuntimeError(
                    f"step {rec['id']} ({rec['step']}) failed: {exc}") from exc
            (self.applied if op else self.docs).append(rec["id"])
        self._write_log()
        ensure_inbox(self.wb)              # create-if-missing, state preserved
        render_reference(self.wb, self.spec)
        render_handoff(self.wb)
        for rec in sorted(deferred, key=self._defer_rank):
            try:
                self.dispatch(rec["op"], rec.get("sheet"))
            except Exception as exc:
                raise RuntimeError(
                    f"deferred step {rec['id']} ({rec['step']}) failed: {exc}") from exc

    def _write_log(self):
        """The Build Log tab is a RENDER of the spec - never hand-edited."""
        if "Build Log" in self.wb.sheetnames:
            del self.wb["Build Log"]
        ws = self.wb.create_sheet("Build Log", 2)
        ws.sheet_properties.tabColor = self._c("grey")
        ws.sheet_view.showGridLines = False
        ws["A1"] = ("Build Log - presentation layer spec "
                    "(rendered from config/polish_spec.yaml)")
        ws["A1"].font = Font(size=14, bold=True, color=self._c("navy"))
        ws["A2"] = ("Generated. Do not hand-edit - edit the YAML and re-run "
                    "tools/register_polish.py.")
        ws["A2"].font = Font(size=9, italic=True, color=self._c("mute"))

        meta = [("Spec version", self.spec["version"]),
                ("Applies to", self.spec["applies_to"]),
                ("Run order", self.spec["run_order"]),
                ("Idempotent", self.spec["idempotent"])]
        for r, (k, v) in enumerate(meta, start=4):
            ws.cell(r, 1, k).font = Font(bold=True)
            ws.cell(r, 2, v)

        fill, font, align = self._hdr()
        heads = ["#", "Step", "Target sheet", "Range / object",
                 "Action", "Detail / value", "Why"]
        for c, name in enumerate(heads, start=1):
            cell = ws.cell(9, c, name)
            cell.fill, cell.font, cell.alignment = fill, font, align

        for r, rec in enumerate(self.spec["steps"], start=10):
            for c, key in enumerate(LOG_COLS, start=1):
                cell = _text(ws.cell(r, c), rec.get(key, ""))
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.number_format = "@"
            if rec.get("flag") == "assumption":        # amber = needs human review
                for c in range(1, 8):
                    ws.cell(r, c).fill = PatternFill("solid", fgColor="FFF2CC")
        ws.freeze_panes = "A10"
        ws.protection.sheet = True


# ---- Polish Inbox merge ------------------------------------------------------------
INBOX_SHEET = "Polish Inbox"
INBOX_HEADER_ROW = 11              # data starts at 12
COL = {"id": 1, "raised": 2, "author": 3, "sheet": 4,
       "change": 5, "payload": 6, "status": 7, "merged_in": 8}

# The op vocabulary: {kind: (required fields, optional fields, one-line description)}.
# ONE declaration, two consumers - it validates inbox payloads AND renders the reference
# tab that Claude-in-Excel reads. test_op_schema_matches_handlers asserts it covers
# exactly the op_* methods on Polisher, so a new handler cannot ship undocumented and a
# documented kind cannot be one that does not exist.
# "sheet" is implicit everywhere except the workbook-level ops and is not listed.
OP_SCHEMA = {
    "unprotect_workbook": ((), (), "Release workbook structure protection"),
    "protect_workbook":   ((), (), "Restore workbook structure protection"),
    "assert_convention":  ((), (), "Audit-trail marker; the guard does the work"),
    "composite":          (("ops",), (), "Run a list of ops in order"),
    "create_sheet":       (("name", "index"), ("tab_color", "gridlines"), "Add or recreate a sheet"),
    "protect_sheet":      (("name",), (), "Lock a sheet"),
    "sheet_order":        (("order",), (), "Reorder tabs; unnamed sheets follow"),
    "toc_inventory":      (("header", "ends_before", "legend_header", "legend"),
                           ("descriptions", "overrides"),
                           "Rebuild the tab inventory + cell-type legend from the sheet list"),
    "set":                (("ref", "value"), (), "Write a literal or formula into one cell"),
    "freeze":             (("ref",), (), "Freeze panes at ref"),
    "gridlines":          (("show",), (), "Show or hide gridlines"),
    "group_columns":      (("first", "last"), (), "Collapsible column outline"),
    "formula_fill":       (("anchor", "count", "template"), (),
                           "Fill one column; {12+i} in the template expands per row"),
    "formula_fill_n":     (("anchor", "count", "templates"), ("formats",),
                           "Fill N adjacent columns, one template each"),
    "formula_fill_2col":  (("anchor", "count", "templates"), ("formats",), "formula_fill_n, 2 columns"),
    "formula_fill_4col":  (("anchor", "count", "templates"), ("formats",), "formula_fill_n, 4 columns"),
    "numfmt":             (("map",), (), "map: {format_key: [ranges]} - keys from formats:"),
    "header":             (("ref",), ("height",), "Navy fill, white bold, centred, wrapped"),
    "title":              (("ref",), ("size",), "Bold navy heading"),
    "note":               (("ref",), ("size", "bold", "italic", "color"), "Small caption or provenance line"),
    "bold":               (("ref",), (), "Bold a range, nothing else"),
    "align":              (("ref",), ("horizontal", "vertical", "wrap"), "Set alignment on a range"),
    "band_headers":       (("bands",), (), "bands: [{ref, fill}] - centerContinuous, never merged"),
    "band_rows":          (("cols", "fill"), ("rows", "labels", "optional"),
                           "Full-width section band; prefer labels: over rows:"),
    "fill_rows":          (("cols", "fill"), ("rows", "labels", "optional"),
                           "Fill only, font untouched - highlights that keep dark text"),
    "autofit_all":        ((), (), "Width pass over every sheet; widths: overrides win"),
    "chart":              (("name", "type", "anchor", "size"),
                           ("title", "legend", "data", "cats", "x", "y",
                            "series_style", "data_labels", "reverse_categories"),
                           "Add a chart; type: bar|col|line|scatter|doughnut"),
}


def validate_op(op):
    """Return a rejection reason, or None if the payload is well formed.

    Runs BEFORE anything is written to the spec. The failure this prevents: an unknown
    kind used to be appended to polish_spec.yaml, marked merged, and only blow up later
    in dispatch() - by which point the canonical spec was already corrupted and the
    inbox row still said pending, so the next run merged it again."""
    if not isinstance(op, dict):
        return "payload must be a YAML mapping"
    kind = op.get("kind")
    if not kind:
        return "payload has no kind:"
    if kind not in OP_SCHEMA:
        near = [k for k in OP_SCHEMA if k.startswith(str(kind)[:4])]
        return (f"unknown op kind {kind!r}"
                + (f" - did you mean {' / '.join(near)}?" if near else "")
                + f" (valid: {', '.join(sorted(OP_SCHEMA))})")
    required, optional, _ = OP_SCHEMA[kind]
    missing = [f for f in required if f not in op]
    if missing:
        return f"{kind} is missing required field(s): {', '.join(missing)}"
    allowed = set(required) | set(optional) | {"kind", "sheet"}
    unknown = sorted(set(op) - allowed)
    if unknown:
        return (f"{kind} does not take {', '.join(unknown)} "
                f"(accepts: {', '.join(sorted(allowed - {'kind'}))})")
    if kind == "composite":
        for i, sub in enumerate(op.get("ops") or []):
            reason = validate_op(sub)
            if reason:
                return f"sub-op {i}: {reason}"
    return None


def _next_step_id(spec):
    return max((s["id"] for s in spec["steps"]), default=0) + 1


def _bump(version):
    """polish-v02 -> polish-v03"""
    stem, _, num = version.rpartition("v")
    return f"{stem}v{int(num) + 1:02d}"


def _reject(ws, row, reason):
    ws.cell(row, COL["status"], "rejected")
    ws.cell(row, COL["merged_in"], reason)
    print(f"inbox: REJECTED row {row} - {reason}")


def merge_inbox(wb, spec):
    """Stage status=pending Polish Inbox rows into the IN-MEMORY spec.

    Nothing is written to disk here. Payloads are validated first and a bad row is
    rejected in place - it never reaches the canonical YAML. Returns the staged records
    so polish() can persist them only after the ops have actually applied.

    This ordering is the whole point. Previously the YAML was written during the merge,
    so an op that failed in dispatch() left the canonical spec corrupted and the inbox
    row still 'pending' - and the next run merged the same bad row again, compounding a
    step and a version bump every time."""
    if INBOX_SHEET not in wb.sheetnames:
        return []
    ws = wb[INBOX_SHEET]
    staged = []

    for row in range(INBOX_HEADER_ROW + 1, ws.max_row + 1):
        status = (ws.cell(row, COL["status"]).value or "").strip().lower()
        if status != "pending":
            continue                      # example / merged / rejected are all inert
        raw = ws.cell(row, COL["payload"]).value
        if not raw or not str(raw).strip():
            _reject(ws, row, "pending but the op: payload is empty")
            continue
        try:
            op = yaml.safe_load(str(raw))
        except yaml.YAMLError as exc:
            _reject(ws, row, f"not valid YAML - {str(exc).splitlines()[0]}")
            continue
        reason = validate_op(op)
        if reason:
            _reject(ws, row, reason)
            continue

        rec = {
            "id": _next_step_id(spec),
            "step": str(ws.cell(row, COL["id"]).value or "inbox amendment"),
            "sheet": ws.cell(row, COL["sheet"]).value or "(all)",
            "target": op.get("name") or op.get("ref") or op["kind"],
            "action": f"inbox merge ({op['kind']})",
            "detail": str(ws.cell(row, COL["change"]).value or ""),
            "why": f"Raised {ws.cell(row, COL['raised']).value} by "
                   f"{ws.cell(row, COL['author']).value}",
            "op": op,
        }
        spec["steps"].append(rec)
        staged.append((row, rec))
    return staged


def commit_inbox(wb, spec, staged, spec_path=None):
    """Persist staged amendments - called only after Polisher.run() has succeeded.

    spec_path resolves at CALL time, not as a default argument: bound at import it
    captures the module-level SPEC once, and a test that redirects it still writes the
    real config/polish_spec.yaml. That is not hypothetical - it happened."""
    if not staged:
        return 0
    spec_path = SPEC if spec_path is None else spec_path
    new_version = _bump(spec["version"])
    spec["version"] = new_version
    ws = wb[INBOX_SHEET]
    for row, _rec in staged:
        ws.cell(row, COL["status"], "merged")
        ws.cell(row, COL["merged_in"], new_version)
    _append_steps(spec_path, new_version, [rec for _row, rec in staged])
    print(f"inbox: merged {len(staged)} amendment(s) -> steps "
          f"{[rec['id'] for _r, rec in staged]} (spec now {new_version})")
    return len(staged)


def _append_steps(spec_path, new_version, records):
    """Rewrite the version line and APPEND the merged records to steps:.

    A yaml.safe_dump of the whole spec would round-trip the content correctly but strip
    every comment and collapse the flow-style op: payloads - the file is hand-maintained
    and that is most of its readability. steps: is the last top-level key, so appending
    to the tail is a safe textual edit. (ruamel.yaml round-trip mode would be the
    general fix; it is not a dependency of this repo.)"""
    text = spec_path.read_text(encoding="utf-8")
    head, sep, tail = text.partition("\nsteps:")
    if not sep:
        raise ValueError(f"{spec_path} has no steps: block to append to")
    if "\n- id:" not in tail and "\n  - id:" not in tail:
        raise ValueError(f"{spec_path} steps: block is not a list of id: records")
    head = re.sub(r"^version:.*$", f"version: {new_version}", head, count=1, flags=re.M)
    block = yaml.safe_dump(records, sort_keys=False, allow_unicode=True, indent=2)
    indent = "  " if "\n  - id:" in tail else ""
    block = "\n".join(indent + ln if ln.strip() else ln for ln in block.splitlines())
    spec_path.write_text(f"{head}{sep}{tail.rstrip()}\n{block}\n", encoding="utf-8")


# ---- meta-tab regeneration ---------------------------------------------------------
# Every meta tab is a RENDER of a repo file, so the repo - not the xlsx - is the carrier.
#   Reference (polish)  render of the source files on disk    -> recreate every run
#   Handoff Prompt      render of docs/polish_handoff.md      -> recreate every run
#   Polish Inbox        stateful queue                        -> CREATE IF MISSING only
MONO = "Consolas"
SRC_FILES = [
    ("FILE 1 of 3   config/polish_spec.yaml",   "config/polish_spec.yaml"),
    ("FILE 2 of 3   tools/register_polish.py",  "tools/register_polish.py"),
    ("FILE 3 of 3   tools/polish_charts.py",    "tools/polish_charts.py"),
]
BANNER = "=" * 95


def _mono_sheet(wb, name, index, tab_color, lines, width=780):
    """Delete-and-recreate a text tab from a list of lines."""
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name, index)
    ws.sheet_properties.tabColor = tab_color
    ws.sheet_view.showGridLines = False
    for r, line in enumerate(lines, start=1):
        c = ws.cell(r, 1)
        _text(c, line)
        c.font = Font(name=MONO, size=9)
        c.number_format = "@"
    ws.column_dimensions["A"].width = width / 7
    ws.freeze_panes = "A2"
    return ws


def render_reference(wb, spec):
    """Reference (polish) = the op vocabulary Claude-in-Excel needs to raise a valid
    Polish Inbox row. GENERATED from OP_SCHEMA, never hand-written.

    It used to dump all three source files as text - about 1,170 rows of Python and YAML
    inside a client-facing workbook, duplicating what git already holds. Nobody reads
    source out of a spreadsheet column; what the one real in-Excel consumer needs is the
    list of verbs and their fields.

    Generated rather than pasted, because a hand-maintained copy drifts the moment a
    handler is added - which is precisely the drift the Build Log tab was invented to
    stop, and it would be embarrassing to reintroduce it here."""
    formats = ", ".join(sorted(spec.get("formats", {})))
    palette = ", ".join(sorted(spec.get("palette", {})))
    lines = [
        "Polish reference - the op vocabulary (GENERATED from the code - do not edit)",
        "",
        f"Rendered by tools/register_polish.py at spec {spec['version']}.",
        "The repo is canonical: config/polish_spec.yaml holds the steps, this tab only",
        "describes what a step may contain. Editing here has no effect.",
        "",
        "HOW TO REQUEST A CHANGE",
        "  Add a row to the Polish Inbox tab with Status = pending and an op: payload",
        "  built from the table below. Do NOT hand-format cells - the next build",
        "  regenerates them and your work is silently discarded.",
        "  An invalid payload is rejected in place, with the reason written into the",
        "  'Merged in' column. It never reaches the spec.",
        "",
        "WHAT THE POLISH LAYER MAY CHANGE",
        "  fill, column width, number format, alignment, freeze panes, column grouping,",
        "  charts, sheet order.",
        "",
        "WHAT IT MUST NEVER CHANGE",
        "  font colour (blue = input, black = formula, amber fill = model write-back,",
        "    thin blue border = model-read - the TOC legend depends on it),",
        "  cell values or formulas, named ranges, anything on a model tab.",
        "  Risk Register / Simulation / Methodology are formatting-only surfaces.",
        "",
        f"  format keys : {formats}",
        f"  palette keys: {palette}",
        "",
        BANNER,
        "OP KINDS",
        BANNER,
        "",
        f"  {'kind':20} {'required':38} {'optional':34} what it does",
    ]
    for kind in sorted(OP_SCHEMA):
        required, optional, doc = OP_SCHEMA[kind]
        lines.append(f"  {kind:20} {', '.join(required) or '-':38} "
                     f"{', '.join(optional) or '-':34} {doc}")
    lines += [
        "",
        "  'sheet' is accepted by every op except the workbook-level ones",
        "  (unprotect_workbook, protect_workbook, sheet_order, create_sheet, protect_sheet).",
        "",
        BANNER,
        "EXAMPLE",
        BANNER,
        "",
        "  kind: numfmt",
        "  sheet: Risk Register",
        "  map:",
        "    money: [P5:R39]",
        "",
        "  A new op KIND cannot be requested from here - that needs a handler in",
        "  tools/register_polish.py. Describe the need in the Change column and leave",
        "  the payload empty; the row will be rejected, which is the correct outcome.",
    ]
    ws = _mono_sheet(wb, "Reference (polish)", len(wb.sheetnames), "7F7F7F", lines)
    ws["A1"].font = Font(name="Calibri", size=13, bold=True, color="1F4E79")
    for row in range(1, ws.max_row + 1):
        text = str(ws.cell(row, 1).value or "")
        if text and text == text.upper() and text.strip() and not text.startswith(("=", " ")):
            ws.cell(row, 1).fill = PatternFill("solid", fgColor="1F4E79")
            ws.cell(row, 1).font = Font(name=MONO, size=9, bold=True, color="FFFFFF")
    return ws


def render_handoff(wb):
    """Handoff Prompt = docs/polish_handoff.md. Version-controlled in the repo, so the
    brief can evolve over time and every register carries the CURRENT one."""
    if not HANDOFF_MD.exists():
        raise FileNotFoundError(
            "docs/polish_handoff.md is missing. It is the canonical handoff brief - "
            "save the Handoff Prompt tab of the golden workbook to that path once, "
            "then it is git-tracked from there.")
    lines = HANDOFF_MD.read_text(encoding="utf-8").splitlines()
    ws = _mono_sheet(wb, "Handoff Prompt", len(wb.sheetnames), "548235", lines)
    ws["A1"].font = Font(name="Calibri", size=15, bold=True, color="548235")
    for row in range(1, ws.max_row + 1):
        if str(ws.cell(row, 1).value or "").startswith("# "):
            ws.cell(row, 1).fill = PatternFill("solid", fgColor="1F4E79")
            ws.cell(row, 1).font = Font(name=MONO, size=9, bold=True, color="FFFFFF")
    return ws


INBOX_HEADS = ["ID", "Raised", "Author", "Target sheet", "Change (human-readable)",
               "op: payload (YAML, 2-space indent)", "Status", "Merged in"]
INBOX_WIDTHS = [9, 11, 14, 14, 43, 49, 11, 11]


def ensure_inbox(wb):
    """CREATE IF MISSING - never recreate. The inbox carries state (status / merged_in);
    deleting it would lose the record of what has already been merged."""
    if "Polish Inbox" in wb.sheetnames:
        return wb["Polish Inbox"]                 # existing queue is preserved untouched

    ws = wb.create_sheet("Polish Inbox", len(wb.sheetnames))
    ws.sheet_properties.tabColor = "C55A11"
    ws.sheet_view.showGridLines = False
    ws["A1"] = "Polish Inbox - pending presentation-layer amendments"
    ws["A1"].font = Font(size=14, bold=True, color="C55A11")
    ws["A2"] = ("ONE-WAY QUEUE. Append changes here; register_polish.py merges them into "
                "config/polish_spec.yaml. Never edit the rendered spec on Reference "
                "(polish), and never hand-format cells instead of raising a row here.")
    ws["A2"].font = Font(size=9, italic=True, color="808080")

    for c, (head, width) in enumerate(zip(INBOX_HEADS, INBOX_WIDTHS), start=1):
        cell = ws.cell(INBOX_HEADER_ROW, c, head)
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[INBOX_HEADER_ROW].height = 30

    example = ["INB-001", str(date.today()), "Claude (Excel)", "Charts",
               "EXAMPLE ROW - shows the required shape. Set Status to pending to activate, "
               "or leave as example to keep it inert.",
               "kind: header\nsheet: Charts\nref: A1", "example", "-"]
    for c, v in enumerate(example, start=1):
        cell = ws.cell(INBOX_HEADER_ROW + 1, c, v)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.font = Font(italic=True, color="808080")
        cell.number_format = "@"
    ws.freeze_panes = f"A{INBOX_HEADER_ROW + 1}"
    return ws


def polish(path: str) -> None:
    """Apply the spec to a register. Amendments are staged, applied, then persisted -
    in that order, so a bad one cannot corrupt the canonical YAML."""
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    wb = load_workbook(path)
    staged = merge_inbox(wb, spec)     # validated + staged in memory; nothing on disk yet
    p = Polisher(wb, spec)
    try:
        p.run()
    except Exception as exc:
        if staged:
            # The spec on disk is untouched. Reload a clean workbook so a half-applied
            # run is not what gets saved, record why against each staged row, and let
            # the caller see the failure.
            clean = load_workbook(path)
            for row, rec in staged:
                _reject(clean[INBOX_SHEET], row,
                        f"applied but failed: {str(exc).splitlines()[0][:180]}")
            clean.save(path)
        raise
    commit_inbox(wb, spec, staged)     # only now does anything reach polish_spec.yaml
    wb.security.lockStructure = True
    wb.save(path)
    print(f"polish {spec['version']}: {len(p.applied)} ops applied, "
          f"{len(p.docs)} documentation-only steps rendered")


if __name__ == "__main__":
    polish(sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_WORKBOOK))
