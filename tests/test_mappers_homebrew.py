"""Homebrew mappers: Action 53 (28) and the NSF subset (31).

Mapper 31's judge, rainwarrior's 31_test, is in the mapper suite
(``testrom.MAPPER_ROMS``). Mapper 28's, tepples's test28 v0.04, needs Start and
a reset partway through, and draws its verdict in a proportional font the
harness cannot read: its final frame, which shows "PASS! RESET LEAVES BANK
UNCHANGED." (checked by eye, docs/validation.md), is pinned by CRC here.
"""

from __future__ import annotations

import zipfile
import zlib

import pytest
from conftest import ROMS, nrom_image

from famicom_python.cartridge import load
from famicom_python.joypad import START
from famicom_python.system import System

TEST28 = ROMS.parent / "nesdev-forum" / "test28-0.04.zip"
#: test28 v0.04's frame after its automated tests and the reset: PASS.
TEST28_PASS_CRC = 0xE096480A


@pytest.mark.slow
def test_test28_passes_after_its_reset() -> None:
    if not TEST28.is_file():
        pytest.skip("test28 not fetched: python scripts/fetch_references.py")
    with zipfile.ZipFile(TEST28) as archive:
        rom = archive.read("test28-8Mbit.nes")
    system = System.from_rom(rom)
    system.board.pads[0].buttons = START  # run the automated tests
    system.run_frames(3600)  # 131,072 bank combinations, then the CHR test
    system.board.pads[0].buttons = 0
    system.reset()  # "One last thing: please press the Reset Button"
    system.run_frames(200)
    assert zlib.crc32(bytes(system.board.ppu.picture)) == TEST28_PASS_CRC


def mapper31_image(prg_kib: int) -> bytes:
    """A mapper-31 image whose 4 KiB banks each begin with their own number."""
    prg = bytearray(prg_kib * 1024)
    for bank in range(prg_kib // 4):
        prg[bank * 0x1000] = bank
    header = bytearray(nrom_image(b"")[:16])
    header[4], header[5] = prg_kib // 16, 0  # no CHR-ROM: 8 KiB of CHR-RAM
    header[6], header[7] = 0xF0, 0x10  # mapper 31 = $1F: low nibble in byte 6, high in 7
    return bytes(header) + bytes(prg)


def test_mapper_31_banks_4k_slots_from_its_registers() -> None:
    cart = load(mapper31_image(64), use_database=False).cartridge
    assert cart.cpu_read(0xF000, 0) == 15  # $F000 powers on with the last bank
    for slot in range(8):
        cart.cpu_write(0x5FF8 + slot, slot + 3, 0)
        assert cart.cpu_read(0x8000 + slot * 0x1000, 0) == slot + 3
    cart.cpu_write(0x5000 + 2, 9, 0)  # any $5xxx: A2-A0 name the slot
    assert cart.cpu_read(0xA000, 0) == 9
