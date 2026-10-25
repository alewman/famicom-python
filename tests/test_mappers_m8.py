"""Milestone 8's mapper: UNROM 512 (30), the homebrew board, on synthetic images.

No judge ROM exists; UNROM_512.wiki and the SST39SF040 data sheet's command
sequences are what these pin.
"""

from __future__ import annotations

from test_mappers import TICKS

from famicom_python.cartridge import BoardInfo, RomImage
from famicom_python.cartridge.discrete import UNROM512


def unrom512(submapper: int = 0, *, flags6: int = 0, battery: bool = False) -> UNROM512:
    prg = bytes((i // 0x400) & 0xFF for i in range(512 * 1024))
    header = b"NES\x1a" + bytes((32, 0, flags6, 0)) + bytes(8)
    board = BoardInfo(mapper=30, submapper=submapper, battery=battery)
    return UNROM512(RomImage(header, b"", prg, b"", b"", board, False), TICKS)


def test_unrom512_banks_prg_chr_and_one_screen() -> None:
    cart = unrom512(1, flags6=0x08)  # one-screen switchable
    assert cart.cpu_read(0xC000, 0) == 240  # the last 16 KiB: KiB 496, & $FF
    cart.cpu_write(0xC000, 0x80 | 0x40 | 0x05, 0)  # screen B, CHR bank 2, PRG bank 5
    assert cart.cpu_read(0x8000, 0) == 80 and cart.ciram_a10(0x2000) == 1
    cart.ppu_write(0x0000, 0x5A, 0)
    assert cart.chr[2 * 0x2000] == 0x5A
    cart.cpu_write(0x8000, 0x01, 0)  # submapper 1: $8000-$BFFF is not the register
    assert cart.cpu_read(0x8000, 0) == 80


def test_unrom512_four_screen_uses_the_last_8k_of_chr_ram() -> None:
    cart = unrom512(1, flags6=0x09)
    assert cart.ciram_a10(0x2400) is None
    cart.ppu_write(0x2C05, 0x77, 0)
    assert cart.ppu_read(0x2C05, 0) == 0x77 and cart.chr[0x6000 + 0x0C05] == 0x77


def test_unrom512_bus_conflicts_without_battery_on_submapper_0() -> None:
    cart = unrom512(0)
    cart.cpu_write(0x8000, 0xFF, 0)  # ANDed with the ROM byte there, 0
    assert cart.latch == 0


def test_unrom512_flash_programs_and_erases_a_sector() -> None:
    cart = unrom512(0, battery=True)

    def command(bank: int, address: int, value: int) -> None:
        cart.cpu_write(0xC000, bank, 0)
        cart.cpu_write(address, value, 0)

    unlock = ((1, 0x9555, 0xAA), (0, 0xAAAA, 0x55))
    for step in (*unlock, (1, 0x9555, 0xA0), (3, 0x8123, 0x0F)):
        command(*step)
    cart.cpu_write(0xC000, 3, 0)
    assert cart.cpu_read(0x8123, 0) == 48 & 0x0F  # bits only clear
    for step in (*unlock, (1, 0x9555, 0x80), *unlock, (3, 0x8000, 0x30)):
        command(*step)
    cart.cpu_write(0xC000, 3, 0)
    assert cart.cpu_read(0x8123, 0) == 0xFF and cart.cpu_read(0x9000, 0) == 52
    assert cart.battery_ram() is not None
