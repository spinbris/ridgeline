"""DAYRATE-01: the per-project run-config contract for the integrated engines.

Both integrated config loaders resolve their per-project run values from the
strawman's ``Run_Config_Preview`` sheet (or, under REG-01, the consolidated
register's ``MC_Params``). Before DAYRATE-01 each carried its own copy of::

    iterations = <literal>
    day_rate = <literal>
    reporting_p_level = <literal>
    if strawman_path.exists():
        try:
            cfg = read_run_config(strawman_path)
        except Exception:
            cfg = {}
        if cfg.get("day_rate_default"):
            day_rate = float(cfg["day_rate_default"])

That block had three defects, all of which produced a plausible wrong number
rather than a stop:

1. A strawman that existed but would not parse was swallowed to ``{}`` and the
   run proceeded on every literal, with nothing raised.
2. A strawman path that did not exist skipped the block entirely, same result.
3. ``if cfg.get("day_rate_default")`` is falsy at zero, so a deliberate zero
   was replaced by the literal - the one value a user cannot express.

This module is the single home for the contract both loaders now share, so the
two cannot drift apart again. It deliberately carries no day-rate literal of
its own: there is nothing here to fall back to.

REG-01 established the same contract for ``load_sra_config`` (see
``src/sra/sra_config.py:161``); this extends it to the integrated arms.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Callable, Mapping

from src.sra.methodology_defaults_reader import MethodologyDefaultsError

logger = logging.getLogger(__name__)

__all__ = [
    "DAY_RATE_KEY",
    "DAY_RATE_SOURCE",
    "PROGRAMME_DAYS_KEY",
    "PROGRAMME_DAYS_SOURCE",
    "RunConfigError",
    "day_rate_audit_fields",
    "read_run_config_strict",
    "require_day_rate",
    "resolve_day_rate",
    "resolve_programme_days",
    "resolve_run_setting",
    "SOURCE_BINDING",
    "SOURCE_OVERRIDE",
    "SOURCE_REGISTER",
]

#: The key ``read_run_config`` returns the day rate under.
DAY_RATE_KEY = "day_rate_default"

#: Where the day rate is expected to come from, quoted verbatim in every
#: refusal so the operator is told what to populate, not merely that something
#: is missing. Matches the day-rate rule ("change the strawman, not the
#: code") and the REG-01 consolidated-register layout.
DAY_RATE_SOURCE = (
    "Run_Config_Preview.Day_rate_default (or the MC_Params day_rate cell "
    "under REG-01)"
)

#: The key ``read_run_config`` returns the programme duration under. DAYRATE-02
#: (Part 3, F-9): the Stage 2.5 loader derived programme_days from this and both
#: Stage 3 builders never consulted it, which is the same strawman-blindness as
#: the day rate one level down. The derivation lives here so all three arms
#: share it.
PROGRAMME_DAYS_KEY = "schedule_duration_weeks"

#: Where the programme duration is expected to come from.
PROGRAMME_DAYS_SOURCE = "Run_Config_Preview.Schedule_duration_weeks"


class RunConfigError(ValueError):
    """A per-project run-config value could not be sourced from the workbook.

    Subclasses ``ValueError`` so callers that already catch the loaders'
    missing-path ``ValueError`` keep working.
    """


def read_run_config_strict(
    strawman_path: Path,
    reader: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Read the run config, raising rather than swallowing a failure.

    ``reader`` is injected rather than imported so the two loaders keep using
    the reader they already use (the Stage 2.5 arm imports ``read_run_config``
    directly; the Stage 3 arm goes through the ``strawman_reader`` module).
    """
    if not strawman_path.exists():
        raise RunConfigError(
            f"run config cannot be read: no workbook at '{strawman_path}'. "
            f"The per-project run values ({DAY_RATE_SOURCE}, iterations, "
            "reporting P-level) are sourced from that workbook and have no "
            "code-level substitute. Point --strawman / STRAWMAN_FILE at the "
            "project's strawman and re-run."
        )
    try:
        return reader(strawman_path)
    except Exception as exc:
        raise RunConfigError(
            f"run config at '{strawman_path}' exists but could not be read: "
            f"{type(exc).__name__}: {exc}. Substituting code-level defaults "
            "for a workbook that failed to parse is how a plausible wrong "
            "number reaches a deliverable, so this stops the run. Repair the "
            "workbook (or close it in Excel, which makes openpyxl return "
            "cached-formula None values) and re-run."
        ) from exc


def resolve_day_rate(cfg: Mapping[str, Any], strawman_path: Path) -> float:
    """Return the day rate from ``cfg``, or raise naming the missing input.

    An explicit zero is permitted and warned about. A zero day rate is a
    legitimate cost-only run, and refusing it would push users to fake it with
    a near-zero value, which is worse. It removes all time-related cost and is
    indistinguishable in the output from a correct run.

    On the integrated arms a zero also gets an in-memory stamp - see
    :func:`day_rate_audit_fields`, called from
    ``integrated_simulation_stage3``. **The warning does not mention it**
    (DAYRATE-02 F-16): this function is shared with ``load_sra_config``, which
    builds no ``config_summary``, so a warning promising a stamp would be
    telling the operator about a record that arm does not write. The durable
    record of the rate on either arm is the run's ``metadata.json``, which
    carries ``day_rate`` at three paths.
    """
    raw = cfg.get(DAY_RATE_KEY)

    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise RunConfigError(
            f"{DAY_RATE_KEY} is absent or blank in '{strawman_path}'. It is "
            f"sourced from {DAY_RATE_SOURCE}. There is no code-level day rate "
            "to fall back to: one project's commercial rate must never stand "
            "in for another's. Populate the cell and re-run."
        )

    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RunConfigError(
            f"{DAY_RATE_KEY} in '{strawman_path}' is not numeric ({raw!r}). "
            f"It is sourced from {DAY_RATE_SOURCE}. Populate the cell with a "
            "number and re-run."
        ) from exc

    if not math.isfinite(value):
        raise RunConfigError(
            f"{DAY_RATE_KEY} in '{strawman_path}' is not finite ({raw!r}). "
            f"It is sourced from {DAY_RATE_SOURCE}."
        )

    if value == 0.0:
        logger.warning(
            "day rate is explicitly ZERO (from %s in '%s'). Every "
            "time-related cost in this run is therefore zero, and the output "
            "is indistinguishable from a correct run. If that is not "
            "intended, populate the cell and re-run.",
            DAY_RATE_SOURCE, strawman_path,
        )

    return value


def require_day_rate(value: float | None, *, caller: str) -> float:
    """Return the day rate, or raise because nothing sourced one.

    Director ruling, 31/08/2026: ``IntegratedConfig.day_rate`` defaults to
    ``None`` and a run that reaches a rate-consuming calculation without one
    stops here. The reasoning is the general form of everything DAYRATE-01 and
    -02 found:

        every hardcoded number is wrong, because it belongs to some other
        project.

    That applies to a literal in engine code, and it applies just as much to a
    literal relocated into a project binding - a binding constant is still a
    number that can go stale against the workbook it was copied from, and it
    still supplies a plausible value rather than stopping. So there is no
    default at all. The rate is sourced from the workbook per run, or the run
    refuses to produce a number.

    ``caller`` names the calculation that needed it, because by the time this
    fires the config was built somewhere else entirely and the traceback alone
    does not say which arm is unconfigured.
    """
    if value is None:
        raise RunConfigError(
            f"{caller} needs a day rate and the config carries none. It is "
            f"sourced from {DAY_RATE_SOURCE}, per run and per project. There "
            "is no code-level default and deliberately so: a hardcoded rate - "
            "in engine code or in a project binding - belongs to whichever "
            "project it was copied from, so on any other project it is simply "
            "wrong, and it is wrong silently. Pass day_rate on the config "
            "(the loaders resolve it for you) and re-run."
        )
    return float(value)


def resolve_programme_days(cfg: Mapping[str, Any]) -> int:
    """Return programme working days derived from the strawman, or 0 if absent.

    SP18b derivation: ``schedule_duration_weeks * 5``. Unlike the day rate this
    does **not** raise when absent, and the asymmetry is deliberate. A missing
    day rate makes the headline wrong; a missing programme duration returns 0,
    which :func:`src.per_day_curve.compute_per_day_curve` treats as an explicit
    "disable the curve" and says so in its ``reason``. There is no plausible
    wrong number to produce, so refusing the run would cost more than it buys.

    Lifted out of ``load_integrated_config`` verbatim by DAYRATE-02 so the two
    Stage 3 builders derive it the same way rather than leaving it at 0.
    """
    weeks = cfg.get(PROGRAMME_DAYS_KEY)
    if not weeks:
        return 0
    return int(round(float(weeks) * 5.0))


def day_rate_audit_fields(day_rate: float) -> dict[str, Any]:
    """Audit-trail fields recording an explicit zero, empty for any real rate.

    Returned empty for every non-zero rate so no existing run artefact gains a
    key - DAYRATE-01's acceptance criterion is that nothing moves. The stamp
    appears exactly in the runs that need it.

    The stamp is unambiguous only because of the contract above: since a
    failed or absent read now raises, a zero reaching this point can only be a
    zero a user typed.
    """
    if float(day_rate) == 0.0:
        return {"day_rate_explicit_zero": True}
    return {}


#: Where a run setting's value came from, as the manifest records it (CONFIGTRUTH-01).
SOURCE_REGISTER = "register"
SOURCE_BINDING = "binding default"
SOURCE_OVERRIDE = "override"

#: The row each setting is read from, by the sheet ``read_run_config`` read, quoted in refusals.
_RUN_SETTING_ROWS: dict[str, dict[str, str]] = {
    "iterations": {"MC_Params": "Iterations (n)", "Run_Config_Preview": "Iterations"},
    "p_level_reporting": {"MC_Params": "Reporting P-Level (pct)",
                          "Run_Config_Preview": "P-Level_reporting"},
}
_BINDING_FIELDS = {"iterations": "default_iterations", "p_level_reporting": "default_reporting_p_level"}


def resolve_run_setting(
    cfg: Mapping[str, Any],
    key: str,
    *,
    strawman_path: Path,
    project: str | None = None,
    override: int | None = None,
    caller_module: str = "unspecified",
) -> tuple[int, str]:
    """The iteration count or reporting P-level a run uses, and where it came from.

    CONFIGTRUTH-01, as the Director ruled it on 08/10/2026: an override wins (iterations only);
    then the register's row; then, **only when the row is absent**, the project's binding's
    declared default. A row that is present but blank, a zero or a negative is refused from
    every source, never replaced: a zero is a mistake, not an absence. A missing row that the
    binding does not cover is refused naming the row, the sheet and the binding. Returns
    ``(value, source)``, ``source`` one of ``SOURCE_*``, which the manifest records so a
    defaulted value never passes for a chosen one.

    The binding is consulted lazily, so a register that carries both rows needs no project
    selection here at all.
    """
    sheet = cfg.get("run_config_sheet", "the run-config sheet")
    row = _RUN_SETTING_ROWS[key].get(sheet, key)
    where = f"{sheet} row {row!r} in '{strawman_path}'"

    def _positive(raw: Any, said_where: str) -> int:
        # A whole number, refused by name otherwise: int() alone raised unnamed on "abc" and
        # silently turned 2.5 into 2. Excel stores 50000 as 50000.0 at times, so an integral
        # float is accepted; a bool is not a count.
        value = None
        if isinstance(raw, int) and not isinstance(raw, bool):
            value = raw
        elif isinstance(raw, float) and math.isfinite(raw) and raw.is_integer():
            value = int(raw)
        elif isinstance(raw, str):
            try:
                value = int(raw.strip())
            except ValueError:
                value = None
        if value is None:
            raise MethodologyDefaultsError(
                f"consumer={caller_module}: {said_where} holds {raw!r}, which is not a whole number."
            )
        if value <= 0:
            word = "zero" if value == 0 else f"negative ({value})"
            raise MethodologyDefaultsError(
                f"consumer={caller_module}: {said_where} is {word}; it must be positive. A zero is "
                f"never read as 'not set'."
            )
        return value

    if override is not None:
        return _positive(override, f"the {key} override"), SOURCE_OVERRIDE

    if key in cfg:
        if cfg[key] is None:
            raise MethodologyDefaultsError(
                f"consumer={caller_module}: {where} is blank. Fill it; a blank row is not "
                f"replaced by the binding's default, which covers only a row that is absent."
            )
        return _positive(cfg[key], where), SOURCE_REGISTER

    field = _BINDING_FIELDS[key]
    from src.sra.cpm.bindings import get_active_binding, get_binding

    try:
        binding = get_binding(project) if project else get_active_binding()
    except Exception as exc:  # noqa: BLE001 - reported by name, not swallowed
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: {where} is absent, and no project binding could be "
            f"resolved to supply {field}: {type(exc).__name__}: {exc}"
        ) from exc
    declared = getattr(binding, field, None)
    if declared is None:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: {where} is absent, and project {binding.name!r}'s binding "
            f"declares none ({field}). The engine has no default: add the row to the register, "
            f"or declare {field} in the binding."
        )
    return _positive(declared, f"project {binding.name!r}'s {field}"), SOURCE_BINDING
