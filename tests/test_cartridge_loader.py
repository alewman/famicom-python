"""The iNES/NES 2.0 parser and the board-identification order (docs/cartridge.md)."""

from __future__ import annotations

import pytest
from conftest import nrom_image

from famicom_python.cartridge import BoardInfo, load
from famicom_python.cartridge.database import NES20DB, load_nes20db
from famicom_python.cartridge.ines import parse


def test_ines1_header() -> None:
    image = parse(nrom_image(b""))
    board = image.board
    assert not image.nes2
    assert (board.mapper, board.mirroring, board.battery) == (0, "H", False)
    assert (len(image.prg), len(image.chr)) == (0x4000, 0x2000)
    assert board.prg_ram == 0x2000  # iNES 1.0 cannot say: 8 KiB assumed


def test_ines1_junk_in_the_tail_drops_the_high_mapper_nibble() -> None:
    data = bytearray(nrom_image(b""))
    data[6] = 0x10  # mapper 1 low nibble
    data[7] = 0x40  # 'D' of "DiskDude!" would set the high nibble
    data[12:16] = b"Dude"
    assert parse(bytes(data)).board.mapper == 1


def test_nes2_header_fields() -> None:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4], header[5] = 2, 0  # 32 KiB PRG, CHR-RAM
    header[6] = 0x12  # mapper 1, battery
    header[7] = 0x08  # NES 2.0
    header[8] = 0x50  # submapper 5
    header[10] = 0x70  # 8 KiB PRG-NVRAM
    header[11] = 0x07  # 8 KiB CHR-RAM
    header[12] = 0x01  # PAL
    image = parse(bytes(header) + bytes(0x8000))
    board = image.board
    assert image.nes2
    assert (board.mapper, board.submapper, board.battery) == (1, 5, True)
    assert (board.prg_nvram, board.chr_ram, board.timing) == (0x2000, 0x2000, 1)


def test_trainer_and_truncation() -> None:
    data = bytearray(nrom_image(b""))
    data[6] |= 0x04
    with pytest.raises(ValueError, match="too short"):
        parse(bytes(data))
    data[16:16] = bytes(512)
    assert len(parse(bytes(data)).trainer) == 512


def test_override_wins_and_disagreements_are_logged() -> None:
    override = BoardInfo(mapper=0, mirroring="V", prg_ram=0)
    loaded = load(nrom_image(b""), override=override, use_database=False)
    assert loaded.source == "override"
    assert loaded.image.board is override
    assert any(line.startswith("mirroring: iNES header says 'H'") for line in loaded.disagreements)


@pytest.mark.skipif(not NES20DB.exists(), reason="nes20db not fetched")
def test_nes20db_is_read_in_place() -> None:
    db = load_nes20db()
    assert db is not None
    assert len(db.by_rom) > 20000
