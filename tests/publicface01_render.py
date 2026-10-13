"""Render a shipped project's production deliverable the way ``RUN_FINAL.bat`` does (PUBLICFACE-01).

The same notebook, the same nbconvert flags, the same committed fixtures; only the iteration count
is lower, because what is scanned is text and the pinned values are taken at that count. The
artefacts are copied out of ``outputs/`` because every production run writes the same dated paths
there and the next run would overwrite them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from tests.tools.outputs_writeset import snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = REPO_ROOT / "outputs"
ITERATIONS = "1000"

FIXTURES = {
    "synthetic_wind": ("synthetic_wind", "wind_register.xlsx", "wind_schedule.xer"),
    "synthetic_road": ("synthetic_road", "road_register.xlsx", "road_schedule.xer"),
}

#: What a public reader must not meet (P2). Matched on text with image blobs removed, because a
#: base64 image contains any three letters by chance.
#: A third party's initials, built so this file does not carry them.
THIRD_PARTY = "S" + "JP"
PUBLIC_FACE_MARKS = {
    THIRD_PARTY: re.compile(THIRD_PARTY),
    "indicative classification": re.compile(r"indicative classification", re.I),
    "Dummy Realistic": re.compile(r"Dummy[ _]Realistic", re.I),
}
_BLOB = re.compile(r"[A-Za-z0-9+/=]{200,}")


@dataclass(frozen=True)
class Rendered:
    project: str
    html: Path
    others: tuple[Path, ...]  # .docx and .html the run wrote besides the report
    cache_dir: Path

    def artefacts(self) -> tuple[Path, ...]:
        return (self.html, *self.others)


def text_of(path: Path) -> str:
    """The readable text of an artefact: a .docx's XML parts, or an HTML file, blobs removed."""
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as z:
            raw = "\n".join(
                z.read(n).decode("utf8", "ignore")
                for n in z.namelist() if n.endswith((".xml", ".rels")))
    else:
        raw = path.read_text(encoding="utf8", errors="ignore")
    return _BLOB.sub("<blob>", raw)


def marks_in(path: Path) -> dict[str, int]:
    text = text_of(path)
    return {name: len(rx.findall(text)) for name, rx in PUBLIC_FACE_MARKS.items()}


def render(project: str, dest: Path) -> Rendered:
    """Execute ``final_runner.ipynb`` for ``project`` once and return copies of what it wrote."""
    folder, register, schedule = FIXTURES[project]
    fx = REPO_ROOT / "tests" / "fixtures" / folder
    env = {
        **os.environ,
        "QRA_PROJECT": project,
        "REGISTER_FILE": str(fx / register),
        "P6_FILE": str(fx / schedule),
        "STRAWMAN_FILE": str(fx / register),
        "SR9_ITERATIONS": ITERATIONS,
        # CONFIGTRUTH-01: unset is now a drawn seed, and the pins below were taken at 42.
        "SR9_SEED": "42",
    }
    env.pop("FINAL_REPORT_MODE", None)
    env.pop("FINAL_REPORT_HEADLINE_METRIC", None)
    dest.mkdir(parents=True, exist_ok=True)
    html = dest / f"{project}_report.html"
    before = snapshot(str(OUTPUTS))
    done = subprocess.run(
        [sys.executable, "-m", "nbconvert", "--to", "html", "--execute", "--allow-errors",
         "--no-input", "--TagRemovePreprocessor.enabled=True",
         "--TagRemovePreprocessor.remove_cell_tags=dev-note",
         "--template-file", "report_html.j2", "--ExecutePreprocessor.timeout=900",
         str(REPO_ROOT / "final_runner.ipynb"),
         "--output", html.name, "--output-dir", str(dest)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env)
    if done.returncode != 0 or not html.exists():
        raise AssertionError(f"nbconvert failed for {project}:\n{done.stderr[-3000:]}")

    now = snapshot(str(OUTPUTS))
    written = sorted(
        Path(k).relative_to(REPO_ROOT).as_posix()
        for k in now if k not in before or now[k] != before[k])
    keep = dest / "artefacts"
    keep.mkdir(exist_ok=True)
    others = []
    for rel in written:
        p = Path(rel)
        if p.parent.as_posix() == "outputs" and p.suffix.lower() in (".docx", ".html") \
                and "deliverable" not in p.name:
            shutil.copy2(REPO_ROOT / rel, keep / p.name)
            others.append(keep / p.name)
    caches = sorted({m.group(1) for r in written if (m := re.match(r"outputs/runs/([^/]+)/", r))
                     and m.group(1).endswith(project)})
    if len(caches) != 1:
        raise AssertionError(f"expected one state cache for {project}, wrote {caches}")
    cache = keep / "runs" / caches[0]
    shutil.copytree(OUTPUTS / "runs" / caches[0], cache)
    return Rendered(project, html, tuple(others), cache)


#: What a complete production run writes besides the report HTML, as file-name patterns.
REQUIRED_ARTEFACTS = (
    r"BETA_executive_summary_.*\.docx",
    r"sra_stage3_standalone_.*\.docx",
    r"sra_stage3_standalone_.*\.html",
)
#: How an error cell reads in the rendered HTML under this template (measured on a planted raise).
ERROR_MARK = re.compile(r"Traceback \(most recent call last\)")


def incomplete(rendered: Rendered) -> list[str]:
    """Why a run cannot be scanned as a whole: an artefact not written, or a cell that errored.

    The notebook runs with ``--allow-errors`` (a failed cross-validation must still write its
    bannered report), so a crash after the first cells leaves an HTML that exists and a scan over
    it that is green over an incomplete run. A scan test calls this first, in its own body.
    """
    names = [p.name for p in rendered.others]
    problems = [f"not written: {pattern}" for pattern in REQUIRED_ARTEFACTS
                if not any(re.fullmatch(pattern, n) for n in names)]
    if ERROR_MARK.search(rendered.html.read_text(encoding="utf8", errors="ignore")):
        problems.append("a notebook cell produced an error output")
    return problems


def headline_stats(cache_dir: Path) -> dict[str, str]:
    """``float.hex`` of the Stage 3 mean / P80 / P95, cost and schedule, from the state cache."""
    import numpy as np
    import pandas as pd

    out: dict[str, str] = {}
    pre = cache_dir / "composed.integrated_section.stage3"
    for axis, name in (("cost", "cost_dollars_array"), ("schedule", "schedule_days_array")):
        arr = pd.read_parquet(f"{pre}.{name}.parquet").to_numpy().ravel().astype(float)
        out[f"{axis}_mean"] = float(arr.mean()).hex()
        out[f"{axis}_p80"] = float(np.percentile(arr, 80)).hex()
        out[f"{axis}_p95"] = float(np.percentile(arr, 95)).hex()
    return out
