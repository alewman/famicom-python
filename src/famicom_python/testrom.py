"""Reading test ROMs' verdicts: blargg's $6000 and $F8 protocols, AccuracyCoin, the screen.

docs/validation.md "The result protocols the harness reads":

- **$6000** (blargg's 2009+ shell, ``common/text_out.s``): $80 running; $81 "press
  reset, but no sooner than 100 ms from now"; $00-$7F finished ($00 passed). The
  bytes $DE $B0 $61 at $6001-$6003 say the data are valid; text at $6004.
- **$F8** (blargg's 2005 shell): zero page $F8, 1 = passed; no "finished" flag,
  so the harness runs for a fixed time and also reads the screen.
- **AccuracyCoin**: RAM $0400-$04FF, one byte per test (milestone 4).
- **The screen**: the nametable as text, for ROMs that report only there.
  blargg's and kevtris's fonts put ASCII at tile = code.

Peeking reads the cartridge and memories directly, with no bus cycle and no
side effect.
"""

from __future__ import annotations

import subprocess
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

from .cartridge import load
from .system import System

SIGNATURE = bytes((0xDE, 0xB0, 0x61))
RUNNING, RESET_REQUEST = 0x80, 0x81


def peek(system: System, address: int) -> int:
    """The byte at a CPU address in RAM or on the cartridge, without a bus cycle."""
    if address < 0x2000:
        return system.board.ram[address & 0x7FF]
    value = system.cartridge.cpu_read(address, system.board.t)
    return 0 if value is None else value


def blargg_text(system: System) -> str:
    chars = []
    for address in range(0x6004, 0x8000):
        value = peek(system, address)
        if value == 0:
            break
        chars.append(chr(value))
    return "".join(chars)


def screen_text(system: System, nametable: int = 0) -> str:
    """Nametable ``nametable`` (0-3) as 30 lines of text: printable tiles as ASCII."""
    ppu = system.board.ppu
    base = 0x2000 + 0x400 * nametable
    rows = []
    for row in range(30):
        tiles = (ppu.bus_read(base + row * 32 + column) for column in range(32))
        rows.append("".join(chr(t) if 0x20 <= t < 0x7F else " " for t in tiles).rstrip())
    return "\n".join(rows).strip("\n")


def holy_mapperel_text(system: System) -> str:
    """Holy Mapperel's screen: its font puts ' '-'?' at their ASCII codes and
    letters at ``code & $3F`` (``src/main.s``: ``'A' & $3F``)."""
    ppu = system.board.ppu
    rows = []
    for row in range(30):
        tiles = (ppu.bus_read(0x2000 + row * 32 + column) for column in range(32))
        rows.append(
            "".join(
                chr(t) if 0x20 <= t < 0x40 else chr(t | 0x40) if 0 < t < 0x20 else " "
                for t in tiles
            ).rstrip()
        )
    return "\n".join(rows).strip("\n")


def _nametable_text(system: System, tile_char) -> str:
    ppu = system.board.ppu
    rows = []
    for row in range(30):
        tiles = (ppu.bus_read(0x2000 + row * 32 + column) for column in range(32))
        rows.append("".join(tile_char(t) for t in tiles).rstrip())
    return "\n".join(rows).strip("\n")


def _rainwarrior_char(t: int) -> str:
    # ASCII, with the hex digits of printed values at $A0-$AF.
    if 0x20 <= t < 0x7F:
        return chr(t)
    return "0123456789ABCDEF"[t & 15] if 0xA0 <= t < 0xB0 else " "


def _tall_char(t: int) -> str:
    # tepples's 8x16 font: the top half of character c is tile 2c, the bottom 2c+1.
    return chr(t >> 1) if t and not t & 1 and 0x20 <= t >> 1 < 0x7F else " "


def _mmc1atest_char(t: int) -> str:
    # Digits at $10-$1F; a byte's two digits share tiles $20+high and $30+low.
    if 0x10 <= t < 0x40:
        return "0123456789ABCDEF"[t & 15]
    return ":" if t == 0x06 else " "


def _vrctest_char(t: int) -> str:
    """AWJ's ``vrctest``: digits at 0, letters at $0A, then ``-!?.,;:()/=`` (``vrctest.inc``)."""
    return "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-!?.,;:()/= "[t] if t < 0x30 else " "


#: Screen decoders by font, for the "values" protocol.
FONTS = {
    "ascii": lambda t: chr(t) if 0x20 <= t < 0x7F else " ",
    "rainwarrior": _rainwarrior_char,
    "tall": _tall_char,
    "mmc1atest": _mmc1atest_char,
    "vrctest": _vrctest_char,
}


def font_text(system: System, font: str, sprites: bool = False) -> str:
    """Nametable 0 as text in one of the test ROMs' fonts (:data:`FONTS`); with
    ``sprites``, the sprites' tiles too, each in the cell its top-left lies in
    once the background's vertical scroll (from t) is undone (OAM Y is one
    line above the sprite's first row)."""
    text = _nametable_text(system, FONTS[font])
    if not sprites:
        return text
    grid = [list(line.ljust(32)) for line in text.splitlines()]
    grid += [[" "] * 32 for _ in range(30 - len(grid))]
    ppu = system.board.ppu
    scroll = ((ppu.t >> 5) & 31) * 8 + ((ppu.t >> 12) & 7)
    for i in range(0, 256, 4):
        y, tile, x = ppu.oam[i] + 1, ppu.oam[i + 1], ppu.oam[i + 3]
        if y < 240 and FONTS[font](tile) != " ":
            grid[(y + scroll) // 8 % 30][x // 8] = FONTS[font](tile)
    return "\n".join("".join(row).rstrip() for row in grid).strip("\n")


@dataclass
class BlarggResult:
    status: int | None  # $00-$7F once finished; None: no result (timed out)
    text: str
    cycles: int
    instructions: int

    @property
    def passed(self) -> bool:
        return self.status == 0


def run_blargg(system: System, *, max_seconds: float = 120.0) -> BlarggResult:
    """Run a $6000-protocol ROM to its result, pressing reset when it asks."""
    cps = system.machine.timing.master_hz / system.machine.timing.cpu_divider
    max_cycles = int(max_seconds * cps)
    start = system.cycles

    def signature() -> bool:
        return bytes(peek(system, 0x6001 + i) for i in range(3)) == SIGNATURE

    def finished() -> bool:
        return signature() and peek(system, 0x6000) < RUNNING

    def reset_requested() -> bool:
        return signature() and peek(system, 0x6000) == RESET_REQUEST

    while system.cycles - start < max_cycles:
        remaining = max_cycles - (system.cycles - start)
        system.run_until(
            lambda: finished() or reset_requested(), max_cycles=remaining, check_every=2000
        )
        if finished():
            return BlarggResult(
                peek(system, 0x6000), blargg_text(system), system.cycles, system.instructions
            )
        if reset_requested():
            system.run_cycles(int(0.1 * cps) + 1)  # "no sooner than 100 ms from now"
            system.reset()
            # $6000 still holds $81 until the ROM's reset code rewrites it, which
            # in apu_reset/4017_timing comes after a 420,000-cycle measurement:
            # one press per request.
            remaining = max_cycles - (system.cycles - start)
            system.run_until(
                lambda: not reset_requested(), max_cycles=max(remaining, 0), check_every=2000
            )
            continue
        break
    return BlarggResult(None, blargg_text(system), system.cycles, system.instructions)


def run_screen(
    system: System, *, passed: str, failed: str, max_seconds: float, nametable: int = 0
) -> tuple[bool | None, str]:
    """Run a screen-only ROM until its nametable shows ``passed`` or ``failed``."""
    frames = 0
    limit = int(max_seconds * 60)
    text = ""
    while frames < limit:
        system.run_frames(30)
        frames += 30
        text = screen_text(system, nametable)
        if passed in text:
            return True, text
        if failed in text:
            return False, text
    return None, text


@dataclass(frozen=True)
class RomCase:
    """One test ROM, how it reports, and how long it may take (emulated seconds)."""

    path: str  # under tests/test_roms/nes-test-roms; "x.7z/member" reads inside an archive
    protocol: str  # "6000", "screen", "holy" (Holy Mapperel), "values" or "ram"
    seconds: float = 60.0
    buttons: int = 0  # held on pad 1 from power-on
    passed: str = "Passed"
    failed: str = "Failed"
    # BoardInfo fields to run with, changed from the identified board: the
    # other submapper of a chip, or RAM a test ROM's board lacks.
    board: tuple[tuple[str, int], ...] = ()
    # "values": blocks of whole lines that must be on screen (in ``font``) after ``seconds``;
    # "ram": "ADDR=VALUE" hex bytes that work RAM must hold then.
    expect: tuple[str, ...] = ()
    font: str = "ascii"
    sprites: bool = False  # "values": read sprite tiles as text too

    @property
    def label(self) -> str:
        changes = ", ".join(f"{field} {value}" for field, value in self.board)
        return self.path + (f" ({changes})" if changes else "")


#: Milestone 1's judges (docs/handoff-brief.md): the CPU on the board.
CPU_ROMS = (
    RomCase("instr_test-v5/all_instrs.nes", "6000", 120),
    RomCase("instr_timing/instr_timing.nes", "6000", 60),
    RomCase("instr_misc/instr_misc.nes", "6000", 60),
    # B held: official and all unofficial instructions (its readme).
    RomCase("cpu_timing_test6/cpu_timing_test.nes", "screen", 30, 0x02, "PASSED", "FAILED"),
    RomCase("branch_timing_tests/1.Branch_Basics.nes", "screen", 20, 0, "PASSED", "FAIL"),
    RomCase("branch_timing_tests/2.Backward_Branch.nes", "screen", 20, 0, "PASSED", "FAIL"),
    RomCase("branch_timing_tests/3.Forward_Branch.nes", "screen", 20, 0, "PASSED", "FAIL"),
    RomCase("cpu_dummy_reads/cpu_dummy_reads.nes", "screen", 20),
    RomCase("cpu_dummy_writes/cpu_dummy_writes_ppumem.nes", "6000", 60),
    RomCase("cpu_exec_space/test_cpu_exec_space_ppuio.nes", "6000", 60),
)


def _ppu_vbl_nmi(name: str) -> RomCase:
    return RomCase(f"ppu_vbl_nmi/rom_singles/{name}.nes", "6000", 40)


def _screen_2005(path: str, seconds: float = 20) -> RomCase:
    return RomCase(path, "screen", seconds, 0, "PASSED", "FAILED")


#: Milestone 2's judges (docs/handoff-brief.md): the PPU, dot by dot. The single
#: ROMs of ppu_vbl_nmi run separately so a failure names its test; the 2005
#: PPU tests print only a result code, "$01" when passed. power_up_palette is
#: left out: it compares with blargg's own console's power-on palette.
PPU_ROMS = (
    *(
        _ppu_vbl_nmi(name)
        for name in (
            "01-vbl_basics",
            "02-vbl_set_time",
            "03-vbl_clear_time",
            "04-nmi_control",
            "05-nmi_timing",
            "06-suppression",
            "07-nmi_on_timing",
            "08-nmi_off_timing",
            "09-even_odd_frames",
            "10-even_odd_timing",
        )
    ),
    *(
        _screen_2005(f"vbl_nmi_timing/{name}.nes")
        for name in (
            "1.frame_basics",
            "2.vbl_timing",
            "3.even_odd_frames",
            "4.vbl_clear_timing",
            "5.nmi_suppression",
            "6.nmi_disable",
            "7.nmi_timing",
        )
    ),
    *(
        _screen_2005(f"sprite_hit_tests_2005.10.05/{name}.nes")
        for name in (
            "01.basics",
            "02.alignment",
            "03.corners",
            "04.flip",
            "05.left_clip",
            "06.right_edge",
            "07.screen_bottom",
            "08.double_height",
            "09.timing_basics",
            "10.timing_order",
            "11.edge_timing",
        )
    ),
    *(
        _screen_2005(f"sprite_overflow_tests/{name}.nes")
        for name in ("1.Basics", "2.Details", "3.Timing", "4.Obscure", "5.Emulator")
    ),
    *(
        RomCase(f"blargg_ppu_tests_2005.09.15b/{name}.nes", "screen", 10, 0, "$01", "$0")
        for name in ("palette_ram", "sprite_ram", "vbl_clear_time", "vram_access")
    ),
    RomCase("ppu_open_bus/ppu_open_bus.nes", "6000", 30),
    RomCase("ppu_read_buffer/test_ppu_read_buffer.nes", "6000", 60),
    RomCase("oam_read/oam_read.nes", "6000", 30),
    RomCase("oam_stress/oam_stress.nes", "6000", 60),
)


#: Milestone 3's judges (docs/handoff-brief.md): the APU, DMA and interrupts.
#: dma_2007_read and double_2007_read print only a CRC; their sources list the
#: CRCs blargg's NES gave in each CPU-PPU synchronization, and the board must
#: show the one for its own (PowerOn): PPUSim at the skew where it passes
#: ppu_vbl_nmi prints 159A7A8F and F018C287 (docs/validation.md, milestone 3).
#: read_joy3's
#: count_errors ROMs only mark where DMC DMA met a pad read, and test_buttons
#: needs a person: thorough_test is its judge.
APU_ROMS = (
    *(
        RomCase(f"apu_test/rom_singles/{name}.nes", "6000", 30)
        for name in (
            "1-len_ctr",
            "2-len_table",
            "3-irq_flag",
            "4-jitter",
            "5-len_timing",
            "6-irq_flag_timing",
            "7-dmc_basics",
            "8-dmc_rates",
        )
    ),
    *(
        RomCase(f"apu_reset/{name}.nes", "6000", 30)
        for name in (
            "4015_cleared",
            "4017_timing",
            "4017_written",
            "irq_flag_cleared",
            "len_ctrs_enabled",
            "works_immediately",
        )
    ),
    *(
        RomCase(f"blargg_apu_2005.07.30/{name}.nes", "screen", 20, 0, "$01", "$0")
        for name in (
            "01.len_ctr",
            "02.len_table",
            "03.irq_flag",
            "04.clock_jitter",
            "05.len_timing_mode0",
            "06.len_timing_mode1",
            "07.irq_flag_timing",
            "08.irq_timing",
            "09.reset_timing",
            "10.len_halt_timing",
            "11.len_reload_timing",
        )
    ),
    # nes20db gives these singles no PRG-RAM, so they report on screen only.
    *(
        RomCase(f"cpu_interrupts_v2/rom_singles/{name}.nes", "screen", 30)
        for name in (
            "1-cli_latency",
            "2-nmi_and_brk",
            "3-nmi_and_irq",
            "4-irq_and_dma",
            "5-branch_delays_irq",
        )
    ),
    # Hardware gave 159A7A8F or 5E3DF9C4 (by synchronization); fails show their CRC.
    RomCase("dmc_dma_during_read4/dma_2007_read.nes", "screen", 20, 0, "159A7A8F", "5E3DF9C4"),
    RomCase("dmc_dma_during_read4/dma_2007_write.nes", "screen", 20),
    RomCase("dmc_dma_during_read4/dma_4016_read.nes", "screen", 20),
    # Hardware gave 85CFD627, F018C287, 440EF923 or E52F41A5 (by synchronization).
    RomCase("dmc_dma_during_read4/double_2007_read.nes", "screen", 20, 0, "F018C287", "?"),
    RomCase("dmc_dma_during_read4/read_write_2007.nes", "screen", 20),
    RomCase("sprdma_and_dmc_dma/sprdma_and_dmc_dma.nes", "screen", 20),
    RomCase("sprdma_and_dmc_dma/sprdma_and_dmc_dma_512.nes", "screen", 20),
    RomCase("read_joy3/thorough_test.nes", "screen", 30),
)


def _mmc3(path: str, submapper: int) -> RomCase:
    return RomCase(path, "6000", 30, board=(("submapper", submapper),))


HOLY_MAPPEREL = "../holy-mapperel/holy-mapperel-bin-0.02.7z/testroms"


def _values(path: str, font: str, *expect: str, board: tuple[tuple[str, int], ...] = ()) -> RomCase:
    return RomCase(f"../nesdev-forum/{path}", "values", 5, board=board, expect=expect, font=font)


def _rainwarrior(mapper: int, submapper: int, *lines: str) -> RomCase:
    """rainwarrior's bus-conflict test: the values of its .txt (forum posts, pinned)."""
    return _values(f"{mapper}_test_src.zip/{mapper}_test_{submapper}.nes", "rainwarrior", *lines)


def _vrctest(build: str, asic: str, pcb: str, mapper: int, submapper: int | None) -> RomCase:
    """AWJ's ``vrctest`` for one board: it probes the wiring and features and names
    the board it found, which must be the build's own (code.s "Identification"),
    with both VRC4 IRQs on time ("YES", not "EARLY" or "LATE") or absent (VRC2)."""
    feature = "YES" if asic == "VRC4" else "NO"

    def row(label: str, value: str, start: int, end: int) -> str:
        return label + " " * (end - start - len(label) - len(value)) + value

    features = [
        row(label, feature, 3, 29)
        for label in (
            "ONE-SCREEN MIRRORING:",
            "FIX 8000,SWITCH C000:",
            "PSEUDO-SCANLINE IRQ:",
            "CYCLE COUNTER IRQ:",
        )
    ]
    ident = [row("ASIC:", asic, 7, 25), row("PCB:", pcb, 7, 25), row("MAPPER:", str(mapper), 7, 25)]
    if submapper is not None:
        ident.append(row("SUBMAPPER:", str(submapper), 7, 25))
    return RomCase(
        f"../nesdev-forum/vrctest.zip/vrctest{build}.nes",
        "values",
        5,
        expect=("\n".join(features), "\n".join(ident)),
        font="vrctest",
        sprites=True,
    )


def _bus_conflict_test(mapper: int, submapper: int, count: str, high: str) -> RomCase:
    """``{mapper}_test_{submapper}``: the bank count, and for submappers 1 and 2 the
    four "high VS low" rows (the AND of the two with conflicts, else high)."""
    label = "CHR BANKS" if mapper == 3 else "PRG BANKS"
    lines = [f"{label}: {count}"]
    if submapper:
        conflicts = submapper == 2
        for a, b in ((high, "00"), ("00", "FF"), (high, "01"), (high, "02")):
            value = int(a, 16) & int(b, 16) if conflicts else int(a, 16)
            lines.append(f"{a} VS {b}: {value:02X}")
        lines.append(f"BUS CONFLICTS: {'AND' if conflicts else 'NONE'}")
        lines.append(f"SUBMAPPER DETECTED: {submapper:02X}")
    return _rainwarrior(mapper, submapper, *lines)


#: rainwarrior's 2/3/7/34 tests against their .txt files. Submapper 0 is
#: "(unknown)" there: only the bank count is claimed (the board treats 0 as
#: 1, docs/cartridge.md). "PRG RAM" in 3_test and "CHR RAM"/"PRG RAM" in
#: 34_test always print YES on any board: the source loads the result, then
#: PPU_LATCH_AT overwrites A with the screen address before yes/no is chosen
#: (docs/validation.md, milestone 5), so the .txt's NO cannot come from these
#: builds and is not claimed.
_RAINWARRIOR = (
    *(
        _bus_conflict_test(mapper, submapper, count, high)
        for mapper, count, high in ((2, "10", "0F"), (3, "04", "03"), (7, "08", "07"))
        for submapper in (0, 1, 2)
    ),
    _rainwarrior(
        34,
        1,
        "NINA-001   PRG BANKS: 02",
        "NINA-001   CHR BANKS: 10",
        "BNROM VALID: NO",
        "NINA-001 VALID: YES",
        "SUBMAPPER DETECTED: 01",
    ),
    _rainwarrior(
        34,
        2,
        "BNROM      PRG BANKS: 08",
        "NINA-001   CHR BANKS: 01",
        "BNROM VALID: YES",
        "NINA-001 VALID: NO",
        "SUBMAPPER DETECTED: 02",
    ),
)


def _mmc1atest_table(mmc1a: bool) -> tuple[str, ...]:
    """``mmc1atest``'s README: the banks at $8000/$C000 for $8000 = 08 and 0C, by $E000.

    MMC1A's rows 10 and 18 differ (D4 passes D3 to PRG A17); on MMC1B they
    repeat rows 00 and 08.
    """
    first = ("0001020304050607", "08090A0B0C0D0E0F")
    last = ("0F1F2F3F4F5F6F7F", "8F9FAFBFCFDFEFFF")
    first_d4 = ("0001020304050607", "88898A8B8C8D8E8F") if mmc1a else first
    last_d4 = ("0717273747576777", "8F9FAFBFCFDFEFFF") if mmc1a else last

    def block(head: str, low: tuple[str, str], high: tuple[str, str]) -> str:
        rows = (f"00 {low[0]}", f"08 {low[1]}", f"10 {high[0]}", f"18 {high[1]}")
        return "\n".join((head, *rows))

    return block("80:08", first, first_d4), block("80:0C", last, last_d4)


def _holy(name: str, *board: tuple[str, int]) -> RomCase:
    return RomCase(f"{HOLY_MAPPEREL}/{name}.nes", "holy", 15, board=board)


#: Milestone 5's blargg judges (docs/handoff-brief.md): the MMC3 and its IRQ.
#: ``mmc3_test_2`` 1-4 must pass on both IRQ behaviours (Sharp 4.0, NEC 4.4),
#: 5 on Sharp and 6 on NEC. ``mmc3_test``'s 6-MMC6 expects NEC's IRQ although
#: MMC6 is Sharp's (contradiction C18): it runs on 4.4 and the claim is NEC's.
#: ``mmc3_irq_tests`` (the 2005 shell) report on screen; its 5 is NEC's
#: ("rev A") and 6 Sharp's ("rev B").
MAPPER_ROMS = (
    *(
        _mmc3(f"mmc3_test_2/rom_singles/{name}.nes", submapper)
        for submapper in (0, 4)
        for name in ("1-clocking", "2-details", "3-A12_clocking", "4-scanline_timing")
    ),
    _mmc3("mmc3_test_2/rom_singles/5-MMC3.nes", 0),
    _mmc3("mmc3_test_2/rom_singles/6-MMC3_alt.nes", 4),
    *(
        _mmc3(f"mmc3_test/{name}.nes", 0)
        for name in ("1-clocking", "2-details", "3-A12_clocking", "4-scanline_timing", "5-MMC3")
    ),
    _mmc3("mmc3_test/6-MMC6.nes", 4),
    *(
        RomCase(
            f"mmc3_irq_tests/{name}.nes",
            "screen",
            20,
            0,
            "PASSED",
            "FAILED",
            (("submapper", submapper),),
        )
        for name, submapper in (
            ("1.Clocking", 0),
            ("2.Details", 0),
            ("3.A12_clocking", 0),
            ("4.Scanline_timing", 0),
            ("5.MMC3_rev_A", 4),
            ("6.MMC3_rev_B", 0),
        )
    ),
    # Holy Mapperel 0.02: every build for mappers 0-4, 7, 9, 10, 66, 69 and 118. None of its MMC3
    # builds has PRG-RAM, so one runs with 8 KiB to reach the $A001 tests, and
    # none of its MMC1 builds is SNROM (8 KiB CHR-RAM and PRG-RAM, the $A000
    # D4 disable), so one runs as that. HM banks MMC1 WRAM as SXROM does, so
    # it cannot judge SOROM; and it expects the D4 disable on every CHR-RAM
    # board of 256 KiB or less, which MMC1.wiki limits to SNROM.
    *(
        _holy(name)
        for name in (
            "M0_P32K_C8K_V",
            "M0_P32K_CR32K_V",
            "M0_P32K_CR8K_V",
            "M1_P128K",
            "M1_P128K_C128K",
            "M1_P128K_C128K_S8K",
            "M1_P128K_C128K_W8K",
            "M1_P128K_C32K",
            "M1_P128K_C32K_S8K",
            "M1_P128K_C32K_W8K",
            "M1_P128K_CR8K",
            "M1_P512K_CR8K_S32K",
            "M1_P512K_CR8K_S8K",
            "M1_P512K_S32K",
            "M1_P512K_S8K",
            "M2_P128K_CR8K_V",
            "M2_P128K_V",
            "M3_P32K_C32K_H",
            "M4_P128K",
            "M4_P128K_CR32K",
            "M4_P128K_CR8K",
            "M4_P256K_C256K",
            "M7_P128K",
            "M7_P128K_CR8K",
            # Milestone 7's mappers with a build.
            "M9_P128K_C64K",
            "M10_P128K_C64K_S8K",
            "M10_P128K_C64K_W8K",
            "M66_P64K_C16K_V",
            "M69_P128K_C64K_S8K",
            "M69_P128K_C64K_W8K",
            "M118_P128K_C64K",
        )
    ),
    _holy("M4_P256K_C256K", ("prg_ram", 0x2000)),
    # tepples's fme7acktest: IRQs at all, then each acknowledge attempt (1 =
    # acknowledged, 2 = still asserted): every $0D write acknowledges, $0E
    # and $0F writes do not (Sunsoft_FME-7.wiki, Oliveira's 2015 hardware run).
    RomCase(
        "../nesdev-forum/fme7acktest-r1.zip/fme7acktest.nes",
        "ram",
        3,
        expect=("0019=02", "001B=01", "001C=01", "001D=01", "001E=01", "001F=02", "0020=02"),
    ),
    _vrctest("21s1", "VRC4", "352398", 21, 1),
    _vrctest("21s2", "VRC4", "352889", 21, 2),
    _vrctest("22", "VRC2", "351618", 22, None),
    _vrctest("23s1", "VRC4", "WORLD HERO", 23, 1),
    _vrctest("23s2", "VRC4", "352396", 23, 2),
    _vrctest("23s3", "VRC2", "350926,ETC.", 23, 3),
    _vrctest("25s1", "VRC4", "351406", 25, 1),
    _vrctest("25s2", "VRC4", "352400", 25, 2),
    _vrctest("25s3", "VRC2", "351948", 25, 3),
    _holy("M1_P128K", ("prg_ram", 0x2000)),
    *_RAINWARRIOR,
    *(
        _values("bntest.zip/" + name, "tall", "0123456789ABCDEF", nametables)
        for name, nametables in (
            ("bntest_h.nes", "01010101"),
            ("bntest_v.nes", "00220022"),
            ("bntest_aorom.nes", "00004444"),
        )
    ),
    _values("serom.zip/serom.nes", "ascii", "All tests passed"),
    *(
        _values(f"mmc1atest-0.01.zip/{name}", "mmc1atest", *_mmc1atest_table(mmc1a=True))
        for name in ("mmc1atest.nes", "mmc1atest-sn.nes")
    ),
    # The same ROM on MMC1B (mapper 1): rows 10 and 18 repeat 00 and 08.
    _values(
        "mmc1atest-0.01.zip/mmc1atest.nes",
        "mmc1atest",
        *_mmc1atest_table(mmc1a=False),
        board=(("mapper", 1),),
    ),
)


@dataclass
class RomOutcome:
    case: RomCase
    passed: bool | None  # None: no verdict before the time limit
    detail: str
    cycles: int
    instructions: int


def rom_bytes(root: Path, path: str) -> bytes:
    """A test ROM's bytes; a path through a ``.7z`` or ``.zip`` reads the member in place."""
    parts = Path(path).parts
    for i, part in enumerate(parts):
        archive = root.joinpath(*parts[: i + 1])
        if part.endswith((".7z", ".zip")) and archive.is_file():
            member = "/".join(parts[i + 1 :])
            if part.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    return z.read(member)
            result = subprocess.run(
                ["7z", "e", "-so", str(archive), member], capture_output=True, check=True
            )
            return result.stdout
    return (root / path).read_bytes()


def holy_mapperel_verdict(system: System) -> tuple[bool | None, str]:
    """Holy Mapperel's screen against the board it ran on (README "Displayed result").

    Passed: the mapper number, the PRG-ROM size, PRG-RAM present (with its
    size) or missing as the board has it, CHR ROM or RAM as the board has it,
    nothing marked PROBLEM, and the detailed code (WRAM, PRG, IRQ, CHR) 0000.
    None until the detailed code is on screen.
    """
    text = holy_mapperel_text(system)
    if "DETAILED TEST RESULT:" not in text:
        return None, text
    board = system.loaded.image.board if system.loaded else None
    image = system.loaded.image if system.loaded else None
    assert board is not None and image is not None
    ram = board.prg_ram + board.prg_nvram
    expected = [
        f"{board.mapper:03d} ",
        f"{len(image.prg) // 1024}K PRG ROM",
        f"{ram // 1024}K PRG RAM OK" if ram else "PRG RAM MISSING",
        "CHR ROM OK" if image.chr else "CHR RAM OK",
        "DETAILED TEST RESULT: 0000",
    ]
    passed = "PROBLEM" not in text and all(line in text for line in expected)
    return passed, text


def run_case(case: RomCase, root: Path) -> RomOutcome:
    """Power on with ``case``'s buttons held and read its verdict.

    A ``$6000`` ROM gets 8 KiB of PRG-RAM if its board has none: nes20db lists
    blargg's MMC3 tests on TxROM boards without RAM, where the text output
    goes nowhere, but the harness reads its verdict there.
    """
    data = rom_bytes(root, case.path)
    board = load(data).image.board
    if case.protocol == "6000" and not board.prg_ram + board.prg_nvram:
        board = replace(board, prg_ram=0x2000)
    board = replace(board, **dict(case.board))
    system = System.from_rom(data, override=board)
    system.board.pads[0].buttons = case.buttons
    if case.protocol == "6000":
        result = run_blargg(system, max_seconds=case.seconds)
        passed = None if result.status is None else result.status == 0
        detail = f"status {result.status}: {result.text.strip()}"
    elif case.protocol == "values":
        system.run_frames(int(case.seconds * 60))
        text = font_text(system, case.font, case.sprites)
        # Each expectation is whole lines, contiguous (a block may span several).
        lines = "\n" + "\n".join(line.strip() for line in text.splitlines()) + "\n"
        missing = [block for block in case.expect if f"\n{block}\n" not in lines]
        passed, detail = not missing, f"missing {missing}:\n{text}"
    elif case.protocol == "ram":
        system.run_frames(int(case.seconds * 60))
        ram = system.board.ram
        wrong = [e for e in case.expect if ram[int(e[:4], 16)] != int(e[5:], 16)]
        passed, detail = not wrong, f"wrong {wrong}: " + bytes(ram[:0x100]).hex(" ")
    elif case.protocol == "holy":
        passed, detail = None, ""
        for _ in range(int(case.seconds)):
            system.run_frames(60)
            passed, detail = holy_mapperel_verdict(system)
            if passed is not None:
                break
    else:
        passed, detail = run_screen(
            system, passed=case.passed, failed=case.failed, max_seconds=case.seconds
        )
    return RomOutcome(case, passed, detail, system.cycles, system.instructions)


# -- AccuracyCoin ---------------------------------------------------------

#: The page names and test names AccuracyCoin's .asm gives its "str_" bytes.
_ACCURACYCOIN_STRINGS = {
    "str_Indirect": "(Indirect)",
    "str_ZeroPage": "Zero Page",
    "str_Absolute": "Absolute",
    "str_Immediate": "#Immediate",
    "str_UnofficialInstructions": "Unofficial Instructions: ",
}


@dataclass(frozen=True)
class AccuracyCoinTest:
    page: str
    name: str
    address: int  # its result byte in $0400-$04FF
    page_number: int  # 1-based, as the menu counts pages
    row: int  # 1-based position on its page, DRAW entries counted


def accuracycoin_tests(asm_text: str) -> list[AccuracyCoinTest]:
    """The tests in the order of AccuracyCoin's ``TestPages:`` table, DRAW entries left out.

    Each ``table``/``tblf1``/``tblf2`` line names a test, its result address
    (a ``result_`` constant) and its routine; each ``Suite_`` label's first
    ``.byte`` line names the page.
    """
    import re

    constants = {
        name: int(value.replace("$", ""), 16)
        for name, value in re.findall(r"^(result_\w+)\s*=\s*\$([0-9A-Fa-f]+)", asm_text, re.M)
    }
    tests = []
    page = ""
    page_number = row = 0
    pending_page = False
    section = asm_text[re.search(r"^TestPages:", asm_text, re.M).start() :]  # type: ignore[union-attr]
    for line in section.splitlines():
        stripped = line.split(";", 1)[0].strip()
        if re.match(r"Suite_\w+:", stripped):
            pending_page, page = True, ""
            page_number += 1
            row = 0
            continue
        if pending_page and stripped.startswith(".byte"):
            parts = re.findall(r'"([^"]*)"|(str_\w+)', stripped)
            page += "".join(text or _ACCURACYCOIN_STRINGS.get(sym, "") for text, sym in parts)
            if stripped.rstrip().endswith("$FF"):
                pending_page = False
            continue
        if ".macro" in stripped:  # the table's macros follow it
            break
        match = re.match(r"(table|tblf1|tblf2)\s+(.*)", stripped)
        if not match:
            continue
        # Commas inside quotes ("$03   SLO", str_Indirect, ",X") are text.
        fields = [field.strip() for field in re.findall(r'\s*("[^"]*"|[^,]+)', match.group(2))]
        result = next(field for field in fields if field.startswith("result_"))
        row += 1
        if result == "result_DrawTest":
            continue
        name = ""
        for field in fields[: fields.index("$FF")]:
            text = field.strip('"') if field.startswith('"') else _ACCURACYCOIN_STRINGS[field]
            name += text if text.startswith(",") or not name else " " + text
        tests.append(
            AccuracyCoinTest(page, " ".join(name.split()), constants[result], page_number, row)
        )
    return tests


def _finished(value: int) -> bool:
    """A result byte that is final: pass (1) or fail (2) in the low bits, or
    $FF skipped; 3 marks a test still running."""
    return value & 3 in (1, 2) or value == 0xFF


def run_accuracycoin(
    system: System, tests: list[AccuracyCoinTest], *, max_seconds: float = 300
) -> dict[AccuracyCoinTest, int]:
    """Press Start on the page index (run all), then read every result byte.

    AccuracyCoin README "Navigating the menus": Start at the page index runs
    all tests and draws the results table. A result byte's low 2 bits are 1
    for pass and 2 for fail, the bits above the error code; $FF is skipped
    (docs/validation.md "The result protocols"). Stops when every test has a
    result or after ``max_seconds`` of emulated time.
    """
    from .joypad import START

    pad = system.board.pads[0]
    system.run_frames(60)  # the menu is up
    pad.buttons = START
    system.run_frames(4)
    pad.buttons = 0
    ram = system.board.ram
    frames, limit = 0, int(max_seconds * 60)

    def done() -> bool:
        return all(_finished(ram[t.address & 0x7FF]) for t in tests)

    while frames < limit and not done():
        system.run_frames(30)
        frames += 30
    return {t: ram[t.address & 0x7FF] for t in tests}


def run_accuracycoin_test(system: System, test: AccuracyCoinTest, max_seconds: float = 20) -> int:
    """Run one test from the menu: Right to its page, Down to its row, A."""
    from .joypad import DOWN, RIGHT, A

    pad = system.board.pads[0]

    def press(button: int) -> None:
        pad.buttons = button
        system.run_frames(3)
        pad.buttons = 0
        system.run_frames(3)

    system.run_frames(60)
    for _ in range(test.page_number - 1):
        press(RIGHT)
    for _ in range(test.row):
        press(DOWN)
    press(A)
    ram = system.board.ram
    for _ in range(int(max_seconds * 2)):
        if _finished(ram[test.address & 0x7FF]):
            break
        system.run_frames(30)
    return ram[test.address & 0x7FF]
