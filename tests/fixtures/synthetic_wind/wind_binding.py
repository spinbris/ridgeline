"""Synthetic-wind binding — SHIM (QRAXL-01 generic decoupling GD-A).

The synthetic-wind binding was promoted to a first-class engine binding at
``src/sra/cpm/bindings/synthetic_wind.py``. This fixture file is retained as a
thin shim so the existing activators (``run_wind_showcase._activate_wind_binding``
and ``test_synthetic_wind._wind_project``) that ``exec`` this path still register
the binding: importing the first-class module self-registers ``synthetic_wind``.
It re-exports ``SYNTHETIC_WIND_BINDING`` for any code that referenced it here.
"""
from __future__ import annotations

from src.sra.cpm.bindings.synthetic_wind import (  # noqa: F401  (re-export)
    SYNTHETIC_WIND_BINDING,
)
