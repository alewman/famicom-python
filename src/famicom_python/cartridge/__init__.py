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

import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path

from .bandai import Bandai74161, BandaiFCG, BandaiFCGRAM, BandaiX24C01, Datach, Karaoke, OekaKids
from .banked import Banked
from .chinese import (
    RT01,
    SL1632,
    TC112,
    Asder112,
    Dance2000,
    Daou156,
    Decathlon244,
    Education178,
    FDSConversion108,
    Fengshenbang246,
    FineStudio417,
    FutureMedia117,
    Hengge,
    Huang116,
    Jncota551,
    Latch240,
    MagicDragon107,
    MiHunChe27,
    Noraebang515,
    Sangokushi330,
    Zemina190,
)
from .connector import Cartridge
from .conversions import (
    CTC15,
    KS7010,
    KS7016B,
    KS7030,
    LH42,
    LH53,
    Board0353,
    Palthena539,
    SoccerChampion538,
    Yung08,
)
from .cony import Cony
from .database import load_mame_features, load_nes20db, lookup_mame, lookup_nes20db
from .discrete import (
    CNROM,
    CPROM,
    J87,
    NROM,
    UN1ROM,
    UNROM180,
    UNROM512,
    AOROMMulticart,
    AxROM,
    CNROMProtected,
    Fujiya170,
    GxROM,
    UxROM,
    mapper_34,
)
from .fds import FDS
from .fds_disk import is_fds, is_qd
from .homebrew import BATMAPSRR, GTROM, NSF31, Action53, DripGame, MagicFloor, SealieRET
from .ines import BoardInfo, RomImage, parse
from .irem import G101, H3001, LROG017, TAMS1
from .jaleco import JF11, JF13, JF16, JF17, SS88006
from .jycompany import JY830623C, JYCompany
from .kaiser import (
    KS7012,
    KS7013B,
    KS7021A,
    KS7032,
    KS7057,
    LH15,
    NTDEC2722,
    Board09034A,
    Board521,
    Board526,
    Contra326,
    DokiDoki103,
    Kaiser42,
    Kaiser303,
    Kaiser305,
    Kaiser306,
    Kaiser307,
    Kaiser522,
    KaiserSMB3,
    N32Mapper50,
    SMB3Bootleg106,
    TonyI43,
    Whirlwind125,
    Whirlwind309,
)
from .konami import (
    AX5705,
    FS306,
    T230,
    TF1201,
    TH2131,
    VRC1,
    VRC3,
    VRC6,
    VRC7,
    VRC24,
    CityFighter266,
    KidDracula272,
    Ninja222,
    ShuiGuan183,
)
from .mmc1 import MMC1, MMC1A, NESEvent
from .mmc2 import MMC2, MMC4
from .mmc3 import AA6023, TQROM, Event2, Kasheng, MMC3Multicart, TxSROM, mindkids_224, mmc3_for
from .mmc3_clones import (
    A9461,
    A9711,
    BATMAP399,
    BMW8544,
    F003,
    GA23C,
    ING003C,
    JC016,
    MRCM196,
    SL5020B,
    T4A54A,
    Board158B,
    Board513,
    Cocoma516,
    ContraFighter238,
    Gouder208,
    Haradius406,
    Haratyler451,
    Henggedianzi412,
    HPxx260,
    Latched165,
    Multicart334,
    Nitra250,
    Outer52,
    PRG32Override,
    ResetTxROM,
    Rewired197,
    Rex263,
    Rinco594,
    SachenShero,
    SuperGame,
    XorRAM254,
    Zhongguo512,
)
from .mmc5 import MMC5
from .multiasic import HSK007, Mindkids446, Techline351
from .multicart import (
    A65AS,
    BS5,
    GK57,
    HP898F,
    JY043,
    K1029,
    N625092,
    NTDEC81,
    SB5013,
    WS332,
    YY850437C,
    AddressLatch58,
    AddressLatch59,
    AddressLatch212,
    AddressLatch225,
    AddressLatch242,
    Asder290,
    Caltron389,
    Champion289,
    DPCMCart409,
    GoldenGame235,
    ImpactSoft471,
    Latch61,
    Latch226,
    Latch229,
    Latch299,
    Latch380,
    Latch519,
    LittleCom541,
    Maxi15,
    Maxivision493,
    NoRepeat314,
    Powerful63,
    ResetMMC1,
    ResetMulticart60,
    RetroUSB400,
    Super700,
)
from .namco import Namco108, Namco163, Namco175, Namco3425, Namco3433, Namco3446
from .nanjing import FC001, FS304, YC0309, Dongda164
from .pic16c54 import Block355
from .sachen import (
    Sachen143,
    Sachen3013,
    Sachen3014,
    Sachen8259,
    Sachen8259D,
    SachenLatch,
    SachenLS374N,
)
from .sunsoft import FME7, Sunsoft1, Sunsoft2, Sunsoft3, mapper_68
from .taito import TC0190, TC0690, X1005, X1017
from .tengen import RAMBO1, RAMBO1TLS
from .txc import ProtectedLatch
from .unlicensed import (
    NINA03,
    NINA08,
    RCM216,
    Action52,
    BitCorp38,
    Caltron41,
    Camerica,
    ColorDreams,
    DeathRace,
    Pegasus104,
    Racermate,
    RumbleStation46,
    Subor167,
)
from .vrc5 import QTa
from .waixing import FK23C, FS309, T9552, Jncota523, MixedCHR, WaixingVRC4, Xiangfeng198

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
    11: ColorDreams,
    12: SL5020B,
    13: CPROM,
    14: SL1632,
    15: K1029,
    16: BandaiFCG,
    18: SS88006,
    19: Namco163,
    21: VRC24,
    22: VRC24,
    23: VRC24,
    24: VRC6,
    25: VRC24,
    26: VRC6,
    27: MiHunChe27,
    28: Action53,
    29: SealieRET,
    30: UNROM512,
    31: NSF31,
    32: G101,
    33: TC0190,
    34: mapper_34,
    35: JYCompany,
    36: ProtectedLatch,
    37: MMC3Multicart,
    38: BitCorp38,
    40: NTDEC2722,
    41: Caltron41,
    42: Kaiser42,
    43: TonyI43,
    45: GA23C,
    46: RumbleStation46,
    47: MMC3Multicart,
    48: TC0690,
    50: N32Mapper50,
    52: Outer52,
    56: KaiserSMB3,
    57: GK57,
    58: AddressLatch58,
    59: AddressLatch59,
    60: ResetMulticart60,
    61: Latch61,
    62: Super700,
    63: Powerful63,
    64: RAMBO1,
    65: H3001,
    66: GxROM,
    67: Sunsoft3,
    68: mapper_68,
    69: FME7,
    70: Bandai74161,
    71: Camerica,
    72: JF17,
    73: VRC3,
    74: MixedCHR,
    75: VRC1,
    76: Namco3446,
    77: LROG017,
    78: JF16,
    79: NINA03,
    80: X1005,
    81: NTDEC81,
    82: X1017,
    83: Cony,
    85: VRC7,
    86: JF13,
    87: J87,
    88: Namco3433,
    89: Sunsoft2,
    90: JYCompany,
    91: JY830623C,
    92: JF17,
    93: Sunsoft2,
    94: UN1ROM,
    95: Namco3425,
    96: OekaKids,
    97: TAMS1,
    103: DokiDoki103,
    104: Pegasus104,
    105: NESEvent,
    106: SMB3Bootleg106,
    107: MagicDragon107,
    108: FDSConversion108,
    111: GTROM,
    112: Asder112,
    113: NINA03,
    114: SuperGame,
    115: Kasheng,
    116: Huang116,
    117: FutureMedia117,
    118: TxSROM,
    119: TQROM,
    120: LH15,
    121: A9711,
    122: JY043,
    123: SuperGame,
    125: Whirlwind125,
    126: ING003C,
    132: ProtectedLatch,
    133: SachenLatch,
    134: T4A54A,
    136: ProtectedLatch,
    137: Sachen8259D,
    138: Sachen8259,
    139: Sachen8259,
    140: JF11,
    141: Sachen8259,
    142: KS7032,
    143: Sachen143,
    144: DeathRace,
    145: SachenLatch,
    147: ProtectedLatch,
    148: SachenLatch,
    149: SachenLatch,
    150: SachenLS374N,
    152: Bandai74161,
    153: BandaiFCGRAM,
    154: Namco3433,
    155: MMC1A,
    156: Daou156,
    157: Datach,
    158: RAMBO1TLS,
    159: BandaiX24C01,
    162: FS304,
    163: FC001,
    164: Dongda164,
    165: Latched165,
    167: Subor167,
    168: Racermate,
    170: Fujiya170,
    172: ProtectedLatch,
    173: ProtectedLatch,
    176: FK23C,
    177: Hengge,
    178: Education178,
    180: UNROM180,
    182: SuperGame,
    183: ShuiGuan183,
    184: Sunsoft1,
    185: CNROMProtected,
    187: SuperGame,
    188: Karaoke,
    189: PRG32Override,
    190: Zemina190,
    191: MixedCHR,
    192: MixedCHR,
    193: TC112,
    194: MixedCHR,
    195: MixedCHR,
    196: MRCM196,
    197: Rewired197,
    198: Xiangfeng198,
    199: FS309,
    205: JC016,
    206: Namco108,
    207: X1005,
    208: Gouder208,
    209: JYCompany,
    210: Namco175,
    211: JYCompany,
    212: AddressLatch212,
    213: AddressLatch58,
    215: SuperGame,
    216: RCM216,
    218: MagicFloor,
    219: A9461,
    221: N625092,
    222: Ninja222,
    224: mindkids_224,
    225: AddressLatch225,
    226: Latch226,
    227: AddressLatch242,
    228: Action52,
    229: Latch229,
    232: Camerica,
    234: Maxi15,
    235: GoldenGame235,
    238: ContraFighter238,
    240: Latch240,
    241: Hengge,
    242: AddressLatch242,
    243: SachenLS374N,
    244: Decathlon244,
    245: F003,
    246: Fengshenbang246,
    249: T9552,
    250: Nitra250,
    252: WaixingVRC4,
    253: WaixingVRC4,
    254: XorRAM254,
    255: AddressLatch225,
    258: Board158B,
    260: HPxx260,
    262: SachenShero,
    263: Rex263,
    264: Cony,
    266: CityFighter266,
    268: AA6023,
    272: KidDracula272,
    284: DripGame,
    285: A65AS,
    286: BS5,
    289: Champion289,
    290: Asder290,
    292: BMW8544,
    298: TF1201,
    299: Latch299,
    301: AddressLatch242,
    302: KS7057,
    303: Kaiser303,
    304: Board09034A,
    305: Kaiser305,
    306: Kaiser306,
    307: Kaiser307,
    308: TH2131,
    309: Whirlwind309,
    312: KS7013B,
    313: ResetTxROM,
    314: NoRepeat314,
    319: HP898F,
    326: Contra326,
    328: RT01,
    330: Sangokushi330,
    332: WS332,
    334: Multicart334,
    346: KS7012,
    347: KS7030,
    351: Techline351,
    355: Block355,
    359: SB5013,
    368: Yung08,
    374: ResetMMC1,
    380: Latch380,
    389: Caltron389,
    394: HSK007,
    396: YY850437C,
    399: BATMAP399,
    400: RetroUSB400,
    406: Haradius406,
    409: DPCMCart409,
    412: Henggedianzi412,
    413: BATMAPSRR,
    415: Board0353,
    417: FineStudio417,
    418: LH42,
    422: ING003C,
    446: Mindkids446,
    451: Haratyler451,
    470: AOROMMulticart,
    471: ImpactSoft471,
    487: NINA08,
    493: Maxivision493,
    512: Zhongguo512,
    513: Board513,
    515: Noraebang515,
    516: Cocoma516,
    517: UxROM,
    518: Dance2000,
    519: Latch519,
    521: Board521,
    522: Kaiser522,
    523: Jncota523,
    525: KS7021A,
    526: Board526,
    529: T230,
    530: AX5705,
    533: Sachen3014,
    534: ING003C,
    535: LH53,
    538: SoccerChampion538,
    539: Palthena539,
    540: SB5013,
    541: LittleCom541,
    544: FS306,
    547: QTa,
    548: CTC15,
    549: KS7016B,
    551: Jncota551,
    552: X1017,
    553: Sachen3013,
    554: KS7010,
    555: Event2,
    557: LH42,
    558: YC0309,
    594: Rinco594,
}

__all__ = [
    "MAPPERS",
    "BoardInfo",
    "Cartridge",
    "Loaded",
    "RomImage",
    "fds_bios",
    "load",
    "read_rom_file",
]


@dataclass
class Loaded:
    """A cartridge ready to plug in, and how its board was identified."""

    cartridge: Banked
    image: RomImage
    source: str  # "override", "nes20db", "NES 2.0 header" or "iNES header"
    disagreements: list[str]
    mame: dict[str, str]


def read_rom_file(path: str | Path, suffixes: tuple[str, ...] = (".nes", ".fds", ".qd")) -> bytes:
    """A ``.nes``, ``.fds`` or ``.qd`` file's bytes, or the one such file in a ``.zip``."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(suffixes)]
            if len(names) != 1:
                raise ValueError(f"{path}: expected one of {suffixes} inside, found {len(names)}")
            return archive.read(names[0])
    return path.read_bytes()


#: The FDS BIOS when FAMICOM_FDS_BIOS does not name it: No-Intro's (Rev 1,
#: CRC32 5E607DCF), under NO_INTRO_DIR as scripts/count_mappers.py reads it.
FDS_BIOS_IN_NO_INTRO = (
    "Nintendo - Family Computer Disk System (FDS)/"
    "[BIOS] Family Computer Disk System (Japan) (En) (Rev 1).zip"
)


def fds_bios() -> bytes:
    """The 8 KiB disk system BIOS: the file (or zip) FAMICOM_FDS_BIOS names, else
    No-Intro's under NO_INTRO_DIR. Never shipped: it is Nintendo's."""
    named = os.environ.get("FAMICOM_FDS_BIOS")
    no_intro = Path(os.environ.get("NO_INTRO_DIR", "No-Intro"))
    path = Path(named) if named else no_intro / FDS_BIOS_IN_NO_INTRO
    if not path.exists():
        raise FileNotFoundError(f"FDS BIOS not found at {path}: set FAMICOM_FDS_BIOS")
    data = read_rom_file(path, (".bin", ".rom"))
    if len(data) != 0x2000:
        raise ValueError(f"{path}: an FDS BIOS is 8 KiB, this is {len(data)} bytes")
    return data


#: How the loader describes a disk image: the RAM adapter, iNES mapper 20
#: (historically reserved for the FDS), 32 KiB PRG-RAM, 8 KiB CHR-RAM.
FDS_BOARD = BoardInfo(mapper=20, mirroring="1", prg_ram=0x8000, chr_ram=0x2000)


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
    if is_fds(data) or is_qd(data):
        image = RomImage(b"", b"", fds_bios(), b"", data, FDS_BOARD, False)
        return Loaded(FDS(image, cpu_cycle_ticks), image, "FDS image", [], {})
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
