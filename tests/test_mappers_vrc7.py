"""Mapper 85, the VRC7: banking (VRC7.wiki); its sound is switched off for now.

The banking is pinned on a synthetic image; *Lagrange Point* and *Tiny Toon
Adventures 2* (J) give Mesen2's frames (docs/validation.md).
"""

from __future__ import annotations

from test_mappers import TICKS

from famicom_python.cartridge import BoardInfo, RomImage
from famicom_python.cartridge.konami import VRC7


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


def test_sound_ports_are_taken_and_the_cartridge_is_silent() -> None:
    # The VRC7's sound is switched off for now (konami.VRC7): no chip behind the ports.
    cart = vrc7()
    assert not cart.expansion_audio
    before = cart.cpu_read(0xA000, 0)
    for address, value in ((0x9010, 0x30), (0x9030, 0x10), (0x9010, 0x10), (0x9030, 0x81)):
        cart.cpu_write(address, value, 0)
        for _ in range(42):
            cart.m2(0)
    assert cart.cpu_read(0xA000, 0) == before  # the PRG bank at $9000 was not touched
    cart.cpu_write(0xE000, 0x40, 0)
    assert cart.sound_silenced
