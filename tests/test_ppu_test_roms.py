"""Milestone 2's hardware-corrected judges: blargg's PPU test ROMs.

Slow (``pytest -m slow``): each runs for emulated seconds. The certification
record, with instruction counts and wall times, comes from
``scripts/run_test_roms.py --suite ppu``.
"""

from __future__ import annotations

import pytest
from conftest import ROMS, rom

from famicom_python.testrom import PPU_ROMS, run_case


@pytest.mark.slow
@pytest.mark.parametrize("case", PPU_ROMS, ids=lambda case: case.path)
def test_ppu_rom_passes(case) -> None:
    rom(case.path)
    outcome = run_case(case, ROMS)
    assert outcome.passed, outcome.detail
