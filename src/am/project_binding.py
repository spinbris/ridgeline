"""Project resolution for the AM monthly cycle (showcase-P4 WS4-B).

Makes the AM consumer project-aware via the engine's binding registry in this
repository. There is no default project (QRAXL-01): ``synthetic_wind`` and
``synthetic_road`` route the cycle to their committed fixtures, and an unregistered
name is refused by the registry.

Why this module exists instead of "just call get_active_binding()":
the registry ``ProjectBinding`` is data-only (filenames, labels, risk-id
prefix), and driver CONSTRUCTION is behaviour. Every project's drivers are
now built one way - ``expand_auto_rules`` over the strawman's Time=Yes rows,
through the same rule builder the deliverable and the showcases use
(GENERICDRV-01, closed by REFRETIRE-01). Until then one project took a
separate pattern-catalogue builder of its own, selected by name.

The active project is selected by the ``project`` argument or the ``QRA_PROJECT``
env var - no default; absent selection raises (QRAXL-01) - and is activated
(the wind fixture binding is loaded by file path, then the env var set) so
``read_risks_v5`` / ``strawman_reader`` resolve the right ``risk_id_prefix``.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


from src.integrated.stage3_config import build_stage3_rules_from_scope  # noqa: E402
from src.sra.cpm.auto_mapper import expand_auto_rules  # noqa: E402
from src.sra.cpm.bindings import (  # noqa: E402
    ACTIVE_PROJECT_ENV_VAR,
    get_active_binding,
    get_binding,
    project_display_name,
)
from src.integrated.stage3_inputs import (  # noqa: E402
    Stage3BindingConfig,
    resolve_float_threshold_hours,
)
from src.sra.cpm.risk_driver_schema import RiskDriver  # noqa: E402
from src.sra import strawman_reader  # noqa: E402


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths (mirror the AM02/AM03 baseline for the engagement; the P3 fixtures for wind)
# ---------------------------------------------------------------------------

AM_REPO_ROOT = Path(__file__).resolve().parents[2]  # this repository; the engine lives here

# Project binding names. Sourced locally rather than from the engine: QRAXL-01
# removed the engine's DEFAULT_PROJECT because it silently fell back to a
# binding for any caller that failed to declare a project. These name
# what they are, not what anything falls back to.
from src.sra.cpm.bindings.synthetic_wind import SYNTHETIC_WIND_BINDING  # noqa: E402
WIND_PROJECT = SYNTHETIC_WIND_BINDING.name

# Synthetic-wind: the committed P3 fixtures under the engine. The binding's
# default_filenames carry the basenames; this is the directory they resolve
# against (the wind binding self-registers from wind_binding.py here).
WIND_FIXTURE_DIR = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind"
WIND_BINDING_MODULE = WIND_FIXTURE_DIR / "wind_binding.py"

# Wind Stage-3 auto-mapper parameters. Sourced from the P3 wind substrate
# (the engine scripts/run_wind_showcase.py:_strawman_stage3_rules and
# tests/test_synthetic_wind.py) so the P4 wind AM cycle's drivers stay
# coherent with the P3 wind upfront analysis. Named constants, not inline
# magic numbers.
#: ROAD-01 §5.3: retired. These were named for wind and applied to every other project,
#: so a third project silently inherited wind's schedule-binding parameters - and a wrong float
#: threshold changes which activities bind, which moves the schedule arm. The threshold is now
#: declared by each project's own binding (`ProjectBinding.float_threshold_hours`). The injection method went the same way on 10/09/2026 and
#: was retired again under GENERICINJ-01: it is the register's to declare, not the binding's,
#: and a binding value nothing reads is a parameter waiting to be believed."


# ---------------------------------------------------------------------------
# Resolved per-project inputs
# ---------------------------------------------------------------------------

# The JSON surface's register label and the methodology note's project label are both the
# project's public display name (PUBLICFACE-01): a binding key or code name is not something a
# reader of the app should meet, and one declaration serves the deliverable and the app.
# The project's public display name for the dashboard chrome (showcase-P5 WS5-C) is emitted into
# meta.project_display_name so the dashboard reads it from data. RIDGELINE-01 moved it from a map
# here into the binding (`project_display_name`), the one declaration the deliverable reads too.


@dataclass(frozen=True)
class ProjectInputs:
    """The resolved inputs the AM cycle needs for the active project."""
    project: str
    register_path: Path
    xer_path: Path
    strawman_path: Path
    risk_id_prefix: str
    register_version: str
    methodology_label: str
    display_name: str


# ---------------------------------------------------------------------------
# Activation + resolution
# ---------------------------------------------------------------------------

def activate_project(project: str | None = None) -> str:
    """Resolve and activate the AM project; return the resolved name.

    Sets ``QRA_PROJECT`` explicitly for the requested project so the
    register / strawman readers resolve the right ``risk_id_prefix`` and so
    a project set by a prior run in the same process cannot leak in.
    Idempotent and cheap to call repeatedly.
    """
    name = project or os.environ.get(ACTIVE_PROJECT_ENV_VAR)
    if not name:
        raise ValueError(
            f"No AM project selected: pass project= or set {ACTIVE_PROJECT_ENV_VAR}. "
            "There is no default (QRAXL-01)."
        )
    # GENERIC-01: no allowlist. `get_binding` resolves any project with a registered or
    # auto-importable binding, and refuses an unknown one by naming what IS registered - the same
    # diagnosis the allowlist gave, from the component that actually knows the answer. The
    # two-name check that stood here duplicated this very call and added only the restriction: a
    # project type is configuration, not a name the engine has to have been taught. Resolved
    # BEFORE the environment variable is set, so a name that cannot be resolved does not leave
    # the process pointing at a project that was never activated.
    # Set the variable BEFORE resolving, and unwind if resolution fails. Order matters in both
    # directions and the first cut got only one of them. `get_binding` may auto-IMPORT a binding
    # module, and module-level code there can read the active project (`src/defaults.py` resolves
    # `get_active_binding()` on attribute access) - so resolving first would let a third project's
    # import capture whatever project was active before. Setting first and not unwinding would
    # leave the process pointing at a project that failed to activate. Found by the GENERIC-01
    # numerics review, on the auto-import path this stage is what opens.
    previous = os.environ.get(ACTIVE_PROJECT_ENV_VAR)
    os.environ[ACTIVE_PROJECT_ENV_VAR] = name
    try:
        binding = get_binding(name)
    except BaseException:
        if previous is None:
            os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
        else:
            os.environ[ACTIVE_PROJECT_ENV_VAR] = previous
        raise
    logger.info("AM project activated: %s (%s)", name, binding.project_name)
    return name


def _from_binding(binding: Any, key: str) -> Path:
    """Resolve one of a project's inputs from its binding alone.

    ``data_dirs[key]`` is the repository-relative directory and
    ``default_filenames[key]`` the name within it; an absent or empty directory
    means the filename is already repository-relative. Keyed per artefact rather
    than one root per project, because a project's three inputs can sit in three
    different directories.

    GENERIC-01: this replaced a branch that used one project's three module
    constants for that project and joined the **wind fixture directory** for
    everything else - so a third project would have activated and then been
    handed wind's register.
    """
    try:
        filename = binding.default_filenames[key]
    except KeyError:
        raise KeyError(
            f"project {binding.name!r} declares no {key!r} in default_filenames; "
            f"a project's inputs are configuration, and this one is missing."
        ) from None
    directory = binding.data_dirs.get(key, "")
    return AM_REPO_ROOT / directory / filename if directory else AM_REPO_ROOT / filename


def resolve_project_inputs(
    project: str | None = None,
    *,
    register_path: Path | None = None,
    xer_path: Path | None = None,
    strawman_path: Path | None = None,
) -> ProjectInputs:
    """Activate the project and resolve its register / xer / strawman paths.

    Explicit path arguments override the per-project defaults (used by the
    CLI ``--register`` / ``--xer`` / ``--strawman`` flags and by tests).
    """
    name = activate_project(project)
    binding = get_binding(name)

    reg = register_path or _from_binding(binding, "register")
    xer = xer_path or _from_binding(binding, "schedule")
    straw = strawman_path or _from_binding(binding, "strawman")

    return ProjectInputs(
        project=name,
        register_path=Path(reg),
        xer_path=Path(xer),
        strawman_path=Path(straw),
        risk_id_prefix=binding.risk_id_prefix,
        register_version=project_display_name(binding),
        methodology_label=project_display_name(binding),
        display_name=project_display_name(binding),
    )


# ---------------------------------------------------------------------------
# Project-aware driver construction
# ---------------------------------------------------------------------------

def build_drivers_for_project(
    *,
    project: str,
    binding_cfg: Stage3BindingConfig,
    schedule_graph: Any,
    xer_tables: dict[str, Any],
    strawman_path: Path,
) -> dict[str, RiskDriver]:
    """Build the per-risk schedule drivers for the active project.

    One path for every project: ``expand_auto_rules`` over the strawman's Time=Yes rows,
    through the rule builder the deliverable and the showcases share. The by-name branch to a
    pattern-catalogue builder retired with that builder (GENERICDRV-01, REFRETIRE-01).
    """
    del xer_tables  # kept on the signature: callers have them parsed, this path reads the graph
    # `project` may be unset: `ConditionalRunInputs` does not require one and relies on the
    # ACTIVE project, which is legitimate. `get_active_binding` resolves that and fails loud when
    # nothing is selected, rather than inventing a default. Before ROAD-01 §5.3 this case was
    # invisible - an unnamed project silently received wind's schedule parameters, so the defect
    # was what made the call work.
    binding = get_binding(project) if project else get_active_binding()
    return _build_generic_drivers(
        strawman_path=strawman_path, schedule_graph=schedule_graph, binding=binding,
        binding_cfg=binding_cfg,
    )


def _build_generic_drivers(
    *, strawman_path: Path, schedule_graph: Any, binding: Any, binding_cfg: Stage3BindingConfig,
) -> dict[str, RiskDriver]:
    """Generic Stage-3 driver build from the strawman Time=Yes rows.

    GENERICINJ-01 (10/09/2026): the rules come from
    :func:`src.integrated.stage3_config.build_stage3_rules_from_scope`, the same function the
    showcase and the deliverable build this project's drivers with, so the period cycle injects
    by the method the register declares and writes to the gate the row declares. Until then this
    function built its own rules with ``injection_method=str(binding.injection_method)`` and no
    gate: the binding said ``additive_pert_days``, the register said
    ``discrete_event_additive_days``, and the period cycle broadcast a delay the deliverable
    wrote to one activity - one project, two methods, chosen by route.
    """
    # ROAD-01 §5.3: the float threshold is the project's own declaration, and the build refuses
    # rather than falls back. Wind's constant applied to every project was what a wrong
    # threshold does - it changes which activities bind, which moves the schedule arm. The
    # refusal itself moved to src.integrated.stage3_inputs at REFRETIRE-01, where every route
    # resolving a threshold now meets the same one.
    threshold = resolve_float_threshold_hours(binding=binding)   # refuses before any read
    scope = strawman_reader.read_risk_scope(str(strawman_path))
    cfg = replace(binding_cfg, float_threshold_hours=threshold)
    rules = build_stage3_rules_from_scope(scope, schedule_graph, cfg)
    if not rules:
        raise ValueError(
            f"No Time=Yes schedule rules found in strawman {strawman_path}. "
            f"The generic driver build needs at least one dual-coded risk."
        )
    drivers = expand_auto_rules(rules, schedule_graph)
    logger.info(
        "build_drivers_for_project (generic): produced %d drivers from %s",
        len(drivers), strawman_path.name,
    )
    return drivers
