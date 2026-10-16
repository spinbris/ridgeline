"""3d: the product is installable, and one version string is the engine's identity.

D-3 / R-6 ruled the product pip-installable, and the roadmap put 3d before stage 4 so the
third-project proof exercises the **installed** product rather than a checkout - otherwise the
F-H class (literal paths, machine assumptions) stays invisible until a user finds it.

These are the cheap structural halves, in the stage lane. The expensive half - build a wheel,
install it into an empty interpreter, and run the deliverable from it - is A-3, and its
transcript is in the 3d running record: it needs a network install and a five-minute engine run,
which is not a per-stage gate.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"


@pytest.fixture(scope="module")
def project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# --- A-2: one version string ---------------------------------------------------------------

def test_the_version_lives_in_one_place(project):
    """`pyproject.toml` reads it from `src/__init__.py`; a literal here would be a second copy
    that drifts from the running code the first time either moves."""
    assert "version" in project["project"]["dynamic"], (
        "version is static in pyproject.toml, so it is typed twice")
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "src.__version__"}
    assert "version" not in project["project"], "a literal version survives alongside the dynamic one"


def test_the_engine_exposes_its_version():
    import src

    assert isinstance(src.__version__, str) and src.__version__, "src.__version__ is unusable"
    parts = src.__version__.split(".")
    assert len(parts) >= 2 and all(p.isdigit() for p in parts[:2]), src.__version__


def test_the_version_is_what_an_installed_run_can_attest_to():
    """Why A-2 is a property and not packaging tidiness.

    Both places this repository records "what produced this number" resolve identity through
    git, and both go silent on an installed copy where there is no repository to ask. That is
    not hypothetical - it is what an installed engine's provenance manifest would carry.
    """
    import src
    from src.am import _provenance

    source = Path(_provenance.__file__).read_text(encoding="utf-8")
    assert "git" in source, (
        "_provenance no longer resolves identity through git; if it now has a non-git "
        "fallback, this test should assert that instead")
    assert src.__version__, (
        "there is no version for an installed run to attest to when git returns nothing")


# --- A-1: the package declares what it is ---------------------------------------------------

def test_requires_python_matches_the_interpreter_that_is_actually_tested(project):
    """Ruled 05/09: >=3.12, widened only when something runs the suite lower.

    `requires-python` is enforced by pip at INSTALL. An untested floor lets a user install
    successfully and fail later on their own machine; widening it later breaks nobody, and
    narrowing it breaks everyone who already installed. PY313-01 is this claim having been
    false once already.
    """
    assert project["project"]["requires-python"] == ">=3.12"


def test_the_package_is_marked_private(project):
    """The repository is private (SPEC §7a) and a public release is a fresh-history snapshot,
    never a visibility flip. The classifier is belt and braces against an accidental upload."""
    assert "Private :: Do Not Upload" in project["project"]["classifiers"]


def test_the_licence_is_declared_and_present(project):
    assert project["project"]["license"] == {"file": "LICENSE"}
    licence = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "PolyForm Noncommercial License 1.0.0" in licence
    assert "Required Notice: Copyright (c) 2026 Stephen Parton" in licence
    assert "MIT License" not in licence
    assert "S" + "JP Consulting" not in licence, "the licence names a holder that is no longer the Director's"
    # The classifier must not claim a licence the file no longer grants.
    assert not any("MIT" in c for c in project["project"]["classifiers"])


def test_the_distribution_carries_the_product_name_and_its_author(project):
    """RIDGELINE-01 P1 (R-11, R-13): the distribution is `ridgeline`, authored by Stephen Parton.
    Nothing that runs is renamed (D-4): the entry point stays `outturn-gate`."""
    assert project["project"]["name"] == "ridgeline"
    assert project["project"]["authors"] == [{"name": "Stephen Parton"}]
    assert "Ridgeline" in project["project"]["description"]
    assert project["project"]["scripts"] == {"outturn-gate": "src.final.deliverable:_cli"}


def test_dependencies_come_from_the_declared_requirements(project):
    """One source. A second list in pyproject is how the installed closure and the locked one
    come to differ without anyone editing either."""
    assert "dependencies" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["dependencies"] == {
        "file": ["requirements.txt"]}


def test_packages_are_listed_explicitly_not_auto_discovered(project):
    """The repository root holds scripts, notebooks, fixtures and a dashboard that are not the
    package; auto-discovery would sweep some of them in."""
    packages = project["tool"]["setuptools"]["packages"]
    assert "src" in packages and "tools" in packages
    for not_a_package in ("tests", "scripts", "dashboard", "docs"):
        assert not any(p == not_a_package or p.startswith(f"{not_a_package}.") for p in packages), (
            f"{not_a_package} is declared as part of the distribution")


# --- B: the dependency surface ---------------------------------------------------------------

def test_the_notebook_runtime_is_a_product_dependency():
    """B-1, and the finding 3c closed on: the product's one report path is a notebook rendered
    by nbconvert (R-2), so a clean product install that lacks it cannot produce the deliverable
    at all. All three, because nbconvert EXECUTES the notebook - that needs a kernel and the
    format reader, and declaring nbconvert alone would install fine and fail at --execute.
    """
    req = (REPO / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("nbconvert", "nbformat", "ipykernel"):
        assert pkg in req, f"{pkg} is not a product dependency, so a clean install cannot render"


def test_there_is_exactly_one_lock():
    """B-2. Two tracked locks is how the wrong one gets installed."""
    locks = sorted(p.name for p in REPO.glob("requirements-lock-*.txt"))
    assert len(locks) == 1, f"expected one lock, found {locks}"


def test_the_lock_carries_the_notebook_runtime():
    """The half that makes B-1 real: declaring it in requirements.txt but not pinning it in the
    lock would leave the locked install unable to render, which is the state 3d found."""
    lock = next(REPO.glob("requirements-lock-*.txt")).read_text(encoding="utf-8").lower()
    for pkg in ("nbconvert==", "nbformat==", "ipykernel=="):
        assert pkg in lock, f"{pkg[:-2]} is not pinned in the lock"


def test_the_lock_records_how_it_was_cut():
    """B-3. A lock without its interpreter and platform is not reproducible, and a quoted
    environment missing either is non-comparable rather than merely unverified."""
    lock = next(REPO.glob("requirements-lock-*.txt")).read_text(encoding="utf-8")
    head = lock[:2000]
    for field in ("interpreter", "platform", "cut on"):
        assert field in head, f"the lock header does not record {field!r}"


def test_the_lock_installs_off_windows():
    """LOCKPLAT-01. `pip freeze` drops environment markers, so the 05/09 cut pinned `pywin32`
    bare and the lock could not install on any machine but Windows - RS-C's second-machine run
    on the Mac died at `pip install` (03/09). Evaluated as macOS and Linux evaluate it, no
    Windows-only distribution may survive; evaluated as Windows does, it must, so the Windows
    closure every committed number was produced on is unchanged. A re-cut by freeze strips the
    marker again, and this is what says so.
    """
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    windows_only = {"pywin32", "pywinpty", "pywin32-ctypes"}
    lock = next(REPO.glob("requirements-lock-*.txt")).read_text(encoding="utf-8")
    reqs = [Requirement(ln) for ln in (s.strip() for s in lock.splitlines()) if ln and not ln.startswith("#")]

    def installed_on(env: dict) -> set[str]:
        return {canonicalize_name(r.name) for r in reqs if r.marker is None or r.marker.evaluate(env)}

    for env in (
        {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix"},
        {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"},
    ):
        leaked = installed_on(env) & windows_only
        assert not leaked, f"{sorted(leaked)} would install on {env['sys_platform']}: no wheel exists there"
    windows = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"}
    assert "pywin32" in installed_on(windows), "the Windows closure lost pywin32"


def test_weasyprint_is_gone_and_stays_gone():
    """D-12 retired the PDF and 3c Part A deleted its only importer. Declaring it again would
    be re-adding a dependency for a feature that was removed by ruling."""
    for name in ("requirements.txt", "requirements_client.txt"):
        assert "weasyprint" not in (REPO / name).read_text(encoding="utf-8").lower(), name
    # Match an IMPORT, not the bare word - this file names it repeatedly and the first version
    # was its own hit, the same self-reference the Part B root guard had to split a literal to
    # avoid. An import is also the thing that actually matters: a mention in prose is fine.
    import re

    pattern = re.compile(r"^\s*(?:import\s+weasyprint|from\s+weasyprint\b)", re.M)
    importers = [
        p.relative_to(REPO).as_posix()
        for p in REPO.rglob("*.py")
        if ".venv" not in p.parts
        and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert importers == [], f"weasyprint is imported again by {importers}"


def test_win32com_is_dev_and_windows_only():
    dev = (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pywin32" in dev, "win32com's provider is not declared"
    assert 'sys_platform == "win32"' in dev, (
        "pywin32 has no platform marker, so a POSIX dev install fails on a package that "
        "cannot build there")
    assert "pywin32" not in (REPO / "requirements.txt").read_text(encoding="utf-8"), (
        "pywin32 is a product dependency; nothing the product runs imports win32com")
