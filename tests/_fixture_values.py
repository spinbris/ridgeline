"""Fixture values shared by tests and smoke scripts (RS-D-1, D-13).

``FIXTURE_DAY_RATE`` is the day rate a test uses when it constructs ``SRAConfig`` directly
instead of loading a register. It is a fixture value and nothing else: production code
reads ``day_rate_default`` from the register and refuses when it is absent (DAYRATE-02), and
``src/`` names no rate at all. It lives here rather than in ``conftest.py`` itself so the
smoke scripts under ``scripts/`` can import it without importing the harness's
module-load side effects (project selection); ``conftest`` re-exports it.
"""
from __future__ import annotations

FIXTURE_DAY_RATE: float = 100000.0
