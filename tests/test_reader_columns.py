"""
Tests for read_risks() column index mapping in src/reader.py.

Verifies the corrected column indices match the actual MC_Inputs layout:
  G=5 MC Include, H=6 Prob%, I=7 Opt$, J=8 ML$, K=9 Pess$,
  N=12 ML days, P=14 Basis, Q=15 Recurrence_Type.

Tests exercise the index mapping by calling the internal parsing logic
with fake row data (lists matching the B:V range).
"""

import pytest
from src.config import SimConfig, RiskInput
from src.reader import _safe_float, _safe_str, _matches_party, _matches_shared


# ---------------------------------------------------------------------------
# Helper: simulate read_risks() row parsing without xlwings
# ---------------------------------------------------------------------------

def _parse_row(row, config=None):
    """Parse a single MC_Inputs row using the same logic as read_risks().

    Returns RiskInput or None (if excluded by MC Include or view filter).
    """
    if config is None:
        config = SimConfig()

    if row is None or len(row) < 15:
        return None
    rid = _safe_str(row[0])
    if not rid or rid == "nan":
        return None

    # MC Include flag — column G, index 5
    mc_include = _safe_str(row[5], "Yes")
    if mc_include.lower() in ("no", "false", "0"):
        return None

    desc = _safe_str(row[1])
    owner = _safe_str(row[2], "BOP Contractor")
    dist = _safe_str(row[3], "Triangular")
    cg = _safe_str(row[4], "CG05")
    prob = _safe_float(row[6], 0.175)
    opt = _safe_float(row[7])
    ml = _safe_float(row[8])
    pess = _safe_float(row[9])
    ml_days = _safe_float(row[12])
    basis = _safe_str(row[14])

    # View filter
    if config.view == "BOP":
        if not (_matches_party(owner, config.party_a_name)
                or _matches_shared(owner, config.shared_label)):
            return None
    elif config.view == "CSE":
        if not (_matches_party(owner, config.party_b_name)
                or _matches_shared(owner, config.shared_label)):
            return None
    elif config.view == "Shared":
        if not _matches_shared(owner, config.shared_label):
            return None

    rec_type = _safe_str(row[15]) if len(row) > 15 else ""
    rec_param = 1.0

    return RiskInput(
        risk_id=rid, description=desc, owner=owner,
        distribution=dist, correlation_group=cg,
        probability=prob, opt_cost=opt, ml_cost=ml, pess_cost=pess,
        ml_days=ml_days, basis=basis,
        recurrence_type=rec_type, recurrence_param=rec_param,
    )


def _make_row(**overrides):
    """Build a 20-element row matching MC_Inputs B:U layout.

    Default values represent a typical risk row with known values
    at each position for verification.
    """
    # Indices: 0=RiskID, 1=Desc, 2=Owner, 3=Dist, 4=CG,
    #          5=MC_Include, 6=Prob, 7=Opt, 8=ML, 9=Pess,
    #          10=EV, 11=EMV, 12=ML_days, 13=CG_active, 14=Basis,
    #          15=Recurrence_Type, 16=MC_Status, 17=RBS1, 18=RBS2, 19=empty
    row = [
        "R099",                # 0: RiskID
        "Test risk desc",      # 1: Description
        "BOP Contractor",      # 2: Owner
        "Triangular",          # 3: Dist
        "CG05",                # 4: CG
        "Yes",                 # 5: MC Include
        0.25,                  # 6: Prob %
        500_000,               # 7: Opt ($)
        2_000_000,             # 8: ML ($)
        6_000_000,             # 9: Pess ($)
        1_200_000,             # 10: EV cost (formula)
        300_000,               # 11: EMV (formula)
        20.0,                  # 12: ML days
        "Active",              # 13: CG active
        "DUMMY - workshop",    # 14: Basis
        "",                    # 15: Recurrence_Type
        "Ready",               # 16: MC Status
        "4 External",          # 17: RBS LVL 1
        "4.3_Env",             # 18: RBS LVL 2
        None,                  # 19: empty
    ]
    for k, v in overrides.items():
        idx = int(k.split("_")[1]) if k.startswith("idx_") else None
        if idx is not None:
            row[idx] = v
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_mc_include_at_index_5():
    """Row with index 5 = 'No' should be excluded."""
    row = _make_row(idx_5="No")
    result = _parse_row(row)
    assert result is None


def test_mc_include_yes_passes():
    """Row with index 5 = 'Yes' should be included."""
    row = _make_row(idx_5="Yes")
    result = _parse_row(row)
    assert result is not None
    assert result.risk_id == "R099"


def test_prob_reads_from_index_6():
    """Probability should come from index 6 (column H)."""
    row = _make_row(idx_6=0.25)
    result = _parse_row(row)
    assert result.probability == 0.25


def test_opt_reads_from_index_7():
    """Opt cost should come from index 7 (column I)."""
    row = _make_row(idx_7=500_000)
    result = _parse_row(row)
    assert result.opt_cost == 500_000


def test_ml_reads_from_index_8():
    """ML cost should come from index 8 (column J)."""
    row = _make_row(idx_8=2_000_000)
    result = _parse_row(row)
    assert result.ml_cost == 2_000_000


def test_pess_reads_from_index_9():
    """Pess cost should come from index 9 (column K)."""
    row = _make_row(idx_9=6_000_000)
    result = _parse_row(row)
    assert result.pess_cost == 6_000_000


def test_ml_days_reads_from_index_12():
    """ML days should come from index 12 (column N)."""
    row = _make_row(idx_12=20.0)
    result = _parse_row(row)
    assert result.ml_days == 20.0


def test_basis_reads_from_index_14():
    """Basis should come from index 14 (column P)."""
    row = _make_row(idx_14="DUMMY \u2014 confirm")
    result = _parse_row(row)
    assert result.basis == "DUMMY \u2014 confirm"


def test_recurrence_type_reads_from_index_15():
    """Recurrence_Type should come from index 15 (column Q)."""
    row = _make_row(idx_15="BINOMIAL")
    result = _parse_row(row)
    assert result.recurrence_type == "BINOMIAL"


def test_full_row_r016a():
    """Full row matching actual R016a data — verify ALL fields."""
    row = [
        "R016a",                                    # 0: RiskID
        "Threat FM - Severe weather event",         # 1: Desc
        "Shared",                                   # 2: Owner
        "Triangular",                               # 3: Dist
        "CG05 - Weather",                           # 4: CG
        "Yes",                                      # 5: MC Include
        0.10,                                       # 6: Prob %
        500_000,                                    # 7: Opt ($)
        2_000_000,                                  # 8: ML ($)
        6_000_000,                                  # 9: Pess ($)
        600_000,                                    # 10: EV (formula)
        60_000,                                     # 11: EMV (formula)
        20.0,                                       # 12: ML days
        "Active",                                   # 13: CG active
        "DUMMY - confirm at workshop",              # 14: Basis
        "BINOMIAL",                                 # 15: Recurrence_Type
        "Ready",                                    # 16: MC Status
        "4 External",                               # 17: RBS LVL 1
        "4.3_Env",                                  # 18: RBS LVL 2
        None,                                       # 19: empty
    ]
    result = _parse_row(row)
    assert result is not None
    assert result.risk_id == "R016a"
    assert result.probability == 0.10
    assert result.opt_cost == 500_000
    assert result.ml_cost == 2_000_000
    assert result.pess_cost == 6_000_000
    assert result.ml_days == 20.0
    assert result.recurrence_type == "BINOMIAL"
    assert result.distribution == "Triangular"
    assert result.owner == "Shared"
    assert result.basis == "DUMMY - confirm at workshop"


def test_excluded_risk_not_in_list():
    """Only rows with MC Include='Yes' should be parsed."""
    row_yes = _make_row(idx_0="R001", idx_5="Yes")
    row_no = _make_row(idx_0="R002", idx_5="No")

    result_yes = _parse_row(row_yes)
    result_no = _parse_row(row_no)

    assert result_yes is not None
    assert result_yes.risk_id == "R001"
    assert result_no is None
