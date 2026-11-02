"""Regenerate tests/golden/wind_register_polished.xlsx from the committed wind fixture.

WINDREAL-01 (Director-approved 01/11/2026). The original snapshot was polished by hand
in Excel from the pre-WINDREAL fixture, so no script could rebuild it once the fixture's
inputs changed. From here it is a regression snapshot: ``polish()`` applied to the
committed fixture, so ``tests/test_polish.py::test_fidelity`` catches any later change
to the polish layer or the scaffold. Run only with Director sign-off, like a golden.

Run:  python scripts/regen_polish_golden.py
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.register_polish import polish  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"
GOLDEN = ROOT / "tests" / "golden" / "wind_register_polished.xlsx"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "absent"


def main() -> int:
    before = _sha(GOLDEN)
    shutil.copyfile(FIXTURE, GOLDEN)
    polish(str(GOLDEN))
    print(f"wrote {GOLDEN.relative_to(ROOT)}: sha256 {before} -> {_sha(GOLDEN)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
