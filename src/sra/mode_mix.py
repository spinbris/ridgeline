"""The one mode-mix formatter (RS-D-5, D-17).

Renders the Modes applied to a set of simulating risks as the compact label every surface
uses - ``"8S"``, ``"3S/2H/3P"``, ``"4S/4H/2P"`` - from the engine's ``mode_used`` (a
``{risk_id: mode}`` dict) or from a plain sequence of Mode names. Until RS-D-5 there were two
implementations (``src/final/executive_summary.format_mode_mix`` and
``src/sra/sra_simulation._mode_mix_summary``) that agreed on every Mode they both knew and
diverged on one they did not: the first rendered ``1?``, the second dropped it silently. Now
there is one, it lives beside the engine, ``final`` imports it, and a Mode outside
Series/Hybrid/Parallel **raises**, naming the risk - the same rule the cross-check applies to
the multiplier grid.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: Order is the label order: S, then H, then P.
MODES: tuple[str, ...] = ("Series", "Hybrid", "Parallel")
_LETTER = {"Series": "S", "Hybrid": "H", "Parallel": "P"}
_CANONICAL = {m.casefold(): m for m in MODES}


def _canonical(mode: Any, key: Any) -> str:
    text = "" if mode is None else str(mode).strip()
    canon = _CANONICAL.get(text.casefold())
    if canon is None:
        where = f" on risk {key!r}" if key is not None else ""
        raise ValueError(
            f"Mode {text!r}{where} is not one of {list(MODES)}; the mode mix cannot be "
            "labelled. Fix the Mode in the register - the label never guesses."
        )
    return canon


def _items(modes: Mapping[Any, Any] | Iterable[Any]) -> list[tuple[Any, Any]]:
    if isinstance(modes, Mapping):
        return list(modes.items())
    return [(None, m) for m in modes]


def count_modes(modes: Mapping[Any, Any] | Iterable[Any]) -> dict[str, int]:
    """Per-Mode counts over ``mode_used`` values or a sequence of Mode names.

    Keys are exactly :data:`MODES`; there is no ``Other`` bucket, because an unknown Mode
    raises. Case and surrounding whitespace of a known Mode are tolerated.
    """
    out = {m: 0 for m in MODES}
    for key, mode in _items(modes):
        out[_canonical(mode, key)] += 1
    return out


def format_mode_mix(modes: Mapping[Any, Any] | Iterable[Any]) -> str:
    """Compact mode-mix label; empty input renders ``"(none)"``."""
    counts = count_modes(modes)
    parts = [f"{counts[m]}{_LETTER[m]}" for m in MODES if counts[m]]
    return "/".join(parts) if parts else "(none)"
