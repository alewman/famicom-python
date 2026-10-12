"""Milestone 3's hardware-corrected judges: the APU, DMA and interrupt test ROMs.

Slow (``pytest -m slow``): each runs for emulated seconds. The certification
record, with instruction counts and wall times, comes from
``scripts/run_test_roms.py --suite apu``.
"""

from __future__ import annotations

import pytest
from conftest import ROMS, rom

from famicom_python.testrom import APU_ROMS, run_case


@pytest.mark.slow
@pytest.mark.parametrize("case", APU_ROMS, ids=lambda case: case.path)
def test_apu_rom_passes(case) -> None:
    rom(case.path)
    outcome = run_case(case, ROMS)
    assert outcome.passed, outcome.detail
