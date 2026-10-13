"""GENERIC-01: a project type is configuration, not a name the engine knows.

The binding registry already resolves any project by convention - `src/sra/cpm/bindings/<p>.py`
self-registers and `get_binding` auto-imports it. `src/am/project_binding.py` put a two-name
allowlist in front of that registry, so a third project was refused before the registry was ever
asked. This suite is the red that had to be written before the deletion: **the restriction had no
test**, so there was no failing check to inherit, and a deletion whose test is written afterwards
proves only that the code does what it now does.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from src.am.project_binding import (
    ACTIVE_PROJECT_ENV_VAR,
    WIND_PROJECT,
    activate_project,
    resolve_project_inputs,
)
from src.sra.cpm.bindings.registry import ProjectBinding, register_binding

REPO = Path(__file__).resolve().parents[1]
AM_BINDING_SOURCE = REPO / "src" / "am" / "project_binding.py"

#: A third project that exists only as a registered binding - no module file, no fixtures. It is
#: deliberately data-only: the point is that configuration alone is enough to be *known*.
THIRD = "generic01_probe"


@pytest.fixture
def third_project_registered():
    """Register a third project for the duration of one test, then remove it.

    Registered directly rather than written to `src/sra/cpm/bindings/`, because a project that
    needs a file committed into the engine package would not be configuration.
    """
    binding = ProjectBinding(
        name=THIRD,
        project_name="GENERIC-01 probe project",
        default_filenames={
            "register": "probe_register.xlsx",
            "strawman": "probe_register.xlsx",
            "schedule": "probe_schedule.xer",
        },
        data_dirs={
            "register": "tests/fixtures/generic01_probe",
            "strawman": "tests/fixtures/generic01_probe",
            "schedule": "tests/fixtures/generic01_probe",
        },
        risk_id_prefix="PR",
    )
    register_binding(binding, overwrite=True)
    saved = os.environ.get(ACTIVE_PROJECT_ENV_VAR)
    try:
        yield binding
    finally:
        from src.sra.cpm.bindings import registry as _reg

        _reg._REGISTRY.pop(THIRD, None)
        if saved is None:
            os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
        else:
            os.environ[ACTIVE_PROJECT_ENV_VAR] = saved


class TestAThirdProjectIsKnownByConfigurationAlone:
    def test_a_project_that_is_only_a_registered_binding_activates(
            self, third_project_registered):
        """**The property the whole stage exists for.** Before the deletion this raised
        `ValueError: Unknown AM project 'generic01_probe'` - the registry was never consulted,
        because the allowlist answered first."""
        assert activate_project(THIRD) == THIRD

    def test_it_resolves_its_paths_from_its_OWN_binding(self, third_project_registered):
        """The second half, and the one a passing activation would hide. Path resolution used to
        join the wind fixture directory for every non-RefProject name, so a third project that
        activated would still have been handed **wind's** register."""
        inputs = resolve_project_inputs(THIRD)
        assert inputs.register_path == REPO / "tests/fixtures/generic01_probe/probe_register.xlsx"
        assert inputs.xer_path == REPO / "tests/fixtures/generic01_probe/probe_schedule.xer"
        assert "synthetic_wind" not in str(inputs.register_path), (
            "a third project resolved into the wind fixture directory")

    def test_it_takes_its_risk_prefix_from_its_binding(self, third_project_registered):
        """A prefix silently defaulting to another project's would read every risk row as a
        non-row and return an empty register rather than an error."""
        assert resolve_project_inputs(THIRD).risk_id_prefix == "PR"

    def test_its_labels_fall_back_to_the_binding_rather_than_failing(
            self, third_project_registered):
        """The display name (a binding key since RIDGELINE-01) and the methodology label (a
        per-project dict that knows only the original projects) both fall back to the binding's
        own `project_name`, so a third project degrades to its own label instead of raising -
        verified rather than assumed."""
        inputs = resolve_project_inputs(THIRD)
        assert inputs.display_name == "GENERIC-01 probe project"
        assert inputs.methodology_label == "GENERIC-01 probe project"


class TestRemovingTheRestrictionDidNotRemoveTheDiagnosis:
    def test_an_unknown_project_still_fails_loudly(self):
        """A-2. The allowlist's one virtue was refusing a typo. `get_binding` refuses it too, and
        names what IS registered - so the diagnosis survives the deletion."""
        with pytest.raises((KeyError, ValueError)) as exc:
            activate_project("no_such_project_anywhere")
        assert "no_such_project_anywhere" in str(exc.value)

    def test_a_failed_activation_leaves_the_environment_as_it_found_it(self):
        """Found by the GENERIC-01 numerics review. The variable is set BEFORE the binding is
        resolved, so that a third project's auto-imported module reads the project being
        activated rather than the one that happened to be active before. That is only safe if a
        failed resolution unwinds: otherwise a typo would leave the process pointing at a project
        that never activated, and the next run would silently use it."""
        os.environ[ACTIVE_PROJECT_ENV_VAR] = WIND_PROJECT
        try:
            with pytest.raises((KeyError, ValueError)):
                activate_project("still_not_a_project")
            assert os.environ.get(ACTIVE_PROJECT_ENV_VAR) == WIND_PROJECT, (
                "a failed activation changed the active project")
        finally:
            os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)

    def test_a_failed_activation_does_not_invent_one_where_there_was_none(self):
        """The other half: unset before, unset after."""
        saved = os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
        try:
            with pytest.raises((KeyError, ValueError)):
                activate_project("still_not_a_project")
            assert ACTIVE_PROJECT_ENV_VAR not in os.environ, (
                "a failed activation left the environment naming a project")
        finally:
            if saved is not None:
                os.environ[ACTIVE_PROJECT_ENV_VAR] = saved

    def test_an_empty_project_is_still_refused(self):
        """There is no default project (QRAXL-01), and de-restricting must not invent one."""
        saved = os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
        try:
            with pytest.raises(ValueError, match="No AM project selected"):
                activate_project(None)
        finally:
            if saved is not None:
                os.environ[ACTIVE_PROJECT_ENV_VAR] = saved


class TestTheTwoExistingProjectsDoNotMove:
    """B-1. This deletes a guard on a live path, so the paths both existing projects resolve to
    must be **exactly** what they were. Pinned as literals, captured from the code before the
    change - a test that recomputed them from the new logic would agree with itself."""

    @pytest.mark.parametrize("project, key, expected", [
        (WIND_PROJECT, "register", "tests/fixtures/synthetic_wind/wind_register.xlsx"),
        (WIND_PROJECT, "strawman", "tests/fixtures/synthetic_wind/wind_register.xlsx"),
        (WIND_PROJECT, "xer", "tests/fixtures/synthetic_wind/wind_schedule.xer"),
    ])
    def test_the_resolved_path_is_unchanged(self, project: str, key: str, expected: str):
        inputs = resolve_project_inputs(project)
        got = {"register": inputs.register_path, "strawman": inputs.strawman_path,
               "xer": inputs.xer_path}[key]
        assert got == REPO / expected

    @pytest.mark.parametrize("project, prefix", [(WIND_PROJECT, "WT")])
    def test_the_risk_prefix_is_unchanged(self, project: str, prefix: str):
        assert resolve_project_inputs(project).risk_id_prefix == prefix


def test_no_project_identity_comparison_remains_on_the_resolution_path():
    """The guard that stops the allowlist coming back, per the guard convention.

    Asserted on the **AST**, not on the words: this module's own docstrings name both projects
    constantly, so any text search would match its own explanation. That mistake has now been made
    six times in this repository (GUARDBYTE-01 is the sixth, and was invisible to reading), so the
    strongest available shape is used - a parse, where a comparison is a node rather than a string.

    Scoped to `activate_project` and `resolve_project_inputs`, which is what GENERIC-01
    repairs, and to `build_drivers_for_project`, which branched by project name until
    REFRETIRE-01 retired the separate builder it branched to (GENERICDRV-01, now closed).
    """
    tree = ast.parse(AM_BINDING_SOURCE.read_text(encoding="utf-8"))
    guarded = {"activate_project", "resolve_project_inputs", "build_drivers_for_project"}
    project_names = {"WIND_PROJECT"}

    #: The literal project names, so an allowlist rebuilt from strings rather than constants is
    #: caught too. Widened after the GENERIC-01 numerics review observed the first version pinned
    #: exactly one shape - a guard narrower than its own docstring claimed.
    project_literals = {WIND_PROJECT, "synthetic_road"}

    def _names_a_project(node: ast.AST) -> str | None:
        """The node identifies a specific project, by constant, literal, or binding attribute."""
        if isinstance(node, ast.Name) and node.id in project_names:
            return node.id
        if isinstance(node, ast.Constant) and node.value in project_literals:
            return repr(node.value)
        if isinstance(node, ast.Attribute) and node.attr == "name":
            return ast.unparse(node)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            hits = [h for h in (_names_a_project(e) for e in node.elts) if h]
            return ", ".join(hits) if hits else None
        return None

    offences: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in guarded:
            continue
        for sub in ast.walk(node):
            # `==` / `!=` / `is` / `is not` / `in` / `not in` - an allowlist can be spelt any of
            # these ways, and the first version of this guard saw only the first two.
            if isinstance(sub, ast.Compare):
                ops = (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.In, ast.NotIn)
                if any(isinstance(op, ops) for op in sub.ops):
                    for operand in (sub.left, *sub.comparators):
                        hit = _names_a_project(operand)
                        if hit:
                            offences.append(f"{node.name} line {sub.lineno}: compares {hit}")
            # `match name: case WIND_PROJECT:` is an allowlist with different punctuation.
            elif isinstance(sub, ast.match_case):
                hit = _names_a_project(getattr(sub.pattern, "value", sub.pattern))
                if hit:
                    offences.append(f"{node.name} line {sub.pattern.lineno}: matches {hit}")

    assert offences == [], (
        "a project-identity comparison is back on the resolution path, which is how the allowlist "
        f"was built the first time: {offences}")


class TestNoProjectsPrefixStandsAsAnotherProjectsDefault:
    """§5.1. `tier1_headless` defaulted `risk_id_prefix` to "WT" and the xlwings shell fell back
    to it when `Set_risk_prefix` was unreadable - so a register that omitted a contract-required
    range had every risk row read against the WIND project's prefix, matched none, and returned
    an EMPTY register as though it were a result. A wrong answer, not an error, and the failure a
    road project would have hit first."""

    @pytest.mark.parametrize("func_name", ["run_headless", "run_headless_from_workbook"])
    def test_the_headless_entry_points_require_a_prefix(self, func_name: str):
        """Asserted on the signature, which is the behaviour: a caller that omits it now fails
        at the call rather than silently running as wind."""
        import inspect

        import src.tier1_headless as headless

        param = inspect.signature(getattr(headless, func_name)).parameters["risk_id_prefix"]
        assert param.default is inspect.Parameter.empty, (
            f"{func_name} defaults risk_id_prefix to {param.default!r}; a project's risk prefix "
            f"is not something another project can supply")

    def test_the_xlwings_shell_reads_the_prefix_with_no_fallback(self):
        """The shell cannot be called without a workbook, so this is asserted on the AST of the
        call itself rather than on behaviour - the shape of the read, not the word "WT", per
        the guard convention. The second argument to `_named("Set_risk_prefix", ...)` must
        be an empty string, so the guard below it can refuse."""
        tree = ast.parse((REPO / "src" / "tier1_xlwings_shell.py").read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "_named" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value == "Set_risk_prefix":
                found.append(node)

        assert found, "the shell no longer reads Set_risk_prefix at all"
        for call in found:
            fallback = call.args[1] if len(call.args) > 1 else None
            assert isinstance(fallback, ast.Constant) and fallback.value == "", (
                f"Set_risk_prefix is read with a fallback of {getattr(fallback, 'value', None)!r} "
                f"at line {call.lineno}; a prefix borrowed from another project reports an empty "
                f"register as a result")

    def test_the_shell_REFUSES_an_empty_prefix_rather_than_running_with_one(self):
        """**The half the fallback check cannot see, and the more dangerous half.**

        Found by the GENERIC-01 numerics review. Asserting only that the fallback is `""` leaves
        the empty string flowing onward, and `rid.startswith("")` is True for *every* string - so
        an empty prefix makes `parse_risks_from_grid` read header, section and blank rows as
        risks. That is a worse wrong answer than borrowing "WT", which at least matched nothing.

        So the `raise` is pinned too: delete it and the previous test still passes, which makes it
        a check that cannot fail for the case that matters most.
        """
        tree = ast.parse((REPO / "src" / "tier1_xlwings_shell.py").read_text(encoding="utf-8"))
        refusals = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name) and node.test.operand.id == "prefix"
            and any(isinstance(stmt, ast.Raise) for stmt in ast.walk(node))
        ]
        assert refusals, (
            "the shell no longer refuses an empty risk prefix. An empty string is not a harmless "
            "default: every risk id starts with it, so the register parses its own headers and "
            "blank rows as risks")

    def test_an_empty_prefix_really_would_match_every_row(self):
        """The control that makes the test above mean something. If `startswith('')` were False
        for anything, an empty prefix would be merely useless rather than dangerous, and the
        refusal would be ceremony."""
        for row_label in ("WT-001", "Risk ID", "", "   ", "SECTION: civils"):
            assert row_label.startswith(""), "an empty prefix no longer matches everything"


class TestNoProjectsSCHEDULEParametersStandAsAnothersDefault:
    """ROAD-01 §5.3. The same defect as the `"WT"` prefix above, one layer down and worse.

    `_build_generic_drivers` - the path *every* non-RefProject project takes - applied
    `WIND_FLOAT_THRESHOLD_HOURS = 480.0` and `WIND_INJECTION_METHOD`, module constants named for
    wind. RefProject's equivalent already lived in its own binding, so the two projects were
    treated inconsistently and a third would silently inherit wind's.

    Why it matters more than a prefix: a wrong float threshold changes **which activities the
    auto-mapper binds**, and binding a different set of activities moves the schedule arm. A
    borrowed prefix returns an empty register, which at least looks wrong; a borrowed threshold
    returns a plausible number.
    """

    def test_a_project_that_declares_no_driver_parameters_is_refused(self):
        from src.am.project_binding import _build_generic_drivers

        binding = ProjectBinding(name="no_params_probe", project_name="Probe")
        with pytest.raises(ValueError, match="declares no"):
            _build_generic_drivers(
                strawman_path=None, schedule_graph=None, binding=binding, binding_cfg=None)

    @pytest.mark.parametrize("field, expected", [
        ("float_threshold_hours", 480.0),
    ])
    def test_wind_declares_exactly_what_the_module_constants_held(self, field, expected):
        """Bit-identity for the schedule arm, pinned as literals captured **before** the move. A
        test that read them back from the binding would agree with whatever the move produced.

        `injection_method` was the second row until GENERICINJ-01 (10/09/2026) retired it from
        the binding: the method is the register's declaration, and the binding's copy said
        `additive_pert_days` while the register said `discrete_event_additive_days`.
        """
        from src.sra.cpm.bindings.synthetic_wind import SYNTHETIC_WIND_BINDING

        assert getattr(SYNTHETIC_WIND_BINDING, field) == expected

    def test_the_wind_named_constants_are_gone_from_the_engine_module(self):
        """Asserted on the AST, not the words: `project_binding.py` discusses wind throughout its
        comments, so a text search would match the note explaining the retirement."""
        tree = ast.parse(AM_BINDING_SOURCE.read_text(encoding="utf-8"))
        assigned = {
            t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name)
        }
        strayed = assigned & {"WIND_FLOAT_THRESHOLD_HOURS", "WIND_INJECTION_METHOD"}
        assert not strayed, (
            f"{strayed} is back in the engine module. A schedule parameter named for one project "
            f"and read by every project is how this defect was built the first time.")


class TestAnIncompleteBindingIsRefusedByName:
    """PROCDIET-01 A1: a binding that declares an input incompletely is refused by name, never
    handed another project's file. The refusal at ``project_binding._from_binding`` had no test."""

    @pytest.mark.parametrize("missing", ["register", "strawman", "schedule"])
    def test_an_input_the_binding_does_not_declare_is_refused_naming_it(self, missing):
        name = "procdiet01_incomplete_probe"
        filenames = {"register": "r.xlsx", "strawman": "r.xlsx", "schedule": "s.xer"}
        del filenames[missing]
        register_binding(ProjectBinding(name=name, project_name="Incomplete probe",
                                        default_filenames=filenames), overwrite=True)
        saved = os.environ.get(ACTIVE_PROJECT_ENV_VAR)
        try:
            with pytest.raises(KeyError, match=f"{name}.*declares no '{missing}'"):
                resolve_project_inputs(name)
        finally:
            from src.sra.cpm.bindings import registry as _reg

            _reg._REGISTRY.pop(name, None)
            if saved is None:
                os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
            else:
                os.environ[ACTIVE_PROJECT_ENV_VAR] = saved
