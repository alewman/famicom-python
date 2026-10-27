"""The console a cartridge asks for (System.machine_for, the window's ``--machine auto``)."""

from __future__ import annotations

from conftest import nrom_image

from famicom_python.machine import MACHINES, NES_001
from famicom_python.system import System


def nes20(timing: int) -> bytes:
    """An NROM image with an NES 2.0 header whose byte 12 holds ``timing``."""
    image = bytearray(nrom_image(b"\x4c\x00\x80"))
    image[7] = 0x08  # NES 2.0 (NES_2.0.wiki byte 7, bits 2-3 = 2)
    image[12] = timing
    return bytes(image)


def test_the_header_timing_picks_the_machine() -> None:
    assert System.machine_for(nes20(0)) is NES_001
    assert System.machine_for(nes20(1)) is MACHINES["pal"]
    assert System.machine_for(nes20(2)) is NES_001  # multi-region: NTSC
    assert System.machine_for(nes20(3)) is MACHINES["dendy"]


def test_a_plain_ines_image_is_an_nes() -> None:
    assert System.machine_for(nrom_image(b"\x4c\x00\x80")) is NES_001
