"""The board's PPU against PPUSim's recorded answers to the C12 sweeps.

``scripts/ppusim_goldens.py`` ran each scene of ppusim_scenes.py on PPUSim
(skew 3) and kept its pixels, ALE addresses and PPUSTATUS reads in
``ppusim_goldens.json.gz``; here our PPU replays the scenes alone. A case in
KNOWN differs from PPUSim, as recorded (docs/undocumented-behavior.md C73): it
must keep differing, so the list stays true.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from ppusim_scenes import SCENES, Board, first_difference

GOLDENS = json.loads(
    gzip.decompress((Path(__file__).parent / "ppusim_goldens.json.gz").read_bytes())
)

# A $2003 write during sprite evaluation that leaves a copy ending on an X byte
# in range of the line: PPUSim realigns the address, the console does not
# (AccuracyCoin "Misaligned OAM behavior" test 6, hardware-captured), and the
# board follows the console (C73). The names are the dots asked for; each write
# lands a dot or two earlier.
KNOWN = {"oamaddr 72", "oamaddr 87", "oamaddr 89", "oamaddr 73+91+163+181"}


@pytest.mark.parametrize("scene", SCENES)
def test_scene_matches_ppusim(scene: str) -> None:
    board = Board()
    SCENES[scene](board)
    differ = []
    for name, ours in board.results.items():
        sim = GOLDENS[name]
        same = ours == sim
        if same == (name in KNOWN):
            why = "now matches; drop it from KNOWN" if same else first_difference(ours, sim)
            differ.append(f"{name}: {why}")
    assert not differ, "\n".join(differ)
