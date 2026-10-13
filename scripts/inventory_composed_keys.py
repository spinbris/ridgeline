"""Write the inventory of composed keys the HTML body can show (DELIVFIX-01, FW-20).

    .venv\\Scripts\\python.exe scripts\\inventory_composed_keys.py

Composes a deliverable for each shipped project at a small iteration count and records every key
inside a section the notebook renders - ``src.final.html_blocks.key_paths`` - to
``tests/fixtures/delivfix01_composed_keys.json``. The fast label test reads that file, so it
needs no composed report of its own; the slow drift test re-composes and reds if the committed
file no longer matches what the composer produces.

Regenerate by running this, never by hand-editing the file (the test discipline).
Numbers do not reach the file - only key names - so the iteration count only buys speed.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT = REPO / "tests" / "fixtures" / "delivfix01_composed_keys.json"
NOTEBOOK = REPO / "final_runner.ipynb"
ITERATIONS = "2000"
#: (binding, fixture directory, file stem) - the two shipped projects' committed inputs.
PROJECTS = (
    ("synthetic_road", "synthetic_road", "road"),
    ("synthetic_wind", "synthetic_wind", "wind"),
)


def rendered_sections(notebook: Path = NOTEBOOK) -> list[str]:
    """The composed keys the notebook renders: its ``show("...")`` calls and its ``PAGES``."""
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    source = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    shown = re.findall(r'^show\("(\w+)"', source, flags=re.MULTILINE)
    pages = re.findall(r'^\s+\("(page\d\w*)", "', source, flags=re.MULTILINE)
    return sorted(set(shown) | set(pages))


def compose_one(binding: str, fixture_dir: str, stem: str, output_dir: Path) -> dict:
    from src.final.deliverable import run_deliverable

    d = REPO / "tests" / "fixtures" / fixture_dir
    env = {
        "QRA_PROJECT": binding,
        "REGISTER_FILE": str(d / f"{stem}_register.xlsx"),
        "P6_FILE": str(d / f"{stem}_schedule.xer"),
        "STRAWMAN_FILE": str(d / f"{stem}_register.xlsx"),
        "SR9_ITERATIONS": ITERATIONS,
    }
    importlib.import_module(f"src.sra.cpm.bindings.{binding}")  # self-registers
    saved = os.environ.get("QRA_PROJECT")
    os.environ["QRA_PROJECT"] = binding
    try:
        return run_deliverable(env=env, output_dir=output_dir).composed
    finally:
        if saved is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = saved


def inventory(output_dir: Path) -> dict:
    from src.final.html_blocks import key_paths

    sections = rendered_sections()
    paths: set[str] = set()
    for binding, fixture_dir, stem in PROJECTS:
        composed = compose_one(binding, fixture_dir, stem, output_dir / binding)
        paths.update(key_paths(composed, sections))
    return {
        "generated_by": "scripts/inventory_composed_keys.py",
        "projects": [p[0] for p in PROJECTS],
        "sections": sections,
        "paths": sorted(paths),
    }


def serialise(data: dict) -> bytes:
    return (json.dumps(data, indent=1) + "\n").encode("utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        data = inventory(Path(tmp))
    before = OUT.read_bytes() if OUT.exists() else b""
    after = serialise(data)
    OUT.write_bytes(after)  # bytes, so the file is LF on every platform
    print(f"wrote {OUT.relative_to(REPO).as_posix()}: {len(data['paths'])} paths, "
          f"{len(before)} -> {len(after)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
