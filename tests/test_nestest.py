"""nestest in automation mode matches nestest.log on every line (milestone 1).

nestest.log is emulator-derived (Nintendulator) and universally cross-checked;
MAME 0.285 matches it too (docs/validation.md). Compared per instruction: PC, A,
X, Y, P masked with $CF, SP and the CPU cycle count, plus the PPU's line and
dot, which follow from the cycle count while the PPU starts at (0, 0) at cycle 0.
"""

from __future__ import annotations

import nestest
import pytest
from conftest import rom

from famicom_python.testrom import peek


@pytest.fixture(scope="module")
def run():
    rom("other/nestest.nes")
    log = nestest.read_log()
    system, rows = nestest.run(len(log))
    return log, system, rows


def test_every_line_matches(run) -> None:
    log, _, rows = run
    assert len(log) == 8991
    for number, (expected, actual) in enumerate(zip(log, rows, strict=True), start=1):
        assert actual.key() == expected.key(), f"line {number}: {expected} != {actual}"


def test_ppu_position_matches(run) -> None:
    log, _, rows = run
    for number, (expected, actual) in enumerate(zip(log, rows, strict=True), start=1):
        assert (actual.line, actual.dot) == (expected.line, expected.dot), f"line {number}"


def test_result_codes_are_zero(run) -> None:
    _, system, _ = run
    assert (peek(system, 0x02), peek(system, 0x03)) == (0, 0)
