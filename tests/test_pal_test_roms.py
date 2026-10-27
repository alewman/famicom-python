"""Milestone 10's hardware-corrected judges: the PAL NES's test ROMs.

Slow (``pytest -m slow``). ``scripts/run_test_roms.py --suite pal`` gives the
certification record.
"""

from __future__ import annotations

import pytest
from conftest import ROMS, rom

from famicom_python.testrom import PAL_ROMS, run_case


@pytest.mark.slow
@pytest.mark.parametrize("case", PAL_ROMS, ids=lambda case: case.label)
def test_pal_rom_passes(case) -> None:
    rom(case.path)
    outcome = run_case(case, ROMS)
    assert outcome.passed, outcome.detail
