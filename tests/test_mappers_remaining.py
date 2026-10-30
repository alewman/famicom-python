"""The unlicensed and homebrew mappers (2026-10-30) on synthetic images.

No judge ROM exists for these boards, and Mesen2 refuses most of them, so their
claims rest on their wiki pages and on looking at the screen (docs/validation.md
"The remaining mappers"). These pin the arithmetic: register decoding, bit
orders, what a reset does, the counters' edges.
"""

from __future__ import annotations

from test_mappers import build

from famicom_python.cartridge.eeprom import Microwire93C56, Microwire93C66
from famicom_python.cartridge.flash import Flash29F040
from famicom_python.cartridge.pic16c54 import PIC16C54, STATUS, Z


def offset(cart, address: int) -> int:
    """The PRG offset behind a CPU address."""
    return cart.prg_offsets[(address >> 13) & 3] + (address & 0x1FFF)


# -- memory parts ---------------------------------------------------------


def shift(part, bits: str) -> None:
    for bit in bits:
        part.lines(1, 0, int(bit))
        part.lines(1, 1, int(bit))
        part.lines(1, 0, int(bit))


def test_93c56_reads_back_a_16_bit_word_msb_first() -> None:
    part = Microwire93C56()
    shift(part, "1" + "00" + "11000000")  # EWEN
    part.lines(0, 0, 0)
    shift(part, "1" + "01" + "00000011" + "1010010111000011")  # WRITE word 3
    part.lines(0, 0, 0)
    assert part.memory[6:8] == bytes([0xA5, 0xC3])
    shift(part, "1" + "10" + "00000011")  # READ
    assert part.output == 0  # the dummy bit
    bits = ""
    for _ in range(16):
        part.lines(1, 1, 0)
        bits += str(part.output)
        part.lines(1, 0, 0)
    assert bits == "1010010111000011"


def test_93c66_still_has_nine_address_bits() -> None:
    part = Microwire93C66()
    shift(part, "1" + "00" + "110000000")  # EWEN
    part.lines(0, 0, 0)
    shift(part, "1" + "01" + "100000001" + "01011010")  # WRITE byte $101
    part.lines(0, 0, 0)
    assert part.memory[0x101] == 0x5A


def test_29f040_unlocks_on_its_low_eleven_lines_and_erases_64_kib() -> None:
    data = bytearray([0xFF]) * 0x80000
    flash = Flash29F040(data, 0xC2, 0xA4)
    for address, value in ((0x8555, 0xAA), (0x82AA, 0x55), (0x8555, 0xA0), (0x12345, 0x0F)):
        flash.write(address, value)
    assert data[0x12345] == 0x0F
    for address, value in ((0x555, 0xAA), (0x2AA, 0x55), (0x555, 0x90)):
        flash.write(address, value)
    assert flash.read(0) == 0xC2 and flash.read(1) == 0xA4
    flash.write(0, 0xF0)
    for address, value in (
        (0x555, 0xAA),
        (0x2AA, 0x55),
        (0x555, 0x80),
        (0x555, 0xAA),
        (0x2AA, 0x55),
        (0x10000, 0x30),
    ):
        flash.write(address, value)
    assert data[0x12345] == 0xFF


def pic(*words: int) -> PIC16C54:
    """A PIC whose reset vector jumps to ``words`` at 0."""
    program = bytearray(1024)
    for i, word in enumerate(words):
        program[i * 2 : i * 2 + 2] = word.to_bytes(2, "little")
    program[0x1FF * 2 : 0x1FF * 2 + 2] = (0xA00).to_bytes(2, "little")  # GOTO 0
    return PIC16C54(bytes(program))


def test_pic_arithmetic_flags_and_skips() -> None:
    core = pic(
        0xC05,  # MOVLW 5
        0x027,  # MOVWF 7
        0x0C7,  # DECF 7, W
        0x2E7,  # DECFSZ 7, F
        0xCFF,  # MOVLW $FF, not skipped
        0xC11,  # MOVLW $11
    )
    for _ in range(2 + 5):
        core.cycle()
    assert core.memory[7] == 4 and core.w == 0xFF
    assert not core.memory[STATUS] & Z


def test_pic_call_and_retlw() -> None:
    core = pic(0x904, 0x000, 0x000, 0x000, 0x842)  # CALL 4; ... RETLW $42
    for _ in range(2 + 2 + 2):
        core.cycle()
    assert core.w == 0x42 and core.pc == 1


# -- FDS conversions ------------------------------------------------------


def test_ks7010_switches_on_reads_of_its_magic_addresses() -> None:
    cart = build(554, prg_kib=128, chr_kib=128)
    assert cart.prg_offsets == [10 * 0x2000, 11 * 0x2000, 6 * 0x2000, 7 * 0x2000]
    cart.cpu_read(0xCAB8, 0)  # A5-A2 = %1110
    assert cart.bank6000 == 0x0E and cart.chr_offsets[0] == 0x0E * 0x2000
    cart.cpu_read(0xC000, 0)
    assert cart.bank6000 == 0x0E


def test_ctc15_latches_by_address_and_applies_on_5000() -> None:
    cart = build(548, prg_kib=128, chr_kib=0)
    assert cart.prg_offsets[0] == 7 * 0x4000 and cart.prg_offsets[2] == 3 * 0x4000
    cart.cpu_write(0x4800 | 0x20 | 0x04, 0, 0)  # A, C
    assert cart.prg_offsets[0] == 7 * 0x4000
    cart.cpu_write(0x5000, 0, 0)
    assert cart.prg_offsets[0] == (0b101 ^ 5) * 0x4000


def test_ctc15_irq_window() -> None:
    cart = build(548, prg_kib=128, chr_kib=0)
    cart.cpu_write(0x4800, 0, 0)  # C clear: counting
    for _ in range(23679):
        cart.m2(0)
    assert not cart.irq
    cart.m2(0)
    assert cart.irq
    for _ in range(640):
        cart.m2(0)
    assert not cart.irq


def test_yung08_latch_reads_back_with_its_fixed_bits() -> None:
    cart = build(368, prg_kib=128, chr_kib=8)
    cart.cpu_write(0x4122, 0x35, 0)
    assert cart.cpu_read(0x4122, 0) == 0b10111111
    cart.cpu_write(0x4122, 0x00, 0)
    assert cart.cpu_read(0x4122, 0) == 0b10001010
    cart.cpu_write(0x4022, 2, 0)
    assert cart.prg_offsets[2] == 5 * 0x2000


def test_mapper_538_bank_table() -> None:
    cart = build(538, prg_kib=128, chr_kib=0)
    expected = {0: (1, 0), 1: (1, 10), 3: (3, 10), 8: (9, 8), 9: (9, 8), 0xF: (0xF, 0xE)}
    for value, (six, eight) in expected.items():
        cart.cpu_write(0xC000, value, 0)
        assert cart.bank6000 == six and cart.prg_offsets[0] == eight * 0x2000


def test_ks7030_lays_ram_over_rom_in_order() -> None:
    cart = build(347, prg_kib=128, chr_kib=0)
    cart.cpu_write(0xB800, 0x12, 0)
    cart.cpu_write(0xCC00, 0x34, 0)
    assert cart.prg_ram[0xC00] == 0x12 and cart.prg_ram[0x1400] == 0x34
    assert cart.cpu_read(0xB800, 0) == 0x12
    cart.cpu_write(0x9005, 0, 0)  # by address
    assert cart._place(0xC000) == (False, 5 * 0x1000)
    assert cart._place(0x6C00) == (False, 5 * 0x1000 + 0xC00)


# -- multicarts -----------------------------------------------------------


def test_mapper_380_modes() -> None:
    cart = build(380, prg_kib=512, chr_kib=0)
    assert cart.prg_offsets[2] == 7 * 0x4000  # UNROM at power-on
    cart.cpu_write(0x8000 | 0x200 | 3 << 2, 0, 0)  # NROM-256, bank 3
    assert cart.prg_offsets[0] == 2 * 0x4000 and cart.prg_offsets[2] == 3 * 0x4000
    cart.cpu_write(0x8000 | 0x200 | 3 << 2 | 1, 0, 0)  # NROM-128
    assert cart.prg_offsets[0] == 3 * 0x4000 and cart.prg_offsets[2] == 3 * 0x4000


def test_mapper_400_outer_banks_and_the_mask_on_7000() -> None:
    cart = build(400, prg_kib=4096, chr_kib=0)
    cart.cpu_write(0x7000, 3 << 3, 0)
    cart.cpu_write(0xC000, 5, 0)
    assert cart.prg_offsets[0] == (3 * 8 + 5) * 0x4000
    cart.cpu_write(0x7001, 7 << 3, 0)  # 8-Bit XMAS 2008's stray APU writes
    assert cart.prg_offsets[0] == (3 * 8 + 5) * 0x4000


def test_mapper_471_irq_on_a12_fall_acknowledged_by_the_latch() -> None:
    cart = build(471, prg_kib=64, chr_kib=16)
    cart.ppu_address(0x1000, 0)
    assert not cart.irq
    cart.ppu_address(0x0000, 0)
    assert cart.irq
    cart.cpu_write(0x8001, 0, 0)
    assert not cart.irq and cart.prg_offsets[0] == 0x8000


def test_mapper_374_steps_on_a_reset() -> None:
    cart = build(374, prg_kib=512, chr_kib=512)
    before = cart.prg_offsets[3]
    cart.m2_gap(0)
    assert cart.prg_offsets[3] == before + 0x20000
    for _ in range(3):
        cart.m2_gap(0)
    assert cart.prg_offsets[3] == before


def test_sb5013_m2_counter_counts_down_to_an_irq() -> None:
    cart = build(359, prg_kib=512, chr_kib=256)
    cart.cpu_write(0xC000, 3, 0)
    cart.cpu_write(0xC001, 0, 0)
    cart.cpu_write(0xC002, 1, 0)
    cart.m2(0)
    cart.m2(0)
    assert not cart.irq
    cart.m2(0)
    assert cart.irq


def test_mapper_540_two_kib_chr_registers() -> None:
    cart = build(540, prg_kib=256, chr_kib=512)
    cart.cpu_write(0xB003, 9, 0)
    assert cart.chr_offsets[6] == 9 * 0x800 and cart.chr_offsets[7] == 9 * 0x800 + 0x400


def test_hsk007_switches_between_its_asics() -> None:
    cart = build(394, prg_kib=1024, chr_kib=1024)
    assert cart.asic is cart.mmc3  # power-on $0F
    cart.cpu_write(0x5009, 0x10, 0)
    assert cart.asic is cart.jy
    cart.cpu_write(0x5009, 0x00, 0)
    assert cart.asic is None


# -- MMC3 and VRC relatives -----------------------------------------------


def test_mapper_334_needs_the_ram_enable_for_its_register() -> None:
    cart = build(334, prg_kib=128, chr_kib=64)
    cart.cpu_write(0x6000, 2, 0)
    assert cart.prg_offsets[0] == 0
    cart.cpu_write(0xA001, 0x80, 0)
    cart.cpu_write(0x6000, 2, 0)
    assert cart.prg_offsets[0] == 0x8000


def test_mapper_516_outer_bank_by_address() -> None:
    cart = build(516, prg_kib=512, chr_kib=512)
    cart.cpu_write(0x8010 | 0b0110, 0, 0)  # CHR outer 1, PRG outer 2
    assert cart.prg_offsets[3] == 2 * 0x20000 + 15 * 0x2000


def test_mapper_266_exchanges_a13_and_a14() -> None:
    cart = build(266, prg_kib=128, chr_kib=128)
    cart.cpu_write(0xD000, 5, 0)  # the VRC's $B000: PPU $0000
    assert cart.chr_offsets[0] == 5 * 0x400
    cart.cpu_write(0xA000, 6, 0)  # its $C000: PPU $0800
    assert cart.chr_offsets[2] == 6 * 0x400
    cart.cpu_write(0x900C, 2 << 2, 0)
    assert cart.prg_offsets[0] == 2 * 0x8000


def test_fs306_chr_ram_window_moves_on_a_write_to_rom() -> None:
    cart = build(544, prg_kib=512, chr_kib=512)
    cart.cpu_write(0xB000, 8, 0)  # $28 low nibble ...
    cart.cpu_write(0xB400, 2, 0)  # ... and high: the RAM's first bank at power-on
    assert cart.chr_ram_window[0]
    cart.ppu_write(0x0000, 0x7E, 0)
    assert cart.ppu_read(0x0000, 0) == 0x7E
    cart.cpu_write(0xB000, 4, 0)
    cart.cpu_write(0xB400, 0, 0)  # bank 4: ROM until $C8 picks it
    assert not cart.chr_ram_window[0]
    cart.ppu_write(0x0000, 0xC8, 0)
    assert cart.chr_ram_window[0]


# -- the triage's additions -----------------------------------------------


def test_mapper_74_rom_banks_keep_their_numbers() -> None:
    cart = build(74, prg_kib=128, chr_kib=256)
    cart.map_chr(0, 1, 0x0A)
    assert not cart.chr_ram_window[0] and cart.chr_offsets[0] == 0x0A * 0x400
    cart.map_chr(1, 1, 9)
    assert cart.chr_ram_window[1] and cart.chr_offsets[1] == 0x400


def test_mapper_112_powers_on_with_vertical_mirroring() -> None:
    assert build(112, prg_kib=128, chr_kib=128).mirroring == "V"


def test_mapper_42_2_banks_6000_from_8001() -> None:
    cart = build(42, prg_kib=160, chr_kib=0, submapper=2)
    cart.cpu_write(0x8000, 5, 0)
    cart.cpu_write(0x8001, 0x3E, 0)
    assert cart.bank6000 == 15
    cart.cpu_write(0x8001, 0x14, 0)
    assert cart.bank6000 == 10


def test_mapper_415_latch() -> None:
    cart = build(415, prg_kib=128, chr_kib=0)
    assert cart.prg_offsets[0] == 96 * 1024
    cart.cpu_write(0xBFFF, 0x1B, 0)
    assert cart.bank6000 == 0x0B and cart.mirroring == "H"
    cart.cpu_write(0xBFFF, 0x07, 0)
    assert cart.bank6000 == 7 and cart.mirroring == "V"


def test_mapper_553_reads_3a_low() -> None:
    cart = build(553, prg_kib=16, chr_kib=8)
    assert cart.cpu_read(0x8000, 0) == 0x3A and cart.cpu_read(0xBFFF, 0) == 0x3A
    assert cart.cpu_read(0xC000, 0) == cart.prg[0]


def test_mapper_530_scrambles_lines_and_takes_a3_for_a12() -> None:
    cart = build(530, prg_kib=128, chr_kib=128)
    cart.cpu_write(0x8000, 0x02, 0)  # PRG A14 goes out as A16
    assert cart.prg_offsets[0] == 8 * 0x2000
    cart.cpu_write(0xA008, 0x0F, 0)  # the VRC4's $B000: low nibble of bank 0
    cart.cpu_write(0xA009, 0x02, 0)  # high nibble: bank $2F: CHR A15 goes out as A16
    assert cart.chr_offsets[0] == 0x4F * 0x400


def test_mapper_326_masks() -> None:
    cart = build(326, prg_kib=128, chr_kib=128)
    cart.cpu_write(0xA000, 3, 0)
    assert cart.prg_offsets[1] == 3 * 0x2000
    cart.cpu_write(0xF013, 5, 0)
    assert cart.chr_offsets[3] == 5 * 0x400
    cart.cpu_write(0xF018, 1, 0)
    assert cart.nametables[0] == 1 and cart.ciram_a10(0x2000) == 1


def test_mapper_330_counter_stops_at_the_wrap() -> None:
    cart = build(330, prg_kib=256, chr_kib=256)
    cart.cpu_write(0x8C00, 0xFE, 0)
    cart.cpu_write(0xAC00, 0xFF, 0)
    cart.m2(0)
    assert not cart.irq
    cart.m2(0)
    assert cart.irq and cart.counter == 0 and not cart.counting
    cart.m2(0)
    assert cart.counter == 0
    cart.cpu_write(0xAC00, 0, 0)
    assert not cart.irq


def test_mappers_252_253_ram_pages() -> None:
    cart = build(253, prg_kib=256, chr_kib=512)
    cart.map_chr(0, 1, 5)
    cart.map_chr(1, 1, 6)
    assert cart.chr_ram_window[:2] == [True, False] and cart.chr_offsets[0] == 0x400
    assert build(252, prg_kib=256, chr_kib=128).first_ram == 6


def test_mapper_117_registers() -> None:
    cart = build(117, prg_kib=128, chr_kib=128)
    cart.cpu_write(0x8002, 4, 0)
    assert cart.prg_offsets[2] == 4 * 0x2000
    cart.cpu_write(0xA003, 9, 0)
    assert cart.chr_offsets[3] == 9 * 0x400
    cart.cpu_write(0xC000, 2, 0)
    cart.cpu_write(0xE000, 1, 0)
    for rise in range(2):
        cart.ppu_address(0, rise * 1000)
        cart.ppu_address(0x1000, rise * 1000 + 500)
    assert cart.irq
