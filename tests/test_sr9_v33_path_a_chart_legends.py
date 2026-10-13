"""SR-S3-Beta-11 §4 — PNG OCR regression test.

Charts in the prod docx leaked five SR9 v3.3 Path A forbidden phrases
("Dummy Realistic", the interim label, "PM review pending", "8S",
"3S/2H/3P") into their LEGENDS since SR9 v3.3 / 2026-04-25, despite
prod mode being active. The body-text invariant test in
``test_sr9_v33_path_a.py`` does not OCR embedded chart PNGs, so the
breach was live for ~7 days.

The main test extracted every embedded image from a prod docx built from the retired
register, OCRed each, and asserted zero hits on the v3.3 forbidden-phrase list. It could
only ever skip, and SNAPSHOTCUT-01 retired it (Director, 11/10/2026). The positive control
below remains: it proves the OCR pipeline can see a forbidden phrase, for whatever next
OCRs a chart.

Skip behaviour
--------------
The control SKIPs cleanly when:
  * pytesseract is not installed (``pytest.importorskip``)
  * the tesseract system binary is not on PATH (``shutil.which`` returns
    None) — Windows developer environments commonly lack tesseract;
    CI environments install it. The test runs whenever both are
    available.

OCR robustness
--------------
matplotlib stylised text is not always pixel-perfect, so the test
normalises (lowercase + strip non-alphanumeric) and uses substring
search. The test fails *closed* — any forbidden-phrase hit fails the
test. The test does NOT require pixel-perfect OCR; only that
forbidden phrases would be detectable when present. To verify, a
positive-control sub-test renders a chart with a forbidden phrase
and asserts the OCR catches it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

# Skip the entire module if pytesseract is not installed.
pytesseract = pytest.importorskip("pytesseract")

# SR9 v3.3 Path A forbidden phrases — must not appear in any prod chart
# legend. Mix-string literals ("8S", "3S/2H/3P", "1S/7P") encode the
# interim-label classification framing and are forbidden alongside the
# overt interim-label/PM-review framing.
FORBIDDEN_PHRASES = [
    "Dummy Realistic",
    "Dummy_Realistic",
    "S" + "JP indicative",
    "PM review pending",
    "PM review",
    "Mode classification",
    "indicative classification",
    "8S",
    "3S/2H/3P",
    "1S/7P",
]


def _normalise(s: str) -> str:
    """Lowercase + strip whitespace and non-alphanumeric punctuation
    EXCEPT '/' (so '3S/2H/3P' substring search still works)."""
    return re.sub(r"[^a-z0-9/]", "", s.lower())


def _phrase_in_ocr(phrase: str, ocr_text: str) -> bool:
    """Robust substring check: normalise both phrase and OCR text and
    look for the phrase as a substring of the OCR text. Robust to OCR
    spacing / capitalisation noise; case-insensitive."""
    return _normalise(phrase) in _normalise(ocr_text)


def _tesseract_available() -> bool:
    """True iff the tesseract binary is locatable on PATH."""
    return shutil.which("tesseract") is not None


# Skip everything in this file if tesseract is not on PATH.
pytestmark = pytest.mark.skipif(
    not _tesseract_available(),
    reason=(
        "tesseract binary not available on PATH; install per "
        "https://github.com/UB-Mannheim/tesseract/wiki (Windows) or "
        "`brew install tesseract` / `apt install tesseract-ocr` "
        "(macOS / Linux). The PNG OCR regression test SKIPs cleanly "
        "without it."
    ),
)


# ---------------------------------------------------------------------------
# Positive control — confirm OCR can detect a forbidden phrase when present
# ---------------------------------------------------------------------------

def test_ocr_detects_forbidden_phrase_in_synthetic_image(tmp_path: Path) -> None:
    """Positive control: render a matplotlib chart with one of the
    forbidden phrases as a label, OCR it, and confirm the phrase is
    detected. If this test fails we know the OCR pipeline itself is
    broken; otherwise the main test's "no forbidden phrases" assertion
    is meaningful.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot([0, 1], [0, 1], label="DP Review baseline (8S, " + "S" + "JP indicative)")
    ax.legend(loc="lower right", fontsize=14)
    out = tmp_path / "control.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)

    text = pytesseract.image_to_string(str(out))
    # OCR output may garble individual characters; check for any of the
    # forbidden phrases with the robust matcher. At least one should hit.
    hits = [p for p in FORBIDDEN_PHRASES if _phrase_in_ocr(p, text)]
    assert hits, (
        f"OCR did not detect any forbidden phrases in the positive "
        f"control image. OCR output:\n{text!r}\n"
        f"Pipeline check failed; the main test's no-hit assertion is "
        f"not meaningful until this is resolved."
    )


# ---------------------------------------------------------------------------
# Main test — extract PNGs from prod docx, OCR each, assert no forbidden phrases
# ---------------------------------------------------------------------------
