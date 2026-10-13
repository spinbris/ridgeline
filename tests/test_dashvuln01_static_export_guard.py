"""
DASHVULN-01 guard: the dashboard's static-export posture is load-bearing on security.

`npm audit` reports two CRITICAL Next.js advisories - unauthenticated RCE on
windows-hosted servers, and unauthenticated RCE in the Image Optimization API.
Neither applies to this product, and the reason is two lines of
`dashboard/next.config.ts`:

    output: "export"              -> no Next.js server runs; Vercel serves static files
    images: { unoptimized: true } -> the image optimizer is not in play

The ledger accepts those advisories ON THAT BASIS (DASHVULN-01). Remove either
line and both criticals go live the same day. This test is what makes the
acceptance durable: it reds when the premise stops holding, so the row gets
re-read rather than silently falsified.

Deliberately a text assertion in pytest rather than a vitest test. A JS test
skips wherever node, npm or `dashboard/node_modules` is absent - a fresh clone,
the Mac, CI - and the stage lane carries no `-rs`, so those runs would report
green with the guard silently missing (the part D review note).
This one cannot skip.

Comments are stripped before matching. The first draft of this guard did not do
that, and its red-first probe PASSED when `output: "export",` was commented out -
the string was still in the file. A guard that a `//` defeats is not a guard.
"""

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "dashboard" / "next.config.ts"


def _code_only() -> str:
    """The config with comments removed, so a commented-out setting cannot satisfy a match."""
    assert CONFIG.is_file(), f"DASHVULN-01: {CONFIG} is missing; the guard cannot check its premise"
    text = CONFIG.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(line.split("//", 1)[0] for line in text.split("\n"))


def test_dashboard_is_a_static_export() -> None:
    """`output: "export"` is why the windows-hosted-server RCE cannot apply."""
    assert re.search(r'output\s*:\s*"export"', _code_only()), (
        'DASHVULN-01: `output: "export"` is no longer active in dashboard/next.config.ts. '
        "A Next.js server now runs, and GHSA-p293-qw3h-jr36 (unauthenticated RCE on "
        "windows-hosted servers) is live. Re-read the DASHVULN-01 row before changing this."
    )


def test_dashboard_images_are_unoptimized() -> None:
    """`images.unoptimized` is why the Image Optimization API RCE cannot apply."""
    assert re.search(r"unoptimized\s*:\s*true", _code_only()), (
        "DASHVULN-01: `images: { unoptimized: true }` is no longer active in "
        "dashboard/next.config.ts. The image optimizer is in play, and GHSA-2xp9-vwfh-vxw4 "
        "(unauthenticated RCE in the Image Optimization API via AVIF) is live. "
        "Re-read the DASHVULN-01 row before changing this."
    )


def test_a_commented_out_setting_does_not_satisfy_the_guard() -> None:
    """The defect the first draft had, pinned so it cannot come back."""
    assert not re.search(r'output\s*:\s*"export"', _strip('// output: "export",'))
    assert not re.search(r"unoptimized\s*:\s*true", _strip("/* unoptimized: true, */"))


def _strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(line.split("//", 1)[0] for line in text.split("\n"))
