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

from dataclasses import dataclass

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

    path: str  # under tests/test_roms/nes-test-roms
    protocol: str  # "6000" or "screen"
    seconds: float = 60.0
    buttons: int = 0  # held on pad 1 from power-on
    passed: str = "Passed"
    failed: str = "Failed"


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


@dataclass
class RomOutcome:
    case: RomCase
    passed: bool | None  # None: no verdict before the time limit
    detail: str
    cycles: int
    instructions: int


def run_case(case: RomCase, root) -> RomOutcome:
    """Power on with ``case``'s buttons held and read its verdict."""
    system = System.from_rom(root / case.path)
    system.board.pads[0].buttons = case.buttons
    if case.protocol == "6000":
        result = run_blargg(system, max_seconds=case.seconds)
        passed = None if result.status is None else result.status == 0
        detail = f"status {result.status}: {result.text.strip()}"
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
        return all(ram[t.address & 0x7FF] & 3 in (1, 2) or ram[t.address & 0x7FF] == 0xFF for t in tests)

    while frames < limit and not done():
        system.run_frames(30)
        frames += 30
    return {t: ram[t.address & 0x7FF] for t in tests}


def run_accuracycoin_test(system: System, test: AccuracyCoinTest, max_seconds: float = 20) -> int:
    """Run one test from the menu: Right to its page, Down to its row, A."""
    from .joypad import A, DOWN, RIGHT

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
        value = ram[test.address & 0x7FF]
        if value & 3 in (1, 2) or value == 0xFF:  # (3 while it runs)
            break
        system.run_frames(30)
    return ram[test.address & 0x7FF]
