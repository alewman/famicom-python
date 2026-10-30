"""Homebrew mappers: Action 53 (28), the NSF subset (31) and GTROM (111).

Mapper 31's judge, rainwarrior's 31_test, is in the mapper suite
(``testrom.MAPPER_ROMS``). Mapper 28's, tepples's test28 v0.04, needs Start and
a reset partway through, and draws its verdict in a proportional font the
harness cannot read: its final frame, which shows "PASS! RESET LEAVES BANK
UNCHANGED." (checked by eye, docs/validation.md), is pinned by CRC here.
GTROM has no test ROM: GTROM.wiki and the SST39SF040 data sheet are what its
tests pin.
"""

from __future__ import annotations

import zipfile
import zlib

import pytest
from conftest import ROMS, nrom_image

from famicom_python.cartridge import load
from famicom_python.cartridge.flash import SST39SF040
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


def test_flash_command_sequences() -> None:
    flash = SST39SF040(bytearray(range(256)) * 0x800)  # 512 KiB
    unlock = ((0x5555, 0xAA), (0x2AAA, 0x55))

    def sequence(*writes: tuple[int, int]) -> None:
        for offset, value in writes:
            flash.write(offset, value)

    sequence(*unlock, (0x5555, 0xA0), (0x12345, 0x0F))
    assert flash.data[0x12345] == 0x45 & 0x0F  # Byte-Program only clears bits
    sequence(*unlock, (0x5555, 0x80), *unlock, (0x12FFF, 0x30))
    assert flash.data[0x12000:0x13000] == bytes([0xFF]) * 0x1000  # its 4 KiB sector
    assert flash.data[0x11FFF] == 0xFF and flash.data[0x13000] == 0  # and no more
    sequence(*unlock, (0x5555, 0x90))
    assert (flash.read(0), flash.read(1), flash.read(2)) == (0xBF, 0xB7, 2)
    sequence((0x0000, 0xF0))  # the short exit
    assert flash.read(0) == 0
    sequence((0xD555, 0xAA), (0x2AAA, 0x55), (0x5555, 0x90))  # A18-A15 don't care
    assert flash.id_mode
    sequence(*unlock, (0x5555, 0xF0))  # the long exit
    assert not flash.id_mode
    sequence((0x5555, 0xAA), (0x2AAB, 0x55), (0x5555, 0xA0), (0x10, 0x00))  # aborted
    assert flash.data[0x10] == 0x10
    sequence(*unlock, (0x5555, 0x80), *unlock, (0x5555, 0x10))
    assert flash.data == bytes([0xFF]) * len(flash.data)  # Chip-Erase
    assert flash.dirty


def gtrom_image(banks: int, program: bytes = b"") -> bytes:
    """A mapper-111 image: each 32 KiB bank begins with ``program`` (the reset
    vector at $8000 in all of them) and holds its own number at $8100."""
    prg = bytearray(banks * 0x8000)
    for bank in range(banks):
        base = bank * 0x8000
        prg[base : base + len(program)] = program
        prg[base + 0x100] = bank
        prg[base + 0x7FFC : base + 0x7FFE] = (0x00, 0x80)
    header = b"NES\x1a" + bytes((banks * 2, 0, 0xF0, 0x60)) + bytes(8)  # 111 = $6F
    return header + bytes(prg)


def test_gtrom_register_banks_prg_chr_and_nametables() -> None:
    cart = load(gtrom_image(16), use_database=False).cartridge
    for address in (0x5000, 0x5FFF, 0x7000, 0x7ABC):
        cart.cpu_write(address, 0x37, 0)  # PRG 7, CHR 1, nametables 1
        assert cart.cpu_read(0x8100, 0) == 7
        cart.cpu_write(address, 0, 0)
    cart.cpu_write(0x6000, 0x05, 0)  # not decoded: A12 low
    cart.cpu_write(0x4800, 0x05, 0)  # nor here: A12 low
    assert cart.cpu_read(0x8100, 0) == 0
    cart.cpu_write(0x5000, 0x10, 0)
    cart.ppu_write(0x0005, 0xA1, 0)
    assert cart.chr[0x2005] == 0xA1
    assert cart.ciram_a10(0x2000) is None  # four screens of cartridge RAM
    for page in (0, 1):
        cart.cpu_write(0x5000, page << 5, 0)
        cart.ppu_write(0x2C00, 0x40 + page, 0)
        cart.ppu_write(0x3123, 0x50 + page, 0)  # the bonus RAM: not $2123
    assert cart.chr[0x4000 + 0x0C00] == 0x40 and cart.chr[0x6000 + 0x0C00] == 0x41
    assert cart.ppu_read(0x3123, 0) == 0x51 and cart.ppu_read(0x2123, 0) == 0


def test_gtrom_flashes_through_the_selected_bank() -> None:
    cart = load(gtrom_image(16), use_database=False).cartridge
    for bank, address, value in ((5, 0xD555, 0xAA), (9, 0xAAAA, 0x55), (0, 0xD555, 0xA0)):
        cart.cpu_write(0x5000, bank, 0)  # the unlock addresses work in any bank
        cart.cpu_write(address, value, 0)
    cart.cpu_write(0x5000, 3, 0)
    cart.cpu_write(0x8100, 0x01, 0)  # program bank 3's $8100 (3) with $01
    assert cart.cpu_read(0x8100, 0) == 1
    assert cart.battery_ram()[3 * 0x8000 + 0x100] == 1  # the flash is the save


def test_gtrom_register_latches_open_bus_on_reads() -> None:
    # LDA #$03 / STA $5000 / LDA $5000 / JMP *: the read latches the bus's
    # byte as M2 falls, the operand's high byte, $50.
    program = bytes((0xA9, 0x03, 0x8D, 0x00, 0x50, 0xAD, 0x00, 0x50, 0x4C, 0x08, 0x80))
    system = System.from_rom(gtrom_image(4, program))
    system.run_frames(1)
    assert system.cartridge.register == 0x50
