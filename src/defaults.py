"""
Centralised default values for the Monte Carlo simulation.

These defaults are used:
  - In headless mode (--no-excel) when no workbook is available
  - As fallbacks when named ranges or cells are missing from the workbook
  - As the single source of truth — no other module should hardcode these values

Values here should match the current cost-model workbook.
Update this file when the workbook structure changes.
"""

# --- Distribution types available ---
# Layer 1 (WBS buckets): Triangular, Lognormal (percentage variation), PERT
# Layer 2 (event risks): Triangular, PERT, Binary, Lognormal (absolute $)
# Lognormal for Layer 2 uses Opt/ML/Pess as P10/median/P90 anchors.
# Use for catastrophic tail risks (force majeure, pandemic, geopolitical).

# --- File paths ---
# DEFAULT_WORKBOOK_FILENAME (the legacy cost-MC model workbook) and
# DEFAULT_REGISTER_FILENAME are project-specific. Since QRAXL-01 generic
# decoupling (Coupling A/C) both live in the active binding — the register in
# DEFAULT_FILENAMES["register"], the workbook in headless_config["workbook_filename"]
# — and are resolved lazily via the module __getattr__ below, so legacy importers
# (`from src.defaults import DEFAULT_WORKBOOK_FILENAME`) keep working while the
# project literals live only in the binding (portability static guard). Under the
# no-defaults directive there is NO cross-project fallback: a project whose binding
# does not supply the value fails loud.
_GENERIC_REGISTER_FILENAME_FALLBACK = ""

# --- Event chain risk ID mapping ---
# The chain role->risk-id map is project-specific. Since Showcase-P2 WS2-B
# it lives in the active project binding's ``LEGACY_CHAIN_IDS``, not as bare
# risk-id literals
# in engine code (portability static guard). It is resolved lazily via the
# module ``__getattr__`` at the bottom of this file, so legacy importers
# (`from src.defaults import CHAIN_RISK_IDS`) keep working unchanged.
#
# A binding returns the chain map it declares; a project with none gets the
# all-None fallback below and the chain skips cleanly. The register's
# ``cfg_chain_risk_ids`` named-range surface (read via methodology_defaults_reader) is the
# authoritative production source; the binding's map is what the cost-engine and legacy paths
# read. **The equality gate between the two retired with the binding it compared**
# (REFRETIRE-01): a register that declares a chain under a binding that declares none now
# no-ops with nothing on screen. Raised as CHAINSYM-01, not fixed here.
_GENERIC_CHAIN_RISK_IDS_FALLBACK: dict = {
    "c1_trigger": None,
    "c1_target": None,
    "c2_trigger": None,
    "c2_targets": [],
}

# --- Chart insertion positions ---
# Maps chart name to (sheet_name, anchor_cell, width, height).
# Used by main.py for insert_chart() calls.
# Future: these positions should come from named ranges in the workbook
# (mc_chart_scurve, mc_chart_tornado, etc.) so row insertions don't break
# chart placement. For now, hardcoded positions that match the layout.
CHART_POSITIONS = {
    "s_curve": ("MC_Dashboard", "B24", 500, 360),
    "gain_pain": ("MC_Dashboard", "K24", 480, 300),
    "output_hist": ("MC_Dashboard", "B48", 480, 300),
    "convergence": ("MC_Dashboard", "K48", 440, 280),
    "tornado": ("MC_Dashboard", "B68", 580, 340),
    "input_dist": ("MC_Dashboard", "B88", 500, 480),
    "wbs_dist": ("MC_Dashboard", "K88", 500, 360),
}

# --- Gain/pain share defaults ---
# DEFAULT_GP_TOC moved to the active binding (headless_config["gp_toc"]) under
# QRAXL-01 Coupling C; resolved via __getattr__ below, fail-loud if unset.
DEFAULT_GP_SHARE_SPLIT = 0.5
DEFAULT_GP_MAX_REWARD_PCT = 0.05
DEFAULT_GP_MAX_RISK_PCT = 0.05

# --- Headless-mode fallbacks (QRAXL-01 Coupling C) ---
# HEADLESS_BUCKETS, HEADLESS_CG_COEFFICIENTS, WBS_CROSS_BUCKET_RHO and
# DEFAULT_PROGRAMME_SEASONS were one project's constants, used on the legacy
# cost-MC / --no-excel / report-fallback paths. Under the no-defaults directive
# they live in the active project's binding (headless_config) and are resolved
# via __getattr__ below (fail-loud if the selected binding does not supply them).
# The integrated client deliverable register-reads every one (SR19), so this is
# bit-neutral for the client numbers.


# --- Project-binding-sourced values (Showcase-P2 WS2-B) ---

def get_chain_risk_ids() -> dict:
    """Return the active project's event-chain role->risk-id map.

    Reads :attr:`ProjectBinding.legacy_chain_ids` from the active binding
    (``QRA_PROJECT``; no default), returning a fresh dict
    each call (callers historically mutated copies). ``c2_targets`` is
    materialised as a list to preserve the legacy shape. A project whose
    binding declares no legacy chain gets :data:`_GENERIC_CHAIN_RISK_IDS_FALLBACK`
    (all-None → the chain is a no-op).

    Imported lazily to avoid an import cycle (the binding imports the
    engine, the engine reads the binding only at call time).
    """
    from src.sra.cpm.bindings import get_active_binding

    ids = get_active_binding().legacy_chain_ids
    if not ids:
        return dict(_GENERIC_CHAIN_RISK_IDS_FALLBACK)
    return {
        k: (list(v) if isinstance(v, (list, tuple)) else v)
        for k, v in ids.items()
    }


def get_default_register_filename() -> str:
    """Return the active project's default register filename (basename).

    Reads ``DEFAULT_FILENAMES["register"]`` from the active binding. Imported
    lazily to avoid an import cycle. Empty string when the binding declares
    no register (a misconfigured/incomplete project).
    """
    from src.sra.cpm.bindings import get_active_binding

    return get_active_binding().default_filenames.get(
        "register", _GENERIC_REGISTER_FILENAME_FALLBACK
    )


# --- Headless-config values, sourced from the active binding (Coupling C) ---

def _headless_value(key: str):
    """Return ``headless_config[key]`` from the active project's binding.

    No cross-project fallback (no-defaults directive): raises if no project is
    selected (``get_active_binding`` → ``NoProjectSelectedError``), if the
    selected binding supplies no ``headless_config``, or if the key is absent.
    These values sit only on the legacy cost-MC / ``--no-excel`` / report-fallback
    paths; the integrated client path register-reads them (SR19), so this fail-loud
    resolution never touches the client bit-identity.
    """
    from src.sra.cpm.bindings import get_active_binding

    binding = get_active_binding()
    cfg = binding.headless_config
    if not cfg or key not in cfg:
        have = sorted(cfg) if cfg else []
        raise ValueError(
            f"Project {binding.name!r} does not supply headless_config[{key!r}] "
            f"(has: {have}). This is a headless/legacy-cost-MC value; under the "
            f"no-defaults directive there is no cross-project fallback. Add it to "
            f"the project's binding (src/sra/cpm/bindings/{binding.name}.py, "
            f"headless_config) or run the integrated path, which register-reads it."
        )
    return cfg[key]


def get_default_workbook_filename() -> str:
    """Legacy cost-MC model workbook filename, from the active binding."""
    return _headless_value("workbook_filename")


def get_default_gp_toc() -> float:
    """Gain/pain TOC fallback, from the active binding."""
    return _headless_value("gp_toc")


def get_headless_buckets() -> list:
    """Headless (--no-excel) WBS buckets, from the active binding (fresh list)."""
    return list(_headless_value("wbs_buckets"))


def get_headless_cg_coefficients() -> dict:
    """Headless CG correlation coefficients, from the active binding (fresh dict)."""
    return dict(_headless_value("cg_coefficients"))


def get_wbs_cross_bucket_rho() -> float:
    """Layer-1 cross-bucket correlation fallback, from the active binding."""
    return _headless_value("wbs_cross_bucket_rho")


def get_default_programme_seasons() -> int:
    """Programme seasonal-exposure-window fallback, from the active binding."""
    return _headless_value("programme_seasons")


# Maps the legacy module-attribute name → its binding-sourced resolver, so
# `from src.defaults import HEADLESS_BUCKETS` (etc.) keeps working while the
# Project literals live only in the binding.
_BINDING_SOURCED = {
    "CHAIN_RISK_IDS": get_chain_risk_ids,
    "DEFAULT_REGISTER_FILENAME": get_default_register_filename,
    "DEFAULT_WORKBOOK_FILENAME": get_default_workbook_filename,
    "DEFAULT_GP_TOC": get_default_gp_toc,
    "HEADLESS_BUCKETS": get_headless_buckets,
    "HEADLESS_CG_COEFFICIENTS": get_headless_cg_coefficients,
    "WBS_CROSS_BUCKET_RHO": get_wbs_cross_bucket_rho,
    "DEFAULT_PROGRAMME_SEASONS": get_default_programme_seasons,
}


def __getattr__(name: str):
    """Lazily resolve binding-sourced module attributes (PEP 562).

    Keeps `from src.defaults import CHAIN_RISK_IDS` / `DEFAULT_REGISTER_FILENAME`
    / `HEADLESS_BUCKETS` / ... working after the project-specific literals were
    evacuated to the active project binding (QRAXL-01 Coupling A/C). With no
    project selected, or a binding that does not supply the value, the resolver
    fails loud — never a cross-project fallback.
    """
    resolver = _BINDING_SOURCED.get(name)
    if resolver is not None:
        return resolver()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
