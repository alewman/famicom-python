"""iNES 1.0 and NES 2.0 files: the header and the ROM it describes.

The header says what the dumper believed about the cartridge; nes20db usually
knows better (``database.py``), and the loader in ``__init__.py`` applies the
override order of docs/cartridge.md "Identifying the board". Layouts from
INES.wiki and NES_2.0.wiki (specification tier).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

MAGIC = b"NES\x1a"

# Nametable arrangement, in nes20db's letters (docs/cartridge.md "File formats"):
# "H" = horizontal mirroring (vertical arrangement, CIRAM A10 = PPU A11, header
# bit 0 clear), "V" = vertical mirroring (CIRAM A10 = PPU A10), "4" = four-screen
# RAM on the cartridge, "1" = the mapper decides.
MIRRORINGS = ("H", "V", "4", "1")


@dataclass(frozen=True)
class BoardInfo:
    """What a cartridge's circuit is: everything a mapper needs besides the ROM."""

    mapper: int
    submapper: int = 0
    mirroring: str = "H"
    battery: bool = False
    prg_ram: int = 0  # bytes of volatile PRG-RAM
    prg_nvram: int = 0  # bytes of battery-backed PRG-RAM (or EEPROM)
    chr_ram: int = 0
    chr_nvram: int = 0
    timing: int = 0  # 0 NTSC, 1 PAL, 2 multi-region, 3 Dendy (NES_2.0.wiki byte 12)
    console: int = 0  # 0 NES/Famicom, 1 Vs., 2 PlayChoice-10, 3 extended


@dataclass(frozen=True)
class RomImage:
    """A cartridge file, split: header, trainer, PRG, CHR and anything after."""

    header: bytes
    trainer: bytes
    prg: bytes
    chr: bytes
    misc: bytes
    board: BoardInfo
    nes2: bool  # the header is NES 2.0

    def with_board(self, board: BoardInfo) -> RomImage:
        return replace(self, board=board)


def _nes2_rom_size(low: int, high_nibble: int, unit: int) -> int:
    if high_nibble == 0x0F:  # exponent-multiplier form: 2^E * (MM * 2 + 1)
        return (1 << (low >> 2)) * ((low & 3) * 2 + 1)
    return ((high_nibble << 8) | low) * unit


def _shift_size(count: int) -> int:
    return 0 if count == 0 else 64 << count


def parse(data: bytes) -> RomImage:
    """Split an iNES or NES 2.0 file into its parts, believing its header."""
    if len(data) < 16 or data[:4] != MAGIC:
        raise ValueError("not an iNES file (no NES<EOF> magic)")
    h = data[:16]
    nes2 = (h[7] & 0x0C) == 0x08
    flags6 = h[6]
    mirroring = "4" if flags6 & 0x08 else ("V" if flags6 & 0x01 else "H")
    battery = bool(flags6 & 0x02)
    mapper = (flags6 >> 4) | (h[7] & 0xF0)
    if nes2:
        mapper |= (h[8] & 0x0F) << 8
        board = BoardInfo(
            mapper=mapper,
            submapper=h[8] >> 4,
            mirroring=mirroring,
            battery=battery,
            prg_ram=_shift_size(h[10] & 0x0F),
            prg_nvram=_shift_size(h[10] >> 4),
            chr_ram=_shift_size(h[11] & 0x0F),
            chr_nvram=_shift_size(h[11] >> 4),
            timing=h[12] & 0x03,
            console=h[7] & 0x03,
        )
        prg_size = _nes2_rom_size(h[4], h[9] & 0x0F, 0x4000)
        chr_size = _nes2_rom_size(h[5], h[9] >> 4, 0x2000)
    else:
        if any(h[12:16]):
            # "DiskDude!" and other junk in bytes 7-15 (INES.wiki): only the low
            # mapper nibble can be trusted.
            mapper &= 0x0F
        prg_size, chr_size = h[4] * 0x4000, h[5] * 0x2000
        # iNES 1.0 cannot say: 8 KiB of PRG-RAM at $6000, battery-backed if the
        # flag says so (INES.wiki byte 8, "0 infers 8 KB for compatibility"), and
        # 8 KiB of CHR-RAM when there is no CHR-ROM.
        board = BoardInfo(
            mapper=mapper,
            mirroring=mirroring,
            battery=battery,
            prg_ram=0 if battery else 0x2000,
            prg_nvram=0x2000 if battery else 0,
            chr_ram=0 if chr_size else 0x2000,
            timing=1 if h[9] & 0x01 else 0,
            console=h[7] & 0x03,
        )
    offset = 16
    trainer = data[offset : offset + 512] if flags6 & 0x04 else b""
    offset += len(trainer)
    prg = data[offset : offset + prg_size]
    offset += prg_size
    chr_ = data[offset : offset + chr_size]
    offset += chr_size
    if len(prg) != prg_size or len(chr_) != chr_size:
        raise ValueError(
            f"file too short: header says {prg_size} PRG + {chr_size} CHR bytes, "
            f"file has {len(data) - 16 - len(trainer)}"
        )
    return RomImage(h, trainer, prg, chr_, data[offset:], board, nes2)
