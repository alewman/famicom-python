"""Milestone 9's judges: the FDS test disks with hardware answers.

Slow (``pytest -m slow``). Skipped without the test disks (fetch_references.py)
or the BIOS (FAMICOM_FDS_BIOS, or No-Intro's under NO_INTRO_DIR), which is
Nintendo's and never fetched.
"""

from __future__ import annotations

import pytest
from conftest import FETCH_HINT, ROMS

from famicom_python.cartridge import fds_bios
from famicom_python.testrom import FDS_ROMS, run_case


def _bios_present() -> bool:
    try:
        fds_bios()
    except (FileNotFoundError, ValueError):
        return False
    return True


@pytest.mark.slow
@pytest.mark.parametrize("case", FDS_ROMS, ids=lambda case: case.label)
def test_fds_rom_passes(case) -> None:
    archive = ROMS / case.path.rsplit("/", 1)[0]
    if not archive.is_file():
        pytest.skip(FETCH_HINT)
    if not _bios_present():
        pytest.skip("no FDS BIOS: set FAMICOM_FDS_BIOS")
    outcome = run_case(case, ROMS)
    assert outcome.passed, outcome.detail
