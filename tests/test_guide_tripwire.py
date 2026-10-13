"""The user guide is checked against the repository, so it cannot drift silently.

v1.1 of ``docs/SOFTWARE_USER_GUIDE.md`` went wrong in some sixty specific claims without a
single test going red, because nothing held it to the tree (GUIDE02 §2). The playbook has
``tests/test_stage5_playbook_tripwire.py``, which walks its fenced command blocks; this walks
the guide, which is prose with inline code spans rather than commands.

What it checks, and why each limb exists:

* **Repository paths and document pointers** named in inline code resolve - now held by
  ``tests/test_doc_paths.py``, which walks the guide, the spec and the playbook with one walker
  (REPORTDOC-01). ``PLAYBOOK.md:8`` cited ``docs/METHODOLOGY.md`` for months while the file sat at
  the repository root: a prose pointer, so the playbook's own fenced-block tripwire could not see
  it, and the spec had no check at all.
* **Sheet names** named in the guide exist in the shipped register template. The guide's §3.2
  table is the reader's map of the workbook.
* **Named ranges** the guide leans on exist in that template. ``MC_day_rate`` is the only thing
  in the workbook that reveals which column of ``MC_Params`` takes values.
* **Environment variables** the guide names are read by the runners.
* **Command flags** the guide documents are accepted by the entry point it attributes them to.
* **Tier 1 entry points** exist in the xlwings shell, under the names the task pane shows.
* **App routes** the guide tabulates have a page in the dashboard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "docs" / "SOFTWARE_USER_GUIDE.md"
TEMPLATE = REPO_ROOT / "templates" / "register_template.xlsx"

CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _spans(text: str) -> list[str]:
    return [m.group(1).strip() for m in CODE_SPAN.finditer(text)]


@pytest.fixture(scope="module")
def guide() -> str:
    assert GUIDE.exists(), f"the guide is missing: {GUIDE}"
    return GUIDE.read_text(encoding="utf-8")


def test_the_guide_has_code_spans_to_check(guide: str) -> None:
    """Guard the guard: a guide stripped of inline code would pass every limb vacuously."""
    assert len(_spans(guide)) > 50


def _section(text: str, heading: str) -> str:
    """The body under one heading, to the next heading of the same or higher level.

    The limbs below check the guide's own tables rather than a hand-kept list, so a sheet added
    to §3.2 is checked from the moment it is written.
    """
    start = text.index(heading)
    depth = len(heading) - len(heading.lstrip("#"))
    nxt = re.compile(r"^#{1,%d} " % depth, re.M)
    m = nxt.search(text, start + len(heading))
    return text[start : m.start() if m else len(text)]


def _sheet_names(path: Path) -> set[str]:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.load_workbook(path, read_only=True)
    try:
        return set(book.sheetnames)
    finally:
        book.close()


def test_every_register_sheet_the_guide_maps_exists(guide: str) -> None:
    """§3.2 is the reader's map of the workbook: every name in it must be a real sheet."""
    sheets = _sheet_names(TEMPLATE)
    mapped = {
        name.strip()
        for span in _spans(_section(guide, "### 3.2 The sheets"))
        for name in span.split(",")
        if name.strip()
    }
    assert len(mapped) >= 15, "§3.2 no longer maps the workbook's sheets"
    missing = sorted(n for n in mapped if n not in sheets)
    assert not missing, f"§3.2 names sheets the template does not have: {missing}"


def test_every_status_workbook_sheet_the_guide_names_exists(guide: str) -> None:
    """The period cycle's input is a contract; §9 names its sheets and they must be real."""
    openpyxl = pytest.importorskip("openpyxl")
    template = REPO_ROOT / "templates" / "status_workbook_template.xlsx"
    book = openpyxl.load_workbook(template, read_only=True)
    try:
        # Sheets and column headers both: the guide names an AM_ sheet in one breath and an
        # AM_ column in the next, and a reader cannot use either if it has been renamed.
        vocabulary = set(book.sheetnames)
        for sheet in book:
            for row in sheet.iter_rows(min_row=1, max_row=20, values_only=True):
                vocabulary.update(str(v).strip() for v in row if isinstance(v, str))
    finally:
        book.close()
    named = {s for s in _spans(_section(guide, "## 9. The status workbook")) if s.startswith("AM_")}
    assert len(named) >= 3, "§9 no longer names the status workbook's sheets"
    missing = sorted(n for n in named if n not in vocabulary)
    assert not missing, f"§9 names status-workbook sheets or columns that do not exist: {missing}"


def test_the_day_rate_cell_the_guide_gives_is_where_the_named_range_points(guide: str) -> None:
    """§3.3's cell map is every fill instruction in the guide.

    A scaffolder remap would leave the prose green and wrong, so the one cell the workbook itself
    discloses - the day rate, through ``MC_day_rate`` - is asserted against the template.
    """
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.load_workbook(TEMPLATE)
    try:
        defined = dict(book.defined_names)
    finally:
        book.close()
    for name in ("MC_day_rate", "Set_Layer1_Enabled"):
        assert name in guide, f"the guide no longer explains {name}"
        assert name in defined, f"the template no longer defines {name}"
    destination = str(defined["MC_day_rate"].attr_text)
    cell = re.search(r"\$([A-Z]+)\$(\d+)", destination)
    assert cell, f"MC_day_rate no longer points at a cell: {destination}"
    column, row = cell.group(1), cell.group(2)
    assert f"| {column}{row} |" in guide, (
        f"the template puts the day rate at {column}{row}, and the guide's cell map does not say so"
    )


def test_environment_variables_the_guide_names_are_read_by_the_runners(guide: str) -> None:
    runners = "\n".join(
        (REPO_ROOT / bat).read_text(encoding="utf-8", errors="ignore")
        for bat in ("RUN_FINAL.bat", "RUN_PERIOD.bat", "PUBLISH_PERIOD.bat")
    )
    sources = runners + (REPO_ROOT / "src" / "final" / "deliverable.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    # An environment variable, not a shouted literal like FALSE: every one of ours carries an
    # underscore, and requiring it keeps the limb off the guide's prose.
    named = {s for s in _spans(guide) if re.fullmatch(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", s)}
    assert {"QRA_PROJECT", "REGISTER_FILE", "P6_FILE", "STRAWMAN_FILE"} <= named
    unread = sorted(v for v in named if v not in sources)
    assert not unread, f"the guide names environment variables nothing reads: {unread}"


def test_flags_the_guide_documents_are_accepted(guide: str) -> None:
    run_final = (REPO_ROOT / "RUN_FINAL.bat").read_text(encoding="utf-8", errors="ignore")
    run_period = (REPO_ROOT / "src" / "am" / "run_period.py").read_text(encoding="utf-8", errors="ignore")
    publish = (REPO_ROOT / "src" / "am" / "publish_period.py").read_text(encoding="utf-8", errors="ignore")
    for flag, source, where in (
        ("--headline", run_final, "RUN_FINAL.bat"),
        ("--show-code", run_final, "RUN_FINAL.bat"),
        ("--allow-dirty", run_period, "run_period.py"),
        ("--replace", publish, "publish_period.py"),
        ("--deploy", publish, "publish_period.py"),
    ):
        assert flag in guide, f"the guide no longer documents {flag}"
        assert flag in source, f"{where} no longer accepts {flag}, which the guide documents"


def test_tier1_entry_points_exist_under_the_names_the_guide_gives(guide: str) -> None:
    shell = (REPO_ROOT / "src" / "tier1_xlwings_shell.py").read_text(encoding="utf-8")
    for entry in ("run_simulation", "run_simulation_100k", "validate_contract"):
        assert entry in guide, f"the guide no longer names the {entry} entry point"
        assert f"def {entry}(" in shell, f"the xlwings shell no longer defines {entry}"


def test_app_routes_the_guide_tabulates_have_pages(guide: str) -> None:
    routes = {s for s in _spans(guide) if s.startswith("/") and not s.startswith("//")}
    assert len(routes) >= 6, "the guide no longer tabulates the app routes"
    app = REPO_ROOT / "dashboard" / "app"
    missing = [r for r in routes if not (app / r.strip("/") / "page.tsx").exists()]
    assert not missing, f"the guide names app routes with no page: {sorted(missing)}"
