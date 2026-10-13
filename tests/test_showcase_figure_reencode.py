"""PRERELEASE-01 P2: the re-encoded showcase S-curve shows exactly what it showed before.

`docs/showcase/figs/wind_schedule_finish_s_curve.png` was re-encoded losslessly because the
client's project acronym stood alone, by chance, in its compressed bytes, and the client gate's
BINARY limb cannot allowlist a file (PM task -6). The bytes changed; what a visitor sees must not.
The expected values were read from the committed blob before the re-encode (`00332c6`).

`scripts/run_wind_showcase.py` regenerates this figure on its next run, and the gate re-checks it
then. A regeneration that moves the figure will red this test; delete it with that change.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

FIG = Path(__file__).resolve().parents[1] / "docs" / "showcase" / "figs" / "wind_schedule_finish_s_curve.png"

MODE = "RGBA"
SIZE = (1484, 880)
PIXELS_SHA256 = "171b091e58e000f57dfc6199cdb4a6f99deea23353ddb6fb27101fc82b75162d"
TEXT = {"Software": "Matplotlib version3.10.7, https://matplotlib.org/"}


def test_the_reencoded_figure_decodes_to_the_committed_pixels():
    with Image.open(FIG) as im:
        assert (im.mode, im.size) == (MODE, SIZE)
        assert hashlib.sha256(im.tobytes()).hexdigest() == PIXELS_SHA256
        assert im.text == TEXT
        assert [round(d, 2) for d in im.info["dpi"]] == [150.01, 150.01]
