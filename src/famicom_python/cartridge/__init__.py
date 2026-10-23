"""Cartridges: the connector protocol, the file loader and the mappers.

Nothing here imports the board: a mapper knows the console only through
:mod:`.connector` (docs/cartridge.md "Where mappers live, and why";
``tests/test_cartridge_boundary.py``).

:func:`load` identifies the board in the override order of docs/cartridge.md:
a caller's override, then nes20db by the whole ROM, then by PRG and CHR, then
the file's NES 2.0 header, then the iNES 1.0 header. Every field on which a
source below the winner disagrees is logged in :attr:`Loaded.disagreements`.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path

from .bandai import BandaiFCG, BandaiX24C01, Datach
from .banked import Banked
from .connector import Cartridge
from .database import load_mame_features, load_nes20db, lookup_mame, lookup_nes20db
from .discrete import CNROM, J87, NROM, AxROM, CNROMProtected, GxROM, UxROM, mapper_34
from .ines import BoardInfo, RomImage, parse
from .irem import G101
from .jaleco import SS88006
from .konami import VRC1, VRC24
from .mmc1 import MMC1, MMC1A
from .mmc2 import MMC2, MMC4
from .mmc3 import AA6023, TxSROM, mmc3_for
from .mmc5 import MMC5
from .namco import Namco108, Namco163, Namco175
from .sunsoft import FME7
from .taito import TC0190

#: Each implemented iNES mapper's board, built from the image and the CPU cycle
#: length in master ticks (a class, or a function choosing one by submapper).
MAPPERS: dict[int, Callable[[RomImage, int], Banked]] = {
    0: NROM,
    1: MMC1,
    2: UxROM,
    3: CNROM,
    4: mmc3_for,
    5: MMC5,
    7: AxROM,
    9: MMC2,
    10: MMC4,
    16: BandaiFCG,
    18: SS88006,
    19: Namco163,
    21: VRC24,
    22: VRC24,
    23: VRC24,
    25: VRC24,
    32: G101,
    33: TC0190,
    34: mapper_34,
    66: GxROM,
    69: FME7,
    75: VRC1,
    87: J87,
    118: TxSROM,
    155: MMC1A,
    157: Datach,
    159: BandaiX24C01,
    185: CNROMProtected,
    206: Namco108,
    210: Namco175,
    268: AA6023,
}

__all__ = ["MAPPERS", "BoardInfo", "Cartridge", "Loaded", "RomImage", "load", "read_rom_file"]


@dataclass
class Loaded:
    """A cartridge ready to plug in, and how its board was identified."""

    cartridge: Banked
    image: RomImage
    source: str  # "override", "nes20db", "NES 2.0 header" or "iNES header"
    disagreements: list[str]
    mame: dict[str, str]


def read_rom_file(path: str | Path) -> bytes:
    """A ``.nes`` file's bytes, or the one ``.nes`` inside a ``.zip``, read in place."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".nes")]
            if len(names) != 1:
                raise ValueError(f"{path}: expected one .nes inside, found {len(names)}")
            return archive.read(names[0])
    return path.read_bytes()


def _differences(winner: BoardInfo, other: BoardInfo, label: str) -> list[str]:
    return [
        f"{field.name}: {label} says {getattr(other, field.name)!r}, "
        f"using {getattr(winner, field.name)!r}"
        for field in fields(BoardInfo)
        if getattr(winner, field.name) != getattr(other, field.name)
    ]


def load(
    rom: str | Path | bytes,
    *,
    cpu_cycle_ticks: int = 12,
    override: BoardInfo | None = None,
    use_database: bool = True,
) -> Loaded:
    """Identify the cartridge in ``rom`` (a path or a file's bytes) and build its mapper."""
    data = rom if isinstance(rom, bytes) else read_rom_file(rom)
    image = parse(data)
    header = image.board
    header_label = "NES 2.0 header" if image.nes2 else "iNES header"
    database = lookup_nes20db(image, load_nes20db()) if use_database else None
    disagreements: list[str] = []
    if override is not None:
        board, source = override, "override"
    elif database is not None:
        board, source = database, "nes20db"
    else:
        board, source = header, header_label
    if database is not None and database is not board:
        disagreements += _differences(board, database, "nes20db")
    if header is not board:
        disagreements += _differences(board, header, header_label)
    image = image.with_board(board)
    mapper = MAPPERS.get(board.mapper)
    if mapper is None:
        raise NotImplementedError(f"mapper {board.mapper} is not implemented yet")
    mame = lookup_mame(image, load_mame_features()) if use_database else {}
    return Loaded(mapper(image, cpu_cycle_ticks), image, source, disagreements, mame)
