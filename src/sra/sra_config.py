"""SRA configuration loader and methodology constants.

The SRAConfig dataclass carries paths and runtime parameters; load_sra_config
resolves the final values from CLI overrides, environment variables, the
strawman's Run_Config_Preview sheet, and hardcoded fallbacks (in that order
of priority).

The Mode multiplier grid is a register value (RS-D-3, D-15): read by
`methodology_defaults_reader.read_mode_multipliers`, carried on `SRAConfig`, never a constant here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.integrated.run_config_contract import (
    read_run_config_strict,
    resolve_day_rate,
)
from src.sra.methodology_defaults_reader import read_mode_multipliers
from src.sra.strawman_reader import read_run_config


# ----------------------------------------------------------------------------
# Methodology values live in the register (RS-D-3, D-15). The Mode multiplier
# grid is read by src.sra.methodology_defaults_reader.read_mode_multipliers and
# carried on SRAConfig.mode_multipliers, a required field. There is no grid here.
# ----------------------------------------------------------------------------


# Mode applied when no strawman value or override is available for a risk.
# Conservative default: zero schedule contribution, matching the cost-only
# treatment of risks not flagged Time_Impact=Yes.
DEFAULT_FALLBACK_MODE: str = "Parallel"


# ----------------------------------------------------------------------------
# Config dataclass
# ----------------------------------------------------------------------------

@dataclass
class SRAConfig:
    # DAYRATE-02 A-ii: day_rate is REQUIRED and carries no definitional
    # default. It sat before random_seed's defaulted fields as
    # ``day_rate: float = <a module constant>``, and 24 of the 31 construction
    # sites - the shipped notebook among them - simply omitted it and took
    # that value while every other field came from the workbook. Nothing
    # enforced the agreement and nothing tested it; the two arms of the
    # deliverable matched only because the strawman's rate and the literal
    # happened to coincide. A required field makes the omission a TypeError
    # at construction instead of a silent divergence the day the strawman
    # is edited, which is exactly what the day-rate rule tells an
    # operator to do.
    register_path: Path
    p6_path: Path
    strawman_path: Path
    day_rate: float
    # RS-D-3b (D-15, shape A): the register's grid, required, no default.
    mode_multipliers: dict[str, float]
    iterations: int = 100000
    seasons: int = 1
    p_levels: tuple[int, ...] = (50, 80, 90, 95, 99)
    random_seed: int | None = None
    cp_hybrid_float_threshold: int = 20
    reporting_p_level: int = 80

    def __post_init__(self) -> None:
        if not self.mode_multipliers:
            raise ValueError(
                "mode_multipliers must be the register's non-empty Mode multiplier grid (RS-D-3, D-15)"
            )


# ----------------------------------------------------------------------------
# Loader
# ----------------------------------------------------------------------------

_ENV_REGISTER = "REGISTER_FILE"
_ENV_P6 = "P6_FILE"
_ENV_STRAWMAN = "STRAWMAN_FILE"


def _resolve_path(
    cli_override: str | None,
    env_var: str,
    fallback: str | None = None,
) -> Path | None:
    """CLI > env var > fallback. Returns None if all missing."""
    if cli_override:
        return Path(cli_override)
    env_val = os.environ.get(env_var)
    if env_val:
        return Path(env_val)
    if fallback:
        return Path(fallback)
    return None


def load_sra_config(
    register_override: str | None = None,
    p6_override: str | None = None,
    strawman_override: str | None = None,
    seed_override: int | None = None,
) -> SRAConfig:
    """Resolve the SRAConfig from CLI args, env vars, and the strawman.

    Paths resolve CLI override > env var. Run values come from the strawman's
    Run_Config_Preview and nowhere else - DAYRATE-02 removed the "or the
    hardcoded field default" tail of that chain, because a value that silently
    substitutes itself when the workbook cannot be read is the whole defect.

    Path env vars consulted: REGISTER_FILE, P6_FILE, STRAWMAN_FILE.

    Raises
    ------
    ValueError
        If any of the three required paths cannot be resolved.
    RunConfigError
        If the strawman is absent or will not parse, or if the day rate is
        absent, blank, non-numeric or non-finite. An explicit zero is
        permitted and warned about.
    """
    register_path = _resolve_path(register_override, _ENV_REGISTER)
    p6_path = _resolve_path(p6_override, _ENV_P6)
    strawman_path = _resolve_path(strawman_override, _ENV_STRAWMAN)

    missing = []
    if register_path is None:
        missing.append("register_path (CLI --register or env REGISTER_FILE)")
    if p6_path is None:
        missing.append("p6_path (CLI --p6 or env P6_FILE)")
    if strawman_path is None:
        missing.append("strawman_path (CLI --strawman or env STRAWMAN_FILE)")
    if missing:
        raise ValueError(f"SRA config missing required paths: {', '.join(missing)}")

    iterations: int = 100000
    seasons: int = 1
    cp_hybrid_float_threshold: int = 20
    reporting_p_level: int = 80

    # DAYRATE-02: the third and last site of the DAYRATE-01 defect. This block
    # kept the `except Exception: cfg = {}` swallow that DAYRATE-01 removed
    # from the two integrated loaders, and the same contract module drops in.
    # day_rate was already guarded here by REG-01 (it started as None and the
    # check below raised), but iterations, seasons, cp_hybrid_float_threshold
    # and reporting_p_level were not: a strawman that existed and would not
    # parse was swallowed to {} and all four silently took their literals.
    #
    # It also fixes DAYRATE-01 review Finding 5. `if cfg.get("day_rate_default")`
    # is falsy at zero, so an operator entering a deliberate zero - a legitimate
    # cost-only run, and permitted by the Director's ruling - left day_rate at
    # None and got a refusal saying the rate "could not be read", which was
    # both wrong and misleading. resolve_day_rate distinguishes absent from
    # zero, permits the zero and warns about it. That refusal also formatted
    # the old module constant into its own message, printing the client's rate to the
    # console on every failure; the contract's refusals name the input instead.
    cfg = read_run_config_strict(strawman_path, read_run_config)
    day_rate = resolve_day_rate(cfg, strawman_path)
    if cfg.get("iterations"):
        iterations = int(cfg["iterations"])
    if cfg.get("programme_seasons"):
        seasons = int(cfg["programme_seasons"])
    if cfg.get("cp_hybrid_float_threshold_days"):
        cp_hybrid_float_threshold = int(cfg["cp_hybrid_float_threshold_days"])
    if cfg.get("p_level_reporting"):
        reporting_p_level = int(cfg["p_level_reporting"])

    return SRAConfig(
        register_path=register_path,
        mode_multipliers=read_mode_multipliers(
            register_path, caller_module="src/sra/sra_config.py"),
        p6_path=p6_path,
        strawman_path=strawman_path,
        iterations=iterations,
        seasons=seasons,
        random_seed=seed_override,
        day_rate=day_rate,
        cp_hybrid_float_threshold=cp_hybrid_float_threshold,
        reporting_p_level=reporting_p_level,
    )
