"""Generate the synthetic-wind showcase fixtures (Showcase-P2 WS2-C, grown by P3).

Produces four artefacts under ``tests/fixtures/synthetic_wind/`` that share
no identifiers with RefProject and exercise the project-agnostic engine
end-to-end (cost + Stage 2.5 + Stage 3) on a *full, publishable* wind-BOP
project — the substrate the P5/P6 marketing layer draws from:

- ``wind_register.xlsx`` — a V5-format register (``Risk Register`` +
  ``MC_Params``), ~35 risks ``WT-001``..``WT-035`` across the CG01-CG06
  wind cost groups, mixed distributions (PERT / Triangular / Lognormal),
  a recurrence-coded risk, a cost cascade group, and ~10 Time_Impact=Yes
  risks (a couple dual-coded across cost + schedule). The per-cost-group
  capex base values tie to an external **Wind Farm Beta** reference spec
  ($45M EPC + $5M grid connect = $50M capex; Showcase-P3 decision 5) and
  the same $50M is written to ``MC_Params`` as ``TIC`` so the QRA
  contingency sits on the capex the feasibility model used.
  Under REG-01 the register is CONSOLIDATED: the themed ``Risk Register``
  sheet also carries Mode + builder-computed EMV literal columns (the blog
  screenshot), a machine-facing ``Mapping`` sheet carries the CPM binding,
  and ``MC_Params`` absorbs the dissolved strawman's run-config (incl. the
  ONE home for the wind day rate). No separate ``wind_strawman.xlsx``.
- ``wind_schedule.xer`` — a believable ~170-activity WTG construction
  schedule (civil / foundations / turbine erection / electrical /
  grid+substation / commissioning) written by
  ``src/sra/cpm/xer_writer.write_xer``, with gating activities the Stage 3
  risk-driver auto-mapper binds the schedule risks onto.

Run:  ``python scripts/build_synthetic_wind_fixture.py``
Re-run to regenerate the committed fixtures after a contract change. The
showcase data is generated, auditable and regenerable — that is itself a
marketing beat.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import openpyxl  # noqa: E402
from openpyxl.styles import (  # noqa: E402
    Alignment, Border, Font, PatternFill, Side,
)
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from src.final.product import MAKER  # noqa: E402
from src.v5_register_reader import SEED_LABEL  # noqa: E402
from src.sra.cpm.xer_writer import write_xer  # noqa: E402

# REG05-A2: the "EMV & Mode Analysis" charts + their openpyxl chart-defect repair
# (``_finalize_chart``) moved to the shared scaffolder (tools/register_scaffold.py);
# this fixture now delegates via ``_build_emv_mode_analysis`` so template + fixture
# share one analysis structure and cannot drift.

# REG-02 house palette (read from the RefProject register's theme1.xml; theme indices are not
# portable to a fresh workbook, so the concrete accent RGBs are applied).
# accent1 header fill, accent2 register tab, accent3 analysis tab.
_HDR_FILL = "231EDC"      # the RefProject register's accent1 - bold header fill
_TAB_REGISTER = "0A7DFF"  # the RefProject register's accent2
_TAB_ANALYSIS = "5AE6FF"  # the RefProject register's accent3
_SECTION_TINT = {         # light band fills for the row-3 section labels
    "cost": "DCE9FF", "time": "E4F6FF", "derived": "EAF7EC",
}

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_wind"

# ---------------------------------------------------------------------------
# Wind Farm Beta capex basis (Showcase-P3 decision 5).
# A 40 MW wind farm: $45M EPC + $5M grid connect = $50M capex on a two-year
# build. The QRA contingency the wind register produces sits *on top of* this
# same capex — so the feasibility model, the contingency model and (in P4) the
# active-management layer share one numeric spine. Each CG cost group carries a
# notional base value; the risk three-point impacts below are sized as plausible
# fractions of the group they belong to, and the total is written to MC_Params
# as TIC so the deliverable expresses contingency as a % of the $50M base.
# ---------------------------------------------------------------------------
CAPEX_BASIS = {
    "CG01": ("Civil & Earthworks", 9_000_000),
    "CG02": ("Turbine Supply & Erection", 22_000_000),
    "CG03": ("Electrical Reticulation", 5_000_000),
    "CG04": ("Grid Connection", 5_000_000),
    "CG05": ("Balance of Plant / Substation", 6_000_000),
    "CG06": ("Commissioning & Controls", 3_000_000),
}
WIND_CAPEX_TOTAL = sum(v[1] for v in CAPEX_BASIS.values())  # $50,000,000

# CG correlation coefficients (the cost groups double as correlation groups).
WIND_CG_COEFFICIENTS = {
    "CG01": 0.6, "CG02": 0.5, "CG03": 0.5,
    "CG04": 0.4, "CG05": 0.5, "CG06": 0.4,
}

# QRAXL-01 GD-B: the Tier-1 METHODOLOGY surface, written to a grid-parseable
# "Methodology" sheet so the shared parser (resolve_methodology_from_grid) reads
# CG coefficients + mode multipliers FROM THE REGISTER, never a hardcoded
# cross-project constant. Values MIRROR build_test_methodology_defaults() (the
# dict the Tier-2 integrated cost arm actually uses); the GD-B methodology-parity
# test gates them equal, so any drift here fails loud. All 13 CG keys are written
# (not just the 6 wind CGs above) so the Tier-1 cg_coefficients dict stays
# bit-identical to Tier-2's and the wind Tier-1 numbers reproduce raw == (the
# Director's Decision-1 option a). These are a DIFFERENT surface from
# WIND_CG_COEFFICIENTS above (the MC_Params per-group correlation labels).
METHODOLOGY_CG_COEFFICIENTS = {
    "CG01": 0.6, "CG02": 0.5, "CG03": 0.5, "CG04": 0.4, "CG05": 0.5,
    "CG06": 0.5, "CG07": 0.4, "CG08": 0.4, "CG09": 0.4, "CG10": 0.4,
    "CG11": 0.5, "CG12": 0.5, "CG13": 0.5,
}
METHODOLOGY_MODE_MULTIPLIERS = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}

# ---------------------------------------------------------------------------
# Risk data — 35 synthetic wind-BOP risks.
# fields: id, status, desc, owner, rbs1, rbs2, dist, cg, recurrence,
#         prob_cost, opt$, ml$, pess$, time?, mode, prob_time, optD, mlD, pessD,
#         cascade_group, sched_prefix
# `sched_prefix` is the schedule WBS prefix the Stage 3 auto-mapper binds the
# risk onto (10 Civil / 20 Foundations / 30 Turbine Erection / 40 Electrical /
# 50 Grid+Substation / 60 Commissioning); blank for cost-only risks.
# Time=Yes set (10): WT-001/002/008/009/020/021/026/027/031/032
#   Modes — Series 4, Hybrid 4, Parallel 2 (a realistic schedule-arm mix).
#   Dual-coded headline risks (big cost AND schedule): WT-008, WT-021.
# ---------------------------------------------------------------------------
WIND_RISKS = [
    # ----- CG01 Civil & Earthworks (base $9.0M) -----
    ("WT-001", "Open", "Turbine foundation rework", "EPC Contractor", "Civil & Earthworks", "Foundations",
     "PERT", "CG01", "", 0.45, 100_000, 300_000, 700_000, "Yes", "Series", 0.45, 5, 12, 24, "", "20"),
    ("WT-002", "Open", "Access road wet-weather damage", "EPC Contractor", "Civil & Earthworks", "Roads",
     "Triangular", "CG01", "Single", 0.50, 60_000, 180_000, 500_000, "Yes", "Hybrid", 0.50, 3, 7, 16, "", "10"),
    ("WT-003", "Open", "Unforeseen ground conditions", "EPC Contractor", "Civil & Earthworks", "Earthworks",
     "Lognormal", "CG01", "", 0.35, 150_000, 400_000, 1_100_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-004", "Open", "Hardstand settlement", "EPC Contractor", "Civil & Earthworks", "Hardstands",
     "PERT", "CG01", "", 0.25, 40_000, 120_000, 350_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-005", "Open", "Bulk earthworks quantity overrun", "EPC Contractor", "Civil & Earthworks", "Earthworks",
     "Triangular", "CG01", "", 0.55, 80_000, 220_000, 480_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-006", "Open", "Drainage & culvert rework", "EPC Contractor", "Civil & Earthworks", "Drainage",
     "PERT", "CG01", "", 0.30, 50_000, 140_000, 300_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-007", "Open", "Erosion & sediment control overrun", "Shared", "Civil & Earthworks", "Environmental",
     "Triangular", "CG01", "", 0.40, 30_000, 90_000, 220_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG02 Turbine Supply & Erection (base $22.0M) -----
    ("WT-008", "Open", "WTG delivery delay (long-lead)", "Wind Farm Owner", "Turbine Supply & Erection", "Procurement",
     "PERT", "CG02", "", 0.40, 200_000, 600_000, 1_500_000, "Yes", "Series", 0.40, 8, 20, 45, "", "30"),
    ("WT-009", "Open", "Main crane mobilisation delay", "EPC Contractor", "Turbine Supply & Erection", "Heavy Lift",
     "Triangular", "CG02", "", 0.45, 150_000, 450_000, 1_200_000, "Yes", "Hybrid", 0.45, 4, 10, 24, "", "30"),
    ("WT-010", "Open", "Blade transport damage", "EPC Contractor", "Turbine Supply & Erection", "Logistics",
     "PERT", "CG02", "", 0.30, 120_000, 350_000, 900_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-011", "Open", "Tower section nonconformance", "Wind Farm Owner", "Turbine Supply & Erection", "Quality",
     "Lognormal", "CG02", "", 0.25, 200_000, 500_000, 1_400_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-012", "Open", "Erection weather standby", "EPC Contractor", "Turbine Supply & Erection", "Weather",
     "Triangular", "CG02", "", 0.60, 100_000, 300_000, 800_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-013", "Open", "Bolt tensioning / torque rework", "EPC Contractor", "Turbine Supply & Erection", "Mechanical",
     "PERT", "CG02", "", 0.35, 60_000, 180_000, 450_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-014", "Open", "Major component warranty defect", "Wind Farm Owner", "Turbine Supply & Erection", "Warranty",
     "PERT", "CG02", "", 0.20, 250_000, 700_000, 2_000_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-015", "Open", "Gearbox / main-bearing replacement", "Wind Farm Owner", "Turbine Supply & Erection", "Mechanical",
     "Lognormal", "CG02", "", 0.15, 300_000, 800_000, 2_400_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG03 Electrical Reticulation (base $5.0M) -----
    ("WT-016", "Open", "Array cable supply shortfall", "EPC Contractor", "Electrical Reticulation", "Procurement",
     "PERT", "CG03", "", 0.45, 90_000, 250_000, 600_000, "No", "", 0.0, 0, 0, 0, "WT-CAS", ""),
    ("WT-017", "Open", "Cable installation productivity", "EPC Contractor", "Electrical Reticulation", "Construction",
     "PERT", "CG03", "", 0.40, 70_000, 220_000, 520_000, "No", "", 0.0, 0, 0, 0, "WT-CAS", ""),
    ("WT-018", "Open", "Cable joint re-termination", "EPC Contractor", "Electrical Reticulation", "Electrical",
     "Triangular", "CG03", "", 0.30, 50_000, 150_000, 400_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-019", "Open", "Trenching clash with civil works", "Shared", "Electrical Reticulation", "Interface",
     "PERT", "CG03", "", 0.25, 40_000, 120_000, 300_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-020", "Open", "HV array cable test failures", "EPC Contractor", "Electrical Reticulation", "Testing",
     "Triangular", "CG03", "", 0.35, 60_000, 170_000, 420_000, "Yes", "Parallel", 0.35, 1, 4, 10, "", "40"),
    # ----- CG04 Grid Connection (base $5.0M) -----
    ("WT-021", "Open", "Grid connection redesign", "Wind Farm Owner", "Grid Connection", "Design",
     "Lognormal", "CG04", "", 0.30, 200_000, 500_000, 1_200_000, "Yes", "Series", 0.30, 6, 15, 35, "", "50"),
    ("WT-022", "Open", "Network operator approval delay", "Wind Farm Owner", "Grid Connection", "Approvals",
     "PERT", "CG04", "", 0.40, 100_000, 280_000, 700_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-023", "Open", "Protection settings rework", "Shared", "Grid Connection", "Electrical",
     "Triangular", "CG04", "", 0.30, 60_000, 160_000, 380_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-024", "Open", "Grid compliance test failure", "Wind Farm Owner", "Grid Connection", "Testing",
     "PERT", "CG04", "", 0.25, 120_000, 320_000, 800_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-025", "Open", "Connection-point scope change", "Wind Farm Owner", "Grid Connection", "Scope",
     "Triangular", "CG04", "", 0.20, 80_000, 200_000, 500_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG05 Balance of Plant / Substation (base $6.0M) -----
    ("WT-026", "Open", "Substation civils delay", "EPC Contractor", "Balance of Plant", "Civil",
     "PERT", "CG05", "", 0.35, 80_000, 220_000, 550_000, "Yes", "Hybrid", 0.35, 2, 6, 14, "", "50"),
    ("WT-027", "Open", "Substation E&I commissioning slip", "Shared", "Balance of Plant", "Commissioning",
     "Triangular", "CG05", "", 0.35, 60_000, 180_000, 450_000, "Yes", "Parallel", 0.35, 1, 4, 10, "", "50"),
    ("WT-028", "Open", "Power transformer delivery delay", "Wind Farm Owner", "Balance of Plant", "Procurement",
     "PERT", "CG05", "", 0.25, 150_000, 400_000, 1_000_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-029", "Open", "Control building fit-out overrun", "EPC Contractor", "Balance of Plant", "Building",
     "Triangular", "CG05", "", 0.30, 50_000, 140_000, 320_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-030", "Open", "Earthing & lightning protection rework", "EPC Contractor", "Balance of Plant", "Electrical",
     "PERT", "CG05", "", 0.25, 40_000, 110_000, 280_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG06 Commissioning & Controls (base $3.0M) -----
    ("WT-031", "Open", "SCADA integration defects", "Shared", "Commissioning & Controls", "Controls",
     "PERT", "CG06", "", 0.50, 110_000, 300_000, 700_000, "Yes", "Series", 0.50, 4, 9, 19, "", "60"),
    ("WT-032", "Open", "Turbine commissioning faults", "EPC Contractor", "Commissioning & Controls", "Commissioning",
     "Triangular", "CG06", "", 0.45, 90_000, 250_000, 600_000, "Yes", "Hybrid", 0.45, 3, 7, 16, "", "60"),
    ("WT-033", "Open", "Power performance test shortfall", "Wind Farm Owner", "Commissioning & Controls", "Testing",
     "PERT", "CG06", "", 0.30, 60_000, 160_000, 400_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-034", "Open", "Grid code compliance retest", "Shared", "Commissioning & Controls", "Testing",
     "Triangular", "CG06", "", 0.25, 70_000, 180_000, 450_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-035", "Open", "Punchlist / defects liability", "EPC Contractor", "Commissioning & Controls", "Closeout",
     "PERT", "CG06", "", 0.40, 50_000, 140_000, 350_000, "No", "", 0.0, 0, 0, 0, "", ""),
]

# Schedule WBS groups: (prefix, wbs_id, name).
WIND_WBS = [
    ("10", 110, "Civil & Earthworks"),
    ("20", 120, "Foundations"),
    ("30", 130, "Turbine Erection"),
    ("40", 140, "Electrical Reticulation"),
    ("50", 150, "Grid & Substation"),
    ("60", 160, "Commissioning"),
]
N_TURBINES = 10  # 10 x 4 MW turbines = the 40 MW Wind Farm Beta

#: One *gating activity* per Time=Yes schedule risk → its unique task_code.
#: Each gate sits on the controlling spine (total_float 0) so the risk affects
#: project finish, and its code is unique so the Stage 3 auto-mapper binds the
#: risk to exactly ONE activity (additive PERT days applied once, not broadcast
#: across a whole WBS group — that over-binding is what inflates a CPM-replay).
#: The strawman points each risk's pattern prefix at its gate code.
GATING = {
    "WT-002": ("10.G.001", "Civil works weather-exposure gate"),
    "WT-001": ("20.G.001", "Foundations-complete gate"),
    "WT-008": ("30.G.001", "WTG delivery gate"),
    "WT-009": ("30.G.002", "Main crane availability gate"),
    "WT-020": ("40.G.001", "HV array cable test gate"),
    "WT-021": ("50.G.001", "Grid connection gate"),
    "WT-026": ("50.G.002", "Substation civils gate"),
    "WT-027": ("50.G.003", "Substation E&I commissioning gate"),
    "WT-031": ("60.G.001", "SCADA integration gate"),
    "WT-032": ("60.G.002", "Turbine commissioning gate"),
}

#: WIND-03 mapping (Director-approved, all ten rows). The strawman
#: ``Prefix_List`` is DECOUPLED from :data:`GATING` here: GATING still
#: defines the on-spine gate activities and thus the .xer topology
#: (UNCHANGED by this brief), while the auto-mapper binding target is this
#: per-risk prefix. Five risks are repointed from their 1:1 gate code onto a
#: work-group prefix so they bind the controlling activity plus the ten
#: per-turbine detail-branch activities (float <= 480h); the other five stay
#: 1:1 on their gate (serial-spine groups where broadening would compound
#: the same delay - the RefProject over-binding failure WIND-03 warns against).
#: ``(prefix, expected_bound_activity_count)``; the counts are asserted in
#: ``tests/test_synthetic_wind.py`` and total 58.
PREFIX_MAPPING = {
    "WT-001": ("20.A", 11),      # foundation: controlling + 10 excavation
    "WT-002": ("10.G.001", 1),   # keep 1:1 (group 10 serial spine)
    "WT-008": ("30.A", 11),      # WTG delivery: controlling + 10 tower-lower (CP competition)
    "WT-009": ("30.G.002", 1),   # keep 1:1 (discrete crane milestone)
    "WT-020": ("40.C", 10),      # HV test: 10 per-turbine array connections (finish-neutral)
    "WT-021": ("50.G.001", 1),   # keep 1:1 (group 50 serial spine)
    "WT-026": ("50.G.002", 1),   # keep 1:1
    "WT-027": ("50.G.003", 1),   # keep 1:1
    "WT-031": ("60.A", 11),      # SCADA: controlling + 10 pre-commissioning
    "WT-032": ("60.B", 10),      # commissioning: 10 per-turbine (finish-neutral)
}

#: Invented wind day rate ($/working day). Proportionate to a ~$50M, ~18-month
#: wind-BOP build (prelims spine far below RefProject's $100,000/wd). Schedule
#: contingency dollarises Time=Yes slip at this rate. REG-01: this is the ONE
#: home for the day rate - written to MC_Params only (the per-row strawman
#: Day_Rate is deleted with the strawman).
WIND_DAY_RATE = 35_000.0

# REG-01 §12.2 no-silent-zero: the Mode multiplier grid this builder WRITES into
# the register (METHODOLOGY_MODE_MULTIPLIERS above) is authoritative; an
# unrecognised/blank Mode on a Time=Yes risk FAILS the build (below), never
# silently multiplies schedule EMV by an implicit zero. RS-D-3: validated against
# the grid the register will carry, not against an engine constant.

#: Phi^{-1}(0.90); the lognormal cost sampler maps Opt->P10, Pess->P90 via
#: this z-score (mirrors src/distributions.lognormal_cost_from_uniform).
_Z90 = 1.2816


def _pert_mean(opt: float, ml: float, pess: float) -> float:
    """Analytic mean of the standard (lambda=4) PERT: (O + 4*ML + P)/6.

    Equals the rescaled-Beta mean the PERT sampler converges to, so a PERT
    risk's deterministic EMV reconciles to its MC mean.
    """
    return (opt + 4.0 * ml + pess) / 6.0


def _cost_distribution_mean(distribution: str, opt: float, ml: float,
                            pess: float) -> float:
    """Analytic mean of a risk's OWN cost distribution (REG-01 §12.5).

    Mirrors src/distributions.sample_cost's dispatch EXACTLY so EMV_cost's
    cross-check partner - the cost MC mean the engine actually draws - is the
    same target, not reporting.py's PERT-for-all bridge:
      PERT       -> (O + 4*ML + P)/6         (rescaled-Beta mean)
      Triangular -> (O + ML + P)/3
      Lognormal  -> ML * exp(sigma^2/2), sigma = (lnP - lnO)/(2*Phi^{-1}.90)
      Binary     -> ML
    """
    import math
    d = distribution.strip().lower()
    if d in ("pert", "binary/pert"):
        return _pert_mean(opt, ml, pess)
    if d == "binary":
        return ml
    if d == "lognormal":
        if ml <= 0:
            return 0.0
        if pess <= opt or pess <= 0 or opt <= 0:
            return abs(ml)
        sigma = max((math.log(abs(pess)) - math.log(abs(opt))) / (2 * _Z90), 0.01)
        return abs(ml) * math.exp(0.5 * sigma * sigma)
    # Default (Triangular).
    return (opt + ml + pess) / 3.0


def _assert_valid_mode(rid: str, mode: str) -> str:
    """REG-01 §12.2 builder assertion: a Time=Yes risk MUST carry a recognised
    Mode. Blank / unrecognised FAILS the build rather than emitting a silent
    zero-contribution schedule EMV."""
    m = (mode or "").strip()
    # Exact-case on purpose: the builder is stricter than the runtime resolver (which
    # folds case, as Excel MATCH does), so the committed fixture only ever carries the
    # canonical spellings. RS-D-3 review NOTE.
    if m not in METHODOLOGY_MODE_MULTIPLIERS:
        raise ValueError(
            f"REG-01 no-silent-zero: risk {rid} is Time_Impact=Yes but its "
            f"Mode is {mode!r}, not one of {sorted(METHODOLOGY_MODE_MULTIPLIERS)}. Fix the "
            "Mode before rebuilding - the build will not emit a silent zero."
        )
    return m


# ===========================================================================
# Register
# ===========================================================================

# ===========================================================================
# REG-02 / REG-03 - EMV/Mode analytics (presentation only; value-neutral).
# The Risk Register theming, dropdowns and named-range contract moved to the
# shared scaffolder (tools/register_scaffold.py) under REG03 S1 so the empty
# per-project template and this CI fixture emit ONE structure and cannot drift.
# ===========================================================================


def _build_emv_mode_analysis(wb, n_rows: int) -> None:
    """REG05-A2 §3.3: the generic "EMV & Mode Analysis" sheet, emitted by the
    SHARED scaffolder (``build_emv_mode_analysis``) so the empty template and this
    CI fixture emit ONE analysis structure and cannot drift. Formulas reference the
    register EMV/Mode columns over the ``n_rows`` data block, so the sheet recomputes
    from whatever the register carries - no wind literals baked in."""
    from tools.register_scaffold import DATA_START_ROW, build_emv_mode_analysis
    build_emv_mode_analysis(wb, DATA_START_ROW, DATA_START_ROW + n_rows - 1)


def _build_layer1_sheets(wb) -> None:
    """QRAXL-01 step 5 / REG05-A2 §3.1 - the wind Layer-1 FILL over the SHARED
    empty builder (``tools.register_scaffold.build_layer1_sheets``), so the fixture
    and the empty per-project template emit ONE Layer-1 structure and cannot drift
    (design brief §5 no-drift rule). Wind column/row labels + values are the fill
    (project data); the structure is shared. Sourced from ``layer1_showcase`` so the
    encoding is the exact dataset ``build_showcase_layer1()`` produces (base written
    in $M from the raw literals, so read x 1e6 == build's base); byte-identical to
    the pre-A2 output (the fixture byte-identity gate).
    """
    from src.layer1_showcase import _BASE_M, _CORR_LOWER, build_showcase_layer1
    from tools.register_scaffold import build_layer1_sheets

    cfg = build_showcase_layer1("elicited")
    factors = [
        (f.name, f.driver, f.opt, f.ml, f.p90,
         "ALL" if "ALL" in f.col_scope else ",".join(f.col_scope))
        for f in cfg.factors
    ]
    alloc = {f.name: ("ALL" if "ALL" in f.rows else list(f.rows)) for f in cfg.factors}
    build_layer1_sheets(
        wb,
        col_labels=cfg.col_labels,
        row_labels=cfg.row_labels,
        base_m=[[float(x) for x in _BASE_M[i]] for i in range(len(cfg.row_labels))],
        factors=factors,
        alloc=alloc,
        corr_names=cfg.corr_names,
        corr_lower=_CORR_LOWER,
        corr_mode=cfg.corr_mode,
        declared_total_m=float(cfg.declared_total) / 1_000_000.0,
    )


# QRAXL-01 GD-B methodology grid, step-6b Settings/Simulation sheets and the
# Grid_*/Set_*/Out_* named-range emission moved to tools/register_scaffold.py
# (build_methodology_sheet, build_settings_and_simulation, finalize_named_ranges)
# under REG03 S1 - the single shared structure source for template + fixture.


def build_register(path: Path) -> None:
    """Write the REG-01 consolidated showcase register (ONE workbook, three
    sheets): themed "Risk Register" (analyst-facing, the blog screenshot;
    originated inputs + builder-computed EMV literals) + "Mapping" (machine,
    CPM binding) + "MC_Params" (config, with the dissolved strawman's
    Run_Config_Preview folded in).

    Bit-identity contract: the id columns (1-13), the cost section (14-19) and
    the time section (20-25) keep the exact VALUES the pre-REG-01 split
    register carried. The time-section day headers are renamed to "(days)" /
    "Probability (Time)" - still prefix-matched by v5_register_reader Pass-3,
    so the cost arm reads byte-identically, while read_risk_scope can match
    them unambiguously. Mode + Impact_Basis + EMV literals live in a new
    "Analyst / Derived" section at col 26, so the cost/time bands are
    untouched.
    """
    # REG03 S1: the register STRUCTURE (row-3 section labels, row-4 headers incl.
    # the P6-ready activity-binding column, theming, dropdowns, methodology grid,
    # Set_*/Out_* + Grid_* names, TOC + Reference) is emitted by the shared
    # scaffolder, so this CI fixture is provably "scaffold structure + synthetic
    # fill" and cannot drift from the empty per-project template.
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

    # Row 3 = section labels; row 4 = column headers; row 5+ = data.
    write_risk_header_rows(ws)

    for i, r in enumerate(WIND_RISKS):
        (rid, status, desc, owner, rbs1, rbs2, dist, cg, recur,
         pc, oc, mc, pcst, timp, mode, ptime, od, md, pd, casc, prefix) = r
        row = 5 + i

        # §12.2: a Time=Yes risk MUST carry a recognised Mode - FAILS the build
        # (fail-fast, before any file is written) on a blank/unrecognised Mode.
        mode_cell = _assert_valid_mode(rid, mode) if timp == "Yes" else ""
        impact_basis = "per_occurrence"  # COST-01 elicitation flag (wind: all per-occurrence)

        # Cols 1-27; EMV cols 28-30 are written as live Excel formulas below (S2).
        vals = [
            rid, status, desc, owner, rbs1, rbs2, "Yes", dist, cg, recur,
            "synthetic cause", "synthetic consequence", "synthetic controls",
            "Yes", pc, oc, mc, pcst, "Wind Farm Beta capex basis",
            timp, ptime, od, md, pd, "Synthetic",
            mode_cell, impact_basis,
        ]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=row, column=c, value=v)

    # --- REG03 S2: EMV cols 28-30 as live Excel formulas (retire the Python
    # literals; the deterministic cross-check is now transparent + auditable). ---
    n_risks = len(WIND_RISKS)
    _last_data = DATA_START_ROW + n_risks - 1
    write_emv_formulas(ws, DATA_START_ROW, _last_data)

    # --- REG-02 theming + REG03 S3a cascade Lists + list-sourced dropdowns
    # (styles + input constraints only, value-neutral) ---
    theme_risk_register(ws, n_risks)
    # REG04 Scope B: seed List_Factor with the fixture's own Layer-1 factor names so
    # the factor dropdown on the Layer-1 sheets is consistent.
    from src.layer1_showcase import build_showcase_layer1 as _bsl  # noqa: E402
    build_lists_sheet(wb, factor_seed=[f.name for f in _bsl().factors])
    add_dropdowns(ws, DATA_START_ROW, _last_data)
    style_register_input_cells(ws, DATA_START_ROW, _last_data)

    # --- Mapping sheet (machine, CPM binding; REG-01 §3). Time=Yes only. ---
    mapping = wb.create_sheet("Mapping")
    map_headers = ["Risk ID", "Pattern_ID", "Prefix_List", "Activity_Count",
                   "Gating_Activity_ID", "Injection_Method"]  # RS-D-6: blank = register default
    for c, h in enumerate(map_headers, start=1):
        mapping.cell(row=1, column=c, value=h)
    mrow = 2
    for r in WIND_RISKS:
        rid, timp = r[0], r[13]
        if timp != "Yes":
            continue
        pfx, acount = PREFIX_MAPPING.get(rid, ("", 1))
        gate = GATING.get(rid, ("", ""))[0]
        for c, v in enumerate(
            [rid, f"P-{rid}", pfx, acount, gate, ""], start=1,
        ):
            mapping.cell(row=mrow, column=c, value=v)
        mrow += 1

    # --- MC_Params (config; existing + folded Run_Config_Preview) ---
    n_time = sum(1 for r in WIND_RISKS if r[13] == "Yes")
    mp = wb.create_sheet("MC_Params")
    params = [
        ("Iterations (n)", 50000),
        (SEED_LABEL, 42),
        ("Stakeholder view", "All"),
        ("Reporting P-Level (pct)", 80),
        # Decision 5: TIC = the Wind Farm Beta capex the contingency sits on.
        ("TIC - Total Installed Cost ($)", WIND_CAPEX_TOTAL),
        ("Cascade enabled", 1),
        ("Cascade slip rate", 1.5),
        ("Cascade slip cap", 3.0),
        ("Cascade cost scale", 0.5),
        ("Chain 1 trigger - planning delay (months)", 3.0),
        ("Chain 1 - weather amplification factor", 2.5),
        ("Chain 2 trigger - site estab delay (weeks)", 2.0),
        ("Chain 2 - cascade factor", 1.5),
        # REG-01 §12.4: dissolved strawman's Run_Config_Preview folds here.
        # The ONE home for the day rate (per-row Risk_Scope.Day_Rate deleted).
        ("day_rate ($/wd)", WIND_DAY_RATE),
        ("programme_seasons", 1),
        ("cp_hybrid_float_threshold_days", 20),
        ("schedule duration (weeks)", 90),
        ("expected_time_yes_count", n_time),
    ]
    # CG correlation coefficients + a documented capex base value per group.
    for cg, (label, base) in CAPEX_BASIS.items():
        params.append((f"{cg} - {label}", WIND_CG_COEFFICIENTS[cg]))
        params.append((f"{cg} capex base ($)", base))
    for i, (label, value) in enumerate(params, start=2):
        mp.cell(row=i, column=2, value=label)
        mp.cell(row=i, column=3, value=value)
    # S2: name the day_rate cell so EMV_sched_dollars references it robustly.
    name_day_rate(wb, mp)

    # --- REG-02: EMV & Mode Analysis sheet (native charts; §3.2) ---
    _build_emv_mode_analysis(wb, len(WIND_RISKS))

    # --- QRAXL-01 step 5 (contract v2, scope C): register-driven Layer 1 ---
    _build_layer1_sheets(wb)

    # --- QRAXL-01 GD-B: the register's own methodology grid (CG + mode mults).
    # REG03: emitted by the shared scaffolder; the fixture supplies the wind CG
    # coefficients (the empty template ships the neutral 0.5 default). REG03 S2b:
    # also the 3rd (description) column - wind CG group names for CG01-06, blank
    # for CG07-13. resolve_methodology_from_grid ignores col C, so cost stays
    # bit-identical. ---
    build_methodology_sheet(
        wb, cg_values=METHODOLOGY_CG_COEFFICIENTS,
        cg_descriptions={cg: label for cg, (label, _base) in CAPEX_BASIS.items()},
    )

    # --- REG03: TOC + Reference tabs (shared scaffold; non-read, value-neutral) ---
    build_toc(wb)
    build_reference(wb)

    # --- QRAXL-01 step 6b: Settings + Simulation output sheets + Grid_*/Set_*/Out_*
    # named ranges (shared scaffolder; grids sized AFTER fill). ---
    build_settings_and_simulation(wb)
    # REG05-A2 §3.2: the wind fixture ships Layer-1 ON (Set_Layer1_Enabled=TRUE) so
    # its filled Layer-1 reads stay byte-identical; the empty template ships FALSE.
    wb["Settings"]["B8"] = True
    finalize_named_ranges(wb)
    apply_finish(wb, project={  # REG05-A1: value-neutral finish; wind project identity
        "Set_ProjectName": "Tropic Ridge Wind Farm",
        "Set_ProjectNumber": "TR-BOP-001", "Set_Client": "Wind Farm Owner",
        "Set_PreparedBy": MAKER, "Set_Revision": "A",
    })
    apply_protection(wb)   # REG04: harden last (after all cells/names/Layer1 exist)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    print(f"wrote {path} (consolidated: themed Risk Register + Mapping + "
          f"MC_Params + EMV & Mode Analysis; {len(WIND_RISKS)} risks, "
          f"{n_time} Time=Yes, TIC=${WIND_CAPEX_TOTAL:,})")


# ===========================================================================
# Strawman
# ===========================================================================

# ===========================================================================
# Schedule (XER)
# ===========================================================================

def _build_schedule_tables() -> dict:
    """Build a believable ~170-activity WTG construction schedule.

    Topology: a single **controlling spine** (site → foundations → erection →
    array cabling → substation/grid → energisation → commissioning → handover)
    whose activities all carry ``total_float = 0`` and form the genuine
    critical path (~90 working weeks, matching the strawman). The ten gating
    activities (one per Time=Yes risk, :data:`GATING`) sit *on* this spine, so
    each schedule risk perturbs project finish, and each gate's code is unique
    so the Stage 3 auto-mapper binds the risk to exactly one activity.

    Hanging off the spine are the per-turbine **detail branches** (foundation
    and erection mini-chains, access spurs, array drops, commissioning pairs)
    that carry positive float — they supply the realistic ~160-activity body
    and a non-degenerate criticality spread without competing with the spine
    for the critical path (each branch is shorter than the controlling
    activity it parallels). Float values are authored, not CPM-derived; they
    are the deterministic-baseline floats the auto-mapper reads.
    """
    import pandas as pd

    calendar = [{
        "clndr_id": 1, "clndr_name": "Standard 5-day", "default_flag": "Y",
        "clndr_data": "(0||CalendarData())", "day_hr_cnt": 8.0,
        "week_hr_cnt": 40.0, "month_hr_cnt": 172.0, "year_hr_cnt": 2000.0,
    }]
    projwbs = [{"wbs_id": 100, "proj_id": 1, "parent_wbs_id": None,
                "wbs_short_name": "WF", "wbs_name": "Wind Farm", "seq_num": 1}]
    for k, (prefix, wid, name) in enumerate(WIND_WBS, start=2):
        projwbs.append({"wbs_id": wid, "proj_id": 1, "parent_wbs_id": 100,
                        "wbs_short_name": prefix, "wbs_name": name, "seq_num": k})

    wbs_id = {prefix: wid for (prefix, wid, _name) in WIND_WBS}
    start = pd.Timestamp("2026-03-02 08:00")
    task: list[dict] = []
    taskpred: list[dict] = []
    seq = {"task": 1000, "pred": 5000}

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

    # --- Controlling spine (float 0 throughout = the critical path) ----------
    nodes: list[int] = []

    def spine(prefix, code, name, hrs):
        tid = add_task(prefix, code, name, hrs, 0.0)
        if nodes:
            link(nodes[-1], tid)
        nodes.append(tid)
        return tid

    def spine_gate(rid, prefix, hrs=40.0):
        code, name = GATING[rid]
        return spine(prefix, code, name, hrs)

    spine("10", "10.A.001", "Site establishment", 80)
    s_road = spine("10", "10.A.002", "Main site access road", 120)
    g_civil = spine_gate("WT-002", "10")
    spine("20", "20.A.900", "Foundation works (controlling)", 700)
    g_found = spine_gate("WT-001", "20")
    spine_gate("WT-008", "30")          # WTG delivery gate
    g_crane = spine_gate("WT-009", "30")  # main crane availability gate
    spine("30", "30.A.900", "Turbine erection (controlling)", 1100)
    s_trench = spine("40", "40.A.001", "Array cable trenching", 200)
    spine("40", "40.A.002", "Array cable pull-in", 160)
    spine("40", "40.A.003", "Array cable terminations", 120)
    s_hvtest = spine("40", "40.A.004", "HV array cable testing", 80)
    spine_gate("WT-020", "40")          # HV array cable test gate
    s_subciv = spine("50", "50.A.001", "Substation civils", 200)
    spine_gate("WT-026", "50")          # substation civils gate
    spine("50", "50.A.002", "Power transformer installation", 120)
    spine("50", "50.A.003", "Switchgear & E&I installation", 160)
    spine_gate("WT-027", "50")          # substation E&I gate
    spine("50", "50.A.004", "Protection & control commissioning", 120)
    s_grid = spine("50", "50.A.005", "Grid connection works", 160)
    spine_gate("WT-021", "50")          # grid connection gate
    s_energise = spine("50", "50.A.006", "Substation energisation", 80)
    spine("60", "60.C.001", "SCADA integration & site controls", 120)
    spine_gate("WT-031", "60")          # SCADA integration gate
    spine("60", "60.A.900", "Turbine commissioning (controlling)", 480)
    g_comm = spine_gate("WT-032", "60")  # turbine commissioning gate
    spine("60", "60.C.002", "Grid code compliance testing", 80)
    spine("60", "60.C.003", "Power performance testing", 120)
    spine("60", "60.C.004", "Punchlist & handover", 80)

    # --- Per-turbine detail branches (positive float, parallel to spine) -----
    for i in range(1, N_TURBINES + 1):
        # Access spur off the main road -> civil gate.
        spur = add_task("10", f"10.C.{i:03d}", f"Turbine {i} access spur & pad", 40, 200.0)
        link(s_road, spur)
        link(spur, g_civil)
        # Foundation mini-chain (civil gate -> foundations gate), parallel to
        # the 700h controlling activity.
        exc = add_task("20", f"20.A.{i:03d}", f"T{i} foundation excavation", 40, 240.0)
        blind = add_task("20", f"20.B.{i:03d}", f"T{i} blinding & rebar cage", 32, 240.0)
        pour = add_task("20", f"20.C.{i:03d}", f"T{i} concrete pour", 24, 240.0)
        cure = add_task("20", f"20.D.{i:03d}", f"T{i} foundation cure", 80, 240.0)
        back = add_task("20", f"20.E.{i:03d}", f"T{i} backfill & plinth", 32, 240.0)
        link(g_civil, exc); link(spur, exc)
        link(exc, blind); link(blind, pour); link(pour, cure); link(cure, back)
        link(back, g_found)
        # Erection mini-chain (crane gate -> trenching start), parallel to the
        # 1100h controlling activity.
        tow1 = add_task("30", f"30.A.{i:03d}", f"T{i} tower lower sections", 32, 320.0)
        tow2 = add_task("30", f"30.B.{i:03d}", f"T{i} tower upper sections", 32, 320.0)
        nac = add_task("30", f"30.C.{i:03d}", f"T{i} nacelle installation", 40, 320.0)
        hub = add_task("30", f"30.D.{i:03d}", f"T{i} hub & blade installation", 48, 320.0)
        mech = add_task("30", f"30.E.{i:03d}", f"T{i} mechanical completion", 32, 320.0)
        link(g_crane, tow1); link(back, tow1)
        link(tow1, tow2); link(tow2, nac); link(nac, hub); link(hub, mech)
        link(mech, s_trench)
        # Array cable drop -> HV testing.
        drop = add_task("40", f"40.C.{i:03d}", f"T{i} array cable connection", 32, 200.0)
        link(hub, drop); link(mech, drop); link(drop, s_hvtest)
        # Commissioning pair (SCADA -> commissioning gate), parallel to the
        # 480h controlling activity.
        pre = add_task("60", f"60.A.{i:03d}", f"T{i} pre-commissioning checks", 24, 240.0)
        comm = add_task("60", f"60.B.{i:03d}", f"T{i} turbine commissioning", 48, 240.0)
        link(s_energise, pre); link(pre, comm); link(comm, g_comm)

    # --- A couple of floated substation items (parallel detail) --------------
    for j in range(1, 3):
        bld = add_task("50", f"50.B.{j:03d}", f"Control building fit-out {j}", 80, 200.0)
        link(s_subciv, bld); link(bld, s_grid)

    return {"CALENDAR": calendar, "PROJWBS": projwbs, "TASK": task, "TASKPRED": taskpred}


def build_schedule(path: Path) -> None:
    """Write wind_schedule.xer (full WTG construction schedule)."""
    tables = _build_schedule_tables()
    write_xer(tables, path)
    print(f"wrote {path} ({len(tables['TASK'])} activities, "
          f"{len(tables['TASKPRED'])} logic links)")


def main() -> int:
    build_register(FIXTURE_DIR / "wind_register.xlsx")
    build_schedule(FIXTURE_DIR / "wind_schedule.xer")
    # REG-01: the strawman is dissolved into the consolidated register. Remove
    # any stale wind_strawman.xlsx so a regenerated tree carries no orphan.
    stale = FIXTURE_DIR / "wind_strawman.xlsx"
    if stale.exists():
        stale.unlink()
        print(f"removed dissolved strawman {stale}")
    print("synthetic-wind fixtures generated (consolidated register).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
