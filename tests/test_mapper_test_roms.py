"""Milestone 5's judges: blargg's MMC3 suites, Holy Mapperel and the forum's mapper tests.

Slow (``pytest -m slow``). The certification record comes from
``scripts/run_test_roms.py --suite mappers``. Holy Mapperel and the forum
tests are read inside their archives (``.7z`` needs the ``7z`` program).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FETCH_HINT, ROMS

from famicom_python.testrom import MAPPER_ROMS, run_case


def _fetched(path: str) -> bool:
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part.endswith((".7z", ".zip")):
            return ROMS.joinpath(*parts[: i + 1]).is_file()
    return (ROMS / path).is_file()


@pytest.mark.slow
@pytest.mark.parametrize("case", MAPPER_ROMS, ids=lambda case: case.label)
def test_mapper_rom_passes(case) -> None:
    if not _fetched(case.path):
        pytest.skip(FETCH_HINT)
    outcome = run_case(case, ROMS)
    assert outcome.passed, outcome.detail
