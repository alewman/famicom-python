"""The board's PPU against PPUSim's recorded answers to the C12 sweeps.

``scripts/ppusim_goldens.py`` ran each scene of ppusim_scenes.py on PPUSim
(skew 3) and kept its pixels, ALE addresses and PPUSTATUS reads in
``ppusim_goldens.json.gz``; here our PPU replays the scenes alone. A case in
KNOWN differs from PPUSim, as recorded (docs/undocumented-behavior.md open
item 18): it must keep differing, so the list stays true.
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

# Each scene's setup turns rendering off and on again around dot 200 of the
# line before; PPUSim's sprite evaluation, so interrupted, copies a misaligned
# entry (53 02 65 68) into secondary OAM and ours copies none (open item 18).
KNOWN = {"mux 1E>0E +6", "mux 0E>1E +5"}
# A $2003 write during sprite evaluation that falls between the main counter's
# steps: PPUSim's counter bits keep part of the old address, the board's
# per-dot counter takes the whole write (open item 23). The names are the dots
# asked for; each write lands about two dots earlier.
KNOWN |= {
    f"oamaddr {dot}"
    for dot in (67, 68, 70, 72, 73, 74, 76, 79, 80, 82, 85, 86, 87, 88, 89, 91, 92, 94, 97)
}
KNOWN.add("oamaddr 73+91+163+181")  # Melanchony of Existance's writes


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
