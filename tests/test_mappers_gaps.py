"""The licensed-gap mappers (2026-10-29) on synthetic images: their wiki pages' bank arithmetic.

No judge ROM exists for these boards; the sweeps against Mesen2 carry the
claims (docs/validation.md "The licensed gaps"). These pin what a game might
not reach: register decoding, bit orders, the counters' edges.
"""

from __future__ import annotations

from test_mappers import build

PRG_8K, PRG_16K = 8, 16  # the PRG label at a bank's start: its first 1 KiB's number


def prg(cart, address: int) -> int:
    return cart.cpu_read(address, 0)


def chr_bank(cart, address: int) -> int:
    return cart.ppu_read(address, 0)


def test_jf17_loads_banks_on_a_command_bits_rise() -> None:
    cart = build(72, prg_kib=128, chr_kib=128)
    cart.prg = bytearray([0xFF]) * len(cart.prg)  # no bus conflicts in the way
    cart.cpu_write(0x8000, 0x83, 0)  # D7 rises: PRG 3
    assert cart.prg_offsets[0] == 3 * 0x4000
    cart.cpu_write(0x8000, 0x85, 0)  # D7 still high: no load
    assert cart.prg_offsets[0] == 3 * 0x4000
    cart.cpu_write(0x8000, 0x00, 0)
    cart.cpu_write(0x8000, 0x45, 0)  # D6 rises: CHR 5
    assert chr_bank(cart, 0x0000) == 5 * 8


def test_mapper_92_fixes_the_first_bank() -> None:
    cart = build(92, prg_kib=256)
    cart.prg = bytearray([0xFF]) * len(cart.prg)
    cart.cpu_write(0x8000, 0x8A, 0)
    assert cart.prg_offsets[0] == 0 and cart.prg_offsets[2] == 10 * 0x4000


def test_camerica_quattro_outer_banks_and_the_aladdin_swap() -> None:
    cart = build(232, prg_kib=256, chr_kib=0)
    cart.cpu_write(0x8000, 0x10, 0)  # outer 2
    cart.cpu_write(0xC000, 0x01, 0)  # inner 1
    assert prg(cart, 0x8000) == (2 * 4 + 1) * PRG_16K and prg(cart, 0xC000) == (2 * 4 + 3) * PRG_16K
    aladdin = build(232, 1, prg_kib=256, chr_kib=0)
    aladdin.cpu_write(0x8000, 0x10, 0)  # bits swapped: outer 1
    assert prg(aladdin, 0xC000) == (1 * 4 + 3) * PRG_16K


def test_fire_hawk_mirroring_waits_for_9000_without_a_submapper() -> None:
    cart = build(71, prg_kib=128, chr_kib=0)
    before = cart.mirroring
    cart.cpu_write(0x8000, 0x10, 0)  # Micro Machines' startup write: not the register
    assert cart.mirroring == before
    cart.cpu_write(0x9000, 0x10, 0)
    assert cart.ciram_a10(0x2000) == 1


def test_nina03_register_decodes_a14_a8_high_a13_low() -> None:
    cart = build(79, prg_kib=64, chr_kib=64)
    cart.cpu_write(0x4100, 0x0D, 0)  # PRG 1, CHR 5
    assert prg(cart, 0x8000) == 32 and chr_bank(cart, 0) == 40
    cart.cpu_write(0x4000 | 0x2000 | 0x100, 0x00, 0)  # $6100: A13 high, not the register
    cart.cpu_write(0x4200, 0x00, 0)  # A8 low, not the register
    assert chr_bank(cart, 0) == 40


def test_lrog017_splits_ppu_space_in_2k_regions() -> None:
    cart = build(77, prg_kib=128, chr_kib=32)
    cart.prg = bytearray([0xFF]) * len(cart.prg)
    cart.cpu_write(0x8000, 0x31, 0)  # CHR-ROM 2 KiB bank 3
    assert chr_bank(cart, 0x0000) == 6
    cart.ppu_write(0x0800, 0xAB, 0)
    cart.ppu_write(0x2400, 0xCD, 0)  # the RAM's last 2 KiB: a nametable
    assert chr_bank(cart, 0x0800) == 0xAB and chr_bank(cart, 0x2400) == 0xCD
    assert cart.ciram_a10(0x2800) == 0 and cart.ciram_a10(0x2C00) == 1
    assert cart.ciram_a10(0x2000) is None and cart.ppu_read(0x3000, 0) is None


def test_sunsoft4_maps_chr_rom_into_the_nametables() -> None:
    cart = build(68, prg_kib=128, chr_kib=256)
    cart.cpu_write(0xC000, 0x05, 0)  # low nametable: 1 KiB bank $85 (D7 forced)
    cart.cpu_write(0xD000, 0x06, 0)
    cart.cpu_write(0xE000, 0x11, 0)  # ROM nametables, horizontal
    assert cart.ciram_a10(0x2000) is None
    assert cart.ppu_read(0x2400, 0) == 0x85 and cart.ppu_read(0x2800, 0) == 0x86


def test_x1017_reverses_prg_lines_on_552_only() -> None:
    old = build(82, prg_kib=128)
    old.cpu_write(0x7EFA, 0x04, 0)  # D2: A13 on 82
    assert prg(old, 0x8000) == 1 * PRG_8K
    new = build(552, prg_kib=512)
    new.cpu_write(0x7EFA, 0x20, 0)  # D5: A13 on 552
    new.cpu_write(0x7EFB, 0x01, 0)  # D0: A18
    assert prg(new, 0x8000) == 1 * PRG_8K and prg(new, 0xA000) == (32 * PRG_8K) & 0xFF


def test_x1017_ram_enables_by_magic_value_and_reads_0_when_off() -> None:
    cart = build(82, prg_kib=128)
    cart.cpu_write(0x6000, 0x55, 0)
    assert prg(cart, 0x6000) == 0  # disabled: the pull-downs
    cart.cpu_write(0x7EF7, 0xCA, 0)
    cart.cpu_write(0x6000, 0x55, 0)
    assert prg(cart, 0x6000) == 0x55 and prg(cart, 0x6800) == 0


def test_x1005_registers_ignore_a7_and_its_ram_needs_a3() -> None:
    cart = build(80, prg_kib=128)
    cart.cpu_write(0x7E7A, 0x05, 0)  # the $7EFA mirror
    assert prg(cart, 0x8000) == 5 * PRG_8K
    cart.cpu_write(0x7F00, 0x12, 0)
    assert prg(cart, 0x7F80) is None
    cart.cpu_write(0x7EF8, 0xA3, 0)
    cart.cpu_write(0x7F00, 0x12, 0)
    assert prg(cart, 0x7F80) == 0x12  # mirrored


def test_mapper_37_prg_windows_follow_the_wiki_table() -> None:
    cart = build(37, prg_kib=256, chr_kib=256)
    # Value written -> the 64/128 KiB window: 3 -> $10000, 7 -> $30000.
    for outer, base_kib in ((0, 0), (3, 64), (4, 128), (7, 192)):
        cart.cpu_write(0x6000, outer, 0)
        assert prg(cart, 0x8000) // 64 * 64 == base_kib, outer


def test_mapper_47_latch_needs_the_mmc3_ram_enabled() -> None:
    cart = build(47, prg_kib=256, chr_kib=256)
    cart.cpu_write(0xA001, 0x00, 0)  # "RAM" disabled
    cart.cpu_write(0x6000, 1, 0)
    assert prg(cart, 0xE000) == 120  # still block 0's last bank
    cart.cpu_write(0xA001, 0x80, 0)
    cart.cpu_write(0x6000, 1, 0)
    assert prg(cart, 0xE000) == 248


def test_tqrom_mixes_chr_rom_and_ram() -> None:
    cart = build(119, prg_kib=128, chr_kib=64)
    cart.cpu_write(0x8000, 2, 0)
    cart.cpu_write(0x8001, 0x41, 0)  # R2 = RAM bank 1 at $1000
    cart.ppu_write(0x1000, 0x77, 0)
    assert chr_bank(cart, 0x1000) == 0x77
    cart.ppu_write(0x1400, 0x77, 0)  # R3 = ROM: no write
    assert chr_bank(cart, 0x1400) == 0


def test_vrc3_counts_up_and_reloads_on_overflow() -> None:
    cart = build(73, prg_kib=128, chr_kib=0)
    for i, nibble in enumerate((0xD, 0xF, 0xF, 0xF)):  # reload $FFFD
        cart.cpu_write(0x8000 + 0x1000 * i, nibble, 0)
    cart.cpu_write(0xC000, 0x02, 0)  # enable: reload the counter
    cart.m2(0)
    cart.m2(0)
    assert not cart.irq
    cart.m2(0)  # $FFFF -> overflow
    assert cart.irq and cart.counter == 0xFFFD


def test_h3001_counts_down_to_zero_and_stops() -> None:
    cart = build(65, prg_kib=256)
    assert prg(cart, 0xA000) == 1 * PRG_8K  # the power-on $A000
    cart.cpu_write(0x9006, 2, 0)
    cart.cpu_write(0x9004, 0, 0)
    cart.cpu_write(0x9003, 0x80, 0)
    cart.m2(0)
    assert not cart.irq
    cart.m2(0)
    assert cart.irq and cart.counter == 0
    cart.m2(0)
    assert cart.counter == 0
    cart.cpu_write(0x9000, 0x80, 0)  # bank 0 moves to $C000
    assert prg(cart, 0x8000) == 30 * PRG_8K


def test_sunsoft3_wraps_asserts_and_pauses() -> None:
    cart = build(67, prg_kib=128)
    cart.cpu_write(0xD800, 0x00, 0)  # reset the toggle
    cart.cpu_write(0xC800, 0x00, 0)
    cart.cpu_write(0xC800, 0x01, 0)  # count = 1
    cart.cpu_write(0xD800, 0x10, 0)
    cart.m2(0)
    assert not cart.irq
    cart.m2(0)  # $0000 -> $FFFF
    assert cart.irq and not cart.counting
    cart.cpu_write(0x9800, 0x07, 0)  # CHR bank at $0800
    assert chr_bank(cart, 0x0800) == 14


def test_oeka_kids_latches_a9_a8_on_entering_the_nametables() -> None:
    cart = build(96, prg_kib=128, chr_kib=0)
    cart.ppu_address(0x2300, 0)  # banks 3
    cart.ppu_write(0x0000, 0x33, 0)
    cart.ppu_address(0x2100, 0)  # still in $2xxx: no latch
    assert chr_bank(cart, 0x0000) == 0x33
    cart.ppu_address(0x1000, 0)
    cart.ppu_address(0x2100, 0)  # entered again: bank 1
    assert chr_bank(cart, 0x0000) == 0


def test_rambo1_k_mode_and_rf() -> None:
    cart = build(64, prg_kib=256, chr_kib=256)
    for register, value in ((0, 0x10), (8, 0x21), (1, 0x30), (9, 0x41), (15, 3)):
        cart.cpu_write(0x8000, 0x20 | register, 0)
        cart.cpu_write(0x8001, value, 0)
    assert [chr_bank(cart, a) for a in (0, 0x400, 0x800, 0xC00)] == [0x10, 0x21, 0x30, 0x41]
    assert prg(cart, 0xC000) == 3 * PRG_8K
    cart.cpu_write(0x8000, 0x40, 0)  # P: RF moves to $8000
    assert prg(cart, 0x8000) == 3 * PRG_8K


def test_nes_event_unlocks_after_i_goes_0_then_1() -> None:
    cart = build(105, prg_kib=256, chr_kib=0)

    def mmc1(address: int, value: int) -> None:
        for bit in range(5):
            cart.cpu_write(address, (value >> bit) & 1, bit * 100)

    mmc1(0xA000, 0x02)  # I = 0, O = 0, A = 1: still locked
    assert prg(cart, 0x8000) == 0
    mmc1(0xA000, 0x12)  # I = 1: unlocked
    assert prg(cart, 0x8000) == 32
