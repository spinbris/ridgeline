"""Capture the SRA-02 AC-5 pinned SCHEDULE-ONLY baseline (brief A2.4, placed by A3.4).

Writes ``tests/fixtures/sra02_schedule_baseline_10k.json`` - the reference for
``tests/test_sra02_sc_schedule_baseline.py``.

Both limbs of AC-5 are required and neither alone is sufficient:

* **Consolidated path.** The entry is ``run_wind_showcase.run_integrated``, whose
  every schedule input comes from ``wind_register.xlsx`` - schedule scope and Mode
  from the ``Risk Register`` sheet, the CPM binding from ``Mapping``, run config
  from ``MC_Params`` (``run_wind_showcase.py:44-46``). That is the branch S-C2's
  ``Mapping.Gating_Activity_ID`` reader change lands on. The existing bit-identity
  gate captures RefProject through ``Risk_Scope`` instead, so it cannot see that
  change at all (brief A2.3).
* **Schedule-only values.** Everything pinned here comes from ``sched_days``, the
  schedule arm's own per-iteration array. The existing gate's
  ``integrated_total_*`` are ``cost + sched * day_rate``, so a schedule move
  reaches them only diluted through a combined aggregate and cannot be attributed
  to the schedule arm.

10,000 iterations, matching REG04 3a.3's ruling for the fast per-sprint gate: this
is a determinism/diff test on a seeded RNG, so 10k pins value-neutrality exactly as
well as 100k.

Values are stored as ``float.hex()`` strings, the golden harness convention - an
exactly round-trippable representation, so nothing can be lost or gained in the
JSON encoding and the comparison is unambiguous.

Run:  python scripts/sra02_capture_schedule_baseline.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.qraxl01_0_capture_baseline as cap  # noqa: E402

#: Matches the fast per-sprint bit-identity gate.
N_ITER = 10_000
OUT = REPO_ROOT / "tests" / "fixtures" / "sra02_schedule_baseline_10k.json"

#: Percentiles pinned off the schedule-only array.
_PCTS = (50, 80, 90)


def _hex(x: float) -> str:
    return float(x).hex()


def capture_wind_schedule(n_iter: int = N_ITER) -> dict:
    """Run the consolidated wind path and pin schedule-only statistics.

    The environment/binding dance mirrors ``cap.capture_wind`` exactly, including
    restoring ``QRA_PROJECT``: ``_activate_wind_binding`` sets it globally
    and a RefProject capture later in the same process would otherwise read the wind
    binding's drivers.
    """
    import scripts.run_wind_showcase as wind

    # run_wind_showcase freezes N_ITER at import, so if another test imported it
    # first the env var alone would not take. run_integrated reads N_ITER at call
    # time, so forcing the module global wins. Same reasoning as cap.capture_wind.
    #
    # Everything mutated here is restored. This is an instrument: it runs inside a
    # shared lane and must not leave WIND_ITERATIONS, N_ITER or the active project
    # binding altered for whatever runs next. cap.capture_wind restores only the
    # binding; a capture that quietly re-points a later test at 10k iterations is
    # the same class of state dependency the S-B close-out logged against
    # outputs/charts.
    _saved_iters_env = os.environ.get("WIND_ITERATIONS")
    _saved_n_iter = wind.N_ITER
    _saved_project = os.environ.get("QRA_PROJECT")
    os.environ["WIND_ITERATIONS"] = str(n_iter)
    wind.N_ITER = n_iter
    try:
        wind._activate_wind_binding()
        integ = wind.run_integrated()
    finally:
        wind.N_ITER = _saved_n_iter
        for _var, _val in (
            ("WIND_ITERATIONS", _saved_iters_env),
            ("QRA_PROJECT", _saved_project),
        ):
            if _val is None:
                os.environ.pop(_var, None)
            else:
                os.environ[_var] = _val

    sched = np.asarray(integ["sched_days"], dtype=float)
    cost = np.asarray(integ["cost"], dtype=float)

    return {
        "entry": (
            "scripts.run_wind_showcase.run_integrated -> sched_days "
            f"(consolidated register path, WIND_ITERATIONS={n_iter})"
        ),
        "seed": int(wind.SEED),
        # n_iter, not wind.N_ITER: the finally block above has already restored the
        # module global by this point, so reading it here would record the default.
        "iterations": int(n_iter),
        "day_rate": _hex(wind.DAY_RATE),
        "n_dual_coded": int(integ["n_dual"]),
        "inputs": {
            "register": {
                "path": cap._relpath(wind.WIND_REGISTER),
                "sha256": cap._sha256(Path(wind.WIND_REGISTER)),
            },
            "xer": {
                "path": cap._relpath(wind.WIND_XER),
                "sha256": cap._sha256(Path(wind.WIND_XER)),
            },
        },
        # --- the pin: schedule-only, nothing combined with cost -------------
        "schedule_days_first_n": [_hex(x) for x in sched[: cap.FINGERPRINT_N]],
        "schedule_days_mean": _hex(sched.mean()),
        "schedule_days_p50": _hex(np.percentile(sched, 50)),
        "schedule_days_p80": _hex(np.percentile(sched, 80)),
        "schedule_days_p90": _hex(np.percentile(sched, 90)),
        "schedule_days_max": _hex(sched.max()),
        "schedule_days_nonzero_count": int((sched > 0.0).sum()),
        # --- wiring cross-check, NOT part of the schedule pin ---------------
        # Proves this script reproduces the same run the existing 10k gate
        # captures. If the two wirings ever diverge, the test that compares this
        # against qraxl01_0_baseline_10k.json's wind cost_arm_p80 reds, rather
        # than the schedule pin silently drifting onto a different run.
        "cost_arm_p80_crosscheck": _hex(np.percentile(cost, 80)),
    }


def main() -> int:
    fixture = {
        "purpose": (
            "SRA-02 AC-5 pinned schedule baseline. Consolidated register path, "
            "schedule-only values, exact equality on float.hex(). Exists because "
            "the bit-identity gate is aggregate-only AND sits on the strawman "
            "branch, so it cannot see a schedule move on the consolidated path "
            "(brief A2.3/A2.4)."
        ),
        "captured_on": cap._provenance(),
        "fingerprint_n": cap.FINGERPRINT_N,
        "percentiles_pinned": list(_PCTS),
    }
    print(f"[wind/consolidated] capturing schedule-only baseline at {N_ITER} iters...")
    fixture["wind_consolidated_schedule"] = capture_wind_schedule(N_ITER)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" explicitly. The default translates to CRLF on Windows, which
    # trips the line-ending check: git ls-files --eol must report no w/crlf.
    OUT.write_text(
        json.dumps(fixture, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    w = fixture["wind_consolidated_schedule"]
    print(f"wrote {OUT}")
    print(f"  schedule days mean = {float.fromhex(w['schedule_days_mean']):.6f}")
    print(f"  schedule days P80  = {float.fromhex(w['schedule_days_p80']):.6f}")
    print(f"  nonzero iterations = {w['schedule_days_nonzero_count']}/{w['iterations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
