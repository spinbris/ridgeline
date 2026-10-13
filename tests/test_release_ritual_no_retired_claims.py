"""Release-ritual guard: quotable generated outputs carry no retired claims.

The release ritual for the wind showcase (and any quotable artefact set):

    1. Check out the final merge SHA (a clean tree - no dirty attestation).
    2. Regenerate the quotable outputs at that SHA
       (``WIND_ITERATIONS=100000 python scripts/run_wind_showcase.py``), so
       ``outputs/wind_showcase/wind_run_meta.json`` stamps the release
       ``engine_sha`` and the disclosure notes are re-emitted from the current
       (corrected) generator strings.
    3. This test then greps every generated ``outputs/**/*.md`` for RETIRED
       claims and fails if any survive.

Why it exists: the WT-002 "MonteCarloEngine overstated / the integrated
sampler is the correct one" reasoning was INVERTED (COST-01 / WIND-06). The
generator strings were corrected, but a stale ``outputs/*.md`` regenerated from
an old checkout - or a future edit that reintroduces the claim - would ship the
wrong statement in a quotable artefact. This locks it out.

If no generated ``outputs/*.md`` are present (fresh clone / CI without a
showcase run), the test SKIPS: there is nothing quotable to guard yet. Run the
showcase first (release-ritual step 2) to make the guard bite.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_OUTPUTS_DIR = Path(__file__).resolve().parents[1] / "outputs"

# Distinctive phrases from the retired / inverted recurrence verdict. Matched
# case-insensitively against generated markdown. These must never appear in a
# quotable artefact again (the truth: the standalone engine HONOURS recurrence
# and is the reference; the integrated engine is the laggard - see COST-01).
# Distinctive PHRASES only (no bare numerics): a coincidental figure must not
# trip the guard. The inverted "$735k" lived in a .py docstring / the COST-01
# verdict, never in a generated output .md, so it is not listed here - it is
# guarded at source (the corrected docstring) and by code review.
_RETIRED_CLAIMS = [
    r"the integrated sampler is the correct one",
    r"overstated one risk",
    r"retired standalone cost mc",
    r"unbounded sampler",
    r"impossible for that distribution",
]


def _generated_markdown() -> list[Path]:
    if not _OUTPUTS_DIR.is_dir():
        return []
    return sorted(_OUTPUTS_DIR.rglob("*.md"))


def test_no_retired_claims_in_generated_outputs():
    md_files = _generated_markdown()
    if not md_files:
        pytest.skip(
            "no generated outputs/*.md present; run the showcase "
            "(release-ritual step 2) to make this guard bite"
        )
    offenders: list[str] = []
    for md in md_files:
        text = md.read_text(encoding="utf-8", errors="replace").lower()
        for pat in _RETIRED_CLAIMS:
            if re.search(pat, text):
                rel = md.relative_to(_OUTPUTS_DIR.parent)
                offenders.append(f"{rel}: retired claim /{pat}/")
    assert not offenders, (
        "retired/inverted claims found in quotable outputs (regenerate at the "
        "final merge SHA from the corrected generators):\n  "
        + "\n  ".join(offenders)
    )
