"""DAYRATE-02: locks for the day-rate contract.

DAYRATE-02 fixed a defect that had never moved a number: the deliverable's
schedule arm took ``day_rate`` from a code literal while its cost arm took it
from the strawman, and they agreed only because the two values coincided.
Nothing enforced the agreement and nothing tested it.

That is the shape GOLDCOLL-01 was left in - a fix with nothing holding it down,
where reverting one line put the defect back and no lane went red. These tests
are the lock. Each is written so that undoing a specific part of the fix makes a
specific test fail, and each was witnessed red against exactly that regression
before its pass was trusted (see the DAYRATE-02 running record).

Four independent locks, because the fix has four independent ways to come back:

1. ``test_sra_config_day_rate_is_required`` - A-ii. Restoring the dataclass
   default re-opens every omission at once.
2. ``test_no_sraconfig_site_omits_day_rate`` - A-i, over calls AND over the two
   notebook generators, which carry the construction as a string and are
   invisible to an AST sweep (F-12).
3. ``test_notebook_matches_its_generator`` - the notebook is generated; fixing
   the cell without the generator means the next regeneration reverts it.
4. ``test_arms_agree_on_the_day_rate`` - the runtime control. Every builder
   resolves the rate from the same strawman, so a strawman edit moves all of
   them or the test fails.
"""
from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES
from tests.conftest import TEST_MODE_MULTIPLIERS

import ast
import dataclasses
import json
import subprocess
from pathlib import Path

import openpyxl
import pytest

from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.sra_config import SRAConfig, load_sra_config
from src.git_identity import git_env

REPO_ROOT = Path(__file__).resolve().parent.parent

# A rate that is nothing like the client's, so a test that accidentally picks
# up a code default cannot pass by coincidence - which is the whole subject.
SENTINEL_DAY_RATE = 12_345.0
OTHER_DAY_RATE = 54_321.0


# ---------------------------------------------------------------------------
# Lock 1 - A-ii: day_rate cannot be omitted
# ---------------------------------------------------------------------------

def test_sra_config_day_rate_is_required() -> None:
    """SRAConfig.day_rate carries no default, so omitting it is a TypeError.

    Witnessed red by restoring ``day_rate: float = FIXTURE_DAY_RATE``.
    """
    field = {f.name: f for f in dataclasses.fields(SRAConfig)}["day_rate"]
    assert field.default is dataclasses.MISSING, (
        "SRAConfig.day_rate has a definitional default again. That is how 24 of "
        "31 construction sites came to omit it, including the shipped notebook."
    )
    assert field.default_factory is dataclasses.MISSING

    with pytest.raises(TypeError):
        SRAConfig(  # type: ignore[call-arg]
            register_path=Path("r"), p6_path=Path("p"), strawman_path=Path("s"),
        mode_multipliers=TEST_MODE_MULTIPLIERS)


def test_integrated_config_day_rate_defaults_to_none(monkeypatch) -> None:
    """IntegratedConfig.day_rate defaults to None, and using one stops the run.

    Director ruling, 31/08: not a literal and not a binding-resolved value
    either. "Every hardcoded number is wrong, because it belongs to some other
    project" - which is as true of a constant relocated into a project binding
    as of one in engine code, since a binding constant can go stale against the
    workbook it was copied from and still supplies a plausible number instead
    of stopping.

    This test replaced two weaker predecessors, both of which were satisfiable
    without the property: one asserted merely that a default_factory existed
    (a literal smuggled in as ``lambda: <rate>`` passed), the next asserted
    that the wind binding raised because it published no rate (true only while
    that arrangement held). This one asserts the absence of any default at all
    and then measures the consequence.
    """
    field = {f.name: f for f in dataclasses.fields(IntegratedConfig)}["day_rate"]
    assert field.default is None, (
        "IntegratedConfig.day_rate has a default again. Whatever it resolves - "
        "a literal, or a project binding's constant - it supplies some other "
        "project's commercial rate to this one, silently."
    )
    assert field.default_factory is dataclasses.MISSING

    from src.sra.methodology_defaults_reader import build_test_methodology_defaults
    from src.integrated.run_config_contract import RunConfigError, require_day_rate

    cfg = IntegratedConfig(
        register_path=Path("r"), p6_path=Path("p"), strawman_path=Path("s"),
        methodology_defaults=build_test_methodology_defaults(),
    **TEST_CALIBRATION_TOLERANCES)
    assert cfg.day_rate is None

    # Constructing without a rate is allowed - most construction sites never
    # read the field. CONSUMING one without a rate is what must stop.
    with pytest.raises(RunConfigError) as exc:
        require_day_rate(cfg.day_rate, caller="a calculation that needs a rate")
    assert "day_rate" in str(exc.value).lower() or "day rate" in str(exc.value).lower()

    # ... and a real rate passes straight through.
    assert require_day_rate(SENTINEL_DAY_RATE, caller="x") == SENTINEL_DAY_RATE


def test_no_src_module_falls_back_to_a_hardcoded_rate() -> None:
    """No module in src/ dollarises against a literal or a binding constant.

    The class of defect, not one instance of it: every read of an
    IntegratedConfig day rate in src/ is the direct argument of
    require_day_rate, so none can quietly substitute one project's rate on
    another. Witnessed red by restoring the
    `.get("day_rate", FIXTURE_DAY_RATE)` fallback in stage3_beta_report.

    Checked on the AST, not line by line. The first version of this test was a
    per-line string check and reported a false positive the moment a call was
    wrapped across two lines - a pattern check standing in for a property
    check, which is the error this whole stage is about.
    """
    offenders: list[str] = []

    for path in _tracked_files(".py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if not rel.startswith("src/"):
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Nodes that are the direct argument of a require_day_rate(...) call.
        guarded = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name == "require_day_rate":
                    for arg in node.args:
                        guarded.add(id(arg))
                    for kw in node.keywords:
                        guarded.add(id(kw.value))

        for node in ast.walk(tree):
            # SRAConfig.day_rate is a REQUIRED field, so it is never None and
            # needs no guard. Only the optional IntegratedConfig one does.
            if rel.startswith("src/sra/"):
                break
            if (isinstance(node, ast.Attribute) and node.attr == "day_rate"
                    and id(node) not in guarded):
                offenders.append(f"{rel}:{node.lineno} (unguarded .day_rate read)")
            if (isinstance(node, ast.Name) and node.id == "FIXTURE_DAY_RATE"
                    and rel != "src/sra/sra_config.py"):
                offenders.append(f"{rel}:{node.lineno} (FIXTURE_DAY_RATE reachable)")

    assert not offenders, (
        "a hardcoded day rate is reachable as a fallback at: " + "; ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Lock 2 - A-i: no construction site omits day_rate
# ---------------------------------------------------------------------------

def _tracked_files(*suffixes: str) -> list[Path]:
    """Tracked **plus untracked-not-ignored** files - the client gate's visibility rule.

    SWEEPBLIND-01. This listed tracked files only, so a module still uncommitted was invisible
    to the contract written to police it. Not hypothetical: ``src/integrated/stage3_config.py``
    violated the day-rate contract from the moment it was written, this lock was green through
    that whole stage, and it redded only when the next commit made the file visible. A sweep
    that cannot see the file being written is not a sweep - the same defect Part B fixed in its
    own guard (GATESCOPE-01), and the same one-line fix.

    ``is_file()`` filters entries git lists that are not on disk: a deletion staged in the index
    still appears under ``--cached``.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         *[f"*{s}" for s in suffixes]],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        env=git_env(),
    )
    seen: dict[str, Path] = {}
    for line in out.stdout.splitlines():
        if line and (REPO_ROOT / line).is_file():
            seen[line] = REPO_ROOT / line  # --cached and --others can both list a path
    return list(seen.values())


def _sraconfig_calls_without_day_rate(source: str) -> list[int]:
    """Line numbers of SRAConfig(...) calls in ``source`` that omit day_rate.

    A file that will not parse RAISES rather than returning no offenders. The
    review caught the swallowing version: it is the same silent-empty shape
    this stage closed in three config loaders, and it would have let any
    unparseable file pass the sweep with no signal at all.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(f"could not parse: {exc}") from exc
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute)
            else ""
        )
        if name != "SRAConfig":
            continue
        if not any(kw.arg == "day_rate" for kw in node.keywords):
            bad.append(node.lineno)
    return bad


def test_no_sraconfig_site_omits_day_rate() -> None:
    """Every SRAConfig(...) call site passes day_rate explicitly.

    Witnessed red by removing the kwarg from one test callsite.
    """
    offenders: list[str] = []
    # This module constructs an SRAConfig without day_rate on purpose, in
    # test_sra_config_day_rate_is_required, to prove the omission raises.
    self_rel = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

    for path in _tracked_files(".py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == self_rel:
            continue
        for lineno in _sraconfig_calls_without_day_rate(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            offenders.append(f"{rel}:{lineno}")

    for path in _tracked_files(".ipynb"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        for i, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            src = "".join(cell.get("source", []))
            for lineno in _sraconfig_calls_without_day_rate(src):
                offenders.append(f"{rel}::cell{i}:{lineno}")

    assert not offenders, (
        "SRAConfig constructed without day_rate at: " + ", ".join(offenders) +
        ". The schedule arm would take a code default while the cost arm reads "
        "the strawman, which is DAYRATE-02's defect returning."
    )


# ---------------------------------------------------------------------------
# Lock 3 - RETIRED at 3c Part A.
#
# F-12 locked the two notebook generators against the notebook they emitted, because the
# notebook was generated and the two could drift. Under R-4 there is no generator: the
# notebook is the tracked artefact, and `final_runner.ipynb` reads its day rate from the
# register through `src/final/deliverable`, which Lock 4 below covers directly. Nothing to
# hold in agreement, so the lock goes with the thing it was holding.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Lock 4 - the runtime control: the arms must agree, and must both move
# ---------------------------------------------------------------------------

def _synthetic_strawman(path: Path, day_rate: float) -> Path:
    """A minimal Run_Config_Preview workbook - no client data involved."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Run_Config_Preview"
    rows = [
        ("iterations", 5000),
        ("programme_seasons", 1),
        ("p-level_reporting", 80),
        ("cp_hybrid_float_threshold_days", 20),
        ("schedule duration (weeks)", 100.4),
        ("day_rate_default ($/wd)", day_rate),
    ]
    for i, (label, value) in enumerate(rows, start=1):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=value)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def _sra_arm(strawman: Path, tmp_path: Path) -> float:
    # RS-D-3b (D-15): the loader reads the register's Mode multiplier grid, so the register
    # must be a real workbook carrying one - the wind fixture register.
    reg = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"
    p6 = tmp_path / "p6.xlsx"
    p6.write_bytes(b"")
    return load_sra_config(str(reg), str(p6), str(strawman)).day_rate


def test_arms_agree_on_the_day_rate(tmp_path: Path, monkeypatch) -> None:
    """Both arms resolve the same rate from the same strawman, and both move.

    This is the control the brief asks for. It is written so it CAN fail: the
    third assertion points the two arms at strawmen carrying different rates
    and requires them to disagree. Without that, a pair of arms that both
    ignored the workbook and returned the same constant would pass.
    """
    lo = _synthetic_strawman(tmp_path / "lo.xlsx", SENTINEL_DAY_RATE)
    hi = _synthetic_strawman(tmp_path / "hi.xlsx", OTHER_DAY_RATE)

    # Both arms read the workbook rather than a code default.
    assert _sra_arm(lo, tmp_path) == SENTINEL_DAY_RATE
    assert _sra_arm(hi, tmp_path) == OTHER_DAY_RATE

    monkeypatch.setenv("REGISTER_FILE", str(tmp_path / "reg.xlsx"))
    monkeypatch.setenv("P6_FILE", str(tmp_path / "p6.xlsx"))

    # ... and the arms agree with each other on the same strawman. The cost arm
    # is exercised through resolve_day_rate, the function every IntegratedConfig
    # builder now routes through, rather than through a full config load (which
    # would need a register workbook carrying the SR19 methodology surface).
    from src.integrated.run_config_contract import (
        read_run_config_strict,
        resolve_day_rate,
    )
    from src.sra.strawman_reader import read_run_config

    for strawman, expected in ((lo, SENTINEL_DAY_RATE), (hi, OTHER_DAY_RATE)):
        cost_arm = resolve_day_rate(
            read_run_config_strict(strawman, read_run_config), strawman
        )
        schedule_arm = _sra_arm(strawman, tmp_path)
        assert cost_arm == schedule_arm == expected, (
            f"the two arms disagree on the day rate for {strawman.name}: "
            f"cost={cost_arm} schedule={schedule_arm}"
        )

    # Counter-control: a check that cannot distinguish the two strawmen would
    # pass everything above by returning one constant. It must not.
    assert _sra_arm(lo, tmp_path) != _sra_arm(hi, tmp_path)


# ---------------------------------------------------------------------------
# Lock 5 - the builders. Added after the fresh-context review, which measured
# that locks 1-4 did not cover the two builders this stage exists to fix.
# ---------------------------------------------------------------------------

#: `IntegratedConfig(...)` sites in src/ that legitimately omit day_rate. Each
#: is a fallback that constructs a config from PLACEHOLDER paths purely to
#: satisfy the dataclass, and never reads the rate - so requiring a strawman
#: read there would be wrong, not merely unnecessary. The exemption is verified
#: below rather than declared: the test asserts neither module reads
#: `config.day_rate` anywhere. If one ever starts to, this list stops covering
#: it and the sweep goes red.
_DAY_RATE_EXEMPT_BUILDERS = {
    "src/final/cross_validator.py": (
        "config-is-None fallback; passes strawman_path for all three paths as a "
        "placeholder and never reads config.day_rate"
    ),
    "src/final/executive_summary.py": (
        "config-is-None fallback for compute_diversification_benefit; passes "
        'empty-string paths as placeholders and never reads config.day_rate'
    ),
}


def _integrated_config_calls_without_day_rate(source: str) -> list[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(f"could not parse: {exc}") from exc
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute)
            else ""
        )
        if name != "IntegratedConfig":
            continue
        if not any(kw.arg == "day_rate" for kw in node.keywords):
            bad.append(node.lineno)
    return bad


def test_every_builder_passes_day_rate() -> None:
    """No IntegratedConfig construction anywhere omits the rate.

    Extended from src/ to the whole tracked tree after the increment lane
    caught this class THREE times, each time in a different test and each time
    a test marked ``slow`` - so the per-stage gate could not see any of them by
    construction. A structural check runs in the fast lane and closes that
    blind spot: the property is "no construction omits the rate", and it is
    now checked where it is cheap rather than discovered where it is
    expensive.

    THIS is the lock the brief's acceptance criterion actually asks for, and
    locks 1-4 did not provide it. They cover the SRAConfig sites, the two
    dataclass defaults and the contract functions - none of them asserts that
    the two builders DAYRATE-02 fixed still route through those functions.

    Why that mattered: revert either builder hunk and the config falls back to
    a code-level rate that equals the strawman's value today. The golden gate,
    the config probe at the unperturbed rate, locks 1-4 and the whole stage
    lane all stay green while the shipped notebook's arm goes strawman-blind
    again - which is precisely the "coincidence, not a mechanism" the brief
    names as the subject of the stage. Witnessed red by removing day_rate from
    _build_default_integrated_config and from the composer fallback.
    """
    offenders: list[str] = []
    self_rel = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    for path in _tracked_files(".py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        # This module builds one without a rate on purpose, to prove the
        # default is None.
        if rel == self_rel:
            continue
        source = path.read_text(encoding="utf-8")
        linenos = _integrated_config_calls_without_day_rate(source)
        if not linenos:
            continue
        if rel in _DAY_RATE_EXEMPT_BUILDERS:
            # The exemption is earned, not declared: a module that reads the
            # rate cannot claim to be a non-reading placeholder fallback.
            assert "config.day_rate" not in source, (
                f"{rel} is exempt from the day_rate builder sweep on the "
                f"grounds that it never reads the rate "
                f"({_DAY_RATE_EXEMPT_BUILDERS[rel]}), but it now reads "
                f"config.day_rate. The exemption no longer holds."
            )
            continue
        offenders.extend(f"{rel}:{n}" for n in linenos)

    assert not offenders, (
        "IntegratedConfig built without day_rate at: " + ", ".join(offenders) +
        ". A builder that does not source the rate takes a code-level default "
        "which happens to equal the strawman's value, so nothing goes red and "
        "the arm is silently strawman-blind - DAYRATE-02's defect returning."
    )
