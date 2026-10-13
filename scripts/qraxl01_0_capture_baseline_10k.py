"""Capture the REG04 §3a.3 10k bit-identity baseline (the fast per-sprint gate).

Writes tests/fixtures/qraxl01_0_baseline_10k.json (wind + RefProject at 10,000 iters,
standard seed) - the reference for tests/test_qraxl01_0_bit_identity_10k.py. Reuses the
100k capture wiring verbatim (qraxl01_0_capture_baseline.capture_wind) at n=10k,
so the two baselines cannot diverge in method. The 100k baseline
(qraxl01_0_capture_baseline.py) stays the milestone/client-release capture.

Run:  python scripts/qraxl01_0_capture_baseline_10k.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.qraxl01_0_capture_baseline as cap  # noqa: E402

N_ITER = 10_000
OUT = REPO_ROOT / "tests" / "fixtures" / "qraxl01_0_baseline_10k.json"


def main() -> int:
    fixture = {
        "purpose": (
            "REG04 3a.3 10k bit-identity gate - the FAST per-sprint value-neutrality "
            "gate (seeded RNG + untouched read path, so 10k proves value-neutrality as "
            "exactly as 100k). The 100k fixture qraxl01_0_baseline.json is the "
            "milestone/client-release check. Regenerate: python "
            "scripts/qraxl01_0_capture_baseline_10k.py"
        ),
        "captured_on": cap._provenance(),
        "fingerprint_n": cap.FINGERPRINT_N,
    }
    print(f"[wind] capturing at {N_ITER} iters...")
    fixture["wind_showcase"] = cap.capture_wind(N_ITER)

    # newline="\n" - see the note in qraxl01_0_capture_baseline.py.
    OUT.write_text(
        json.dumps(fixture, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    w = fixture["wind_showcase"]
    print(f"\nwind  cost P80 = {w['cost_arm_p80']!r}")
    print(f"wind  joint P80 = {w['integrated_total_p80']!r}")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
