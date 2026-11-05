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

# Rendering turned off during sprite evaluation and on again: PPUSim's OAM
# counter takes a last step Visual 2C02's does not (C73); the board follows
# Visual 2C02 (tests/test_visual2c02_goldens.py, "off overflow 210").
KNOWN = {"mux 1E>0E +5", "mux 1E>0E +6"}


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
