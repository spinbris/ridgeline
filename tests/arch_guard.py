"""ARM64ULP-01: the exact-sample pins are x86-64-only (Director, 11/09/2026).

The pinned 100k values and the wind 10k first-N samples were captured on x86-64. On arm64 (the
Apple M4, measured twice - 03/09 and 11/09 at `4a5cb77`) a handful of cost-layer percentiles and
single draws land 1-2 ULP away, while every base-layer value and every mean is bit-identical and
the goldens pass. A check that asserts exact equality on one sample cannot pass there as pinned,
and the Director ruled it x86-64-only rather than keeping a second set of pins. The cross-machine
gate is the goldens and the bit-identical means; these two checks are not.
"""
from __future__ import annotations

import math
import platform

import pytest

#: `platform.machine()` for x86-64: "AMD64" on Windows, "x86_64" on Linux and Intel macOS.
X86_64 = frozenset({"amd64", "x86_64"})

#: XPLATTOL-01 (Director, 12/10/2026): every golden and pin is blessed on x86-64 and is exact there.
#: On another architecture a value may land a few ULP away (the Mac's wind golden mean, 1 ULP), so
#: there it passes within one part in a billion: half a cent on $5M, far below any real code change.
CROSS_PLATFORM_RTOL = 1e-9


def is_x86_64(machine: str | None = None) -> bool:
    return (platform.machine() if machine is None else machine).lower() in X86_64


def same_value(got, want, machine: str | None = None) -> bool:
    """Exact on x86-64; elsewhere floats match within CROSS_PLATFORM_RTOL. Lists compare elementwise."""
    if isinstance(want, (list, tuple)):
        return (isinstance(got, (list, tuple)) and len(got) == len(want)
                and all(same_value(g, w, machine) for g, w in zip(got, want)))
    if is_x86_64(machine) or not (isinstance(want, float) and isinstance(got, float)):
        return got == want
    return math.isclose(got, want, rel_tol=CROSS_PLATFORM_RTOL, abs_tol=0.0)


x86_64_only = pytest.mark.skipif(
    not is_x86_64(),
    reason="ARM64ULP-01: exact-sample pins captured on x86-64; arm64 lands 1-2 ULP away on the "
           "cost layer (Director 11/09/2026 ruled these checks x86-64-only)",
)
