"""Milestone 5's mappers where no judge ROM reaches: MMC6, MC-ACC, the A12 filter's edge.

The judge ROMs (``famicom_python.testrom.MAPPER_ROMS``) carry the claims;
these pin what they leave open (docs/claims.md) on synthetic images.
"""

from __future__ import annotations

from famicom_python.cartridge import MAPPERS, BoardInfo, RomImage
from famicom_python.cartridge.discrete import BNROM, NINA001
from famicom_python.cartridge.mmc3 import MCACC, MMC3, MMC6

TICKS = 12  # master ticks per CPU cycle


def image(mapper: int, submapper: int = 0, *, prg_kib: int = 128, chr_kib: int = 128) -> RomImage:
    """PRG and CHR whose every 1 KiB starts with its own bank number."""
    prg = bytes((i // 0x400) & 0xFF for i in range(prg_kib * 1024))
    chr_rom = bytes((i // 0x400) & 0xFF for i in range(chr_kib * 1024))
    board = BoardInfo(mapper=mapper, submapper=submapper, prg_ram=0x2000)
    return RomImage(b"", b"", prg, chr_rom, b"", board, True)


def build(mapper: int, submapper: int = 0, **sizes: int):
    return MAPPERS[mapper](image(mapper, submapper, **sizes), TICKS)


def clock_a12(cart: MMC3, t: int) -> int:
    """A12 low for a long while, then a rise: one filtered clock. Returns the next time."""
    cart.ppu_address(0x0000, t)
    cart.ppu_address(0x1000, t + 10 * TICKS)
    return t + 20 * TICKS


def test_submappers_choose_the_chip() -> None:
    assert type(build(4, 0)) is MMC3
    assert isinstance(build(4, 1), MMC6)
    assert isinstance(build(4, 3), MCACC)
    assert isinstance(build(34, 2, chr_kib=8), BNROM)
    assert isinstance(build(34, 1, chr_kib=8), NINA001)
    # Mapper 34 without a submapper: CHR over 8 KiB means NINA-001 (the wiki).
    assert isinstance(build(34, 0, chr_kib=16), NINA001)
    assert isinstance(build(34, 0, chr_kib=8), BNROM)


def test_a12_filter_needs_three_m2_falls_while_low() -> None:
    cart = build(4)
    cart.ppu_address(0x1000, 0)  # A12 high (from power-on low: a clock)
    cart.cpu_write(0xC000, 5, 0)  # latch
    cart.cpu_write(0xC001, 0, 0)  # reload on the next clock
    # Low at a fall time + 1: the falls at +12, +24 and +36 ticks are the three.
    cart.ppu_address(0x0000, 1001 * TICKS + 1)
    cart.ppu_address(0x1000, 1004 * TICKS - 1)  # two falls: filtered
    assert cart.counter == 0 and cart.reload
    cart.ppu_address(0x0000, 1010 * TICKS + 1)
    cart.ppu_address(0x1000, 1013 * TICKS)  # the third fall at the rise counts
    assert cart.counter == 5 and not cart.reload


def test_sharp_interrupts_every_clock_with_latch_zero_and_nec_once() -> None:
    for submapper, expected in ((0, [True, True, True]), (4, [True, False, False])):
        cart = build(4, submapper)
        cart.cpu_write(0xC000, 0, 0)
        cart.cpu_write(0xC001, 0, 0)
        cart.cpu_write(0xE001, 0, 0)
        t, seen = 100 * TICKS, []
        for _ in range(3):
            t = clock_a12(cart, t)
            seen.append(cart.irq)
            cart.cpu_write(0xE000, 0, t)  # acknowledge
            cart.cpu_write(0xE001, 0, t)
        assert seen == expected, submapper


def test_mcacc_counts_every_eighth_fall_of_a12_unfiltered() -> None:
    cart = build(4, 3)
    cart.cpu_write(0xC000, 3, 0)
    cart.cpu_write(0xC001, 0, 0)
    t = 0
    for _ in range(7):  # 1 dot apart: an MMC3 would filter all of these
        cart.ppu_address(0x1000, t)
        cart.ppu_address(0x0000, t + 4)
        t += 8
    assert cart.reload  # seven falls: not yet
    cart.ppu_address(0x1000, t)
    cart.ppu_address(0x0000, t + 4)
    assert cart.counter == 3 and not cart.reload


def test_mmc6_ram_halves_and_their_enables() -> None:
    cart = build(4, 1)
    assert cart.cpu_read(0x7000, 0) is None  # RAM off: open bus
    cart.cpu_write(0xA001, 0xF0, 0)  # ignored while $8000 D5 is clear
    assert cart.protect == 0
    cart.cpu_write(0x8000, 0x20, 0)
    cart.cpu_write(0xA001, 0x30, 0)  # low half read + write only
    cart.cpu_write(0x7001, 0x11, 0)
    cart.cpu_write(0x7201, 0x22, 0)  # high half not writable
    assert cart.cpu_read(0x7001, 0) == 0x11
    assert cart.cpu_read(0x7401, 0) == 0x11  # 1 KiB mirrored through $7000-$7FFF
    assert cart.cpu_read(0x7201, 0) == 0  # one half readable: the other reads 0
    assert cart.cpu_read(0x6001, 0) is None  # $6000-$6FFF: open bus
    cart.cpu_write(0xA001, 0x80, 0)  # high half readable, not writable
    cart.cpu_write(0x7201, 0x22, 0)
    assert cart.cpu_read(0x7201, 0) == 0
    cart.cpu_write(0xA001, 0x40, 0)  # write enable without read enable: no write
    cart.cpu_write(0x7201, 0x33, 0)
    cart.cpu_write(0xA001, 0xC0, 0)
    assert cart.cpu_read(0x7201, 0) == 0
    cart.cpu_write(0x7201, 0x44, 0)
    assert cart.cpu_read(0x7201, 0) == 0x44
    cart.cpu_write(0x8000, 0x00, 0)  # RAM disabled: $A001 held at 0
    assert cart.protect == 0 and cart.cpu_read(0x7201, 0) is None


def test_mmc3_banks_and_modes() -> None:
    cart = build(4)
    for register, value in enumerate((0, 2, 4, 5, 6, 7, 3, 9)):
        cart.cpu_write(0x8000, register, 0)
        cart.cpu_write(0x8001, value, 0)
    # PRG mode 0: R6, R7, second-last, last (8 KiB banks of 1 KiB tags: bank * 8).
    assert [cart.cpu_read(a, 0) for a in (0x8000, 0xA000, 0xC000, 0xE000)] == [24, 72, 112, 120]
    cart.cpu_write(0x8000, 0x40, 0)  # mode 1 swaps $8000 and $C000
    assert [cart.cpu_read(a, 0) for a in (0x8000, 0xC000)] == [112, 24]
    assert [cart.ppu_read(a * 0x400, 0) for a in range(8)] == [0, 1, 2, 3, 4, 5, 6, 7]
    cart.cpu_write(0x8000, 0x80, 0)  # CHR A12 inversion
    assert [cart.ppu_read(a * 0x400, 0) for a in range(8)] == [4, 5, 6, 7, 0, 1, 2, 3]


def test_bnrom_always_has_and_bus_conflicts() -> None:
    # INES_Mapper_034.wiki: "always subject to AND-type bus conflicts". No
    # judge reaches it: 34_test's line for it prints YES on any board (C28).
    cart = build(34, 2, chr_kib=8)
    cart.cpu_write(0x8000, 3, 0)  # the ROM byte at $8000 is 0 (bank 0's tag)
    assert cart.cpu_read(0x8000, 0) == 0  # still bank 0 (32 tags a bank)
    cart.cpu_write(0x8400, 3, 0)  # $8400 holds 1 in bank 0: 3 AND 1
    assert cart.cpu_read(0x8000, 0) == 32
