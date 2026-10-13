"""QRAXL-01 step 6a - the Tier-1 headless read path.

Tier 1 (xlwings Lite / Pyodide) reads the LIVE workbook via xlwings ranges; this
headless module reads the SAME contract-v2 register via openpyxl for the
risk-first cross-runtime gate (no Excel needed). BOTH paths extract a plain GRID
of cell values and feed the shared, I/O-free parser
(``src.qra_register_parse``), so Tier-1 == Tier-2 on the read side is structural.

The grid extraction here is the seam the 6b xlwings shell mirrors: replace
``extract_grids_openpyxl`` with an xlwings ``sheet.range(...).value`` reader and
the identical parser produces the identical objects. ``extract_grids_openpyxl``
imports openpyxl (fine headless); the PARSER stays Pyodide-clean, so the Tier-1
runtime never imports openpyxl.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

import src.qra_core as qra_core
from src.bootstrap import bootstrap_percentile_ci
from src.config import RiskInput
from src.layer1_factors import Layer1Config
from src.rng_streams import require_seed
from src.register_contract import LAYER1_ENABLED_NAME, layer1_enabled_flag
from src.qra_register_parse import (
    RISK_REGISTER_SHEET,
    _LAYER1_SHEETS,
    _METHODOLOGY_SHEET,
    parse_layer1_from_grids,
    parse_risks_from_grid,
    resolve_aux_from_grid,
)

# The register's methodology sheet (CG coefficients + mode multipliers) - GD-B.
# The Tier-1 grids-dict key and the openpyxl/xlwings sheet title (title-cased).
METHODOLOGY_SHEET_TITLE = "Methodology"

# P-levels for the Tier-1 output P-curve (P5..P95, RF-01 output pattern).
P_LEVELS: tuple[int, ...] = tuple(range(5, 100, 5))
# Correlation-sensitivity triple (GN3A §4.1 bounding) - a required owner-view output.
CORR_MODES: tuple[str, ...] = ("zero", "elicited", "one")


def extract_grids_openpyxl(workbook_path: str | Path) -> dict[str, Any]:
    """Read the register into plain grids (list of row-tuples per sheet).

    Returns ``{"risk_register": grid, "layer1": {sheet: grid, ...},
    "methodology": grid}`` - exactly the cell values an xlwings ``range.value``
    read would surface, so the grids serialize cleanly for the Pyodide
    cross-runtime harness. The methodology grid (GD-B) is present when the
    register carries a "Methodology" sheet; absent -> {} -> the resolver fails
    loud (no cross-project methodology fallback).
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(workbook_path), data_only=True, read_only=True)
    try:
        risk_grid = [list(r) for r in wb[RISK_REGISTER_SHEET].iter_rows(values_only=True)]
        layer1 = {
            name: [list(r) for r in wb[name].iter_rows(values_only=True)]
            for name in _LAYER1_SHEETS if name in wb.sheetnames
        }
        methodology = (
            [list(r) for r in wb[METHODOLOGY_SHEET_TITLE].iter_rows(values_only=True)]
            if METHODOLOGY_SHEET_TITLE in wb.sheetnames else []
        )
        layer1_enabled = _read_layer1_flag(wb)
    finally:
        wb.close()
    return {"risk_register": risk_grid, "layer1": layer1,
            "methodology": methodology, "layer1_enabled": layer1_enabled}


def _read_layer1_flag(wb) -> bool:
    """Read ``Set_Layer1_Enabled`` from an open workbook via its named range
    (read_only-safe). Absent/blank/unrecognised -> FALSE: a pre-1.4 register carries
    no Layer-1 sheets, so OFF is correct and the empty-present parser crash (brief
    §8.1) can never fire."""
    try:
        sh, coord = list(wb.defined_names[LAYER1_ENABLED_NAME].destinations)[0]
        return layer1_enabled_flag(wb[sh][coord].value)
    except Exception:  # noqa: BLE001 - a missing/renamed flag reads as OFF
        return False


def _layer1_from_grids(grids: dict, source: str = "<grids>") -> Layer1Config | None:
    """REG05-A2 §3.2: the SHARED Layer-1 read gate for both boundaries. Parse the
    four grids only when ``Set_Layer1_Enabled`` (threaded in as ``grids["layer1_
    enabled"]``) reads TRUE; else Layer-1 = None. An empty, present-but-disabled
    Layer-1 is thus a read no-op - identical to the pre-A2 cost-only path."""
    if not grids.get("layer1_enabled", False):
        return None
    return parse_layer1_from_grids(grids.get("layer1", {}), source=source)


def parse_grids(
    grids: dict[str, Any], risk_id_prefix: str, source: str = "<grids>"
) -> tuple[list[RiskInput], Layer1Config | None]:
    """The Tier-1 read: grids -> (RiskInput list, Layer1Config | None) via the
    shared parser. Pyodide-clean (no openpyxl). This is the exact call the 6b
    xlwings shell makes after reading its own grids from the live workbook."""
    risks = parse_risks_from_grid(grids["risk_register"], risk_id_prefix, source=source)
    layer1 = _layer1_from_grids(grids, source=source)
    return risks, layer1


def read_register_headless(
    workbook_path: str | Path, risk_id_prefix: str
) -> tuple[list[RiskInput], Layer1Config | None]:
    """Convenience: openpyxl grid extraction + the shared parser."""
    grids = extract_grids_openpyxl(workbook_path)
    return parse_grids(grids, risk_id_prefix, source=str(workbook_path))


# ---------------------------------------------------------------------------
# QRAXL-01 step 6b - the headless run core (keep the @script a thin wrapper)
# ---------------------------------------------------------------------------

def _run_cost_layer(grids, risks, aux, n_iter, seed, layer1):
    res = qra_core.run_cost_layer(
        n_iter=n_iter, risks=risks, cg_coefficients=aux["cg_coefficients"],
        dual_lookup=aux["dual_lookup"], chain_risk_ids=aux["chain_risk_ids"],
        chain_config=aux["chain_config"], seed=seed, layer1=layer1,
    )
    return np.ascontiguousarray(res["cost_dollars_array"], dtype=np.float64), res


def _p_table(cost: np.ndarray) -> list[list[float]]:
    return [[float(p), float(np.percentile(cost, p))] for p in P_LEVELS]


def _s_curve(cost: np.ndarray, n_points: int = 101) -> dict[str, list[float]]:
    """Downsampled S-curve: cost value at evenly-spaced cumulative probabilities."""
    probs = np.linspace(0.0, 1.0, n_points)
    xs = np.percentile(cost, probs * 100.0)
    return {"prob": [float(p) for p in probs], "value": [float(v) for v in xs]}


def run_headless(
    grids: dict,
    risk_id_prefix: str,
    n_iter: int = 25_000,
    seed: int | None = None,
    view: str = "owner",
) -> dict[str, Any]:
    """Pure, headless-testable Tier-1 run: grids -> resolved inputs -> run_cost_layer
    -> output arrays. The @script ``run_simulation`` is a thin xlwings wrapper over
    this (read ranges -> call this -> write ranges). Pyodide-clean.

    ``view``: "owner" -> Layer 1 ON; "shared-pool"/"shared" -> Layer 1 OFF.
    Returns the P-curve, S-curve, Corr_flag, per-factor mean multipliers, and -
    for the owner view - the correlation-sensitivity triple (rho zero/elicited/one).

    ``seed`` is required: the shell resolves the workbook's (SEEDZERO-01), and this core never
    chooses one.
    """
    seed = require_seed(seed, where="src.tier1_headless.run_headless")
    risks = parse_risks_from_grid(grids["risk_register"], risk_id_prefix)
    layer1 = _layer1_from_grids(grids)   # REG05-A2 §3.2: gated on Set_Layer1_Enabled
    aux = resolve_aux_from_grid(
        grids["risk_register"], grids.get("methodology", []), risk_id_prefix)
    owner = view.strip().lower() == "owner"
    layer1_arg = layer1 if owner else None  # view gate is the second, later gate

    cost, res = _run_cost_layer(grids, risks, aux, n_iter, seed, layer1_arg)
    out: dict[str, Any] = {
        "view": "owner" if owner else "shared-pool",
        "layer1_enabled": bool(res["layer1_enabled"]),
        "n_iter": n_iter,
        "seed": seed,
        "p_table": _p_table(cost),
        "s_curve": _s_curve(cost),
        "cost_mean": float(cost.mean()),
        "corr_flag": None,
        "triple": {},
    }
    # Convergence note: the P80 CI half-width at the interactive default (25k),
    # via the engine's block-bootstrap CI machinery (src/bootstrap.py). Reported
    # in-sheet so the 25k default carries a documented convergence figure. It resamples on the
    # run's own seed, so one recorded seed reproduces the note with the run (SEEDZERO-01 P2).
    ci = bootstrap_percentile_ci(cost, percentile=80.0, n_blocks=100, n_resamples=1000, seed=seed)
    half = float(ci["ci95_width"]) / 2.0
    out["convergence_note"] = {
        "p80_point": float(ci["point"]),
        "p80_ci95_half_width": half,
        "p80_ci95_half_width_pct": (100.0 * half / ci["point"]) if ci["point"] else 0.0,
        "n_iter": n_iter, "n_blocks": 100, "n_resamples": 1000,
    }
    if owner and layer1 is not None:
        diag = res.get("layer1_corr_diag") or {}
        out["corr_flag"] = (
            f"invalid (min eig {diag.get('min_eig', float('nan')):.4g})"
            if diag.get("invalid") else
            f"valid (min eig {diag.get('min_eig', float('nan')):.4g})"
        )
        # correlation-sensitivity triple: re-run the sim at each correlation mode
        # (GN3A §4.1 bounding), exactly as RF-01 does - three short runs.
        for mode in CORR_MODES:
            l1 = replace(layer1, corr_mode=mode)
            c_m, _ = _run_cost_layer(grids, risks, aux, n_iter, seed, l1)
            out["triple"][mode] = _p_table(c_m)
    return out


def run_headless_from_workbook(
    workbook_path: str | Path, risk_id_prefix: str,
    n_iter: int = 25_000, seed: int | None = None, view: str = "owner",
) -> dict[str, Any]:
    """openpyxl grid extraction + the headless run (CI convenience)."""
    return run_headless(
        extract_grids_openpyxl(workbook_path), risk_id_prefix, n_iter, seed, view,
    )
