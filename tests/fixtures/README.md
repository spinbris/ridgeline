# Test fixtures - SR9 v3.1 baseline

Frozen v3.1 deliverable artefacts plus a pinned JSON of key numeric
values, used as regression-test ground truth for SR9 v3.2 dual-mode
work and any later cycles that touch the final report renderer.

## Files

| File | Source | Purpose |
|---|---|---|
| `runs/v31_baseline/` | derived from `sr9_state_cache_v31_baseline.pkl` via `scripts/sr9_v34_migrate_fixture.py` | **Canonical v3.1 state cache** in the SR9-v3.4 parquet+JSON layout. ~13 MB total across per-array parquets + `metadata.json` + `manifest.json`. New tests should read from this directory via `src.final.state_cache.read_state_cache`. |
| `sr9_state_cache_v31_baseline.pkl` | `outputs/sr9_state_cache_2026-04-26.pkl` | **Legacy** state cache (pre-SR9-v3.4 pickle). Retained for one release cycle to validate the legacy pickle reader path; new tests should use `runs/v31_baseline/` instead. |
| `v31_baseline_values.json` | derived from the legacy pickle | Small JSON of pinned scalar values for use in tests (avoids loading the full state cache on every test run). |
| `delivfix01_composed_keys.json` | `scripts/inventory_composed_keys.py` (both shipped projects, n=2,000) | **Key names only, no numbers**: every key a real compose puts inside a section the HTML body renders. Read by `test_delivfix01_html_blocks.py` so the label test needs no composed report; held to the composer by the slow `test_delivfix01_composed_keys_drift.py`. Regenerate by the script, never by hand (DELIVFIX-01). |

## SR9-v3.4 layout note

State cache persistence migrated from a single pickle to per-array
parquet + JSON metadata under SR9-v3.4 (April 2026). The canonical fixture
is `runs/v31_baseline/`; the legacy pickle is retained alongside as a
backward-compatibility safety net for one release cycle. See
`SCALABILITY.md` §3.2 / §4 / §5 and `ARCHITECTURE.md` §9 for the ADR.

## When to update the fixtures

Only when PM explicitly approves a change to the v3.1 expected text
content. For example: an upstream library version bump that produces
identical numerics but slightly different formatting; a deliberate
text-content change to a `commentary_text` constant.

To update:

```
# Regenerate the parquet+JSON state cache from the latest run:
cp -r outputs/runs/<date>{_PROD}/ tests/fixtures/runs/v31_baseline/
# (Or, to convert from a legacy pickle:)
cp outputs/sr9_state_cache_<date>.pkl tests/fixtures/sr9_state_cache_v31_baseline.pkl
python scripts/sr9_v34_migrate_fixture.py
```

`v31_baseline_values.json` has no regeneration script in this repository or either archive: the
one this README used to name does not exist anywhere. Neither v31 fixture is here - both froze at
the split, and the tests that read them skip (SKIPDEAD-01).

Document the regeneration reason in a CHANGELOG entry.
