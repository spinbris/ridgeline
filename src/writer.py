"""
Excel writer — pushes simulation results back to the workbook.

Writes to three targets:
  1. MC_Engine!C168:D{end} — key-value pairs read by XLOOKUP formulas
  2. MC_SingleRun — single-iteration detail table
  3. Chart images — matplotlib PNGs inserted as pictures

Uses xlwings Standard for all write operations.
"""

from pathlib import Path
import xlwings as xw
from src.config import SingleRunResult


# ---------------------------------------------------------------------------
# Target 1: Key-value output table → MC_Engine
# ---------------------------------------------------------------------------

def write_results(wb: xw.Book, output_table: list[list]) -> None:
    """Write the key-value output table to MC_Engine starting at mc_results.

    Uses the mc_results named range as the anchor so the start row is
    immune to future sheet restructuring. Falls back to C6 if name absent.
    """
    sht = wb.sheets["MC_Engine"]

    # Resolve start cell via named range, fall back to C6
    try:
        start = wb.names["mc_results"].refers_to_range
    except Exception:
        start = sht.range("C6")

    # Clear 600 rows from start
    end_row = start.row + 600
    clear_range = sht.range(f"C{start.row}:D{end_row}")
    try:
        clear_range.clear_contents()
    except Exception:
        try:
            clear_range.api.UnMerge()
            clear_range.clear_contents()
        except Exception:
            for r in range(start.row, end_row):
                sht.range(f"C{r}").value = None
                sht.range(f"D{r}").value = None

    if output_table:
        start.value = output_table


# ---------------------------------------------------------------------------
# Target 2: Single run detail → MC_SingleRun
# ---------------------------------------------------------------------------

def write_single_run(wb: xw.Book, result: SingleRunResult) -> None:
    """Write single-iteration detail to MC_SingleRun sheet."""
    sht = wb.sheets["MC_SingleRun"]

    # Clear previous data (preserve headers in rows 1-4)
    try:
        sht.range("A5:P200").clear_contents()
    except Exception:
        try:
            sht.range("A5:P200").api.UnMerge()
            sht.range("A5:P200").clear_contents()
        except Exception:
            pass

    # Clear legacy right-hand summary panel (broken formulas for Shared/L2Only view)
    if result.view in ("Shared", "L2Only"):
        try:
            sht.range("I3:P44").clear_contents()
        except Exception:
            pass

    rows = []

    if result.view in ("Shared", "L2Only"):
        _build_shared_single_run(rows, result)
    else:
        _build_standard_single_run(rows, result)

    sht.range("A5").value = rows

    # Write summary panel to right-hand area
    if result.view in ("Shared", "L2Only"):
        status = "WITHIN BUDGET" if result.pool_headroom >= 0 else "OVER BUDGET"
        panel = [
            ["Shared Risk Pool", ""],
            ["Pool Cost", result.l2_total],
            ["Budget", result.pool_budget],
            ["Headroom", result.pool_headroom],
            ["Fired", f"{result.n_fired} of {result.n_risks}"],
            ["Status", status],
        ]
        sht.range("I3").value = panel
        try:
            sht.range("J4:J6").number_format = '$#,##0'
        except Exception:
            pass

    # Apply number formats to the data region
    _format_single_run(sht, result)


def _build_shared_single_run(rows: list, result: SingleRunResult) -> None:
    """Build SingleRun output rows for Shared view (pool sizing).

    Layout: pool summary at top, then fired-only events sorted by cost desc.
    Designed for director meeting readability.
    """
    # Title
    rows.append(["SHARED RISK POOL - SINGLE SCENARIO", "", "", "", "", "", "", ""])
    rows.append(["", "", "", "", "", "", "", ""])

    # Pool summary block (before events - director reads this first)
    status = "WITHIN BUDGET" if result.pool_headroom >= 0 else "OVER BUDGET"
    rows.append(["POOL SUMMARY", "", "", "", "", "", "", ""])
    rows.append(["Risks fired", f"{result.n_fired} of {result.n_risks}",
                 "", "", "", "", "", ""])
    rows.append(["Pool cost (this scenario)", "", "",
                 result.l2_total, "", "", "", ""])
    rows.append([result.pool_budget_label, "", "",
                 result.pool_budget, "", "", "", ""])
    rows.append(["Pool headroom", "", "",
                 result.pool_headroom, "", status, "", ""])
    rows.append(["", "", "", "", "", "", "", ""])

    # Fired events only, sorted by cost descending
    fired = [ev for ev in result.events if ev.fired]
    fired.sort(key=lambda e: e.cost_impact, reverse=True)
    n_unfired = len(result.events) - len(fired)

    rows.append(["RISKS THAT FIRED", "Prob", "Dist", "Fired?",
                 "Cost Impact", "Days", "Detail", "Running $"])

    running = 0.0
    for ev in fired:
        detail = ev.chain_note
        if ev.per_occurrence_costs:
            occ_strs = [f"${c/1e6:,.3f}M" for c in ev.per_occurrence_costs]
            detail = f"{len(ev.per_occurrence_costs)} occ: {', '.join(occ_strs)}"
        running += ev.cost_impact
        rows.append([
            f"{ev.risk_id} {ev.description[:60]}",
            ev.probability,
            ev.distribution,
            "YES",
            ev.cost_impact,
            ev.days_impact if ev.days_impact > 0 else "",
            detail,
            running,
        ])

    rows.append(["", "", "", "", "", "", "", ""])
    rows.append([f"{n_unfired} risks did not fire in this scenario",
                 "", "", "", "", "", "", ""])


def _build_standard_single_run(rows: list, result: SingleRunResult) -> None:
    """Build SingleRun output rows for All/BOP/CSE views."""

    # Layer 1 section
    rows.append(["LAYER 1: WBS VARIATION", "Base", "Var%", "Impact",
                 "Dist", "", "", ""])
    for b in result.buckets:
        rows.append([b.name, b.base_cost, b.var_pct, b.impact,
                     b.distribution, "", "", ""])

    rows.append(["Layer 1 subtotal", "", "",
                 result.l1_total_variation, "",
                 result.l1_outturn, "", ""])
    rows.append(["", "", "", "", "", "", "", ""])

    # Layer 2 section
    rows.append(["LAYER 2: EVENT RISKS", "Owner", "Dist", "Prob",
                 "Fired?", "Cost Impact", "Days", "Chain"])
    for ev in result.events:
        detail = ev.chain_note
        if ev.per_occurrence_costs:
            occ_strs = [f"${c/1e6:+,.3f}M" for c in ev.per_occurrence_costs]
            detail = f"{len(ev.per_occurrence_costs)} occ: {', '.join(occ_strs)}"
        rows.append([
            f"{ev.risk_id} {ev.description[:60]}",
            ev.owner[:15],
            ev.distribution,
            ev.probability,
            "Yes" if ev.fired else "",
            ev.cost_impact if ev.fired else 0,
            ev.days_impact if ev.fired and ev.days_impact > 0 else "",
            detail,
        ])

    rows.append(["", "", "", "", "", "", "", ""])

    # Cost summary
    rows.append(["COST SUMMARY", "", "", "", "All", "BOP", "CSE", ""])
    rows.append(["L1 variation", "", "", "",
                 result.l1_total_variation, "", "", ""])
    rows.append(["L2 event costs", "", "", "",
                 result.l2_total, result.bop_l2, result.cse_l2, ""])
    rows.append(["Total outturn", "", "", "",
                 result.total_outturn, result.bop_outturn,
                 result.cse_outlay, ""])


def _format_single_run(sht: xw.Sheet, result: SingleRunResult) -> None:
    """Apply Excel formatting to SingleRun output."""

    if result.view in ("Shared", "L2Only"):
        # Pool summary costs: D9 (pool cost), D10 (budget), D11 (headroom)
        try:
            sht.range("D9:D11").number_format = '$#,##0'
        except Exception:
            pass

        # Headroom conditional colour (row 11)
        try:
            if result.pool_headroom >= 0:
                sht.range("D11").font.color = (0, 128, 0)  # green
                sht.range("F11").font.color = (0, 128, 0)
            else:
                sht.range("D11").font.color = (192, 0, 0)  # red
                sht.range("F11").font.color = (192, 0, 0)
        except Exception:
            pass

        # Fired events section starts at row 14
        n_fired = sum(1 for ev in result.events if ev.fired)
        ev_start = 14
        ev_end = ev_start + n_fired - 1
        if n_fired > 0:
            try:
                sht.range(f"B{ev_start}:B{ev_end}").number_format = '0%'
                sht.range(f"E{ev_start}:E{ev_end}").number_format = '$#,##0'
                sht.range(f"H{ev_start}:H{ev_end}").number_format = '$#,##0'
            except Exception:
                pass
    else:
        # Standard view formatting
        # L1 section starts row 6 (A5 + 1 header)
        if result.buckets:
            l1_end = 6 + len(result.buckets) - 1
            try:
                sht.range(f"B6:B{l1_end}").number_format = '$#,##0'
                sht.range(f"C6:C{l1_end}").number_format = '0.0%'
                sht.range(f"D6:D{l1_end}").number_format = '$#,##0'
            except Exception:
                pass

        # L2 events: header row = 6 + n_buckets + 3, data starts one after
        l2_start = 6 + len(result.buckets) + 3
        l2_end = l2_start + len(result.events) - 1
        try:
            # Prob is now col D (after Owner, Dist)
            sht.range(f"D{l2_start}:D{l2_end}").number_format = '0%'
            sht.range(f"F{l2_start}:F{l2_end}").number_format = '$#,##0'
        except Exception:
            pass

        # Cost summary block: 3 rows after L2 events + blank + header
        cs_start = l2_end + 3  # blank + "COST SUMMARY" header + first data row
        try:
            sht.range(f"E{cs_start}:G{cs_start + 2}").number_format = '$#,##0'
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Target 3: Chart images
# ---------------------------------------------------------------------------

def insert_chart(
    wb: xw.Book,
    sheet_name: str,
    cell: str,
    image_path: str | Path,
    name: str = "mc_chart",
    width: float = 550,
    height: float = 350,
) -> None:
    """Insert a matplotlib PNG into the workbook as a picture.

    Removes any existing picture with the same name before inserting,
    so repeated runs don't accumulate images.

    Parameters
    ----------
    wb : open xlwings Book
    sheet_name : target sheet (e.g. "MC_Dashboard")
    cell : anchor cell (e.g. "B25")
    image_path : path to PNG file
    name : picture name (for identification / replacement)
    width, height : display dimensions in points
    """
    sht = wb.sheets[sheet_name]

    # Remove existing picture with same name
    for pic in sht.pictures:
        if pic.name == name:
            pic.delete()
            break

    anchor = sht.range(cell)
    sht.pictures.add(
        str(image_path),
        name=name,
        left=anchor.left,
        top=anchor.top,
        width=width,
        height=height,
    )


# ---------------------------------------------------------------------------
# Write run metadata
# ---------------------------------------------------------------------------

def write_run_metadata(wb: xw.Book, n_iter: int, n_risks: int,
                       elapsed_sec: float, view: str) -> None:
    """Write run timestamp and metadata to MC_Engine header area."""
    import datetime
    sht = wb.sheets["MC_Engine"]
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sht.range("E3").value = (
        f"Last run: {timestamp} | {n_iter:,} iterations | "
        f"{n_risks} risks | View: {view} | {elapsed_sec:.1f}s"
    )
