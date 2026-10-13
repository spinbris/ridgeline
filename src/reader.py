"""
Excel reader — extracts simulation parameters from the workbook.

Reads from MC_Params and MC_Inputs sheets using xlwings Standard.
If MC_Inputs data is broken (#REF! errors), signals the caller
to fall back to register_loader.py.

Uses Excel named ranges (defined in Name Manager, workbook scope) so that
structural changes to MC_Params do not require reader.py edits. Falls back
to hardcoded cell addresses if a named range is missing, so the reader
degrades gracefully against older workbook versions.

Named ranges expected (all workbook scope):
  mc_n_iter, mc_seed, mc_view, mc_bop_contract,
  mc_bop_cont, mc_cse_cont, mc_tic, mc_contingency,
  mc_wbs_labels, mc_wbs_base, mc_wbs_lo, mc_wbs_hi, mc_wbs_dist,
  mc_c1_trigger, mc_c1_amp, mc_c2_trigger, mc_c2_factor,
  mc_cascade_on, mc_cascade_slip, mc_cascade_cap, mc_cascade_cost,
  mc_cg_coeffs, mc_party_a, mc_party_b, mc_shared_label,
  mc_results,
  mc_programme_seasons, mc_wbs_rho
"""

import xlwings as xw
from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig
from src.rng_streams import stated_seed



def _safe_float(val, default=0.0) -> float:
    """Convert a cell value to float, handling None, strings, errors."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s in ("", "#REF!", "#N/A", "#VALUE!", "nan", "None"):
        return default
    try:
        return float(s.replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return default


def _safe_str(val, default="") -> str:
    if val is None:
        return default
    s = str(val).strip()
    if s in ("#REF!", "#N/A", "nan", "None"):
        return default
    return s


def _named(wb: xw.Book, name: str, fallback: str):
    """Read a named range value, falling back to a cell address if missing.

    Parameters
    ----------
    wb       : open xlwings Book
    name     : workbook-scope named range (e.g. "mc_c1_trigger")
    fallback : cell address used if name is absent (e.g. "MC_Params!C35")

    Returns the raw cell value (or list of values for multi-cell ranges).
    Callers pass the result through _safe_float / _safe_str as normal.
    """
    try:
        rng = wb.names[name].refers_to_range
        val = rng.value
        # Multi-cell ranges return a 2D list; flatten to 1D for column ranges
        if isinstance(val, list) and val and isinstance(val[0], list):
            val = [row[0] for row in val]
        return val
    except Exception:
        sheet_name, cell = fallback.split("!") if "!" in fallback else ("MC_Params", fallback)
        return wb.sheets[sheet_name].range(cell).value


# ---------------------------------------------------------------------------
# MC_Params reader
# ---------------------------------------------------------------------------

def read_params(wb: xw.Book) -> tuple[SimConfig, list[WBSBucket], ChainConfig, dict[str, float], float]:
    """Read all parameters from MC_Params sheet.

    Returns
    -------
    config : SimConfig
    buckets : list[WBSBucket] (8 items)
    chains : ChainConfig
    corr_coefficients : dict mapping "CG01"–"CG10" to rho
    wbs_rho : float — cross-bucket correlation for Layer 1
    """
    # Section A — Simulation control
    config = SimConfig(
        n_iter=int(_safe_float(_named(wb, "mc_n_iter",        "MC_Params!C4"),  100_000)),
        seed=stated_seed(      _named(wb, "mc_seed",          "MC_Params!C5"), where="mc_seed"),
        view=_safe_str(        _named(wb, "mc_view",          "MC_Params!C6"),  "All"),
        bop_contract=_safe_float(_named(wb, "mc_bop_contract","MC_Params!C9"),  300_000_000),
        bop_contingency=_safe_float(_named(wb, "mc_bop_cont", "MC_Params!C10"), 5_000_000),
        cse_contingency=_safe_float(_named(wb, "mc_cse_cont", "MC_Params!C11"), 5_000_000),
        tic=_safe_float(       _named(wb, "mc_tic",           "MC_Params!C13"), 300_000_000),
        contingency=_safe_float(_named(wb, "mc_contingency",  "MC_Params!C14"), 30_000_000),
        party_a_name=_safe_str(_named(wb, "mc_party_a",       "MC_Params!C58"), "BOP Contractor"),
        party_b_name=_safe_str(_named(wb, "mc_party_b",       "MC_Params!C59"), "Owner"),
        shared_label=_safe_str(_named(wb, "mc_shared_label",  "MC_Params!C60"), "Shared"),
        programme_seasons=int(_safe_float(_named(wb, "mc_programme_seasons", "MC_Params!C99"), 3)),
        reporting_p_level=int(_safe_float(_named(wb, "mc_reporting_p", "MC_Params!C7"), 80)),
        # SP18a — bootstrap CI parameters; named ranges optional, fall back to defaults
        bootstrap_n_blocks=int(_safe_float(
            _named(wb, "mc_bootstrap_n_blocks", "MC_Params!ZZ1"), 100)),
        bootstrap_n_resamples=int(_safe_float(
            _named(wb, "mc_bootstrap_n_resamples", "MC_Params!ZZ2"), 1000)),
        bootstrap_seed=stated_seed(
            _named(wb, "mc_bootstrap_seed", "MC_Params!ZZ3"), where="mc_bootstrap_seed"),
    )

    # Section B — WBS cost buckets (named ranges cover rows 16–30; blank rows skipped)
    wbs_base   = _named(wb, "mc_wbs_base",   "MC_Params!C16:C30")
    wbs_lo     = _named(wb, "mc_wbs_lo",     "MC_Params!D16:D30")
    wbs_hi     = _named(wb, "mc_wbs_hi",     "MC_Params!E16:E30")
    wbs_dist   = _named(wb, "mc_wbs_dist",   "MC_Params!F16:F30")
    wbs_labels = _named(wb, "mc_wbs_labels", "MC_Params!B16:B30")

    # Ensure lists even if range returns a single value
    def _as_list(v): return v if isinstance(v, list) else [v]
    wbs_base, wbs_lo, wbs_hi, wbs_dist, wbs_labels = (
        _as_list(x) for x in (wbs_base, wbs_lo, wbs_hi, wbs_dist, wbs_labels)
    )

    buckets = []
    for i in range(len(wbs_base)):
        lo   = _safe_float(wbs_lo[i])
        hi   = _safe_float(wbs_hi[i])
        base = _safe_float(wbs_base[i])
        dist = _safe_str(wbs_dist[i], "Triangular")
        name = _safe_str(wbs_labels[i], f"WBS-{i+1}")
        if lo == 0 and hi == 0:
            continue  # row not configured for sampling
        buckets.append(WBSBucket(name=name, base_cost=base,
                                 low_var=lo, high_var=hi, distribution=dist))

    # Section C — Chain parameters
    chains = ChainConfig(
        c1_trigger_months=   _safe_float(_named(wb, "mc_c1_trigger",   "MC_Params!C35"), 3.0),
        c1_amplification=    _safe_float(_named(wb, "mc_c1_amp",       "MC_Params!C36"), 2.5),
        c2_trigger_weeks=    _safe_float(_named(wb, "mc_c2_trigger",   "MC_Params!C37"), 2.0),
        c2_cascade_factor=   _safe_float(_named(wb, "mc_c2_factor",    "MC_Params!C38"), 1.5),
        cascade_enabled= bool(_safe_float(_named(wb, "mc_cascade_on",  "MC_Params!C39"), 0)),
        cascade_slip_rate=   _safe_float(_named(wb, "mc_cascade_slip", "MC_Params!C40"), 1.5),
        cascade_slip_cap=    _safe_float(_named(wb, "mc_cascade_cap",  "MC_Params!C41"), 3.0),
        cascade_cost_scale_rate=_safe_float(_named(wb, "mc_cascade_cost","MC_Params!C42"), 0.5),
    )

    # Section D — Correlation coefficients. REG03 S2b: the mc_cg_coeffs NAMED RANGE
    # is authoritative and address-independent (the reference register = C27:C39, 13 cells); the
    # positional C46:C55 is only a legacy fallback for old workbooks with no name.
    cg_raw = _as_list(_named(wb, "mc_cg_coeffs", "MC_Params!C46:C55"))
    corr_coefficients = {
        f"CG{i+1:02d}": _safe_float(cg_raw[i], 0.5) for i in range(len(cg_raw))
    }

    # WBS cross-bucket correlation
    wbs_rho = _safe_float(_named(wb, "mc_wbs_rho", "MC_Params!C44"), 0.4)

    return config, buckets, chains, corr_coefficients, wbs_rho


# ---------------------------------------------------------------------------
# MC_Inputs reader
# ---------------------------------------------------------------------------

def read_risks(wb: xw.Book, config: SimConfig) -> list[RiskInput] | None:
    """Read risk inputs from MC_Inputs sheet.

    Returns list of RiskInput, or None if data is broken (#REF! errors)
    indicating the caller should use register_loader instead.
    """
    sht = wb.sheets["MC_Inputs"]

    # Check first data cell — if #REF!, the sheet is broken
    test_cell = sht.range("B6").value
    if test_cell is not None and "#REF!" in str(test_cell):
        return None  # Signal: use register_loader

    # --- Build header-to-index map from row 3 (dynamic) ---
    # SP8b/SP9 fallback indices used when a header is not found.
    _SP8B_FALLBACKS = {
        "risk_id": 0, "description": 1, "owner": 2,
        "distribution": 3, "corr_group": 4, "mc_include": 5,
        "probability": 6, "opt_cost": 7, "ml_cost": 8, "pess_cost": 9,
        "ml_days": 12, "basis": 14, "recurrence": 15,
    }

    header_range = sht.range("B3").expand("right")
    raw_headers = header_range.value
    if not isinstance(raw_headers, list):
        raw_headers = [raw_headers]
    headers = [_safe_str(h).strip() for h in raw_headers]
    n_cols = len(headers)

    def _find(names, partial=False):
        """Return 0-based index for the first header matching any of *names*."""
        for name in names:
            nl = name.lower()
            for i, h in enumerate(headers):
                hl = h.lower()
                if (hl == nl) or (partial and nl in hl):
                    return i
        return None

    col = {}
    col["risk_id"]      = _find(["Risk ID"])                       or _SP8B_FALLBACKS["risk_id"]
    col["description"]  = _find(["Description"])                   or _SP8B_FALLBACKS["description"]
    col["owner"]        = _find(["Package", "Owner"])              or _SP8B_FALLBACKS["owner"]
    col["distribution"] = _find(["Dist"])                          or _SP8B_FALLBACKS["distribution"]
    col["corr_group"]   = _find(["CG"])                            or _SP8B_FALLBACKS["corr_group"]
    col["mc_include"]   = _find(["MC Include"])                    or _SP8B_FALLBACKS["mc_include"]
    col["probability"]  = _find(["Prob"], partial=True)            or _SP8B_FALLBACKS["probability"]
    col["opt_cost"]     = _find(["Opt ($)", "Opt"])                or _SP8B_FALLBACKS["opt_cost"]
    col["ml_cost"]      = _find(["ML ($)", "ML"])                  or _SP8B_FALLBACKS["ml_cost"]
    col["pess_cost"]    = _find(["Pess ($)", "Pess"])              or _SP8B_FALLBACKS["pess_cost"]
    col["ml_days"]      = _find(["ML days"])  # None if not found (removed in SP11a)
    col["basis"]        = _find(["Basis"])                         or _SP8B_FALLBACKS["basis"]
    col["recurrence"]   = _find(["Recurrence_Type", "Recurrence"]) or _SP8B_FALLBACKS["recurrence"]

    # Max Occ — try header lookup, fall back to column AG
    col["max_occ"] = _find(["Max Occ", "Max_Occ"])
    # Stage B: qualitative fields for risk cards (all optional)
    col["cause"]        = _find(["Causes", "Cause"], partial=True)
    col["consequence"]  = _find(["Consequences", "Consequence"], partial=True)
    col["controls"]     = _find(["Existing Controls", "Controls"], partial=True)
    col["risk_status"]  = _find(["Risk Status", "Status"])

    # --- Read data range dynamically (width matches header row) ---
    last_row = sht.range("B6").end("down").row
    if last_row > 500:
        last_row = 200  # safety cap
    last_col_letter = header_range[-1].address.split("$")[1]  # e.g. "V" or "X"
    data = sht.range(f"B6:{last_col_letter}{last_row}").value

    if data is None:
        return None

    # Read Max Occ per-risk (BINOMIAL cap)
    if col["max_occ"] is not None:
        # Max Occ is within the data range — will read from row directly
        max_occ_list = None
    else:
        # Fallback: read from column AG (hardcoded position)
        max_occ_range = sht.range(f"AG6:AG{last_row}").value
        if max_occ_range is None:
            max_occ_list = [0.0] * (last_row - 5)
        elif not isinstance(max_occ_range, list):
            max_occ_list = [max_occ_range]
        else:
            if max_occ_range and isinstance(max_occ_range[0], list):
                max_occ_list = [row[0] for row in max_occ_range]
            else:
                max_occ_list = max_occ_range

    risks = []
    for data_row_idx, row in enumerate(data):
        if row is None or len(row) < min(n_cols, 15):
            continue
        rid = _safe_str(row[col["risk_id"]])
        if not rid or rid == "nan":
            continue

        # MC Include gate
        mc_include = _safe_str(row[col["mc_include"]], "Yes")
        if mc_include.lower() in ("no", "false", "0"):
            continue

        desc  = _safe_str(row[col["description"]])
        owner = _safe_str(row[col["owner"]], "BOP Contractor")
        dist  = _safe_str(row[col["distribution"]], "Triangular")
        cg    = _safe_str(row[col["corr_group"]], "CG_UNASSIGNED")
        prob  = _safe_float(row[col["probability"]], 0.0)
        opt   = _safe_float(row[col["opt_cost"]])
        ml    = _safe_float(row[col["ml_cost"]])
        pess  = _safe_float(row[col["pess_cost"]])
        basis = _safe_str(row[col["basis"]])

        # ML days — removed in SP11a; default to 0.0 if column absent
        if col["ml_days"] is not None and col["ml_days"] < len(row):
            ml_days = _safe_float(row[col["ml_days"]])
        else:
            ml_days = 0.0

        # SP11a: All risks are BOP-owned in the register. Stakeholder view
        # filtering is bypassed - all MC Include = Yes risks are treated as
        # shared pool risks regardless of the Package/Owner column value.
        # The view filter can be re-enabled if multi-owner structure returns.

        # Recurrence type
        if col["recurrence"] is not None and col["recurrence"] < len(row):
            rec_type = _safe_str(row[col["recurrence"]])
        else:
            rec_type = ""

        # Max Occ: per-risk cap on BINOMIAL occurrences
        # 0 or blank = use programme_seasons as fallback
        if col["max_occ"] is not None and col["max_occ"] < len(row):
            rec_param = _safe_float(row[col["max_occ"]], 0.0)
        elif max_occ_list is not None:
            rec_param = _safe_float(
                max_occ_list[data_row_idx] if data_row_idx < len(max_occ_list) else None,
                0.0
            )
        else:
            rec_param = 0.0

        # Cascade fields — not currently populated in MC_Inputs
        casc_group = ""
        opt_sched = 0.0
        pess_sched = 0.0

        # Stage B: qualitative fields for risk cards
        cause = _safe_str(row[col["cause"]]) if col["cause"] is not None and col["cause"] < len(row) else ""
        consequence = _safe_str(row[col["consequence"]]) if col["consequence"] is not None and col["consequence"] < len(row) else ""
        controls = _safe_str(row[col["controls"]]) if col["controls"] is not None and col["controls"] < len(row) else ""
        risk_status = _safe_str(row[col["risk_status"]], "Open") if col["risk_status"] is not None and col["risk_status"] < len(row) else "Open"
        direction = "Opportunity" if desc.lower().startswith("opportunity") else "Threat"

        risks.append(RiskInput(
            risk_id=rid, description=desc, owner=owner,
            distribution=dist, correlation_group=cg,
            probability=prob, opt_cost=opt, ml_cost=ml, pess_cost=pess,
            ml_days=ml_days, basis=basis,
            recurrence_type=rec_type, recurrence_param=rec_param,
            cascade_group=casc_group, opt_schedule_days=opt_sched,
            pess_schedule_days=pess_sched,
            cause=cause, consequence=consequence, existing_controls=controls,
            risk_status=risk_status, direction=direction,
        ))

    return risks


# ---------------------------------------------------------------------------
# Gain/pain config and pool budget
# ---------------------------------------------------------------------------

def read_gain_pain_config(wb: xw.Book) -> GainPainConfig:
    """Read gain/pain share parameters from MC_Params section G.

    Named ranges: mc_gp_enabled, mc_gp_toc, mc_gp_share_split,
    mc_gp_max_reward, mc_gp_max_risk.
    Falls back to cell addresses, then to defaults.py values.
    """
    from src.defaults import (
        DEFAULT_GP_TOC, DEFAULT_GP_SHARE_SPLIT,
        DEFAULT_GP_MAX_REWARD_PCT, DEFAULT_GP_MAX_RISK_PCT,
    )
    enabled_val = _safe_float(
        _named(wb, "mc_gp_enabled", "MC_Params!C75"), 0
    )
    toc = _safe_float(
        _named(wb, "mc_gp_toc", "MC_Params!C76"), DEFAULT_GP_TOC
    )
    share_split = _safe_float(
        _named(wb, "mc_gp_share_split", "MC_Params!C77"), DEFAULT_GP_SHARE_SPLIT
    )
    max_reward_pct = _safe_float(
        _named(wb, "mc_gp_max_reward", "MC_Params!C78"), DEFAULT_GP_MAX_REWARD_PCT
    )
    max_risk_pct = _safe_float(
        _named(wb, "mc_gp_max_risk", "MC_Params!C79"), DEFAULT_GP_MAX_RISK_PCT
    )
    return GainPainConfig(
        toc=toc,
        share_split=share_split,
        max_reward_pct=max_reward_pct,
        max_risk_pct=max_risk_pct,
        enabled=bool(enabled_val),
    )


def read_pool_budget(wb: xw.Book) -> float:
    """Read Shared Risk Pool budget from MC_Params!C14.

    Named range: mc_contingency
    Returns 0.0 if cell is missing or zero (surfaces as "not configured").
    """
    try:
        val = _safe_float(
            _named(wb, "mc_contingency", "MC_Params!C14"), 0
        )
        if val > 0:
            return val
    except Exception:
        pass
    return 0.0


def _matches_party(owner: str, party_name: str) -> bool:
    return owner.lower().startswith(party_name.lower()[:6])


def _matches_shared(owner: str, shared_label: str) -> bool:
    return owner.lower() == shared_label.lower()
