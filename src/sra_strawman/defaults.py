"""Defaults for the SRA strawman subpackage.

Central location for constants that would otherwise be hardcoded in
runtime modules. Every value here is traceable to the SP17 SRA Option A
build brief v2
or to Steve's in-session direction.

Do not add a new constant here without citing the authorising source.
"""

from __future__ import annotations

# --- Option Z hybrid classifier (Brief Amendment 1 / Section 3.2) ---

# Activities with total_float in (0, HYBRID_FLOAT_THRESHOLD_DAYS] are Hybrid.
# Activities with total_float > HYBRID_FLOAT_THRESHOLD_DAYS are Parallel.
HYBRID_FLOAT_THRESHOLD_DAYS: float = 20.0

# Sanity bounds on Series count across the whole schedule. Outside these
# bounds, the classifier is presumed broken. From Brief Section 3.2 unit
# tests: "Total Series count ... MUST be in the 200-300 range. If below
# 150 or above 350, the classifier is broken - FAIL the test suite and stop."
SERIES_COUNT_TARGET_MIN: int = 200
SERIES_COUNT_TARGET_MAX: int = 300
SERIES_COUNT_HARD_FLOOR: int = 150
SERIES_COUNT_HARD_CEILING: int = 350

# --- Duration parser (Brief Section 3.4) ---

# "5 working days per week" - Brief Section 3.4 explicitly specifies this
# conversion for phrases like "2-8 weeks delay".
WORKING_DAYS_PER_WEEK: int = 5

# --- Reconciliation treatment (Brief Amendment 2, Section 4.2 column S) ---

# Divisor applied to Opt/ML/Pess durations when Reconciliation = B.
# From Amendment 2: "divide ML and Pess duration figures by 3 in the
# strawman inputs when Reconciliation treatment = B".
RECONCILIATION_B_DIVISOR: int = 3

# Default Reconciliation treatment for rows where Recurrence Type is NOT
# BINOMIAL. Per Steve's resolution (pre-flight 3.0.3 unblock), every row
# currently defaults to "A" because the earlier reference register has zero BINOMIAL risks under
# seasons=1. When seasons=N years is activated and rows are retagged
# BINOMIAL, those rows flip to "B" automatically.
DEFAULT_RECONCILIATION_NON_BINOMIAL: str = "A"
DEFAULT_RECONCILIATION_BINOMIAL: str = "B"

# --- Day-rate (Brief Section 3.5) ---

# Programme working days from P6 (Brief Section 1.1 / Section 3.5).
PROGRAMME_WORKING_DAYS: int = 912

# Calendar-to-working-day ratio (7/5). Brief Section 3.5.
CALENDAR_PER_WORKING_DAY_RATIO: float = 7.0 / 5.0

# --- Broad-scope confidence downgrade (SP17 SRA Gate 3, 2026-04-22) ---

# Risks whose linkage resolves to more than this many activities have
# their Mapping confidence auto-downgraded to 'Low' to surface them for
# workshop tightening. Steve's in-session direction at Gate 2 pause:
# "accept broad linkages but auto-flag >N links as Low confidence" - the
# strawman uses 500 as the threshold (roughly 25% of the 1959 activities
# in the current reference P6 export).
BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD: int = 500

# --- Programme seasons (Run_Config_Preview, Brief Section 4.8) ---

# Option B will run with programme_seasons = 3 (three wet seasons over
# project life). This is the sign-off value recorded in the
# Run_Config_Preview sheet; it does NOT change the current cost MC.
OPTION_B_PROGRAMME_SEASONS: int = 3
