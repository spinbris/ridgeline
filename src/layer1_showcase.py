"""QRAXL-01 step 4 - the RF-01 $50M Layer-1 showcase starter (data only).

The pinned 14-factor / $50M-base / 7-factor-correlated dataset from the step-4
brief (rev 2), expressed as a ``Layer1Config`` for the engine's Beta-PERT +
Cholesky Layer-1 path. This is the WIND-SHOWCASE STARTER (brief decision 5);
swap in a real estimate per project - none of it is client data.

Pyodide-clean: numpy + src.layer1_factors only.
"""

from __future__ import annotations

import numpy as np

from src.layer1_factors import Factor, Layer1Config

_ALL = ("ALL",)

# Cost columns and WBS rows (brief section 2), order fixed.
COLS = (
    "Staff", "Labour", "Plant", "Concrete", "Steel", "General",
    "Subcontract", "Provisional",
)
ROWS = (
    "Development & approvals",
    "Turbine supply",
    "Turbine transport & erection",
    "BOP civils",
    "Electrical BOP",
    "Substation & grid connection",
    "Commissioning",
    "Owners costs & PM",
)

# $50M base matrix in $M (brief section 2); rows x cols in ROWS/COLS order.
_BASE_M = np.array(
    [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.2, 0.0],   # Development & approvals
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 26.5, 1.0],  # Turbine supply
        [0.2, 0.8, 1.2, 0.0, 0.0, 0.0, 0.8, 0.0],   # Turbine transport & erection
        [0.0, 1.3, 1.2, 1.8, 0.7, 0.6, 0.0, 0.4],   # BOP civils
        [0.2, 0.9, 0.0, 0.0, 0.0, 1.5, 0.9, 0.0],   # Electrical BOP
        [0.3, 0.0, 0.0, 0.0, 0.6, 1.2, 2.5, 0.4],   # Substation & grid connection
        [0.4, 0.0, 0.0, 0.0, 0.0, 0.1, 0.5, 0.0],   # Commissioning
        [1.8, 0.0, 0.0, 0.0, 0.0, 0.2, 0.0, 0.0],   # Owners costs & PM
    ],
    dtype=np.float64,
)

# 14 factors (brief section 1). opt=P10 delta, ml=mode (0), p90=P90 delta.
# driver is the no-double-count classification (brief section 4) - none collide
# with the weather / geotech-surprise / grid-delay EVENT classes (the weather
# Productivity factor was dropped, decision 4).
_FACTORS = (
    Factor("Provisions", "provisions", -0.50, 0.00, 0.30, ("Provisional",), _ALL),
    Factor("Duration", "duration", -0.05, 0.00, 0.15, _ALL,
           ("Turbine transport & erection", "Commissioning", "Owners costs & PM")),
    Factor("Q_Civils", "civils_quantity", -0.08, 0.00, 0.20, _ALL, ("BOP civils",)),
    Factor("Q_Elec", "elec_quantity", -0.05, 0.00, 0.15, _ALL, ("Electrical BOP",)),
    Factor("Q_Grid", "grid_scope", -0.05, 0.00, 0.25, _ALL,
           ("Substation & grid connection",)),
    Factor("R_Turbine", "turbine_price", -0.05, 0.00, 0.12, _ALL, ("Turbine supply",)),
    Factor("FX", "fx", -0.06, 0.00, 0.10, ("Subcontract", "General"),
           ("Turbine supply", "Electrical BOP")),
    Factor("R_Concrete", "concrete_rate", -0.05, 0.00, 0.15, ("Concrete",), _ALL),
    Factor("R_Steel", "steel_rate", -0.08, 0.00, 0.20, ("Steel",), _ALL),
    Factor("R_General", "general_rate", -0.05, 0.00, 0.12, ("General",), _ALL),
    Factor("R_Plant", "plant_rate", -0.05, 0.00, 0.12, ("Plant",), _ALL),
    Factor("R_Subcon", "subcon_rate", -0.04, 0.00, 0.10, ("Subcontract",),
           ("Development & approvals", "Turbine transport & erection",
            "Electrical BOP", "Substation & grid connection", "Commissioning")),
    Factor("R_Staff", "staff_rate", -0.03, 0.00, 0.08, ("Staff",), _ALL),
    Factor("R_Labour", "labour_rate", -0.04, 0.00, 0.12, ("Labour",), _ALL),
)

# Correlated set: 7 market-rate factors (brief section 3, FX added - decision 3).
CORR_NAMES = (
    "R_Turbine", "FX", "R_Concrete", "R_Steel", "R_General", "R_Plant", "R_Subcon",
)

# Elicited lower triangle (brief section 3); the engine mirrors it at runtime.
_CORR_LOWER = np.array(
    [
        [1.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],  # R_Turbine
        [0.30, 1.00, 0.00, 0.00, 0.00, 0.00, 0.00],  # FX
        [0.30, 0.10, 1.00, 0.00, 0.00, 0.00, 0.00],  # R_Concrete
        [0.40, 0.20, 0.50, 1.00, 0.00, 0.00, 0.00],  # R_Steel
        [0.30, 0.30, 0.40, 0.40, 1.00, 0.00, 0.00],  # R_General
        [0.20, 0.10, 0.30, 0.30, 0.30, 1.00, 0.00],  # R_Plant
        [0.20, 0.10, 0.30, 0.30, 0.40, 0.30, 1.00],  # R_Subcon
    ],
    dtype=np.float64,
)

# Factor drivers active in the showcase set - for the no-double-count guard.
SHOWCASE_FACTOR_DRIVERS = frozenset(f.driver for f in _FACTORS)


def build_showcase_layer1(corr_mode: str = "elicited") -> Layer1Config:
    """Return the $50M showcase Layer1Config (base in DOLLARS), given a
    correlation sensitivity mode (``zero`` | ``elicited`` | ``one``)."""
    return Layer1Config(
        base=_BASE_M * 1_000_000.0,       # $M -> dollars
        row_labels=ROWS,
        col_labels=COLS,
        factors=_FACTORS,
        corr_names=CORR_NAMES,
        corr_matrix=_CORR_LOWER,
        corr_mode=corr_mode,
        declared_total=50_000_000.0,
    )
