"""Mapper 85, the VRC7: banking (VRC7.wiki) and its sound wired to ym2413-python's DS1001.

The banking is pinned on a synthetic image; *Lagrange Point* and *Tiny Toon
Adventures 2* (J) give Mesen2's frames (docs/validation.md). The sound chip is
judged in ym2413-python against Nuked-OPLL; here only its wiring.
"""

from __future__ import annotations

from test_mappers import TICKS

from famicom_python.cartridge import BoardInfo, RomImage
from famicom_python.cartridge.connector import Unplugged
from famicom_python.cartridge.konami import FM_CPU_CYCLES_PER_SAMPLE, VRC7


def vrc7(submapper: int = 2) -> VRC7:
    prg = bytes((i // 0x2000) & 0xFF for i in range(256 * 1024))  # each 8 KiB bank: its number
    chr_rom = bytes((i // 0x400) & 0xFF for i in range(128 * 1024))
    board = BoardInfo(mapper=85, submapper=submapper, prg_ram=0x2000)
    return VRC7(RomImage(b"", b"", prg, chr_rom, b"", board, False), TICKS)


def test_prg_banks_and_the_fixed_last() -> None:
    cart = vrc7()
    assert cart.cpu_read(0xE000, 0) == 31
    cart.cpu_write(0x8000, 3, 0)
    cart.cpu_write(0x8010, 4, 0)  # VRC7a: A4 selects the second register
    cart.cpu_write(0x9000, 5, 0)
    assert [cart.cpu_read(a, 0) for a in (0x8000, 0xA000, 0xC000)] == [3, 4, 5]
    tiny_toon = vrc7(1)
    tiny_toon.cpu_write(0x8008, 6, 0)  # VRC7b: A3
    assert tiny_toon.cpu_read(0xA000, 0) == 6


def test_chr_banks_two_per_page() -> None:
    cart = vrc7()
    for page, window in ((0xA000, 0), (0xB000, 2), (0xC000, 4), (0xD000, 6)):
        cart.cpu_write(page, 10 + window, 0)
        cart.cpu_write(page | 0x10, 11 + window, 0)
    assert [cart.ppu_read(w * 0x400, 0) for w in range(8)] == list(range(10, 18))


def test_mirroring_and_prg_ram_enable() -> None:
    cart = vrc7()
    cart.cpu_write(0xE000, 0x81, 0)  # RAM on, horizontal
    assert cart.ciram_a10(0x2800) == 1 and cart.ciram_a10(0x2400) == 0
    cart.cpu_write(0x6000, 0x42, 0)
    assert cart.cpu_read(0x6000, 0) == 0x42


def test_sound_writes_reach_the_chip_and_drive_the_level() -> None:
    cart = vrc7()
    cart.audio_out = Unplugged()
    for register, value in ((0x30, 0x10), (0x10, 0x81), (0x20, 0x19)):
        cart.cpu_write(0x9010, register, 0)
        for _ in range(6):
            cart.m2(0)
        cart.cpu_write(0x9030, value, 0)
        for _ in range(42):
            cart.m2(0)
    assert cart.fm.instrument[0] == 1 and cart.fm.key[0] == 1
    levels = set()
    for _ in range(FM_CPU_CYCLES_PER_SAMPLE * 400):
        cart.m2(0)
        levels.add(round(cart.audio_out.expansion, 6))
    assert len(levels) > 50  # a tone, not silence


def test_e000_d6_holds_the_sound_in_reset() -> None:
    cart = vrc7()
    cart.audio_out = Unplugged()
    cart.cpu_write(0x9010, 0x30, 0)
    for _ in range(6):  # games wait between the address and the data (VRC7_audio.wiki)
        cart.m2(0)
    cart.cpu_write(0x9030, 0x50, 0)
    for _ in range(80):
        cart.m2(0)
    assert cart.fm.instrument[0] == 5
    cart.cpu_write(0xE000, 0x40, 0)
    assert cart.fm.instrument[0] == 0 and cart.audio_out.expansion == 0.0
