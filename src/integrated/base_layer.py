"""The base layer beneath the integrated total: Layer 1 drawn on its own stream (INTSCURVE-01 B).

Part B puts the base estimate under the event-risk contingency, so the report can draw the
total-cost S-curve (base + event-risk cost + delay cost) and read contingency off it as P-value
minus the declared base. Two rules make that safe.

**The cost arm never sees the base** (Reviewer R1, 28/10/2026). ``run_cost_layer`` adds a
``layer1_config`` into ``cost_dollars_array`` itself, which would move every headline, the
cross-validation inputs and the bounding reproduce check. So the deliverable never sets
``IntegratedConfig.layer1_config``: the base is one separate ``run_layer1_base`` call on
``layer1_generator(seed)``, and every event-risk array is byte-identical with it on or off.

**Time is priced once** (D-4 (a), Director 28/10/2026). With the CPM delay cost in the total, a
Layer 1 factor whose register driver is ``duration`` would price project time a second time. It
is left out of this base draw by name, logged, and stated in the report. The register is not
edited, because the Tier 1 owner view reads the same sheets and its numbers must not move.

Pure data (hard invariant 9): a register path and integers in, a dict out.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

#: The register ``driver`` tag of a Layer 1 factor that prices project duration. D-4 (a): left
#: out of the base when the CPM delay cost is in the total. Matched case-insensitively.
TIME_DRIVER_TAG = "duration"

_log = logging.getLogger(__name__)


def register_layer1(register_path: str | Path):
    """The register's ``Layer1Config``, or ``None`` when ``Set_Layer1_Enabled`` is not TRUE."""
    import openpyxl

    from src.register_contract import LAYER1_ENABLED_NAME, layer1_enabled_flag
    from src.v5_register_reader import read_layer1_v5

    wb = openpyxl.load_workbook(register_path, data_only=True)
    try:
        dest = wb.defined_names.get(LAYER1_ENABLED_NAME)
        enabled = False
        if dest is not None:
            sheet, coord = next(iter(dest.destinations))
            enabled = layer1_enabled_flag(wb[sheet][coord].value)
    finally:
        wb.close()
    return read_layer1_v5(register_path) if enabled else None


def exclude_time_factors(cfg) -> tuple[Any, list[dict[str, Any]]]:
    """``cfg`` without its ``duration``-driven factors, and a record of each one left out.

    Each record carries the factor's name, rows, columns and its expected dollar effect: its
    PERT mean delta times the base it binds, before any interaction with other factors. A
    correlated factor leaves the correlation block with its row and column.
    """
    from src.layer1_factors import _cell_masks, fit_pert_from_percentiles

    masks = _cell_masks(cfg)
    keep, dropped = [], []
    for f, mask in zip(cfg.factors, masks):
        if str(f.driver).strip().lower() != TIME_DRIVER_TAG:
            keep.append(f)
            continue
        lo, mode, hi = fit_pert_from_percentiles(f.opt, f.ml, f.p90)
        mean_delta = (lo + 4.0 * mode + hi) / 6.0
        dropped.append({
            "name": f.name,
            "driver": f.driver,
            "rows": tuple(f.rows),
            "columns": tuple(f.col_scope),
            "bound_base_dollars": float(cfg.base[mask].sum()),
            "mean_effect_dollars": float(mean_delta * cfg.base[mask].sum()),
        })
    if not dropped:
        return cfg, []
    gone = {d["name"] for d in dropped}
    idx = [i for i, n in enumerate(cfg.corr_names) if n not in gone]
    corr = np.asarray(cfg.corr_matrix, dtype=float)
    return replace(
        cfg,
        factors=tuple(keep),
        corr_names=tuple(cfg.corr_names[i] for i in idx),
        corr_matrix=corr[np.ix_(idx, idx)] if idx else np.zeros((0, 0)),
    ), dropped


def deliverable_base_layer(
    register_path: str | Path, n_iter: int, seed: int, *, delay_cost_in_total: bool = True,
) -> dict[str, Any] | None:
    """The base array the deliverable draws beneath the total, or ``None`` with Layer 1 off.

    Returns ``{"base_array", "base_total_dollars", "excluded_factors", "factor_mean_mult",
    "stream"}``. ``base_total_dollars`` is the declared base (the sum of the base grid), the
    figure contingency is read against.
    """
    from src.layer1_factors import run_layer1_base
    from src.rng_streams import LAYER1_STREAM, layer1_generator, require_seed

    cfg = register_layer1(register_path)
    if cfg is None:
        return None
    excluded: list[dict[str, Any]] = []
    if delay_cost_in_total:
        cfg, excluded = exclude_time_factors(cfg)
    for d in excluded:
        _log.warning(
            "INTSCURVE-01 D-4: Layer 1 factor %r (driver %r, rows %s) left out of the base: the "
            "CPM delay cost prices project time. Expected effect at the mean $%.2fM.",
            d["name"], d["driver"], ", ".join(d["rows"]), d["mean_effect_dollars"] / 1e6)
    seed = require_seed(seed, where="src/integrated/base_layer.deliverable_base_layer")
    out = run_layer1_base(int(n_iter), cfg, layer1_generator(seed))
    return {
        "base_array": np.asarray(out["base_array"], dtype=float),
        "base_total_dollars": float(out["base_total"]),
        "excluded_factors": excluded,
        "factor_mean_mult": out["factor_mean_mult"],
        "stream": f"[seed, 0x{LAYER1_STREAM:X}]",
    }
