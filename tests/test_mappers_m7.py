"""Milestone 7's mappers where neither a judge ROM nor the sweep reaches.

The sweep (``scripts/compat_sweep.py``) compares games' frames with Mesen2's
and never saves, so the EEPROMs' protocol, counter edges and latch order
are pinned here on synthetic images (docs/claims.md).
"""

from __future__ import annotations

from test_mappers import TICKS, build, image

from famicom_python.cartridge import MAPPERS, BoardInfo, RomImage
from famicom_python.cartridge.eeprom import X24C01, Eeprom


def send_byte(eeprom: Eeprom, byte: int) -> int:
    """Clock a byte in MSB first; returns the part's acknowledge (0 = ack)."""
    for bit in range(7, -1, -1):
        sda = (byte >> bit) & 1
        eeprom.lines(0, sda)
        eeprom.lines(1, sda)
    eeprom.lines(0, 1)
    eeprom.lines(1, 1)
    ack = eeprom.output
    eeprom.lines(0, 1)
    return ack


def receive_byte(eeprom: Eeprom, last: bool) -> int:
    value = 0
    for _ in range(8):
        eeprom.lines(0, 1)
        eeprom.lines(1, 1)
        value = value << 1 | eeprom.output
    eeprom.lines(0, int(last))
    eeprom.lines(1, int(last))
    eeprom.lines(0, int(last))
    return value


def start(eeprom: Eeprom) -> None:
    eeprom.lines(0, 1)
    eeprom.lines(1, 1)
    eeprom.lines(1, 0)


def stop(eeprom: Eeprom) -> None:
    eeprom.lines(0, 0)
    eeprom.lines(1, 0)
    eeprom.lines(1, 1)


def test_24c02_writes_a_page_and_reads_it_back_randomly() -> None:
    eeprom = Eeprom()
    start(eeprom)
    assert send_byte(eeprom, 0xA0) == 0
    assert send_byte(eeprom, 0x3E) == 0
    for value in (0x11, 0x22, 0x33):  # the third wraps within the 8-byte page
        assert send_byte(eeprom, value) == 0
    stop(eeprom)
    assert eeprom.memory[0x3E:0x40] == b"\x11\x22" and eeprom.memory[0x38] == 0x33
    start(eeprom)
    send_byte(eeprom, 0xA0)
    send_byte(eeprom, 0x3E)
    start(eeprom)  # repeated START: a random read
    assert send_byte(eeprom, 0xA1) == 0
    assert receive_byte(eeprom, last=False) == 0x11
    assert receive_byte(eeprom, last=True) == 0x22
    stop(eeprom)
    start(eeprom)
    assert send_byte(eeprom, 0xA2) == 1  # another device address: no acknowledge


def test_x24c01_takes_the_address_in_the_first_byte() -> None:
    eeprom = X24C01()
    start(eeprom)
    assert send_byte(eeprom, 0x05 << 1) == 0
    send_byte(eeprom, 0x5A)
    stop(eeprom)
    assert eeprom.memory[5] == 0x5A
    start(eeprom)
    send_byte(eeprom, 0x05 << 1 | 1)
    assert receive_byte(eeprom, last=True) == 0x5A


def test_bandai_lz93d50_reads_the_sda_line_on_d4_alone() -> None:
    cart = MAPPERS[16](_with_nvram(image(16, 5), 256), TICKS)
    # D7 set: the master releases SDA; the idle part leaves it high.
    cart.cpu_write(0x800D, 0x80, 0)
    value = cart.cpu_read(0x6000, 0)
    assert value is not None and value & 0xFF == 0x10 and value >> 8 == 0xEF
    assert cart.battery_ram() == bytes(256)


def test_bandai_acknowledge_holds_sda_when_the_master_releases_it() -> None:
    # Rokudenashi Blues: START, device byte $A0, then SCL high on the ninth
    # clock, and only then the release (D7). The 24C02 still pulls SDA low;
    # released SDA reading high there would be a STOP.
    cart = MAPPERS[16](_with_nvram(image(16, 5), 256), TICKS)
    writes = [0x00, 0x40, 0x60, 0x20, 0x00]  # START
    for bit in (1, 0, 1, 0, 0, 0, 0, 0):
        writes += [bit << 6, bit << 6 | 0x20, bit << 6]
    writes += [0x00, 0x20, 0xA0]
    for value in writes:
        cart.cpu_write(0x800D, value, 0)
    value = cart.cpu_read(0x6000, 0)
    assert value is not None and value & 0x10 == 0


def test_datach_chr_ram_is_unbanked() -> None:
    cart = build(157, chr_kib=0)
    for kib in range(8):
        cart.ppu_write(kib * 0x400, kib + 1, 0)
    assert [cart.ppu_read(kib * 0x400, 0) for kib in range(8)] == list(range(1, 9))


def test_bandai_counter_is_tested_then_decremented() -> None:
    cart = build(16, 5)
    cart.cpu_write(0x800B, 2, 0)
    cart.cpu_write(0x800C, 0, 0)
    cart.cpu_write(0x800A, 1, 0)  # the LZ93D50 copies the latch in
    for t in range(3):
        assert not cart.irq
        cart.m2(t)
    assert cart.irq and cart.counter == 0xFFFF


def test_ss88006_counter_widths_borrow_into_irq() -> None:
    cart = build(18)
    for nibble, value in enumerate((1, 2, 0, 0)):  # reload $0021
        cart.cpu_write(0xE000 + nibble, value, 0)
    cart.cpu_write(0xF000, 0, 0)
    cart.cpu_write(0xF001, 0x09, 0)  # 4-bit counter, counting
    cart.m2(0)
    assert cart.counter == 0x20 and not cart.irq
    cart.m2(0)
    assert cart.counter == 0x2F and cart.irq  # the borrow stays in the low nibble


def test_namco163_counts_up_to_7fff_and_stops() -> None:
    cart = build(19)
    cart.cpu_write(0x5000, 0xFE, 0)
    cart.cpu_write(0x5800, 0xFF, 0)  # $7FFE, enabled
    cart.m2(0)
    assert cart.irq and cart.counter == 0x7FFF
    cart.m2(0)
    assert cart.counter == 0x7FFF
    assert cart.cpu_read(0x5800, 0) == 0xFF
    cart.cpu_write(0x5000, 0, 0)
    assert not cart.irq


def test_namco163_chip_ram_port_auto_increments() -> None:
    cart = build(19)
    cart.cpu_write(0xF800, 0x80 | 0x10, 0)
    cart.cpu_write(0x4800, 0xAB, 0)
    cart.cpu_write(0x4800, 0xCD, 0)
    assert cart.chip_ram[0x10:0x12] == b"\xab\xcd"


def test_namco163_nametables_from_chr_rom() -> None:
    cart = build(19)
    cart.cpu_write(0xC000, 0xE1, 0)  # CIRAM B
    cart.cpu_write(0xC800, 0x05, 0)  # CHR-ROM page 5
    assert cart.ciram_a10(0x2000) == 1
    assert cart.ciram_a10(0x2400) is None and cart.ppu_read(0x2400, 0) == 5


def test_mmc2_latch_switches_after_the_triggering_read() -> None:
    cart = build(9)
    cart.cpu_write(0xD000, 3, 0)  # $FD/1000
    cart.cpu_write(0xE000, 7, 0)  # $FE/1000 (the power-on latch)
    assert cart.ppu_read(0x1FD8, 0) == 7 * 4 + 3  # the trigger itself: the old bank
    assert cart.ppu_read(0x1000, 0) == 3 * 4
    cart.cpu_write(0xB000, 1, 0)
    cart.cpu_write(0xC000, 2, 0)
    cart.ppu_read(0x0FD9, 0)  # latch 0 answers $0FD8 alone on the MMC2
    assert cart.ppu_read(0x0000, 0) == 2 * 4
    mmc4 = build(10)
    mmc4.cpu_write(0xB000, 1, 0)
    mmc4.ppu_read(0x0FD9, 0)
    assert mmc4.ppu_read(0x0000, 0) == 1 * 4


def test_txsrom_chr_d7_is_ciram_a10() -> None:
    cart = build(118)
    for register, bank in ((0, 0x80), (1, 0x00)):
        cart.cpu_write(0x8000, register, 0)
        cart.cpu_write(0x8001, bank, 0)
    assert [cart.ciram_a10(0x2000 + 0x400 * i) for i in range(4)] == [1, 1, 0, 0]
    cart.cpu_write(0x8000, 0x80 | 3, 0)  # CHR inversion: R2-R5 own $0000-$0FFF
    cart.cpu_write(0x8001, 0x80, 0)
    assert [cart.ciram_a10(0x2000 + 0x400 * i) for i in range(4)] == [0, 1, 0, 0]


def test_cnrom_185_disables_chr_unless_the_chip_selects_match() -> None:
    cart = build(185, 5, prg_kib=32, chr_kib=8)
    cart.cpu_write(0x8000, 0x01, 0)  # bus conflict: the ROM byte there is 0
    assert cart.ppu_read(0x0000, 0) == 0x01  # disabled: low byte, D0 pulled up
    cart.prg = bytes([0xFF]) * len(cart.prg)
    cart.cpu_write(0x8000, 0x01, 0)
    assert cart.ppu_read(0x0800, 0) == 2


def _with_nvram(rom: RomImage, nvram: int) -> RomImage:
    board = rom.board
    return RomImage(
        rom.header,
        rom.trainer,
        rom.prg,
        rom.chr,
        rom.misc,
        BoardInfo(mapper=board.mapper, submapper=board.submapper, prg_nvram=nvram),
        True,
    )
