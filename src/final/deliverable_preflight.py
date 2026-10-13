"""One pre-flight for the deliverable: every missing setting in a single message.

3c Part A A-1, Director 04/09/2026 ("add the single pre-flight"). The deliverable needs a
handful of things before it computes anything: three input paths, and a set of methodology
settings that live in the register. Each of those already refuses loudly on its own - the path
resolvers raise on an unset variable, and each register reader raises naming the range or grid
row it wanted (RS-D). Four separate refusals means four round trips: fix the day rate, re-run,
learn about the tolerances, re-run.

This module keeps the same refusal posture and collects it. Every check runs, every failure is
gathered, and one message names all of them at once with the sheet row or named range to add.
Nothing here supplies a default for anything it cannot find - a missing setting is still a
refusal, by ruling (RS-D-2/3/6, D-14/15/18).

Ordering is honest about dependency: when the paths are unset or the workbook is absent, the
register checks cannot run at all, and the message says so rather than reporting twenty
settings as "missing" when the truth is that nothing could be opened.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

#: The three input paths §6a names, and the environment variable each is read from. The
#: deliverable takes them from the environment explicitly; there is no default project and no
#: literal path in any entry point (SPEC §6c).
REQUIRED_PATHS: tuple[tuple[str, str], ...] = (
    ("register", "REGISTER_FILE"),
    ("p6", "P6_FILE"),
    ("strawman", "STRAWMAN_FILE"),
)

#: The binding selector. No default: an unset value is a refusal, not a fallback (QRAXL-01).
PROJECT_ENV = "QRA_PROJECT"

#: The working tree this code runs from. An input outside it is legitimate - a client register
#: can live anywhere - but it is said out loud: leg 1 ran a clone against a schedule from the MAIN
#: checkout, and an existence check alone passed it silently (FW-16).
WORKING_TREE = Path(__file__).resolve().parents[2]


def where_it_is(path: Path) -> str:
    """The input's resolved absolute path, with a note when it lies outside this working tree."""
    resolved = path.resolve()
    try:
        resolved.relative_to(WORKING_TREE)
    except ValueError:
        return (f"resolved: {resolved}\n           NOTE: outside this working tree "
                f"({WORKING_TREE}) - check it is the file you meant")
    return f"resolved: {resolved}"


class DeliverablePreflightError(RuntimeError):
    """Every unmet preconditon for one deliverable run, in one message."""


@dataclass(frozen=True)
class CheckResult:
    """One precondition, and what was found."""

    label: str
    #: Where an operator fixes it: an environment variable, a sheet row, or a named range.
    where: str
    ok: bool
    detail: str

    def line(self) -> str:
        mark = "OK  " if self.ok else "MISSING"
        return f"  [{mark}] {self.label} - {self.where}\n           {self.detail}"


def _check(label: str, where: str, read: Callable[[], Any]) -> CheckResult:
    """Run one reader, converting its refusal into a row instead of a stack trace."""
    try:
        value = read()
    except Exception as exc:  # noqa: BLE001 - every reader's refusal is a row, not a halt
        return CheckResult(label, where, False, f"{type(exc).__name__}: {exc}")
    return CheckResult(label, where, True, f"resolved: {value!r}")


def check_paths(env: dict[str, str] | None = None) -> list[CheckResult]:
    """The binding selection and the three input paths: set, and present on disk."""
    env = dict(os.environ if env is None else env)
    results: list[CheckResult] = []

    project = env.get(PROJECT_ENV, "").strip()
    results.append(CheckResult(
        "project binding", f"env {PROJECT_ENV}", bool(project),
        f"selected: {project!r}" if project
        else "unset - the deliverable has no default project; set it to the binding's name",
    ))

    for label, var in REQUIRED_PATHS:
        raw = env.get(var, "").strip()
        if not raw:
            results.append(CheckResult(
                f"{label} path", f"env {var}", False,
                "unset - the deliverable resolves every path from the environment, never "
                "from a literal in an entry point (SPEC 6c)",
            ))
            continue
        path = Path(raw)
        if not path.exists():
            results.append(CheckResult(
                f"{label} path", f"env {var}", False, f"set to {raw!r}, but no such file",
            ))
            continue
        lock = path.parent / f"~${path.name}"
        if lock.exists():
            results.append(CheckResult(
                f"{label} path", f"env {var}", False,
                f"{path.name} is open in Excel ({lock.name}); a stale cached value would "
                f"otherwise propagate silently. Close it and re-run",
            ))
            continue
        results.append(CheckResult(f"{label} path", f"env {var}", True, where_it_is(path)))

    return results


def check_register_settings(
    register_path: Path | str,
    strawman_path: Path | str,
    *,
    project: str | None = None,
    iterations_override: str | None = None,
    caller_module: str = "src/final/deliverable_preflight.py",
) -> list[CheckResult]:
    """Every methodology setting the run reads, each reported by name.

    ``project`` names the binding a missing iterations or P-level row resolves from, and
    ``iterations_override`` is the raw ``SR9_ITERATIONS``: when set, the register's count is not
    the run's and is not checked (CONFIGTRUTH-01).

    Works for both register shapes: each reader named here prefers the grid-native
    ``Methodology`` sheet and falls back to the legacy named ranges, so the "where to fix it"
    text names both.
    """
    from src.integrated.run_config_contract import (
        read_run_config_strict,
        resolve_day_rate,
        resolve_programme_days,
        resolve_run_setting,
    )
    from src.sra import strawman_reader
    from src.sra.methodology_defaults_reader import (
        read_calibration_tolerances,
        read_cg_coefficients,
        read_default_injection_method,
        read_mode_multipliers,
    )

    register_path = Path(register_path)
    strawman_path = Path(strawman_path)

    results = [
        _check(
            "Mode multiplier grid",
            "register Methodology sheet rows Series/Hybrid/Parallel, or named ranges meth_mode_mult_*",
            lambda: read_mode_multipliers(register_path, caller_module=caller_module),
        ),
        _check(
            "CG correlation coefficients",
            "register Methodology sheet rows CG01..CG13, or named range mc_cg_coeffs",
            lambda: read_cg_coefficients(register_path, caller_module=caller_module),
        ),
        _check(
            "five calibration tolerances",
            "register Methodology sheet rows Cost_Calibration_Tolerance_Dollars / _Pct, "
            "Schedule_Calibration_Tolerance_Days / _Pct and Schedule_Top3_Tie_Tolerance_Pct, "
            "or named ranges meth_cal_tol_* and meth_top3_tie_tol_pct",
            lambda: read_calibration_tolerances(register_path, caller_module=caller_module),
        ),
        _check(
            "default injection method",
            "register Methodology sheet row Default_Injection_Method, or named range "
            "meth_default_injection_method",
            lambda: read_default_injection_method(register_path, caller_module=caller_module),
        ),
    ]

    # The run-config block is one read, but three values the run cannot proceed without, so
    # each is reported separately - "the run config failed" does not tell an operator which
    # cell to open.
    try:
        run_cfg = read_run_config_strict(strawman_path, strawman_reader.read_run_config)
    except Exception as exc:  # noqa: BLE001
        results.append(CheckResult(
            "run configuration block", "register MC_Params sheet (or strawman Run_Config_Preview)",
            False, f"{type(exc).__name__}: {exc}",
        ))
        return results

    results.append(_check(
        "day rate", "register MC_Params row 'day_rate ($/wd)' (or strawman Day_rate_default)",
        lambda: resolve_day_rate(run_cfg, strawman_path),
    ))
    results.append(_check(
        "programme days", "register MC_Params row 'schedule duration (weeks)'",
        lambda: resolve_programme_days(run_cfg),
    ))
    # CONFIGTRUTH-01: presence, not truth. Absent, blank, zero and negative are each reported
    # as what they are, a missing row the binding supplies passes saying so, and an
    # SR9_ITERATIONS override replaces the register's count rather than being checked beside it.
    for label, key in (("iterations", "iterations"), ("reporting P-level", "p_level_reporting")):
        where = f"register {run_cfg.get('run_config_sheet', 'MC_Params')} row for {label}"
        if key == "iterations" and (iterations_override or "").strip():
            try:
                value = iteration_override({"SR9_ITERATIONS": iterations_override})
            except DeliverablePreflightError as exc:
                results.append(CheckResult(label, "env SR9_ITERATIONS", False, str(exc)))
            else:
                results.append(CheckResult(
                    label, "env SR9_ITERATIONS", True,
                    f"resolved: {value!r} (override, SR9_ITERATIONS); the register's count is not used"))
            continue
        try:
            value, source = resolve_run_setting(
                run_cfg, key, strawman_path=strawman_path, project=project,
                caller_module=caller_module)
        except Exception as exc:  # noqa: BLE001 - a failure is a row in the report, not a halt
            results.append(CheckResult(label, where, False, str(exc)))
        else:
            results.append(CheckResult(label, where, True, f"resolved: {value!r} ({source})"))

    return results


def iteration_override(env: dict[str, str]) -> int | None:
    """``SR9_ITERATIONS`` as a positive count, ``None`` for "the register's", or a refusal.

    CONFIGTRUTH-01 P4: testing the string's truthiness let ``"0"`` through as an iteration count
    of 0, and a non-numeric value surfaced as a bare ``ValueError`` naming nothing.
    """
    raw = (env.get("SR9_ITERATIONS") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or value <= 0:
        raise DeliverablePreflightError(
            f"SR9_ITERATIONS={raw!r} is not a positive whole number of iterations. Set it to one, "
            f"or unset it to run at the register's own count."
        )
    return value


#: Where the deliverable's seed came from, as the manifest records it (CONFIGTRUTH-01).
SEED_SOURCE_OVERRIDE = "override"
SEED_SOURCE_DRAWN = "drawn"

#: A drawn seed's range: positive, and inside every arm's seed range (the Stage 3 streams take one
#: 32-bit word; the legacy cost MC reads 0 as "random", so 0 is excluded).
_DRAWN_SEED_MAX = 2**31 - 1


def seed_override(env: dict[str, str]) -> tuple[int, str]:
    """The deliverable's seed and where it came from: ``SR9_SEED``, or one drawn now.

    The Director's ruling, 08/10/2026: unset, blank or ``0`` is random. The seed is drawn ONCE
    here, before any engine is called, and that one value goes to every arm - the standalone cost
    MC reads 0 as "fresh random" while Stage 3 and the SRA arm read it as a fixed seed, so passing
    0 through made a run whose headline reproduced and whose cost-MC reference did not. The drawn
    value is recorded in the manifest, so the run is reproducible by giving it back. A positive
    whole number is used as given; negative, non-numeric or too large is refused by name.
    """
    import secrets

    raw = (env.get("SR9_SEED") or "").strip()
    try:
        value = int(raw) if raw else 0
    except ValueError:
        value = None
    if value is None or not 0 <= value < 2**32:
        raise DeliverablePreflightError(
            f"SR9_SEED={raw!r} is not a whole number from 1 to {2**32 - 1}. Set one for a "
            f"repeatable run, or leave it unset (or 0) for a random one, drawn and recorded."
        )
    if value == 0:
        return secrets.randbelow(_DRAWN_SEED_MAX) + 1, SEED_SOURCE_DRAWN
    return value, SEED_SOURCE_OVERRIDE


def run_preflight(env: dict[str, str] | None = None) -> list[CheckResult]:
    """Every precondition for one deliverable run. Reports; does not raise."""
    path_results = check_paths(env)
    if not all(r.ok for r in path_results):
        return path_results

    env = dict(os.environ if env is None else env)
    return path_results + check_register_settings(
        env["REGISTER_FILE"].strip(), env["STRAWMAN_FILE"].strip(),
        project=env.get(PROJECT_ENV, "").strip() or None,
        iterations_override=env.get("SR9_ITERATIONS"),
    )


def assert_ready(env: dict[str, str] | None = None) -> list[CheckResult]:
    """Run the pre-flight and refuse, once, naming everything that is missing.

    Returns the full result list on success so a caller can render it as the run's first
    evidence rather than re-reading the register to find out what it used.
    """
    results = run_preflight(env)
    failures = [r for r in results if not r.ok]
    if not failures:
        return results

    reached_register = any(r.where.startswith("register") for r in results)
    body = "\n".join(r.line() for r in results)
    tail = (
        "" if reached_register else
        "\n\nThe register settings were NOT checked: nothing could be opened until the paths "
        "above are set. Expect a second pre-flight message once they are."
    )
    raise DeliverablePreflightError(
        f"the deliverable cannot start: {len(failures)} unmet precondition(s).\n"
        f"Every check is listed so this is one round trip, not one per missing setting.\n\n"
        f"{body}{tail}"
    )


def _cli(argv: list[str] | None = None) -> int:
    """``python -m src.final.deliverable_preflight --paths``: every input, resolved, before a run.

    ``RUN_FINAL.bat`` calls this ahead of nbconvert, so the analyst sees which files the run will
    read while they can still act - the client report is no place for local paths. Paths only:
    the register settings are checked once, by the run itself.
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paths", action="store_true", required=True,
                        help="check and print the input paths")
    parser.parse_args(argv)
    results = check_paths()
    print("Inputs:")
    for r in results:
        print(r.line())
    return 0 if all(r.ok for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(_cli())
