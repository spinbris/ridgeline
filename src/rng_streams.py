"""The random streams a run draws from, derived from its one seed and named in one place.

RNGSTREAM-01. A Stage 3 run makes two draws per risk per iteration - whether it fires, and how
severe it is - and they must be independent. They were not: both generators were seeded with the
same integer, so they read one stream, and where a single-member or rho <= 0 correlation group was
drawn first a risk's fire uniform *was* its severity uniform, so a fired risk could never sample its
upper tail. Every generator a run needs for those draws is made here, and nowhere else.

numpy only, so ``src.qra_core`` can import it under Pyodide.
"""
from __future__ import annotations

import operator

import numpy as np

#: Entropy word that puts the severity uniforms on a stream of their own. **Must not be 0**:
#: ``SeedSequence([seed, 0])`` is the same stream as ``SeedSequence(seed)`` (numpy pads entropy
#: with zeros), which would put severity straight back on the fire stream. Changing it moves every
#: Stage 3 number.
SEVERITY_STREAM = 0x5E7E1

#: Entropy word for the deliverable's Layer 1 base draw (INTSCURVE-01 Part B, Reviewer R1). The
#: base is drawn on a stream of its own so that adding it moves no event-risk draw: the cost arm
#: never sees it. **Must not be 0** (the fire stream) **nor ``SEVERITY_STREAM``**. Changing it
#: moves the base layer and the total, never the event-risk contingency.
LAYER1_STREAM = 0xBA5E1


def _seed(seed: int) -> int:
    """The run seed as one 32-bit entropy word, or a refusal.

    Not ``int(seed)``, which would quietly turn 42.9 into 42. Below 2**32 because a larger seed is
    several entropy words, and ``[low, SEVERITY_STREAM]`` is then the fire stream of the seed
    ``low + SEVERITY_STREAM * 2**32``.
    """
    value = operator.index(seed)
    if not 0 <= value < 2**32:
        raise ValueError(f"run seed must be an integer in [0, 2**32); got {seed!r}")
    return value


def fire_generator(seed: int) -> np.random.Generator:
    """The run seed's own stream: the cost arm's fire draw, then the cost arm's other draws.

    ``run_cost_layer`` takes ``draw_fire_matrix`` first from it, then any severity it draws itself,
    chain resamples, cascade and Layer 1 - one generator, in sequence, so none of those overlap.
    The period route reproduces the fire draw on a fresh one (``period_fire_mask``).
    """
    return np.random.default_rng(_seed(seed))


def severity_generator(seed: int) -> np.random.Generator:
    """The shared severity uniforms' stream, independent of the fire stream.

    Built on entropy ``[seed, SEVERITY_STREAM]``, so it is neither the fire stream nor any child
    ``.spawn()`` derives from the run seed - which is what the Stage 3 kernel's per-batch generators
    are (``kernel_generator``). "The first spawned child of the seed" would have collided with the
    kernel's batch 0.
    """
    return np.random.default_rng(np.random.SeedSequence([_seed(seed), SEVERITY_STREAM]))


def layer1_generator(seed: int) -> np.random.Generator:
    """The deliverable's Layer 1 base stream, independent of the fire, severity and kernel streams.

    Entropy ``[seed, LAYER1_STREAM]``, as ``severity_generator`` is built, so it is none of the
    others. The Tier 1 owner view still draws Layer 1 on the fire stream after the event draws
    (``run_cost_layer``); this stream is for the deliverable's separate base array only.
    """
    return np.random.default_rng(np.random.SeedSequence([_seed(seed), LAYER1_STREAM]))


def kernel_generator(seed: int) -> np.random.Generator:
    """The parent the Stage 3 kernel spawns its per-batch generators from.

    Its children carry spawn keys under the run seed, so they are distinct from the fire stream
    (the seed itself, no spawn key) and from the severity stream (different entropy). On the
    integrated routes the kernel is given fires and severity and draws nothing from them.

    **Its own stream is the fire stream**, so the kernel may only spawn from it. A direct draw on
    it, on a route that also supplies fires, would replay the fire uniforms.
    """
    return np.random.default_rng(_seed(seed))


# --- How a seed reaches the streams (SEEDZERO-01) ---------------------------------------------
#
# One rule on every route. A seed someone states - environment, register cell, CLI, a binding, a
# baseline's record - is parsed by `parse_seed`. A run's entry resolves an unstated one with
# `resolve_seed` (drawn once, and the caller records it). Everything below an entry takes the
# resolved seed through `require_seed`, which refuses a missing one by name rather than choosing.

#: Where a run's seed came from, as a record states it.
SEED_SET = "set"
SEED_DRAWN = "drawn"

#: A drawn seed's range: positive, and inside every arm's (the deliverable draws in the same one).
_DRAWN_SEED_MAX = 2**31 - 1


def parse_seed(value: object, *, where: str) -> int:
    """A stated seed as one integer in [0, 2**32), or a refusal naming where it came from.

    ``int()`` turned 42.9 into 42 and ran a seed nobody asked for (SEEDINPUT-01). A whole-valued
    float is accepted, because xlwings hands every Excel number over as one (42.0); a fractional,
    negative, too large, boolean or non-numeric value is refused.
    """
    raw = value
    if isinstance(value, str):
        text = value.strip()
        try:
            value = int(text)
        except ValueError:
            try:
                value = float(text)
            except ValueError:
                value = None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    try:
        if isinstance(value, bool):
            raise TypeError
        seed = operator.index(value)
    except TypeError:
        seed = -1
    if not 0 <= seed < 2**32:
        raise ValueError(
            f"{where}: seed {raw!r} is not a whole number from 0 to {2**32 - 1}. A fraction is "
            f"refused rather than truncated, because the run would not be the one asked for.")
    return seed


def require_seed(value: object, *, where: str) -> int:
    """The seed an engine was handed. A missing one is refused by name, never defaulted."""
    if value is None:
        raise ValueError(
            f"{where}: no seed was given. There is no default seed (SEEDZERO-01): the run's entry "
            f"resolves one - stated, or drawn and recorded - and passes it down.")
    return parse_seed(value, where=where)


def draw_seed() -> int:
    """A fresh seed for a run that stated none. The caller records it."""
    import secrets

    return secrets.randbelow(_DRAWN_SEED_MAX) + 1


def resolve_seed(value: object, *, where: str) -> tuple[int, str]:
    """A run's seed and its source: stated is used as given; unset, blank or 0 is drawn once, here.

    The CONFIGTRUTH-01 convention, applied on every route (Director, 11/10/2026). The source is
    ``SEED_SET`` or ``SEED_DRAWN``; the caller records both, so a drawn run is reproducible by
    giving its seed back.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return draw_seed(), SEED_DRAWN
    seed = parse_seed(value, where=where)
    if seed == 0:
        return draw_seed(), SEED_DRAWN
    return seed, SEED_SET


def stated_seed(value: object, *, where: str) -> int | None:
    """A seed cell as read: ``None`` when it is empty, else parsed. Resolving it is the run's job."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_seed(value, where=where)
