"""The APU and DMC DMA (milestone 3): channels, mixer, and the DMA cycle costs.

Each case names its source (docs/timing.md "The APU" and "DMA"). The test ROMs
judge the frame counter, length counters and DMA timing on the whole board
(``tests/test_apu_test_roms.py``); these pin the channel arithmetic the ROMs
cannot hear, and the DMA cycle counts directly.
"""

from __future__ import annotations

from itertools import pairwise

from conftest import nrom_system

from famicom_python.apu import APU, NOISE_PERIODS


def _apu() -> APU:
    apu = APU()
    apu.power()
    return apu


def _transitions(apu: APU, channel, cycles: int) -> list[int]:
    """CPU cycles at which ``channel.output`` changed."""
    times, last = [], channel.output
    for cycle in range(cycles):
        apu.clock()
        apu._mix()  # refreshes the pulse and noise outputs
        if channel.output != last:
            times.append(cycle)
            last = channel.output
    return times


def test_pulse_period_is_16_cpu_cycles_per_timer_step_plus_one() -> None:
    # APU_Pulse.wiki: f = f_CPU / (16 (t + 1)); duty 2 is high half the time.
    apu = _apu()
    apu.write(0x4015, 0x01)
    apu.write(0x4000, 0xBF)  # duty 2, halt, constant volume 15
    apu.write(0x4002, 0x20)
    apu.write(0x4003, 0x08)  # t = $020, length loaded
    edges = _transitions(apu, apu.pulse1, 2000)
    periods = {b - a for a, b in zip(edges[2::2], edges[4::2], strict=False)}
    assert periods == {16 * (0x20 + 1)}


def test_pulse_mutes_below_period_8_and_above_target_7ff() -> None:
    # APU_Sweep.wiki "Muting": regardless of the enable flag.
    apu = _apu()
    apu.write(0x4015, 0x01)
    apu.write(0x4000, 0xBF)
    apu.write(0x4002, 0x07)
    apu.write(0x4003, 0x08)
    assert not _transitions(apu, apu.pulse1, 400)
    apu.write(0x4002, 0xFF)
    apu.write(0x4003, 0x0C)  # t = $4FF: shift 0 makes the target 2t > $7FF
    assert not _transitions(apu, apu.pulse1, 400)
    apu.write(0x4001, 0x01)  # shift 1: target 1.5t = $77E, unmuted
    assert _transitions(apu, apu.pulse1, 2 * 16 * 0x500)  # edges 8 (t + 1) cycles apart


def test_sweep_negate_is_ones_complement_on_pulse_1_only() -> None:
    # APU_Sweep.wiki: pulse 1 adds -c - 1, pulse 2 adds -c.
    apu = _apu()
    for base in (0x4000, 0x4004):
        apu.write(base + 1, 0x09)  # negate, shift 1
        apu.write(base + 2, 0x00)
        apu.write(base + 3, 0x01)  # t = $100
    assert apu.pulse1.target == 0x100 - 0x80 - 1
    assert apu.pulse2.target == 0x100 - 0x80


def test_envelope_decays_once_per_divider_period_and_loops() -> None:
    # APU_Envelope.wiki: start -> 15, then down one per (V + 1) quarter frames.
    apu = _apu()
    envelope = apu.pulse1.envelope
    apu.write(0x4000, 0x21)  # loop, envelope period 1
    apu.write(0x4003, 0x00)  # start flag
    levels = []
    for _ in range(34):
        envelope.quarter()
        levels.append(envelope.volume)
    assert levels[:5] == [15, 15, 14, 14, 13]
    assert levels[31:34] == [0, 15, 15]  # looped


def test_triangle_steps_every_t_plus_1_cpu_cycles_while_both_counters_run() -> None:
    # APU_Triangle.wiki: 32 steps per period of 32 (t + 1) CPU cycles; it stops
    # (holding its level) when the linear counter reaches 0.
    apu = _apu()
    apu.write(0x4015, 0x04)
    apu.write(0x4008, 0x81)  # control, linear reload 1
    apu.write(0x400A, 0x09)
    apu.write(0x400B, 0x08)
    apu.clock()  # the length load settles
    triangle = apu.triangle
    triangle.quarter()  # reload the linear counter
    steps, last = [], triangle.step
    for cycle in range(200):
        apu.clock()
        if triangle.step != last:
            steps.append(cycle)
            last = triangle.step
    assert {b - a for a, b in pairwise(steps)} == {10}
    apu.write(0x4008, 0x01)  # control off: the next quarter frames count it down
    triangle.quarter()
    triangle.quarter()
    assert triangle.linear == 0
    assert not any(triangle.clock_timer() for _ in range(200))


def test_noise_lfsr_sequence_lengths() -> None:
    # APU_Noise.wiki: 32767 steps in mode 0; 93 or 31 in mode 1.
    apu = _apu()
    noise = apu.noise
    noise.period = 0
    start = noise.shift
    period = next(n for n in range(1, 40000) if noise.clock_timer() and noise.shift == start)
    assert period == 32767
    noise.mode_bit = 6
    seen = []
    for _ in range(400):
        noise.clock_timer()
        seen.append(noise.shift)
    period = seen[100:].index(seen[100], 1)
    assert period in (93, 31)
    assert NOISE_PERIODS[0] == 4


def test_mixer_is_blargg_formula() -> None:
    # APU_Mixer.wiki: pulse_out = 95.88 / (8128 / (p1 + p2) + 100), and tnd_out.
    apu = _apu()
    apu.write(0x4015, 0x03)
    for base in (0x4000, 0x4004):
        apu.write(base, 0xBF)
        apu.write(base + 2, 0x40)
        apu.write(base + 3, 0x08)
    apu.clock()
    apu.pulse1.step = apu.pulse2.step = 4  # inside duty 2's high half
    apu.triangle.output = 0
    assert abs(apu._mix() - 95.88 / (8128 / 30 + 100)) < 1e-12
    apu.write(0x4015, 0x00)
    apu.clock()
    apu.dmc.output = 64
    apu.noise.output = 0
    assert abs(apu._mix() - 159.79 / (1 / (64 / 22638) + 100)) < 1e-12


def test_4017_write_takes_effect_3_cycles_after_a_put_and_4_after_a_get() -> None:
    # APU_Frame_Counter.wiki: 3 if written during an APU cycle, 4 if between.
    # "During" is a write on a put: cpu_interrupts_v2 4-irq_and_dma's "8 +526"
    # (hardware) needs this reading (docs/validation.md, milestone 3).
    for put, expected in ((True, 3), (False, 4)):
        apu = _apu()
        while apu.put != put:
            apu.clock()
        apu.write(0x4017, 0x80)
        cycles = 0
        while apu.pending_frame_write is not None:
            apu.clock()
            cycles += 1
        assert cycles == expected, put


def _dmc_board():
    system = nrom_system(b"")
    board = system.board
    board.write_byte(0x4010, 0x0F)  # fastest rate, no IRQ, no loop
    board.write_byte(0x4012, 0x00)  # $C000
    board.write_byte(0x4013, 0x01)  # 17 bytes
    return board


def _stolen(board, reads: int) -> list[int]:
    """Cycles each of ``reads`` CPU reads took beyond its own."""
    stolen = []
    for _ in range(reads):
        before = board.cycles
        board.read_byte(0x0000)
        stolen.append(board.cycles - before - 1)
    return stolen


def test_dmc_load_dma_takes_3_cycles_on_the_4th_or_3rd_cycle_after_4015() -> None:
    # DMA.wiki "DMC DMA": halt on the get of the 2nd APU cycle after the write;
    # halt, dummy, get.
    for write_on_put in (False, True):
        board = _dmc_board()
        while board.apu.put == write_on_put:  # the next cycle is the other kind
            board.read_byte(0x0000)
        board.write_byte(0x4015, 0x10)
        stolen = _stolen(board, 6)
        assert sum(stolen) == 3
        # The 3rd CPU cycle after a write on a put, the 4th after one on a get.
        assert stolen.index(3) == (2 if write_on_put else 3)
        assert board.apu.dmc.buffer is not None


def test_dmc_reload_dma_takes_4_cycles_and_a_write_delay_makes_it_3() -> None:
    # DMA.wiki "Reload DMA" examples: halt (put), dummy, alignment, get: 4; a
    # halt deferred by one write cycle lands on a get: 3.
    board = _dmc_board()
    board.write_byte(0x4015, 0x10)
    _stolen(board, 6)  # the load
    reloads = [n for n in _stolen(board, 2000) if n]
    assert reloads and set(reloads) == {4}
    board = _dmc_board()
    board.write_byte(0x4015, 0x10)
    _stolen(board, 6)
    for _ in range(2000):
        if board.apu.dmc_request:
            break
        board.read_byte(0x0000)
    board.write_byte(0x0000, 0)  # the halt attempt fails on a write
    assert _stolen(board, 1) == [3]


def test_dmc_irq_is_set_when_the_last_byte_is_fetched() -> None:
    # APU_DMC.wiki: the IRQ fires on the last fetch, not when it has played.
    board = _dmc_board()
    board.write_byte(0x4010, 0x8F)  # IRQ on
    board.write_byte(0x4013, 0x00)  # 1 byte
    board.write_byte(0x4015, 0x10)
    _stolen(board, 6)
    assert board.apu.dmc.irq and board.apu.irq
    assert board.read_byte(0x4015) & 0x80  # $4015 shows it ...
    assert board.apu.dmc.irq  # ... and reading does not clear it (7-dmc_basics #10)


def test_dmc_dma_during_oam_dma_costs_2_cycles() -> None:
    # DMA.wiki "DMC DMA during OAM DMA": its get, then an OAM realignment.
    def oam_cycles(with_dmc: bool) -> int:
        board = _dmc_board()
        if with_dmc:
            board.write_byte(0x4015, 0x10)
        board.write_byte(0x4014, 0x02)
        before = board.cycles
        board.read_byte(0x0000)
        return board.cycles - before

    plain, with_dmc = oam_cycles(False), oam_cycles(True)
    assert plain in (514, 515)
    assert with_dmc - plain in (1, 2, 3)  # 2 mid-DMA; at its edges 1 or 3
