"""Project-binding registry and active-project selection (Showcase-P2 WS2-A).

The engine in ``src/`` is project-agnostic; every project-specific value
(default filenames, party labels, narrative-template copy, the transitional
legacy chain IDs) lives in a *project binding* under
``src/sra/cpm/bindings/``. This module is the seam: it holds the registry
and resolves the *active* project from the ``QRA_PROJECT`` env var
(no default: an unset selection fails loud).

Design constraints
------------------
- **Import-light.** This module imports only the stdlib + ``dataclasses``.
  It must never import engine modules or a binding module at module load,
  or it would create import cycles (a binding imports the engine, the
  engine — once WS2-B lands — reads the active binding). Binding modules
  register themselves at *their* import time; this module auto-imports a
  binding lazily, by name, only when first requested.
- **Auto-import by name.** A project ``<p>`` lives in
  ``src/sra/cpm/bindings/<p>.py`` and calls :func:`register_binding` at
  module scope. :func:`get_binding` lazily imports ``<p>`` if it is not
  already registered, so callers never have to import the binding module
  explicitly.

The env var keeps its legacy prefix by Director decision
(brief §8 decision 2): renaming it would break back-compat for no gain.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from src.rng_streams import parse_seed

__all__ = [
    "ProjectBinding",
    "NoProjectSelectedError",
    "register_binding",
    "get_binding",
    "get_active_binding",
    "active_project_name",
    "active_risk_id_prefix",
    "list_bindings",
    "ACTIVE_PROJECT_ENV_VAR",
]

#: Env var selecting the active project. Legacy-named (kept for back-compat
#: per brief §8 decision 2); documented in PORTABILITY.md.
ACTIVE_PROJECT_ENV_VAR = "QRA_PROJECT"

# QRAXL-01 generic decoupling (Director directive, 17/07/2026): there is NO
# default project - defaults are dangerous. An unset selection fails loud
# (NoProjectSelectedError) and never falls back to a project nobody named. Every
# entry point selects its project explicitly.


class NoProjectSelectedError(RuntimeError):
    """Raised when the engine needs a project but none is explicitly selected."""


@dataclass(frozen=True)
class ProjectBinding:
    """Declarative, data-only surface a project supplies to the engine.

    Behavioural wire-up (driver construction, calendar quirks, the cost-
    engine call) stays as ordinary functions in the binding *module*; this
    object carries only the project-specific *data* the generic engine
    reads. Frozen so a registered binding cannot be mutated in place.

    Attributes
    ----------
    name:
        Registry key (matches the binding module filename, e.g. ``"synthetic_wind"``).
    project_name:
        Human-facing project label (e.g. ``"SyntheticWind"``).
    default_filenames:
        Keys ``"register"`` / ``"strawman"`` / ``"schedule"`` → filename or
        path. Consumed by the engine's path-resolution fallback layer.
    data_dirs:
        Same keys → the repository-relative **directory** each filename sits
        in, joined to the repository root by the resolver. Per artefact
        rather than one root per project, because a project's three inputs
        need not share a directory (a project's three can sit in three,
        ``outputs/sra_strawman/`` and ``inputs/...``).
        Absent or empty means the filename is already repository-relative.
        This is what makes a project's data location **configuration**:
        before GENERIC-01 the resolver joined one hardcoded fixture
        directory for every project but one, so a third project resolved
        onto the wind fixtures.
    party_labels:
        Contractual party labels (e.g. ``{"contractor": "BOP Contractor",
        "owner": "Owner", "shared": "Shared"}``). Workbook
        ``MC_Params`` remains the live source where present; these are the
        binding-level defaults/fallbacks.
    narrative_templates:
        Project-specific report copy keyed by role (e.g. ``"report_title"``,
        ``"dominant_risk"``). The engine reads a template from here and
        falls back to a generic string when the key is absent.
    wbs_labels:
        Optional WBS/RBS Level-1 code→label overrides (e.g.
        ``{"50": "Wind Grid & Substation"}``) layered over the generic
        discipline-name base map in ``src.final.rbs_mapping``. Empty for a
        project that uses only the generic labels.
    risk_id_prefix:
        The leading string every Risk ID in this project's register
        carries (synthetic wind: ``"WT"``; synthetic road: ``"KH"``). The V5
        register reader uses it to tell risk rows from header/blank rows.
        Defaults to ``"R"`` so existing projects are unchanged.
    contract_type:
        The commercial shape of the engagement this project is delivered under, or ``None``
        (PRESENT-01 D-3). It selects the deliverable's contract-shape wording - what the
        headline contingency is called, and which deferred commercial layers are named - and
        nothing else; it never reaches the engines. ``None`` is the default and yields neutral
        wording, so a project that has not declared its contract shape does not have one
        assumed for it. Recognised values live with the wording, in
        ``src.final.contract_terms``.
    float_threshold_hours:
        Total-float ceiling, in hours, below which the Stage-3 auto-mapper treats
        an activity as bindable. A project property: it follows from how much
        float that project's schedule actually carries, and a threshold borrowed
        from another project changes **which activities bind**, which moves the
        schedule arm. ``None`` means the project has not declared one, and the
        generic driver build refuses rather than choosing for it.
    default_iterations, default_reporting_p_level:
        The iteration count and reporting P-level this project runs at when its register has no
        such row (CONFIGTRUTH-01, Director 08/10/2026). The register's row wins whenever it is
        present; a value taken from here is recorded as ``"binding default"`` in the run's
        manifest, so it never passes for a chosen one. ``None`` means the project declares none,
        and a register without the row is then refused by name. A declared value must be a
        positive ``int``: a zero is a mistake, not an absence.
    period_seed:
        The seed every period run of this project uses (SEEDZERO-01 P3, Director 11/10/2026), so
        that what moves from one period to the next is the register, not sampling noise. The
        period run's ``--seed`` overrides it for one run, and the period JSON records which.
        ``None`` means the project declares none, and a period run without ``--seed`` is then
        refused by name. A declared value is a positive whole number: 0 means "draw", which a
        period seed exists to prevent.
    legacy_chain_ids:
        Transitional event-chain role→risk-id map (``c1_trigger`` etc.), or
        ``None``. See the binding's own docstring for the authoritative
        source and retirement path.
    headless_config:
        Project-specific headless / legacy-cost-MC fallback values (QRAXL-01
        generic decoupling, Coupling C), or ``None``. Keys: ``workbook_filename``,
        ``gp_toc``, ``wbs_buckets``, ``cg_coefficients``, ``wbs_cross_bucket_rho``,
        ``programme_seasons``. These were one project's constants, loose in
        ``src/defaults.py``; under the no-defaults directive they live in the
        selected project's binding and a value the binding does not supply
        **fails loud** rather than falling back to a cross-project constant.
        ``None`` for a project that never runs the ``--no-excel`` / legacy path
        (e.g. synthetic_wind).
    publish:
        Whether this project may be published to the app (RELEASE-01 D-5 as amended,
        DASHGATE-01). **Default ``False``: nothing is published unless it is named.**
    confidential:
        Whether this project's material is confidential. **Default ``True``** (DASHGATE-01 D-A):
        a project that says nothing is treated as confidential, so a new project must declare
        ``confidential=False`` as well as ``publish=True`` before anything ships. The second
        lock: a confidential project is refused even with ``publish`` set. It must agree with
        the golden registry's ``confidential``, which is not itself the publish gate.
    illustrative_base:
        Whether the register's base estimate is illustrative rather than a real estimate: a
        synthetic project's. **Default ``False``.** Where the report draws the base beneath the
        contingency (INTSCURVE-01 Part B), it says "illustrative" when this is ``True``.
    """

    name: str
    project_name: str
    default_filenames: Mapping[str, str] = field(default_factory=dict)
    data_dirs: Mapping[str, str] = field(default_factory=dict)
    party_labels: Mapping[str, str] = field(default_factory=dict)
    narrative_templates: Mapping[str, str] = field(default_factory=dict)
    wbs_labels: Mapping[str, str] = field(default_factory=dict)
    risk_id_prefix: str = "R"
    contract_type: str | None = None
    float_threshold_hours: float | None = None
    default_iterations: int | None = None
    default_reporting_p_level: int | None = None
    period_seed: int | None = None
    legacy_chain_ids: Mapping[str, object] | None = None
    headless_config: Mapping[str, object] | None = None
    publish: bool = False
    confidential: bool = True
    illustrative_base: bool = False

    def __post_init__(self) -> None:
        # DASHGATE-01 round 1, N7: the two publish locks are real booleans, never truthy stand-ins.
        for lock in ("publish", "confidential", "illustrative_base"):
            if type(getattr(self, lock)) is not bool:
                raise TypeError(f"binding {self.name!r}: {lock} must be a bool, "
                                f"not {type(getattr(self, lock)).__name__}")
        # CONFIGTRUTH-01: a declared run-setting default is a positive int, never a bool or a float.
        for setting in ("default_iterations", "default_reporting_p_level"):
            value = getattr(self, setting)
            if value is None:
                continue
            if type(value) is not int:
                raise TypeError(f"binding {self.name!r}: {setting} must be an int, "
                                f"not {type(value).__name__}")
            if value <= 0:
                raise ValueError(f"binding {self.name!r}: {setting} must be positive, not {value}")
        # A declared period seed is fixed: 0 would mean "draw", which a period seed exists not to.
        if self.period_seed is not None and parse_seed(
                self.period_seed, where=f"binding {self.name!r} period_seed") == 0:
            raise ValueError(f"binding {self.name!r}: period_seed must be positive, not 0")
        # Freeze the mappings so a registered binding is truly immutable.
        object.__setattr__(self, "default_filenames", MappingProxyType(dict(self.default_filenames)))
        object.__setattr__(self, "data_dirs", MappingProxyType(dict(self.data_dirs)))
        object.__setattr__(self, "party_labels", MappingProxyType(dict(self.party_labels)))
        object.__setattr__(self, "narrative_templates", MappingProxyType(dict(self.narrative_templates)))
        object.__setattr__(self, "wbs_labels", MappingProxyType(dict(self.wbs_labels)))
        if self.legacy_chain_ids is not None:
            object.__setattr__(self, "legacy_chain_ids", MappingProxyType(dict(self.legacy_chain_ids)))
        if self.headless_config is not None:
            object.__setattr__(self, "headless_config", MappingProxyType(dict(self.headless_config)))

    def narrative(self, key: str, default: str = "") -> str:
        """Return narrative-template copy for ``key``, or ``default``."""
        return self.narrative_templates.get(key, default)


def is_publishable(binding: ProjectBinding) -> bool:
    """The one answer to "may this project be published?" (DASHGATE-01 P1, D-5 as amended).

    Both locks: the project names itself for publication AND is not confidential. Every publish
    check - the dashboard copy, ``publish_period`` and the deploy guard - asks this, never a
    project's name.
    """
    return binding.publish is True and binding.confidential is False


def shipped_binding_names() -> list[str]:
    """Every project module in this package - the shipped projects - sorted.

    From the package's own modules rather than ``list_bindings()``, which at any moment holds
    whatever has been resolved so far (and, in a test run, fixture bindings too).
    """
    import pkgutil
    from pathlib import Path

    here = Path(__file__).resolve().parent
    return sorted(m.name for m in pkgutil.iter_modules([str(here)])
                  if m.name != "registry" and not m.name.startswith("_"))


def publishable_projects() -> list[str]:
    """The shipped projects ``is_publishable`` says may be published, sorted (DASHGATE-01 P2).

    ``dashboard/publish.json`` is this list, written by ``scripts/release/write_publish_list.py``
    and held equal to it by a test; the dashboard copy reads that file. The deploy guard does not:
    it calls this function, asking the bindings directly.
    """
    return [n for n in shipped_binding_names() if is_publishable(get_binding(n))]


# Registry state. Module-global by design (one registry per process).
_REGISTRY: dict[str, ProjectBinding] = {}


def register_binding(binding: ProjectBinding, *, overwrite: bool = False) -> ProjectBinding:
    """Register ``binding`` under ``binding.name``; return it.

    Raises :class:`ValueError` on a duplicate name unless ``overwrite`` is
    set (tests use ``overwrite=True`` to re-register fixtures).
    """
    if not isinstance(binding, ProjectBinding):
        raise TypeError(f"register_binding expects a ProjectBinding, got {type(binding)!r}")
    if binding.name in _REGISTRY and not overwrite:
        raise ValueError(
            f"A project binding named {binding.name!r} is already registered. "
            f"Pass overwrite=True to replace it."
        )
    _REGISTRY[binding.name] = binding
    return binding


def get_binding(name: str) -> ProjectBinding:
    """Return the binding registered under ``name``.

    Lazily imports ``src.sra.cpm.bindings.<name>`` (which self-registers) if
    ``name`` is not already in the registry. Raises a clear
    :class:`KeyError` listing the registered names if it still cannot be
    found.
    """
    if name not in _REGISTRY:
        _try_autoimport(name)
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No project binding registered under {name!r}. "
            f"Registered: {sorted(_REGISTRY)}. "
            f"A binding must live in src/sra/cpm/bindings/{name}.py and call "
            f"register_binding(...) at module scope, or be selected via "
            f"{ACTIVE_PROJECT_ENV_VAR}."
        ) from None


def project_display_name(binding: ProjectBinding) -> str:
    """The project's public name: one declaration, read by the deliverable and the app alike.

    RIDGELINE-01 (HTMLPROV-01): the report's run identity printed the binding key and the app read
    a separate map, so one project could carry two names. A binding declares the name as its
    ``project_display_name`` narrative key; without one it is the binding's ``project_name``,
    never the binding key.
    """
    return binding.narrative("project_display_name") or binding.project_name


def active_project_name() -> str:
    """Return the EXPLICITLY-selected project name from ``QRA_PROJECT``.

    No default (Director directive, QRAXL-01 generic decoupling): an unset
    selection fails loud with a located :class:`NoProjectSelectedError` - it must
    NEVER silently fall back to a project nobody named. Every entry point selects a
    project explicitly (production: the ``RUN_*.bat`` set ``QRA_PROJECT``;
    tests: the ``tests/conftest.py`` autouse select).
    """
    name = os.environ.get(ACTIVE_PROJECT_ENV_VAR)
    if not name:
        raise NoProjectSelectedError(
            f"No project selected: {ACTIVE_PROJECT_ENV_VAR} is unset. There is no "
            f"default project (dangerous) - select one explicitly, e.g. "
            f"{ACTIVE_PROJECT_ENV_VAR}=synthetic_wind. "
            f"Registered bindings: {sorted(_REGISTRY)}."
        )
    return name


def get_active_binding() -> ProjectBinding:
    """Return the binding for the active project (``QRA_PROJECT``).

    Fails loud (``NoProjectSelectedError``) when no project is selected - never a
    fallback to a project nobody named.
    """
    return get_binding(active_project_name())


def list_bindings() -> tuple[str, ...]:
    """Return the sorted names of currently-registered bindings."""
    return tuple(sorted(_REGISTRY))


def active_risk_id_prefix() -> str:
    """Risk-ID prefix for the ACTIVE (explicitly-selected) project.

    Returns the active binding's ``risk_id_prefix`` (synthetic road ``"KH"``, synthetic
    wind ``"WT"``). Fail-loud (no cross-project ``"R"`` default): with no project
    selected, :func:`get_active_binding` raises ``NoProjectSelectedError`` rather
    than a reader silently defaulting to another project's prefix. Callers that already
    KNOW the prefix pass it directly to the reader and never reach this.
    """
    return get_active_binding().risk_id_prefix


def _try_autoimport(name: str) -> None:
    """Import ``bindings.<name>`` so it can self-register; swallow ImportError.

    Leaves the clear KeyError to :func:`get_binding` when the module does
    not exist. A name with a dot or path separator is rejected (it could
    only ever be a typo or an injection attempt, never a real binding).
    """
    if not name.isidentifier():
        return
    try:
        importlib.import_module(f"{__package__}.{name}")
    except ImportError:
        # No module by that name, or it failed to import. get_binding raises
        # the user-facing error; we do not mask an unrelated ImportError
        # inside the module by re-raising here.
        pass
