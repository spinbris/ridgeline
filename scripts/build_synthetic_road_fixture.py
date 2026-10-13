"""Generate the synthetic ROAD fixture - ROAD-01, project #2.

Produces `tests/fixtures/synthetic_road/road_register.xlsx` (contract 1.4, consolidated: themed
"Risk Register" + "Mapping" + "MC_Params") and `road_schedule.xer`, for the **Kestrel Highway
Upgrade**: a 7.2 km brownfield highway upgrade with one viaduct and one bridge, business-case
phase, base estimate $68.4M (Director ruling 07/09/2026, brief §5.4).

**The shape is the department's, the numbers are ours - and the split is the point.**

Stage 4 asks whether the product is project-generic. A project the Builder invents by reading the
engine proves only that the Builder can read the engine, so ROAD-01 §A-2 requires every WBS
heading and every Layer-1 factor name to trace to the department's published guidance. They do: the WBS
comes from the department's own road worked example (`models/RFM3_Estimate_summary.csv`) and the
factor names from its factor table (`models/RFM3_Risk_factors.csv`).

**Quantities, rates and risk values are authored here** (§A-3). Copying the worked example's
figures would make project #2 a reproduction of a published example - the golden would be
measuring the department's numbers rather than ours, and the provenance question would never
close.

**Structure is shared, not copied.** Every sheet, named range and grid is emitted by
`tools/register_scaffold.py`, the same builders the empty per-project template and the wind
fixture use, so this fixture cannot drift from the contract. What lives here is data.

Deliberately NOT generated (ROAD-01 §D-3): an escalation rate and a base date. The register
carries neither, because the contract 1.4 -> 1.5 bump is unspent - and those two are exactly
GN4-31's absent inputs 2 and 4 (GN4's escalation text).

Run:  python scripts/build_synthetic_road_fixture.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.final.product import MAKER  # noqa: E402
from src.v5_register_reader import SEED_LABEL  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_road"

PROJECT_DISPLAY_NAME = "Kestrel Highway Upgrade"
RISK_PREFIX = "KH"

# ---------------------------------------------------------------------------
# Cost basis - $68.4M (brief §5.4). Every group label traces to the department's
# road worked example, RFM3_Estimate_summary.csv; the dollars are ours.
# ---------------------------------------------------------------------------
CAPEX_BASIS = {
    "CG01": ("Establishment & Preliminaries", 4_100_000),   # RFM3 "Establishment and preliminaries"
    "CG02": ("Earthworks", 9_800_000),                      # RFM3 "Earthworks"
    "CG03": ("Drainage & Stormwater", 5_400_000),           # RFM3 "Stormwater drainage"
    "CG04": ("Pavement & Surfacing", 12_600_000),           # RFM3 "Pavement"
    "CG05": ("Retaining Walls & Barriers", 4_900_000),      # RFM3 "Retaining walls", "Barriers"
    "CG06": ("Structures - Viaduct", 16_200_000),           # RFM3 "Viaduct"
    "CG07": ("Structures - Bridge", 11_800_000),            # RFM3 "Bridge"
    "CG08": ("Traffic Staging & Finishing", 3_600_000),     # GN3B Table 1 "Constructability"
}
ROAD_CAPEX_TOTAL = sum(v[1] for v in CAPEX_BASIS.values())  # $68,400,000

#: Per-group correlation labels written to MC_Params. Higher where the brownfield
#: setting couples groups: staging touches everything on a live carriageway.
ROAD_CG_COEFFICIENTS = {
    "CG01": 0.5, "CG02": 0.6, "CG03": 0.5, "CG04": 0.6,
    "CG05": 0.5, "CG06": 0.6, "CG07": 0.6, "CG08": 0.5,
}

#: The Tier-1 methodology surface. All 13 CG keys are written because
#: `register_contract._N_CG` requires 13 rows whatever a project's real group count
#: (REGCG13-01) - CG09-CG13 are padding this project does not use.
METHODOLOGY_CG_COEFFICIENTS = {
    "CG01": 0.5, "CG02": 0.6, "CG03": 0.5, "CG04": 0.6, "CG05": 0.5,
    "CG06": 0.6, "CG07": 0.6, "CG08": 0.5, "CG09": 0.4, "CG10": 0.4,
    "CG11": 0.5, "CG12": 0.5, "CG13": 0.5,
}
METHODOLOGY_MODE_MULTIPLIERS = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}

#: $/working day for schedule contingency. A 7.2 km brownfield upgrade runs a smaller
#: prelims spine than a power-station BOP; authored, and the ONE home for the rate.
ROAD_DAY_RATE = 48_000.0

# ---------------------------------------------------------------------------
# Layer 1 - the GN3A factor model, on this project's WBS.
# Column vocabulary and factor names trace to RFM3; the base matrix and the
# three-point ranges are authored.
# ---------------------------------------------------------------------------
_ALL = ("ALL",)

L1_COLS = ("Staff", "Labour", "Plant", "Concrete", "Steel", "General",
           "Subcontract", "Provisional")

L1_ROWS = ("Establishment & preliminaries", "Earthworks", "Drainage & stormwater",
           "Pavement & surfacing", "Retaining walls & barriers", "Viaduct",
           "Bridge", "Traffic staging & finishing")

#: $M, rows x cols in L1_ROWS / L1_COLS order. Row sums equal CAPEX_BASIS.
_BASE_M = np.array([
    [2.30, 0.30, 0.60, 0.00, 0.00, 0.40, 0.30, 0.20],  # Establishment & preliminaries  4.10
    [0.20, 2.60, 4.10, 0.00, 0.00, 1.50, 1.10, 0.30],  # Earthworks                     9.80
    [0.10, 1.30, 0.90, 1.60, 0.20, 0.90, 0.30, 0.10],  # Drainage & stormwater          5.40
    [0.20, 2.90, 3.60, 0.00, 0.00, 4.60, 1.10, 0.20],  # Pavement & surfacing          12.60
    [0.10, 1.20, 0.70, 1.50, 0.60, 0.50, 0.20, 0.10],  # Retaining walls & barriers     4.90
    [0.40, 3.10, 2.60, 5.20, 3.10, 1.20, 0.40, 0.20],  # Viaduct                       16.20
    [0.30, 2.30, 1.90, 3.80, 2.20, 0.90, 0.30, 0.10],  # Bridge                        11.80
    [0.30, 0.90, 0.70, 0.00, 0.20, 0.80, 0.60, 0.10],  # Traffic staging & finishing    3.60
], dtype=np.float64)

#: (name, driver, opt/P10 delta, ml/mode delta, p90 delta, col_scope, rows).
#: **Names are RFM3's** (`models/RFM3_Risk_factors.csv`); ranges are authored.
#: RFM3's "Duration" carries no cost range - it is the schedule arm, and is not a
#: Layer-1 cost factor here.
L1_FACTORS = (
    ("Provisions",                       "commercial", -0.03, 0.0, 0.16, ("Provisional",), _ALL),
    ("Preliminaries rate",               "commercial", -0.04, 0.0, 0.13, _ALL, ("Establishment & preliminaries",)),
    ("Engineering scale",                "scope",      -0.08, 0.0, 0.18, ("Staff",), _ALL),
    ("Productivity",                     "delivery",   -0.06, 0.0, 0.22, ("Labour", "Plant"), _ALL),
    ("Plant and site equipment quantity", "quantity",   0.00, 0.0, 0.20, ("Plant",), _ALL),
    ("Earthworks quantity",              "quantity",   -0.06, 0.0, 0.17, _ALL, ("Earthworks",)),
    ("Concrete quantity",                "quantity",   -0.04, 0.0, 0.12, ("Concrete",), _ALL),
    ("Retaining walls quantity",         "quantity",   -0.05, 0.0, 0.19, _ALL, ("Retaining walls & barriers",)),
    ("Pavement quantity",                "quantity",   -0.04, 0.0, 0.09, _ALL, ("Pavement & surfacing",)),
    ("Barriers quantity",                "quantity",    0.00, 0.0, 0.11, ("General",), ("Retaining walls & barriers",)),
    ("Piling quantity",                  "quantity",   -0.05, 0.0, 0.21, ("Subcontract",), ("Viaduct", "Bridge")),
    ("Structural steel quantity",        "quantity",   -0.04, 0.0, 0.13, ("Steel",), _ALL),
    ("Concrete rate",                    "rate",       -0.09, 0.0, 0.14, ("Concrete",), _ALL),
    ("Steel rate",                       "rate",       -0.11, 0.0, 0.12, ("Steel",), _ALL),
    ("General bulks rate",               "rate",       -0.05, 0.0, 0.11, ("General",), _ALL),
    ("Plant rate",                       "rate",       -0.08, 0.0, 0.07, ("Plant",), _ALL),
    ("Subcontract rates",                "rate",       -0.09, 0.0, 0.08, ("Subcontract",), _ALL),
    ("Staff rate",                       "rate",        0.00, 0.0, 0.06, ("Staff",), _ALL),
    ("Labour rate",                      "rate",        0.00, 0.0, 0.11, ("Labour",), _ALL),
)

#: The correlated block: RFM3's seven **rate** factors. Rates move together because
#: they share input markets, which is the same reasoning GN4 gives for escalation
#: (`text/GN4_escalation.txt:268-272`).
L1_CORR_NAMES = ("Concrete rate", "Steel rate", "General bulks rate", "Plant rate",
                 "Subcontract rates", "Staff rate", "Labour rate")

#: Lower triangle, in L1_CORR_NAMES order. Kept modest so the elicited set is
#: jointly possible - a non-PSD matrix is refused by the register reader.
_CORR_LOWER = np.array([
    [1.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],  # Concrete rate
    [0.45, 1.00, 0.00, 0.00, 0.00, 0.00, 0.00],  # Steel rate
    [0.40, 0.40, 1.00, 0.00, 0.00, 0.00, 0.00],  # General bulks rate
    [0.25, 0.25, 0.30, 1.00, 0.00, 0.00, 0.00],  # Plant rate
    [0.30, 0.30, 0.35, 0.35, 1.00, 0.00, 0.00],  # Subcontract rates
    [0.15, 0.15, 0.20, 0.20, 0.25, 1.00, 0.00],  # Staff rate
    [0.20, 0.20, 0.25, 0.25, 0.30, 0.55, 1.00],  # Labour rate
], dtype=np.float64)

# ---------------------------------------------------------------------------
# Schedule WBS - the .xer topology the Stage 3 auto-mapper binds risks onto.
# ---------------------------------------------------------------------------
ROAD_WBS = [
    ("10", 110, "Site Establishment & Traffic Staging"),
    ("20", 120, "Earthworks & Drainage"),
    ("30", 130, "Structures - Viaduct"),
    ("40", 140, "Structures - Bridge"),
    ("50", 150, "Pavement & Surfacing"),
    ("60", 160, "Finishing & Handover"),
]

#: One gating activity per Time=Yes risk, each on the controlling spine with a
#: unique code, so the auto-mapper binds a risk to exactly one activity.
GATING = {
    f"{RISK_PREFIX}-002": ("10.G.001", "Traffic switch stage 1"),
    f"{RISK_PREFIX}-004": ("20.G.001", "Bulk earthworks main line"),
    f"{RISK_PREFIX}-007": ("20.G.002", "Trunk drainage installation"),
    f"{RISK_PREFIX}-011": ("30.G.001", "Viaduct piling"),
    f"{RISK_PREFIX}-013": ("30.G.002", "Viaduct girder erection"),
    f"{RISK_PREFIX}-017": ("40.G.001", "Bridge substructure"),
    f"{RISK_PREFIX}-019": ("40.G.002", "Bridge deck pour"),
    f"{RISK_PREFIX}-023": ("50.G.001", "Asphalt base course"),
    f"{RISK_PREFIX}-026": ("50.G.002", "Final wearing course"),
    f"{RISK_PREFIX}-029": ("60.G.001", "Line marking & handover"),
}

#: risk id -> (auto-mapper prefix, expected bound activity count). Five risks bind
#: 1:1 to their gate; five broaden onto a work-group prefix, which is the shape
#: WIND-03 warns must be chosen deliberately rather than applied to everything.
PREFIX_MAPPING = {
    f"{RISK_PREFIX}-002": ("10.G.001", 1),
    f"{RISK_PREFIX}-004": ("20.", 7),
    f"{RISK_PREFIX}-007": ("20.G.002", 1),
    f"{RISK_PREFIX}-011": ("30.", 8),
    f"{RISK_PREFIX}-013": ("30.G.002", 1),
    f"{RISK_PREFIX}-017": ("40.", 7),
    f"{RISK_PREFIX}-019": ("40.G.002", 1),
    f"{RISK_PREFIX}-023": ("50.", 5),
    f"{RISK_PREFIX}-026": ("50.G.002", 1),
    f"{RISK_PREFIX}-029": ("60.G.001", 1),
}


# ---------------------------------------------------------------------------
# Risk data - 30 synthetic road risks, 10 of them Time=Yes.
# fields: id, status, desc, owner, rbs1, rbs2, dist, cg, recurrence,
#         prob_cost, opt$, ml$, pess$, time?, mode, prob_time, optD, mlD, pessD,
#         cascade_group, sched_prefix
#
# The heavy risks cluster where GN3B Table 1 says a road's uncertainty sits: site
# information (geotechnical, services, contamination), constructability and staging,
# and project interfaces (`text/GN3B_deterministic.txt:245-283`). The Director's
# brownfield ruling is what makes that the right cluster - on a greenfield alignment
# the weight would sit elsewhere.
# ---------------------------------------------------------------------------
ROAD_RISKS = [
    # ----- CG01 Establishment & Preliminaries ($4.1M) -----
    ("KH-001", "Open", "Site compound relocation for utility access", "Contractor",
     "Establishment", "Site setup", "PERT", "CG01", "", 0.35, 40_000, 120_000, 300_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-002", "Open", "Traffic staging redesign after road-authority review", "Principal",
     "Establishment", "Traffic staging", "PERT", "CG01", "", 0.45, 90_000, 260_000, 640_000,
     "Yes", "Series", 0.45, 6, 15, 32, "", "10"),
    ("KH-003", "Open", "Extended night-works restrictions", "Contractor",
     "Establishment", "Approvals", "Triangular", "CG01", "Single", 0.30, 50_000, 150_000, 380_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG02 Earthworks ($9.8M) -----
    ("KH-004", "Open", "Unforeseen ground conditions in main-line cut", "Contractor",
     "Earthworks", "Bulk earthworks", "Lognormal", "CG02", "", 0.40, 260_000, 780_000, 2_100_000,
     "Yes", "Series", 0.40, 8, 20, 45, "", "20"),
    ("KH-005", "Open", "Unsuitable material requiring off-site disposal", "Contractor",
     "Earthworks", "Spoil", "PERT", "CG02", "", 0.45, 120_000, 400_000, 1_050_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-006", "Open", "Contaminated soil in former industrial verge", "Principal",
     "Earthworks", "Contamination", "Lognormal", "CG02", "", 0.25, 180_000, 620_000, 1_900_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG03 Drainage & Stormwater ($5.4M) -----
    ("KH-007", "Open", "Undetected services along trunk drainage alignment", "Contractor",
     "Drainage", "Services", "PERT", "CG03", "Multiple", 0.55, 90_000, 300_000, 760_000,
     "Yes", "Hybrid", 0.55, 5, 12, 26, "", "20"),
    ("KH-008", "Open", "Wet-weather shutdown of open trench works", "Contractor",
     "Drainage", "Weather", "Triangular", "CG03", "Multiple", 0.50, 60_000, 190_000, 470_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-009", "Open", "Outfall approval delay from water authority", "Principal",
     "Drainage", "Approvals", "PERT", "CG03", "", 0.30, 40_000, 130_000, 340_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-010", "Open", "Scour protection extended beyond design allowance", "Contractor",
     "Drainage", "Scour", "PERT", "CG03", "", 0.35, 50_000, 150_000, 390_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG06 Structures - Viaduct ($16.2M) -----
    ("KH-011", "Open", "Pile founding level deeper than investigation indicated", "Contractor",
     "Structures", "Viaduct piling", "Lognormal", "CG06", "", 0.40, 320_000, 950_000, 2_600_000,
     "Yes", "Series", 0.40, 10, 24, 52, "", "30"),
    ("KH-012", "Open", "Precast girder supply delay from single fabricator", "Contractor",
     "Structures", "Viaduct supply", "PERT", "CG06", "", 0.30, 200_000, 640_000, 1_700_000,
     "No", "", 0.0, 0, 0, 0, "CHAIN-A", ""),
    ("KH-013", "Open", "Crane access constrained by live carriageway", "Contractor",
     "Structures", "Viaduct erection", "PERT", "CG06", "", 0.45, 180_000, 540_000, 1_400_000,
     "Yes", "Hybrid", 0.45, 7, 18, 38, "CHAIN-A", "30"),
    ("KH-014", "Open", "Bearing and expansion-joint rework", "Contractor",
     "Structures", "Viaduct fitout", "Triangular", "CG06", "", 0.30, 70_000, 220_000, 560_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-015", "Open", "Additional temporary works for span over rail reserve", "Contractor",
     "Structures", "Temporary works", "PERT", "CG06", "", 0.35, 150_000, 460_000, 1_200_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-016", "Open", "Viaduct parapet finish rejected at hold point", "Contractor",
     "Structures", "Quality", "Triangular", "CG06", "Single", 0.25, 60_000, 180_000, 450_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG07 Structures - Bridge ($11.8M) -----
    ("KH-017", "Open", "Abutment excavation encounters high groundwater", "Contractor",
     "Structures", "Bridge substructure", "Lognormal", "CG07", "", 0.35, 210_000, 680_000, 1_900_000,
     "Yes", "Series", 0.35, 8, 19, 42, "", "40"),
    ("KH-018", "Open", "Reinforcement supply escalation on long-lead order", "Contractor",
     "Structures", "Bridge supply", "PERT", "CG07", "", 0.30, 120_000, 380_000, 980_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-019", "Open", "Deck pour deferred by concrete plant availability", "Contractor",
     "Structures", "Bridge deck", "PERT", "CG07", "Multiple", 0.40, 90_000, 290_000, 740_000,
     "Yes", "Parallel", 0.40, 4, 11, 24, "", "40"),
    ("KH-020", "Open", "Waterway occupation window missed", "Principal",
     "Structures", "Environmental", "PERT", "CG07", "", 0.20, 130_000, 420_000, 1_150_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-021", "Open", "Bridge barrier crash-test certification shortfall", "Contractor",
     "Structures", "Compliance", "Triangular", "CG07", "", 0.20, 50_000, 160_000, 410_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG04 Pavement & Surfacing ($12.6M) -----
    ("KH-022", "Open", "Subgrade CBR below design assumption", "Contractor",
     "Pavement", "Subgrade", "Lognormal", "CG04", "", 0.40, 240_000, 720_000, 2_000_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-023", "Open", "Asphalt supply interrupted by plant outage", "Contractor",
     "Pavement", "Supply", "PERT", "CG04", "Multiple", 0.45, 110_000, 350_000, 900_000,
     "Yes", "Hybrid", 0.45, 5, 13, 28, "", "50"),
    ("KH-024", "Open", "Additional pavement rehabilitation on tie-in sections", "Principal",
     "Pavement", "Tie-ins", "PERT", "CG04", "", 0.50, 160_000, 520_000, 1_350_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-025", "Open", "Surfacing temperature restrictions in winter window", "Contractor",
     "Pavement", "Weather", "Triangular", "CG04", "Multiple", 0.40, 70_000, 210_000, 530_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-026", "Open", "Wearing course rejected on ride-quality testing", "Contractor",
     "Pavement", "Quality", "PERT", "CG04", "", 0.25, 130_000, 400_000, 1_050_000,
     "Yes", "Series", 0.25, 4, 10, 22, "", "50"),
    # ----- CG05 Retaining Walls & Barriers ($4.9M) -----
    ("KH-027", "Open", "Retaining wall founding redesign", "Contractor",
     "Retaining", "Walls", "PERT", "CG05", "", 0.35, 90_000, 280_000, 730_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    ("KH-028", "Open", "Barrier deflection zone conflicts with property boundary", "Principal",
     "Retaining", "Barriers", "Triangular", "CG05", "", 0.30, 60_000, 190_000, 490_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG08 Traffic Staging & Finishing ($3.6M) -----
    ("KH-029", "Open", "Final line marking and signage rework after audit", "Contractor",
     "Finishing", "Line marking", "PERT", "CG08", "", 0.35, 40_000, 130_000, 330_000,
     "Yes", "Parallel", 0.35, 3, 8, 17, "", "60"),
    ("KH-030", "Open", "Landscaping establishment period extended", "Principal",
     "Finishing", "Landscaping", "Triangular", "CG08", "", 0.30, 30_000, 95_000, 240_000,
     "No", "", 0.0, 0, 0, 0, "", ""),
]


# ===========================================================================
# Register
# ===========================================================================

def _build_layer1_sheets(wb) -> None:
    """Fill Layer 1 over the SHARED empty builder, exactly as the wind fixture does.

    The structure comes from `tools.register_scaffold.build_layer1_sheets`, so this
    fixture and the empty per-project template cannot drift. What is supplied here
    is the road project's fill: RFM3's factor names, this project's WBS rows, and
    an authored base matrix and correlation set.
    """
    from tools.register_scaffold import build_layer1_sheets

    factors = [
        (name, driver, opt, ml, p90,
         "ALL" if "ALL" in cols else ",".join(cols))
        for (name, driver, opt, ml, p90, cols, _rows) in L1_FACTORS
    ]
    alloc = {
        name: ("ALL" if "ALL" in rows else list(rows))
        for (name, _d, _o, _m, _p, _c, rows) in L1_FACTORS
    }
    build_layer1_sheets(
        wb,
        col_labels=list(L1_COLS),
        row_labels=list(L1_ROWS),
        base_m=[[float(x) for x in _BASE_M[i]] for i in range(len(L1_ROWS))],
        factors=factors,
        alloc=alloc,
        corr_names=list(L1_CORR_NAMES),
        corr_lower=_CORR_LOWER,
        corr_mode="elicited",
        declared_total_m=float(ROAD_CAPEX_TOTAL) / 1_000_000.0,
    )


def _assert_valid_mode(rid: str, mode: str) -> str:
    """A Time=Yes risk must carry a recognised Mode, and the build fails before any
    file is written rather than emitting a register the schedule arm cannot read."""
    if mode not in METHODOLOGY_MODE_MULTIPLIERS:
        raise ValueError(
            f"{rid}: Time=Yes risk carries mode {mode!r}, which is not one of "
            f"{sorted(METHODOLOGY_MODE_MULTIPLIERS)}")
    return mode


def build_register(path: Path) -> None:
    """Write the consolidated road register: themed "Risk Register" + "Mapping" +
    "MC_Params", plus the shared Layer-1, methodology, settings and simulation sheets."""
    from tools.register_scaffold import (  # noqa: E402
        DATA_START_ROW, add_dropdowns, apply_finish, apply_protection,
        build_lists_sheet, build_methodology_sheet, build_reference,
        build_settings_and_simulation, build_toc, finalize_named_ranges,
        name_day_rate, style_register_input_cells, theme_risk_register,
        write_emv_formulas, write_risk_header_rows,
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Risk Register"
    write_risk_header_rows(ws)

    for i, r in enumerate(ROAD_RISKS):
        (rid, status, desc, owner, rbs1, rbs2, dist, cg, recur,
         pc, oc, mc, pcst, timp, mode, ptime, od, md, pd, casc, prefix) = r
        row = DATA_START_ROW + i
        mode_cell = _assert_valid_mode(rid, mode) if timp == "Yes" else ""
        vals = [
            rid, status, desc, owner, rbs1, rbs2, "Yes", dist, cg, recur,
            "synthetic cause", "synthetic consequence", "synthetic controls",
            "Yes", pc, oc, mc, pcst, "Kestrel Highway Upgrade base estimate",
            timp, ptime, od, md, pd, "Synthetic",
            mode_cell, "per_occurrence",
        ]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=row, column=c, value=v)

    n_risks = len(ROAD_RISKS)
    _last_data = DATA_START_ROW + n_risks - 1
    write_emv_formulas(ws, DATA_START_ROW, _last_data)
    theme_risk_register(ws, n_risks)
    build_lists_sheet(wb, factor_seed=[f[0] for f in L1_FACTORS])
    add_dropdowns(ws, DATA_START_ROW, _last_data)
    style_register_input_cells(ws, DATA_START_ROW, _last_data)

    # --- Mapping sheet (machine-facing CPM binding; Time=Yes only) ---
    mapping = wb.create_sheet("Mapping")
    for c, h in enumerate(["Risk ID", "Pattern_ID", "Prefix_List", "Activity_Count",
                           "Gating_Activity_ID", "Injection_Method"], start=1):
        mapping.cell(row=1, column=c, value=h)
    mrow = 2
    for r in ROAD_RISKS:
        rid, timp = r[0], r[13]
        if timp != "Yes":
            continue
        pfx, acount = PREFIX_MAPPING.get(rid, ("", 1))
        gate = GATING.get(rid, ("", ""))[0]
        for c, v in enumerate([rid, f"P-{rid}", pfx, acount, gate, ""], start=1):
            mapping.cell(row=mrow, column=c, value=v)
        mrow += 1

    # --- MC_Params (run config; the ONE home for the day rate) ---
    n_time = sum(1 for r in ROAD_RISKS if r[13] == "Yes")
    mp = wb.create_sheet("MC_Params")
    params = [
        ("Iterations (n)", 50000),
        (SEED_LABEL, 42),
        ("Stakeholder view", "All"),
        ("Reporting P-Level (pct)", 80),
        ("TIC - Total Installed Cost ($)", ROAD_CAPEX_TOTAL),
        ("Cascade enabled", 1),
        ("Cascade slip rate", 1.5),
        ("Cascade slip cap", 3.0),
        ("Cascade cost scale", 0.5),
        ("Chain 1 trigger - planning delay (months)", 3.0),
        ("Chain 1 - weather amplification factor", 2.5),
        ("Chain 2 trigger - site estab delay (weeks)", 2.0),
        ("Chain 2 - cascade factor", 1.5),
        ("day_rate ($/wd)", ROAD_DAY_RATE),
        ("programme_seasons", 1),
        ("cp_hybrid_float_threshold_days", 20),
        ("schedule duration (weeks)", 104),
        ("expected_time_yes_count", n_time),
    ]
    for cg, (label, base) in CAPEX_BASIS.items():
        params.append((f"{cg} - {label}", ROAD_CG_COEFFICIENTS[cg]))
        params.append((f"{cg} capex base ($)", base))
    for i, (label, value) in enumerate(params, start=2):
        mp.cell(row=i, column=2, value=label)
        mp.cell(row=i, column=3, value=value)
    name_day_rate(wb, mp)

    _build_layer1_sheets(wb)
    build_methodology_sheet(
        wb, cg_values=METHODOLOGY_CG_COEFFICIENTS,
        cg_descriptions={cg: label for cg, (label, _b) in CAPEX_BASIS.items()},
    )
    build_toc(wb)
    build_reference(wb)
    build_settings_and_simulation(wb)
    wb["Settings"]["B8"] = True          # Layer 1 ON: this project has a base estimate
    wb["Settings"]["B4"] = RISK_PREFIX   # Set_risk_prefix - no fallback exists any more
    finalize_named_ranges(wb)
    apply_finish(wb, project={
        "Set_ProjectName": PROJECT_DISPLAY_NAME,
        "Set_ProjectNumber": "KH-UPG-001",
        "Set_Client": "State Road Authority",
        "Set_PreparedBy": MAKER,
        "Set_Revision": "A",
    })
    apply_protection(wb)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    print(f"wrote {path} ({n_risks} risks, {n_time} Time=Yes, "
          f"TIC=${ROAD_CAPEX_TOTAL:,})")


# ===========================================================================
# Schedule (XER)
# ===========================================================================

def _build_schedule_tables() -> dict:
    """A ~2-year brownfield highway upgrade.

    Topology: one controlling spine (establishment -> traffic staging -> earthworks
    and drainage -> structures -> pavement -> finishing) carrying all ten gating
    activities at zero float, with floated detail branches hanging off it. Each gate
    code is unique so the Stage 3 auto-mapper binds a risk to exactly one activity;
    detail activities carry float below the project's 480-hour threshold so a
    work-group prefix binds them too.

    Activity counts per WBS prefix are what `PREFIX_MAPPING` asserts, and the suite
    checks the two agree - a mapping that expects more activities than exist would
    bind silently short.
    """
    import pandas as pd

    calendar = [{
        "clndr_id": 1, "clndr_name": "Standard 5-day", "default_flag": "Y",
        "clndr_data": "(0||CalendarData())", "day_hr_cnt": 8.0,
        "week_hr_cnt": 40.0, "month_hr_cnt": 172.0, "year_hr_cnt": 2000.0,
    }]
    projwbs = [{"wbs_id": 100, "proj_id": 1, "parent_wbs_id": None,
                "wbs_short_name": "KH", "wbs_name": "Kestrel Highway Upgrade",
                "seq_num": 1}]
    for k, (prefix, wid, name) in enumerate(ROAD_WBS, start=2):
        projwbs.append({"wbs_id": wid, "proj_id": 1, "parent_wbs_id": 100,
                        "wbs_short_name": prefix, "wbs_name": name, "seq_num": k})

    wbs_id = {prefix: wid for (prefix, wid, _n) in ROAD_WBS}
    start = pd.Timestamp("2026-07-06 08:00")
    task: list[dict] = []
    taskpred: list[dict] = []
    seq = {"task": 2000, "pred": 6000}

    def add_task(prefix: str, code: str, name: str, hrs: float, float_h: float):
        seq["task"] += 1
        tid = seq["task"]
        end = start + pd.Timedelta(hours=hrs)
        task.append({
            "task_id": tid, "proj_id": 1, "wbs_id": wbs_id[prefix], "clndr_id": 1,
            "task_code": code, "task_name": name, "task_type": "TT_Task",
            "target_drtn_hr_cnt": float(hrs), "total_float_hr_cnt": float(float_h),
            "free_float_hr_cnt": float(min(float_h, 40.0)),
            "early_start_date": start, "early_end_date": end,
            "late_start_date": start, "late_end_date": end,
            "target_start_date": start, "target_end_date": end,
            "cstr_date": None, "cstr_type": "",
            "driving_path_flag": "Y" if float_h == 0.0 else "N",
        })
        return tid

    def link(pred_tid: int, succ_tid: int, ptype: str = "PR_FS", lag: float = 0.0):
        seq["pred"] += 1
        taskpred.append({
            "task_pred_id": seq["pred"], "task_id": succ_tid,
            "pred_task_id": pred_tid, "pred_type": ptype, "lag_hr_cnt": float(lag),
        })

    nodes: list[int] = []

    def spine(prefix, code, name, hrs):
        tid = add_task(prefix, code, name, hrs, 0.0)
        if nodes:
            link(nodes[-1], tid)
        nodes.append(tid)
        return tid

    # --- Controlling spine: the ten gates sit on it -------------------------
    g_stage = spine("10", "10.G.001", "Traffic switch stage 1", 240)
    g_earth = spine("20", "20.G.001", "Bulk earthworks main line", 1360)
    g_drain = spine("20", "20.G.002", "Trunk drainage installation", 720)
    g_vpile = spine("30", "30.G.001", "Viaduct piling", 880)
    g_vgird = spine("30", "30.G.002", "Viaduct girder erection", 640)
    g_bsub = spine("40", "40.G.001", "Bridge substructure", 720)
    g_bdeck = spine("40", "40.G.002", "Bridge deck pour", 480)
    g_abase = spine("50", "50.G.001", "Asphalt base course", 560)
    g_awear = spine("50", "50.G.002", "Final wearing course", 320)
    g_hand = spine("60", "60.G.001", "Line marking & handover", 240)

    # --- Floated detail, sized so each prefix carries exactly the activity
    #     count PREFIX_MAPPING declares (10:4, 20:7, 30:8, 40:7, 50:5, 60:3) ---
    for code, name, hrs, fl in [
        ("10.A.001", "Site compound establishment", 160, 200.0),
        ("10.A.002", "Temporary barrier installation", 200, 160.0),
        ("10.A.003", "Environmental controls", 120, 320.0),
    ]:
        t = add_task("10", code, name, hrs, fl)
        link(t, g_stage)

    for code, name, hrs, fl in [
        ("20.A.001", "Topsoil strip and stockpile", 240, 240.0),
        ("20.A.002", "Cut to fill haulage", 480, 160.0),
        ("20.A.003", "Subsoil drainage", 200, 280.0),
        ("20.A.004", "Culvert extensions", 320, 200.0),
        ("20.A.005", "Batter stabilisation", 240, 360.0),
    ]:
        t = add_task("20", code, name, hrs, fl)
        link(g_stage, t); link(t, g_drain)

    for code, name, hrs, fl in [
        ("30.A.001", "Viaduct pile caps", 320, 200.0),
        ("30.A.002", "Viaduct pier columns", 400, 160.0),
        ("30.A.003", "Viaduct headstocks", 280, 240.0),
        ("30.A.004", "Viaduct bearings", 160, 320.0),
        ("30.A.005", "Viaduct deck fit-out", 360, 200.0),
        ("30.A.006", "Viaduct parapets", 240, 280.0),
    ]:
        t = add_task("30", code, name, hrs, fl)
        link(g_vpile, t); link(t, g_vgird)

    for code, name, hrs, fl in [
        ("40.A.001", "Bridge abutment excavation", 240, 240.0),
        ("40.A.002", "Bridge piling", 320, 200.0),
        ("40.A.003", "Bridge girder delivery", 200, 320.0),
        ("40.A.004", "Bridge barrier installation", 240, 200.0),
        ("40.A.005", "Bridge expansion joints", 160, 280.0),
    ]:
        t = add_task("40", code, name, hrs, fl)
        link(g_bsub, t); link(t, g_bdeck)

    for code, name, hrs, fl in [
        ("50.A.001", "Subgrade preparation", 320, 200.0),
        ("50.A.002", "Granular pavement layers", 400, 160.0),
        ("50.A.003", "Kerb and channel", 240, 280.0),
    ]:
        t = add_task("50", code, name, hrs, fl)
        link(g_abase, t); link(t, g_awear)

    for code, name, hrs, fl in [
        ("60.A.001", "Signage and furniture", 160, 200.0),
        ("60.A.002", "Landscaping establishment", 240, 400.0),
    ]:
        t = add_task("60", code, name, hrs, fl)
        link(g_awear, t); link(t, g_hand)

    return {"CALENDAR": calendar, "PROJWBS": projwbs, "TASK": task,
            "TASKPRED": taskpred}


def build_schedule(path: Path) -> None:
    """Write road_schedule.xer."""
    from src.sra.cpm.xer_writer import write_xer

    tables = _build_schedule_tables()
    write_xer(tables, path)
    print(f"wrote {path} ({len(tables['TASK'])} activities, "
          f"{len(tables['TASKPRED'])} logic links)")


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    build_register(FIXTURE_DIR / "road_register.xlsx")
    build_schedule(FIXTURE_DIR / "road_schedule.xer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
