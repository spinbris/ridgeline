"""WS4-A reproducibility gate for a period JSON - the mask behind the period golden.

Named for workstream WS4-A of the archived showcase-P4 brief, where it began as the engagement's
active-management gate. It now masks the wind period golden (tests/test_7a_period_json_golden.py).

Diff a freshly-generated period JSON against a frozen baseline, masking the
two non-deterministic provenance fields, and report PASS/FAIL.

The period JSON is deterministic in every field except a small set of
provenance fields that echo the run clock / a random id, not the engine:

  Pure provenance (ALWAYS masked):
    - meta.engine_run_hash  (uuid.uuid4(),  json_writer.py)
    - meta.engine_run_date  (datetime.now(), run_period.py)

  Run-date-derived (masked with --mask-rundate):
    - meta.period_end_date          (the AM template carries no
      am_period_end, so run_period.py defaults period_end to the run
      date; on 2026-05-28 -> "2026-05-28", today -> the current date)
    - trend.periods[*].period_end   (the current period's entry echoes
      meta.period_end_date)

  Additive identity/attestation (ALWAYS popped; baseline predates them):
    - meta.project_display_name                              (showcase-P5)
    - meta.tornado_sample_sigma_days  [per risks[] entry]    (AM04, interim)
    - meta.{engine_sha, engine_sha_pinned, engine_sha_matches_pin,
      engine_tree_dirty, input_sha256}                       (AM09)
    - schema_version  [top level]                            (AM09)
  These carry NO figure. BOUNDARY: the allowlist is meta-only + the
  top-level schema_version string; every NUMBER stays bit-locked. The AM09
  provenance CLAIM is witnessed separately on the served files, not here.
  period_end_date feeds NO computed value: headline / distribution dates
  use the fixed project_start (2024-01-01) + engine finish hours; delta /
  trend glob the output dir. So masking it removes a clock artifact, not
  an engine result. (This blank-am_period_end behaviour is itself a
  finding for WS4-C: wind period workbooks must populate am_period_end.)

With the appropriate mask, a re-run on a bit-identical engine MUST be
byte-identical to the baseline. If anything ELSE moves, a change reached a
covered surface - follow GOLDEN01 rule 4 (the failure protocol): stop, report
the diff, and wait; do not edit the baseline, add a tolerance, or work around it.

Usage:
    python scripts/ws4a_repro_gate.py <baseline.json> <candidate.json>
    python scripts/ws4a_repro_gate.py <baseline.json> <candidate.json> --mask-rundate

Run it BOTH ways: the minimal mask shows the Director exactly what differs
(should be only the run-date fields); --mask-rundate proves engine
bit-identity. Exit 0 = PASS; 1 = FAIL (moved); 2 = usage / load error.
Re-runnable by the adversarial verifier lane (guardrail 4); no side effects.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MASKED_META_FIELDS = ("engine_run_hash", "engine_run_date")
RUNDATE_META_FIELDS = ("period_end_date",)
# Presentational fields that carry NO figure and are POPPED (not sentinel-
# masked) from both docs before diffing, so their presence/absence/value is
# fully neutralised. showcase-P5 WS5-C added meta.project_display_name: a
# fresh re-run emits it, but the frozen inaugural baseline predates
# it (field-less). Popping it keeps the figure-reproducibility gate green
# without weakening it (it is chrome, like engine_run_hash/date).
#
# AM09 (2026-07-09, Director-approved): the engine-provenance meta fields are
# added here (five then; three since RS-A2 P-3 dropped the two pin fields). The frozen inaugural baseline predates them (field-less), and
# a stamped re-run emits them, so popping neutralises presence/absence/value -
# exactly the project_display_name case. They are meta identity/attestation,
# NOT engine output. BOUNDARY (do not widen past these named fields): the
# allowlist is meta-only plus the top-level schema_version string (see
# NEUTRALISED_TOPLEVEL_FIELDS); EVERY number - headline, risks, activities,
# distribution, delta, trend - stays bit-locked and unmasked. The provenance
# CLAIM (engine_sha / engine_tree_dirty) is witnessed separately on the served
# files, not relaxed here.
NEUTRALISED_META_FIELDS = (
    "project_display_name",
    # Stage 7 part C (B-2), contract 1.4: `meta.project_key`. The SAME case as
    # `project_display_name` directly above, on the same reasoning - it is meta identity,
    # it carries no figure, and the frozen inaugural baseline predates it, so a fresh
    # keyed run would otherwise red this gate on a field that decides nothing numeric.
    # Widening the boundary this once, and only to a field of the class the boundary
    # already admits: every number stays compared, unmasked.
    "project_key",
    "engine_sha",
    "engine_sha_pinned",
    "engine_sha_matches_pin",
    "engine_tree_dirty",
    "input_sha256",
    # SEEDZERO-01 P3: where the period's seed came from (binding or --seed). The same class as
    # project_key above: it carries no figure and the frozen baseline predates it. The seed
    # itself stays compared.
    "seed_source",
)
# Top-level (non-meta) fields POPPED from both docs before diffing. AM09 bumped
# the contract string schema_version ("1.0" inaugural baseline -> "1.2"); it is
# a version label carrying no figure, so it is neutralised like the additive
# meta fields. NOTHING else top-level is listed here - the eight data blocks
# stay fully compared.
NEUTRALISED_TOPLEVEL_FIELDS = ("schema_version",)
# Per-risk fields POPPED from every risks[] entry before diffing, so their
# presence/absence/value is fully neutralised. AM04 added
# risks[].tornado_sample_sigma_days: a fresh re-run emits it, but
# the frozen inaugural baseline predates it (field-less). It is an AM-layer
# computed value (metrics.py + json_writer), not an engine byte-identity
# result, so its reproducibility belongs in the AM04 unit tests, not this
# ENGINE repro gate. Popping it keeps the gate green WITHOUT a 100k re-run and
# bakes in NO engine drift. The pin this comment once referred to no longer
# exists (RS-A2 P-3); re-freezing the baseline now would still contaminate it.
# This neutralisation is INTERIM per AM04 Director decision 5: fold the field
# back into the compared set at the next legitimate re-baseline.
NEUTRALISED_RISK_FIELDS = ("tornado_sample_sigma_days",)
_MASK = "<<masked>>"
_MAX_DIFFS = 50


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _mask(doc: dict[str, Any], *, mask_rundate: bool) -> dict[str, Any]:
    """Return a deep-ish copy with the volatile fields masked.

    Always masks the pure-provenance meta fields. With ``mask_rundate``,
    also masks the run-date-derived fields (meta.period_end_date and the
    matching trend.periods[*].period_end), so the diff isolates the engine
    output from the run clock.
    """
    out = json.loads(json.dumps(doc))  # cheap deep copy
    # AM09: neutralise the additive top-level version label (schema_version).
    for f in NEUTRALISED_TOPLEVEL_FIELDS:
        out.pop(f, None)
    # AM04: neutralise the additive per-risk sample-sigma field on every
    # risks[] entry (interim; see NEUTRALISED_RISK_FIELDS).
    risks = out.get("risks")
    if isinstance(risks, list):
        for r in risks:
            if isinstance(r, dict):
                for f in NEUTRALISED_RISK_FIELDS:
                    r.pop(f, None)
    meta = out.get("meta")
    masked_period_end = None
    if isinstance(meta, dict):
        for f in NEUTRALISED_META_FIELDS:
            meta.pop(f, None)  # remove entirely (presence/value neutralised)
        for f in MASKED_META_FIELDS:
            if f in meta:
                meta[f] = _MASK
        if mask_rundate:
            masked_period_end = meta.get("period_end_date")
            for f in RUNDATE_META_FIELDS:
                if f in meta:
                    meta[f] = _MASK
    if mask_rundate:
        trend = out.get("trend")
        if isinstance(trend, dict):
            for p in trend.get("periods", []):
                # Mask only the current period's date echo (the one that
                # equals this run's period_end_date); prior periods carry
                # their own committed dates and must still match.
                if isinstance(p, dict) and p.get("period_end") == masked_period_end:
                    p["period_end"] = _MASK
    return out


def _diff(a: Any, b: Any, path: str, acc: list[str]) -> None:
    if len(acc) >= _MAX_DIFFS:
        return
    if type(a) is not type(b) and not (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
    ):
        acc.append(f"{path}: type {type(a).__name__} != {type(b).__name__} "
                   f"({a!r} vs {b!r})")
        return
    if isinstance(a, dict):
        for k in a.keys() | b.keys():
            if k not in a:
                acc.append(f"{path}.{k}: missing in baseline (candidate={b[k]!r})")
            elif k not in b:
                acc.append(f"{path}.{k}: missing in candidate (baseline={a[k]!r})")
            else:
                _diff(a[k], b[k], f"{path}.{k}", acc)
    elif isinstance(a, list):
        if len(a) != len(b):
            acc.append(f"{path}: list length {len(a)} != {len(b)}")
        for i in range(min(len(a), len(b))):
            _diff(a[i], b[i], f"{path}[{i}]", acc)
    else:
        if a != b:
            acc.append(f"{path}: {a!r} != {b!r}")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    mask_rundate = "--mask-rundate" in argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    baseline_path, candidate_path = Path(args[0]), Path(args[1])
    try:
        baseline_raw = _load(baseline_path)
        candidate_raw = _load(candidate_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL (load error): {exc}")
        return 2

    # Sanity: confirm the candidate is a genuinely fresh run (the masked
    # fields differ from the baseline's). A match here would mean we diffed
    # the baseline against itself.
    b_meta = baseline_raw.get("meta", {})
    c_meta = candidate_raw.get("meta", {})
    fresh_evidence = {
        f: (b_meta.get(f), c_meta.get(f)) for f in MASKED_META_FIELDS
    }

    baseline = _mask(baseline_raw, mask_rundate=mask_rundate)
    candidate = _mask(candidate_raw, mask_rundate=mask_rundate)

    diffs: list[str] = []
    _diff(baseline, candidate, "", diffs)

    # Byte-level confirmation on the masked, canonically re-serialised form.
    b_bytes = json.dumps(baseline, indent=2, ensure_ascii=False, sort_keys=True)
    c_bytes = json.dumps(candidate, indent=2, ensure_ascii=False, sort_keys=True)
    byte_identical = b_bytes == c_bytes

    print(f"baseline : {baseline_path}")
    print(f"candidate: {candidate_path}")
    print(f"mask mode: {'provenance + run-date' if mask_rundate else 'provenance only (transparent)'}")
    print("provenance fields (must differ -> proves fresh run):")
    for f, (bv, cv) in fresh_evidence.items():
        marker = "OK-differs" if bv != cv else "WARN-SAME"
        print(f"  meta.{f}: baseline={bv!r} candidate={cv!r}  [{marker}]")

    if not diffs and byte_identical:
        print("\nWS4-A GATE: PASS - JSON bit-identical (masked provenance only).")
        return 0

    print(f"\nWS4-A GATE: FAIL - {len(diffs)} differing path(s) "
          f"(showing up to {_MAX_DIFFS}):")
    for d in diffs:
        print(f"  {d}")
    if not diffs and not byte_identical:
        print("  (value-equal but byte-differ: key ordering or numeric "
              "formatting drift)")
    print("\nThe period output moved: a change reached a covered surface. Follow "
          "GOLDEN01 rule 4 - stop, report the diff above, and wait. "
          "Do not edit the baseline, add a tolerance, or work around it.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
