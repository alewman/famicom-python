"""Milestone 1's hardware-corrected judges: blargg's and Bisqwit's CPU test ROMs.

Slow (``pytest -m slow``): each runs for emulated seconds. The certification
record, with instruction counts and wall times, comes from
``scripts/run_test_roms.py``.
"""

from __future__ import annotations

import pytest
from conftest import ROMS, rom

from famicom_python.testrom import CPU_ROMS, run_case


@pytest.mark.slow
@pytest.mark.parametrize("case", CPU_ROMS, ids=lambda case: case.path)
def test_cpu_rom_passes(case) -> None:
    rom(case.path)
    outcome = run_case(case, ROMS)
    assert outcome.passed, outcome.detail
