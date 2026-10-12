"""The board's CPU side: memory map, open bus, ports, OAM DMA, power-on (milestone 1).

Each case names its source (docs/start-here.md "The CPU side", docs/timing.md).
Board methods called directly are CPU cycles, exactly as the core makes them.
"""

from __future__ import annotations

import dataclasses

from conftest import nrom_system

from famicom_python.joypad import RIGHT, START, A
from famicom_python.machine import FAMICOM, NES_001, PowerOn


def _strobe(board, value: int) -> None:
    """Write $4016, then two cycles: OUT0 reaches the pads at the next put."""
    board.write_byte(0x4016, value)
    board.read_byte(0x0000)
    board.read_byte(0x0000)


def test_power_on_state_after_the_reset_sequence() -> None:
    # CPU_power_up_state.wiki: S = $FD, I set (P = $24 as nestest.log shows); 7 cycles.
    system = nrom_system(b"")
    cpu = system.cpu
    assert (cpu.a, cpu.x, cpu.y, cpu.s, cpu.p, cpu.pc) == (0, 0, 0, 0xFD, 0x24, 0x8000)
    assert system.cycles == 7


def test_ram_is_mirrored_every_2_kib() -> None:
    # LDA #$5A; STA $0805; LDX $1805 (CPU_memory_map.wiki)
    system = nrom_system(bytes((0xA9, 0x5A, 0x8D, 0x05, 0x08, 0xAE, 0x05, 0x18)))
    for _ in range(3):
        system.step()
    assert system.board.ram[5] == 0x5A
    assert system.cpu.x == 0x5A


def test_undriven_reads_return_the_last_bus_value() -> None:
    # Open_bus_behavior.wiki: LDA abs of nothing returns the operand's high byte;
    # an indexed read returns the *base* high byte; write-only $4000 reads open bus.
    program = bytes((0xAD, 0x00, 0x50, 0xA2, 0x01, 0xBD, 0xFF, 0x57, 0xAC, 0x00, 0x40))
    system = nrom_system(program)
    system.step()
    assert system.cpu.a == 0x50
    system.step()
    system.step()
    assert system.cpu.a == 0x57  # $57FF + 1 = $5800, but the bus held $57
    system.step()
    assert system.cpu.y == 0x40


def test_4015_read_takes_bit_5_from_the_internal_bus_and_leaves_the_external_alone() -> None:
    # APU.wiki l.204-205: $4015 is internal to the 2A03. AccuracyCoin "Internal
    # Data Bus" 2/3: bit 5 is the internal bus's; the external bus keeps its value.
    board = nrom_system(b"").board
    board.internal_bus, board.data_bus = 0x20, 0x00
    assert board.read_byte(0x4015) & 0x20 == 0x20
    assert board.data_bus == 0x00
    board.internal_bus, board.data_bus = 0x00, 0xE0
    assert board.read_byte(0x4015) & 0x20 == 0
    assert board.data_bus == 0xE0


def test_4016_reads_the_pad_in_order_with_open_bus_above() -> None:
    # Standard_controller.wiki: A, B, Select, Start, Up, Down, Left, Right, then 1s.
    board = nrom_system(b"").board
    board.pads[0].buttons = A | START | RIGHT
    _strobe(board, 1)
    _strobe(board, 0)
    bits = []
    for _ in range(9):
        board.data_bus = 0x40
        value = board.read_byte(0x4016)
        assert value & 0xE0 == 0x40
        bits.append(value & 1)
        board.read_byte(0x0000)  # end the /OE pulse
    assert bits == [1, 0, 0, 1, 0, 0, 0, 1, 1]


def test_strobe_high_returns_a_every_read() -> None:
    board = nrom_system(b"").board
    board.pads[0].buttons = A
    _strobe(board, 1)
    assert [board.read_byte(0x4016) & 1 for _ in range(4)] == [1, 1, 1, 1]


def test_back_to_back_reads_clock_the_pad_once_on_the_nes_and_twice_on_the_rf_famicom() -> None:
    # Fiskbit's capture (DMA.wiki "Register conflicts"); AccuracyCoin "Controller Clocking".
    for machine, expected in ((NES_001, 1), (FAMICOM, 2)):
        board = nrom_system(b"", machine).board
        board.pads[0].buttons = 0
        _strobe(board, 1)
        _strobe(board, 0)
        board.read_byte(0x4016)
        board.read_byte(0x4016)
        board.read_byte(0x0000)
        ones = bin(board.pads[0].shift).count("1")
        assert ones == expected, machine.name


def _oam_dma_cycles(put_first: bool) -> tuple[int, bytes]:
    # LDA #$02; STA $4014; NOP: the NOP's opcode read is where the DMA halts.
    machine = dataclasses.replace(NES_001, power_on=PowerOn(apu_put_first=put_first))
    system = nrom_system(bytes((0xA9, 0x02, 0x8D, 0x14, 0x40, 0xEA)), machine)
    system.board.ram[0x200:0x300] = bytes(range(256))
    system.step()
    system.step()
    before = system.cycles
    system.step()  # NOP: 2 cycles plus the DMA's
    return system.cycles - before - 2, bytes(system.board.ppu.oam)


def test_oam_dma_takes_513_or_514_cycles_and_copies_the_page() -> None:
    # DMA.wiki "OAM DMA": a halt, an alignment cycle if needed, 256 get/put pairs.
    stolen = set()
    for put_first in (False, True):
        cycles, oam = _oam_dma_cycles(put_first)
        stolen.add(cycles)
        # Attribute bytes (every 4th from 2) have no bits 4-2 (PPU_OAM.wiki).
        assert oam == bytes(b & 0xE3 if i & 3 == 2 else b for i, b in enumerate(range(256)))
    assert stolen == {513, 514}


def test_frame_irq_arrives_about_29830_cycles_after_4017() -> None:
    # LDA #$00; STA $4017; CLI; loop: JMP loop. IRQ handler at $8200.
    system = nrom_system(bytes((0xA9, 0x00, 0x8D, 0x17, 0x40, 0x58, 0x4C, 0x06, 0x80)))
    write = system.cycles + 6  # the STA's fourth cycle
    while system.cpu.pc != 0x8200 and system.cycles - write < 40000:
        system.step()
    # The flag sets 3 or 4 cycles (the $4017 delay) + 29828 after the write; the
    # JMP in progress finishes (up to 3 cycles), then the 7-cycle entry.
    assert 3 + 29828 + 7 <= system.cycles - write <= 4 + 29828 + 3 + 7
    assert system.board.read_byte(0x4015) & 0x40
    # The read's clear lands at the next put -> get transition, a cycle or two
    # on (AccuracyCoin "Frame Counter IRQ" 6 and 7).
    system.board.read_byte(0x0000)
    system.board.read_byte(0x0000)
    assert not system.board.read_byte(0x4015) & 0x40
