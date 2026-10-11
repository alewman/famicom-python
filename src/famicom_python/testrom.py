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
