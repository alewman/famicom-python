"""The APU's noise and DMC period tables, decoded from the 2A03's and 2A07's die
masks (scripts/apu_period_roms.py): die-derived for both chips' tables."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apu_period_roms.py"


def test_the_period_tables_are_the_dies() -> None:
    if not (ROOT / "reference" / "src" / "breaks").exists():
        pytest.skip("reference/src/breaks missing: python scripts/fetch_references.py")
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
