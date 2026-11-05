"""The board's OAM counter against Visual 2C02's recorded answers.

``scripts/visual2c02/goldens.py`` ran each case of its CASES on Visual 2C02
(Quietust's transistor netlist) and kept OAMADDR on each odd dot of sprite
evaluation in ``visual2c02_goldens.json.gz``; here the board replays the same
schedules (``compare.run_board``). A case in KNOWN differs, as recorded: it
must keep differing, so the list stays true.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "visual2c02"))

import compare  # noqa: E402
from goldens import CASES, FIRST, LAST  # noqa: E402

GOLDENS = json.loads(
    gzip.decompress((Path(__file__).parent / "visual2c02_goldens.json.gz").read_bytes())
)

# Rendering turned off in a copy, on a cycle beginning on an even dot: Visual
# 2C02's OAM data reads $E0 while it is off, not the byte at the address, so the
# check as rendering returns finds nothing (C73, not modelled).
KNOWN = {"off copy 96"}
# Visual 2C02's saved state has the secondary OAM address frozen at row 4, so
# rendering's start at line 5, dot 30 copies OAM's row 0 over row $20 (C26, open
# item 24); the board starts with nothing frozen. The C73 cases reach row $20 on
# dot 89, so they are compared up to there.
LAST_DOT = {"C73 X in range": 87, "C73 X out of range": 87}


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_oam_counter_matches_visual2c02(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    scenario, env = CASES[name]
    for key, value in env.items():
        monkeypatch.setitem(os.environ, key, value)
    probes = compare.run_board(compare.SCENARIOS[scenario]())["probes"]
    ours = {str(h): probes[f"7:{h}"][0] for h in range(FIRST, LAST_DOT.get(name, LAST) + 1, 2)}
    differ = [h for h in ours if ours[h] != GOLDENS[name][h]]
    if name in KNOWN:
        assert differ, f"{name} now matches; drop it from KNOWN"
    else:
        dot = differ[0] if differ else ""
        assert not differ, f"dot {dot}: ours {ours[dot]:02X}, Visual 2C02 {GOLDENS[name][dot]:02X}"
