"""Project-specific bindings for the generic Stage 3 CPM kernel.

The kernel modules in :mod:`src.sra.cpm` are project-agnostic; the per-
project wire-up to actual register / schedule / strawman inputs lives in
this subpackage. Per the SR-S3-Beta-00.3 reusability invariant, future
Projects add a binding module here rather than modifying the kernel.

Showcase-P2 WS2-A promoted this subpackage to a first-class extension
point: :func:`register_binding` / :func:`get_binding` /
:func:`get_active_binding` resolve the active project from the
``QRA_PROJECT`` env var. QRAXL-01 generic decoupling removed the
default: an unset selection now fails loud (:class:`NoProjectSelectedError`),
never falling back to a project nobody named. The registry lives in the import-light
:mod:`.registry` module; binding modules (``synthetic_wind``, ``synthetic_road``)
self-register at *their* import time and are auto-imported by name on first
lookup. This package ``__init__`` deliberately does **not** import any binding
module, to keep ``import src.sra.cpm.bindings`` cheap and cycle-free.
"""
from __future__ import annotations

from src.sra.cpm.bindings.registry import (
    ACTIVE_PROJECT_ENV_VAR,
    NoProjectSelectedError,
    ProjectBinding,
    active_project_name,
    active_risk_id_prefix,
    get_active_binding,
    get_binding,
    is_publishable,
    list_bindings,
    project_display_name,
    register_binding,
)

__all__ = [
    "ACTIVE_PROJECT_ENV_VAR",
    "NoProjectSelectedError",
    "ProjectBinding",
    "active_project_name",
    "active_risk_id_prefix",
    "get_active_binding",
    "get_binding",
    "is_publishable",
    "list_bindings",
    "project_display_name",
    "register_binding",
]
