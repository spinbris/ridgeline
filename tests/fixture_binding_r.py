"""A test-only project binding whose register IDs carry the ``R`` prefix.

Several committed fixtures - the SRA-02 S-E cross-check register, the SR12 strawman, the
scaffolder's output - were built with ``R``-prefixed risk IDs, because the project this
repository was cut from used that prefix. The V5 reader tells risk rows from header rows by the
ACTIVE binding's ``risk_id_prefix``, so those fixtures only read under a binding that declares
``R``: they used to name the project that has now retired (REFRETIRE-01), and would otherwise
read zero rows and make every assertion in their files vacuous.

What they need is a prefix, not a project, so this is a binding of the tests' own. It declares
the minimum: a name, a prefix, and the float threshold the driver build refuses without. It has
no files, no narrative templates and no WBS labels, so anything resolved through it falls back
to the engine's generic text - which is what a test asserting generic behaviour wants.

Registered at import; ``tests/conftest.py`` imports this module so ``@pytest.mark.project(...)``
can select it by name.
"""

from __future__ import annotations

from src.sra.cpm.bindings.registry import ProjectBinding, register_binding

#: The name tests select with ``@pytest.mark.project(R_PREFIX_PROJECT)``.
R_PREFIX_PROJECT = "fixture_r_prefix"

R_PREFIX_BINDING: ProjectBinding = register_binding(
    ProjectBinding(
        name=R_PREFIX_PROJECT,
        project_name="Fixture (R-prefixed register)",
        risk_id_prefix="R",
        float_threshold_hours=480.0,
    ),
    overwrite=True,
)
