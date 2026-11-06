"""Generate the synthetic-wind showcase fixtures (Showcase-P2 WS2-C, grown by P3).

Produces four artefacts under ``tests/fixtures/synthetic_wind/`` that share
no identifiers with RefProject and exercise the project-agnostic engine
end-to-end (cost + Stage 2.5 + Stage 3) on a *full, publishable* wind-BOP
project — the substrate the P5/P6 marketing layer draws from:

- ``wind_register.xlsx`` — a V5-format register (``Risk Register`` +
  ``MC_Params``), 30 risks in ``WT-001``..``WT-032`` across the CG01-CG06
  wind cost groups, mixed distributions (PERT / Triangular / Lognormal),
  a recurrence-coded risk, a cost cascade group, and ~10 Time_Impact=Yes
  risks (WINDREAL-01: 30 risks, 15 dual-coded). The per-cost-group
  capex base values are derived from the Layer 1 base matrix
  ($120M for 40 MW; WINDREAL-01, was the $50M Showcase-P3 decision 5) and
  the same total is written to ``MC_Params`` as ``TIC`` so the QRA
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
# Tropic Ridge capex basis (WINDREAL-01, Director-approved 01/11/2026).
# A 40 MW wind farm at about A$3.0M/MW: $120M capex on an ~18-month build (it was
# $50M, about 40% of what a real 40 MW farm costs). The QRA contingency sits on
# top of this capex. The CG cost-group bases are DERIVED from the Layer 1 base
# matrix (src/layer1_showcase.py), so the register carries one breakdown, not two
# that disagree (the old CAPEX_BASIS put turbines at $22M while Layer 1 said $31M).
# Each Layer 1 row maps wholly to one CG, except "Substation & grid connection",
# which splits 5/12 grid connection (CG04) and 7/12 substation (CG05).
# Development & approvals sits with grid connection (connection approvals are the
# long pole of development); owner's costs & PM sit with commissioning & controls.
# ---------------------------------------------------------------------------
_CG_LABELS = {
    "CG01": "Civil & Earthworks",
    "CG02": "Turbine Supply & Erection",
    "CG03": "Electrical Reticulation",
    "CG04": "Grid Connection",
    "CG05": "Balance of Plant / Substation",
    "CG06": "Commissioning & Controls",
}
#: Layer 1 row -> {CG: share}. Shares per row sum to 1.
_L1_ROW_TO_CG = {
    "Development & approvals": {"CG04": 1.0},
    "Turbine supply": {"CG02": 1.0},
    "Turbine transport & erection": {"CG02": 1.0},
    "BOP civils": {"CG01": 1.0},
    "Electrical BOP": {"CG03": 1.0},
    "Substation & grid connection": {"CG04": 5.0 / 12.0, "CG05": 7.0 / 12.0},
    "Commissioning": {"CG06": 1.0},
    "Owners costs & PM": {"CG06": 1.0},
}


def _derive_capex_basis() -> dict:
    """CG -> (label, base $), summed from the Layer 1 rows; whole dollars."""
    from src.layer1_showcase import _BASE_M, DECLARED_TOTAL, ROWS
    acc = {cg: 0.0 for cg in _CG_LABELS}
    for row_label, row in zip(ROWS, _BASE_M):
        for cg, share in _L1_ROW_TO_CG[row_label].items():
            acc[cg] += float(row.sum()) * share * 1_000_000.0
    basis = {cg: (_CG_LABELS[cg], int(round(v))) for cg, v in acc.items()}
    total = sum(v for _l, v in basis.values())
    if total != int(DECLARED_TOTAL):
        raise ValueError(f"CG capex basis {total} != Layer 1 declared total {DECLARED_TOTAL}")
    return basis


CAPEX_BASIS = _derive_capex_basis()
WIND_CAPEX_TOTAL = sum(v[1] for v in CAPEX_BASIS.values())  # $120,000,000

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
# Risk data — 30 synthetic wind risks (WINDREAL-01, 01/11/2026).
# fields: id, status, desc, owner, rbs1, rbs2, dist, cg, recurrence,
#         prob_cost, opt$, ml$, pess$, time?, mode, prob_time, optD, mlD, pessD,
#         cascade_group, sched_prefix
# `sched_prefix` is the schedule WBS prefix the Stage 3 auto-mapper binds the
# risk onto (10 Civil / 20 Foundations / 30 Turbine Erection / 40 Electrical /
# 50 Grid+Substation / 60 Commissioning); blank for cost-only risks.
# WINDREAL-01 re-scale, Director-approved 01/11/2026:
#   - cost three-points x2.4 (the $50M -> $120M base), rounded to $10k;
#     probabilities unchanged. Cost impacts stay direct-only (no prelims).
#   - RISKDRV-01 (Director 02/11/2026, plan R3): WT-017 cable installation productivity is
#     folded into shared driver D3 (electrical productivity), which prices the same uncertainty
#     on every electrical activity at once. 30 risks become 29.
#   - removed as operating-phase, not construction: WT-014 warranty defect,
#     WT-015 gearbox / main bearing, WT-033 power performance test, WT-035
#     defects liability; WT-034 grid-code retest folded into WT-024. IDs are
#     not renumbered, so a reader can trace each risk to its prior version.
#   - newly Time=Yes (a wind practitioner expects each to move finish):
#     WT-003 ground, WT-012 erection weather, WT-022 network approval,
#     WT-028 transformer delivery, WT-024 grid-compliance hold points.
#   - schedule days recalibrated for NEM conditions: WT-021 grid connection
#     20/50/130 (was 6/15/35), WT-008 WTG delivery 10/30/80 (was 8/20/45).
#     First-cut practitioner judgment, not a dataset (findings note
#     WINDREAL_input_realism_20261101).
# Time=Yes set (15): WT-001/002/003/008/009/012/020/021/022/024/026/027/028/031/032
#   Modes — Series 7, Hybrid 6, Parallel 2.
# ---------------------------------------------------------------------------
WIND_RISKS = [
    # ----- CG01 Civil & Earthworks -----
    ("WT-001", "Open", "Turbine foundation rework", "EPC Contractor", "Civil & Earthworks", "Foundations",
     "PERT", "CG01", "", 0.45, 240_000, 720_000, 1_680_000, "Yes", "Series", 0.45, 5, 12, 24, "", "20"),
    ("WT-002", "Open", "Access road wet-weather damage", "EPC Contractor", "Civil & Earthworks", "Roads",
     "Triangular", "CG01", "Single", 0.5, 140_000, 430_000, 1_200_000, "Yes", "Hybrid", 0.5, 3, 7, 16, "", "10"),
    ("WT-003", "Open", "Unforeseen ground conditions", "EPC Contractor", "Civil & Earthworks", "Earthworks",
     "Lognormal", "CG01", "", 0.35, 360_000, 960_000, 2_640_000, "Yes", "Hybrid", 0.35, 3, 8, 20, "", "20"),
    ("WT-004", "Open", "Hardstand settlement", "EPC Contractor", "Civil & Earthworks", "Hardstands",
     "PERT", "CG01", "", 0.25, 100_000, 290_000, 840_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-005", "Open", "Bulk earthworks quantity overrun", "EPC Contractor", "Civil & Earthworks", "Earthworks",
     "Triangular", "CG01", "", 0.55, 190_000, 530_000, 1_150_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-006", "Open", "Drainage & culvert rework", "EPC Contractor", "Civil & Earthworks", "Drainage",
     "PERT", "CG01", "", 0.3, 120_000, 340_000, 720_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-007", "Open", "Erosion & sediment control overrun", "Shared", "Civil & Earthworks", "Environmental",
     "Triangular", "CG01", "", 0.4, 70_000, 220_000, 530_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG02 Turbine Supply & Erection -----
    ("WT-008", "Open", "WTG delivery delay (long-lead)", "Wind Farm Owner", "Turbine Supply & Erection", "Procurement",
     "PERT", "CG02", "", 0.4, 480_000, 1_440_000, 3_600_000, "Yes", "Series", 0.4, 10, 30, 80, "", "30"),
    ("WT-009", "Open", "Main crane mobilisation delay", "EPC Contractor", "Turbine Supply & Erection", "Heavy Lift",
     "Triangular", "CG02", "", 0.45, 360_000, 1_080_000, 2_880_000, "Yes", "Hybrid", 0.45, 4, 10, 24, "", "30"),
    ("WT-010", "Open", "Blade transport damage", "EPC Contractor", "Turbine Supply & Erection", "Logistics",
     "PERT", "CG02", "", 0.3, 290_000, 840_000, 2_160_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-011", "Open", "Tower section nonconformance", "Wind Farm Owner", "Turbine Supply & Erection", "Quality",
     "Lognormal", "CG02", "", 0.25, 480_000, 1_200_000, 3_360_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-012", "Open", "Erection weather standby", "EPC Contractor", "Turbine Supply & Erection", "Weather",
     "Triangular", "CG02", "", 0.6, 240_000, 720_000, 1_920_000, "Yes", "Hybrid", 0.6, 5, 12, 25, "", "30"),
    ("WT-013", "Open", "Bolt tensioning / torque rework", "EPC Contractor", "Turbine Supply & Erection", "Mechanical",
     "PERT", "CG02", "", 0.35, 140_000, 430_000, 1_080_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG03 Electrical Reticulation -----
    ("WT-016", "Open", "Array cable supply shortfall", "EPC Contractor", "Electrical Reticulation", "Procurement",
     "PERT", "CG03", "", 0.45, 220_000, 600_000, 1_440_000, "No", "", 0.0, 0, 0, 0, "WT-CAS", ""),
    # RISKDRV-01 stage 2: WT-018 joins WT-CAS in place of the folded WT-017, so the showcase
    # keeps a two-member cascade group (cascade is off by default, so no number moves).
    ("WT-018", "Open", "Cable joint re-termination", "EPC Contractor", "Electrical Reticulation", "Electrical",
     "Triangular", "CG03", "", 0.3, 120_000, 360_000, 960_000, "No", "", 0.0, 0, 0, 0, "WT-CAS", ""),
    ("WT-019", "Open", "Trenching clash with civil works", "Shared", "Electrical Reticulation", "Interface",
     "PERT", "CG03", "", 0.25, 100_000, 290_000, 720_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-020", "Open", "HV array cable test failures", "EPC Contractor", "Electrical Reticulation", "Testing",
     "Triangular", "CG03", "", 0.35, 140_000, 410_000, 1_010_000, "Yes", "Parallel", 0.35, 1, 4, 10, "", "40"),
    # ----- CG04 Grid Connection -----
    ("WT-021", "Open", "Grid connection redesign", "Wind Farm Owner", "Grid Connection", "Design",
     "Lognormal", "CG04", "", 0.3, 480_000, 1_200_000, 2_880_000, "Yes", "Series", 0.3, 20, 50, 130, "", "50"),
    ("WT-022", "Open", "Network operator approval delay", "Wind Farm Owner", "Grid Connection", "Approvals",
     "PERT", "CG04", "", 0.4, 240_000, 670_000, 1_680_000, "Yes", "Series", 0.4, 10, 25, 60, "", "50"),
    ("WT-023", "Open", "Protection settings rework", "Shared", "Grid Connection", "Electrical",
     "Triangular", "CG04", "", 0.3, 140_000, 380_000, 910_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-024", "Open", "Grid compliance test failure", "Wind Farm Owner", "Grid Connection", "Testing",
     "PERT", "CG04", "", 0.25, 290_000, 770_000, 1_920_000, "Yes", "Series", 0.25, 5, 15, 40, "", "60"),
    ("WT-025", "Open", "Connection-point scope change", "Wind Farm Owner", "Grid Connection", "Scope",
     "Triangular", "CG04", "", 0.2, 190_000, 480_000, 1_200_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG05 Balance of Plant / Substation -----
    ("WT-026", "Open", "Substation civils delay", "EPC Contractor", "Balance of Plant", "Civil",
     "PERT", "CG05", "", 0.35, 190_000, 530_000, 1_320_000, "Yes", "Hybrid", 0.35, 2, 6, 14, "", "50"),
    ("WT-027", "Open", "Substation E&I commissioning slip", "Shared", "Balance of Plant", "Commissioning",
     "Triangular", "CG05", "", 0.35, 140_000, 430_000, 1_080_000, "Yes", "Parallel", 0.35, 1, 4, 10, "", "50"),
    ("WT-028", "Open", "Power transformer delivery delay", "Wind Farm Owner", "Balance of Plant", "Procurement",
     "PERT", "CG05", "", 0.25, 360_000, 960_000, 2_400_000, "Yes", "Series", 0.25, 10, 30, 70, "", "50"),
    ("WT-029", "Open", "Control building fit-out overrun", "EPC Contractor", "Balance of Plant", "Building",
     "Triangular", "CG05", "", 0.3, 120_000, 340_000, 770_000, "No", "", 0.0, 0, 0, 0, "", ""),
    ("WT-030", "Open", "Earthing & lightning protection rework", "EPC Contractor", "Balance of Plant", "Electrical",
     "PERT", "CG05", "", 0.25, 100_000, 260_000, 670_000, "No", "", 0.0, 0, 0, 0, "", ""),
    # ----- CG06 Commissioning & Controls -----
    ("WT-031", "Open", "SCADA integration defects", "Shared", "Commissioning & Controls", "Controls",
     "PERT", "CG06", "", 0.5, 260_000, 720_000, 1_680_000, "Yes", "Series", 0.5, 4, 9, 19, "", "60"),
    ("WT-032", "Open", "Turbine commissioning faults", "EPC Contractor", "Commissioning & Controls", "Commissioning",
     "Triangular", "CG06", "", 0.45, 220_000, 600_000, 1_440_000, "Yes", "Hybrid", 0.45, 3, 7, 16, "", "60"),
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
    # WINDREAL-01: one gate each for the five risks newly coded Time=Yes.
    "WT-003": ("20.G.002", "Ground conditions gate"),
    "WT-012": ("30.G.003", "Erection weather window gate"),
    "WT-022": ("50.G.004", "Network operator approval gate"),
    "WT-028": ("50.G.005", "Power transformer delivery gate"),
    "WT-024": ("60.G.003", "Grid compliance hold-point gate"),
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
#: ``tests/test_synthetic_wind.py`` and total 63 (58 before WINDREAL-01).
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
    # WINDREAL-01: the five new Time=Yes risks stay 1:1 on their own spine gate
    # (each is a discrete hold on the path to energisation or handover). Total 63.
    "WT-003": ("20.G.002", 1),
    "WT-012": ("30.G.003", 1),
    "WT-022": ("50.G.004", 1),
    "WT-028": ("50.G.005", 1),
    "WT-024": ("60.G.003", 1),
}

#: WINDREAL-01: the controlling network. (prefix, code, name, hours, gate risk id,
#: path). A row with a risk id is that risk's GATING hold point (1 day). Rows run in
#: order within each path. "pre" runs to the foundations gate; there the job forks
#: into the "turbine" path (delivery, erection, array cabling) and the "substation"
#: path (substation, transformer, network approval, grid connection), which run in
#: parallel, as on a real job, and rejoin at energisation; "post" is commissioning
#: to handover. The Director approved the parallel path at Stage A review
#: (01/11/2026): the serial spine stacked every delay end to end (P80 slip 34%).
GATE_HRS = 8.0
SPINE = (
    ("10", "10.A.001", "Site establishment", 80, "", "pre"),
    ("10", "10.A.002", "Main site access road", 120, "", "pre"),
    ("10", "10.G.001", "", 0, "WT-002", "pre"),
    ("20", "20.G.002", "", 0, "WT-003", "pre"),
    ("20", "20.A.900", "Foundation works (controlling)", 480, "", "pre"),
    ("20", "20.G.001", "", 0, "WT-001", "pre"),
    ("30", "30.G.001", "", 0, "WT-008", "turbine"),
    ("30", "30.G.002", "", 0, "WT-009", "turbine"),
    ("30", "30.G.003", "", 0, "WT-012", "turbine"),
    ("30", "30.A.900", "Turbine erection (controlling)", 480, "", "turbine"),
    ("40", "40.A.001", "Array cable trenching", 160, "", "turbine"),
    ("40", "40.A.002", "Array cable pull-in", 120, "", "turbine"),
    ("40", "40.A.003", "Array cable terminations", 80, "", "turbine"),
    ("40", "40.A.004", "HV array cable testing", 80, "", "turbine"),
    ("40", "40.G.001", "", 0, "WT-020", "turbine"),
    ("50", "50.A.001", "Substation civils", 200, "", "substation"),
    ("50", "50.G.002", "", 0, "WT-026", "substation"),
    ("50", "50.G.005", "", 0, "WT-028", "substation"),
    ("50", "50.A.002", "Power transformer installation", 120, "", "substation"),
    ("50", "50.A.003", "Switchgear & E&I installation", 160, "", "substation"),
    ("50", "50.G.003", "", 0, "WT-027", "substation"),
    ("50", "50.A.004", "Protection & control commissioning", 120, "", "substation"),
    ("50", "50.G.004", "", 0, "WT-022", "substation"),
    ("50", "50.A.005", "Grid connection works", 160, "", "substation"),
    ("50", "50.G.001", "", 0, "WT-021", "substation"),
    ("50", "50.A.006", "Substation energisation", 80, "", "post"),
    ("60", "60.C.001", "SCADA integration & site controls", 120, "", "post"),
    ("60", "60.G.001", "", 0, "WT-031", "post"),
    ("60", "60.A.900", "Turbine commissioning (controlling)", 320, "", "post"),
    ("60", "60.G.002", "", 0, "WT-032", "post"),
    ("60", "60.C.002", "Grid code compliance testing", 80, "", "post"),
    ("60", "60.G.003", "", 0, "WT-024", "post"),
    ("60", "60.C.003", "Power performance testing", 80, "", "post"),
    ("60", "60.C.004", "Punchlist & handover", 80, "", "post"),
)


def _path_hours(path: str) -> float:
    return sum(GATE_HRS if rid else hrs for (_p, _c, _n, hrs, rid, pth) in SPINE if pth == path)


#: Deterministic hours on each parallel path, and the float the shorter one carries
#: (authored floats are the CPM floats here, so the auto-mapper reads true values).
TURBINE_PATH_HOURS = _path_hours("turbine")
SUBSTATION_PATH_HOURS = _path_hours("substation")
SUBSTATION_FLOAT_HOURS = max(TURBINE_PATH_HOURS - SUBSTATION_PATH_HOURS, 0.0)
TURBINE_FLOAT_HOURS = max(SUBSTATION_PATH_HOURS - TURBINE_PATH_HOURS, 0.0)
#: Planned duration on the 5-day, 8-hour calendar, written to MC_Params (it said
#: 90 weeks while the CPM ran ~118; now one number, computed from the network).
SCHEDULE_HOURS = (_path_hours("pre") + max(TURBINE_PATH_HOURS, SUBSTATION_PATH_HOURS)
                  + _path_hours("post"))
SCHEDULE_WEEKS = round(SCHEDULE_HOURS / 40.0)

#: Wind day rate ($/working day): preliminaries, site overheads and owner's
#: time-related costs only, per PLAYBOOK (no standby, no lost revenue). WINDREAL-01
#: check: about 12% of the $120M capex over the ~405 wd build is about $35-37k/wd,
#: so the value is unchanged from the $50M era but is now right for the reason the
#: playbook gives. Lost revenue (about $38k/wd at 40 MW, 35% capacity factor,
#: ~$80/MWh) is an owner exposure, deliberately NOT in this rate or in contingency.
#: Schedule contingency dollarises Time=Yes slip at this rate. REG-01: this is the ONE
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


# ---------------------------------------------------------------------------
# RISKDRV-01 shared drivers (Director 02/11/2026, plan R1/R3). First-cut practitioner
# judgment, not a dataset. P = productivity (own range on the duration delta, cost on the
# named grid cells); Q = quantity-linked (the named Layer 1 factor's draw, no added cost).
# Columns as src.shared_drivers.COLUMNS.
# ---------------------------------------------------------------------------
WIND_SHARED_DRIVERS = [
    {"Driver_ID": "D1", "Name": "Civil productivity and ground", "Kind": "P",
     "Tag": "civil_productivity", "P10": -0.05, "Mode": 0.0, "P90": 0.20,
     "WBS_Codes": "10, 20", "Grid_Rows": "BOP civils", "Grid_Columns": "Labour, Plant",
     "Ruled_Risks": "WT-003, WT-005",
     "Basis": "Earthworks and foundation crews' output across the site: ground that digs harder "
              "than the geotech, wet days that are not stoppages. WT-003 (a discrete ground "
              "event) and WT-005 (quantity, beside Q_Civils) stay as they are."},
    {"Driver_ID": "D2", "Name": "Erection productivity", "Kind": "P",
     "Tag": "erection_productivity", "P10": -0.05, "Mode": 0.0, "P90": 0.15,
     "WBS_Codes": "30", "Grid_Rows": "Turbine transport & erection",
     "Grid_Columns": "Labour, Plant",
     "Ruled_Risks": "WT-009, WT-012",
     "Basis": "Lift rate in workable weather: crane crew learning, rigging and bolting cycle "
              "times. WT-012 (wind standby, a stoppage) and WT-009 (crane mobilisation) stay "
              "as events."},
    {"Driver_ID": "D3", "Name": "Electrical installation productivity", "Kind": "P",
     "Tag": "electrical_productivity", "P10": -0.05, "Mode": 0.0, "P90": 0.15,
     "WBS_Codes": "40", "Grid_Rows": "Electrical BOP", "Grid_Columns": "Labour, Subcontract",
     "Ruled_Risks": "",
     "Basis": "Cable laying, jointing and termination output. Absorbs the former WT-017 "
              "(cable installation productivity), which priced the same uncertainty as a "
              "discrete risk."},
    {"Driver_ID": "D4", "Name": "Grid and substation scope", "Kind": "Q",
     "Tag": "", "P10": None, "Mode": None, "P90": None,
     "Linked_Factors": "Q_Grid", "Elasticity": 1.0,
     "WBS_Codes": "50", "Grid_Rows": "", "Grid_Columns": "",
     "Ruled_Risks": "WT-025",
     "Basis": "More substation and connection scope takes proportionally longer to build. "
              "Q_Grid already prices its cost. WT-025 (a discrete scope change) stays."},
]


def _build_shared_drivers_sheet(wb) -> None:
    """RISKDRV-01: the Shared_Drivers sheet, header-driven as src.shared_drivers reads it."""
    from src.shared_drivers import COLUMNS, SHEET

    ws = wb.create_sheet(SHEET)
    ws.append(["Shared risk drivers (RISKDRV-01): always present, act on many activities at "
               "once; not register risks"])
    ws.append(list(COLUMNS))
    for d in WIND_SHARED_DRIVERS:
        ws.append([d.get(c) for c in COLUMNS])


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
            "Yes", pc, oc, mc, pcst, "Tropic Ridge capex basis",
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
        ("schedule duration (weeks)", SCHEDULE_WEEKS),
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
    _build_shared_drivers_sheet(wb)  # RISKDRV-01
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
    critical path (:data:`SCHEDULE_WEEKS`; WINDREAL-01 forks it into parallel turbine and
    substation paths, the substation path carrying float). The
    gating activities (one per Time=Yes risk, :data:`GATING`) sit *on* this spine, so
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
    # WINDREAL-01: the build starts 28/04/2025 so the ~14-month plan finishes 29/06/2026,
    # the commissioning date the AM periods narrate (period runs pass the same start).
    start = pd.Timestamp("2025-04-28 08:00")
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

    # --- Controlling network (WINDREAL-01: pre -> turbine || substation -> post) --
    handles: dict[str, int] = {}
    tails: dict[str, int] = {}
    path_float = {"pre": 0.0, "post": 0.0, "turbine": TURBINE_FLOAT_HOURS,
                  "substation": SUBSTATION_FLOAT_HOURS}

    def spine_gate(rid, prefix, float_h, hrs=GATE_HRS):
        code, name = GATING[rid]
        return add_task(prefix, code, name, hrs, float_h)

    for prefix, code, name, hrs, gate_rid, path in SPINE:
        fl = path_float[path]
        tid = spine_gate(gate_rid, prefix, fl) if gate_rid else add_task(prefix, code, name, hrs, fl)
        if path in ("turbine", "substation") and path not in tails:
            link(tails["pre"], tid)                      # the fork at the foundations gate
        elif path == "post" and "post" not in tails:
            link(tails["turbine"], tid)                  # rejoin at energisation
            link(tails["substation"], tid)
        elif path in tails:
            link(tails[path], tid)
        tails[path] = tid
        handles[code] = tid

    s_road, g_civil, g_found = handles["10.A.002"], handles["10.G.001"], handles["20.G.001"]
    g_crane, s_trench, s_hvtest = handles["30.G.002"], handles["40.A.001"], handles["40.A.004"]
    s_subciv, s_grid, s_energise = handles["50.A.001"], handles["50.A.005"], handles["50.A.006"]
    g_comm = handles["60.G.002"]

    # --- Per-turbine detail branches (positive float, parallel to spine) -----
    for i in range(1, N_TURBINES + 1):
        # Access spur off the main road -> civil gate.
        spur = add_task("10", f"10.C.{i:03d}", f"Turbine {i} access spur & pad", 40, 200.0)
        link(s_road, spur)
        # WINDREAL-01: the spur feeds its own foundation only. It used to feed the civil
        # gate too, which put 40h of "floated" spur work on the critical path (CPM finish
        # 5 wd past the controlling spine while the spur was authored with 200h float).
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
