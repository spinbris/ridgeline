"""The outturn engine: cost QRA, schedule risk analysis, and the integrated result.

3d A-2: **one version string, and this is it.** ``pyproject.toml`` reads it from here rather
than carrying a second copy, so the package metadata and the running code cannot disagree.

That is not packaging tidiness. Both places this repository records "what produced this number"
resolve identity through git - ``src/am/_provenance.py`` shells out to ``git rev-parse`` and
``tests/golden/golden_harness.engine_ref`` to ``git describe`` - and **both go silent on an
installed copy**, where there is no repository to ask. A provenance manifest written by an
installed engine would carry a null engine identity and attest to nothing. ``__version__`` is
what such a run can still state, which is why it belongs to the engine rather than to the build
configuration.
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
