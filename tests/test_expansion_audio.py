"""Milestone 8's expansion sound: the chips' channels on synthetic images, and the path.

The mix levels are judged by rainwarrior's ``db_*`` ROMs
(``scripts/expansion_levels.py``); these pin each channel's sequence as the
wiki describes it, and that the board mixes a chip's level only on a
console that routes the cartridge's sound (the Famicom's pins 45/46).
"""

from __future__ import annotations

from conftest import nrom_image
from test_mappers import TICKS, build

from famicom_python.cartridge import load
from famicom_python.cartridge.connector import APU_SQUARE, Unplugged, expansion_gain
from famicom_python.cartridge.konami import VRC6, VRC6_DB
from famicom_python.machine import FAMICOM, NES_001
from famicom_python.system import System


def levels(cart, cycles: int) -> list[int]:
    """The chip's summed DAC value after each of ``cycles`` CPU cycles."""
    out = []
    for i in range(cycles):
        cart.m2(i * TICKS)
        out.append(round(cart.audio_out.expansion / cart.gain))
    return out


def test_vrc6_pulse_sequence_and_duty() -> None:
    cart = build(24)
    assert isinstance(cart, VRC6)
    cart.cpu_write(0x9000, 0x3F, 0)  # duty 3 (4/16), volume 15
    cart.cpu_write(0x9001, 0x00, 0)  # period 0: a step every cycle
    cart.cpu_write(0x9002, 0x80, 0)
    # Steps count down from 15: high on 3, 2, 1, 0 of each 16.
    assert levels(cart, 16) == [0] * 11 + [15] * 4 + [0]


def test_vrc6_mode_bit_ignores_duty_and_disable_restarts_the_step() -> None:
    cart = build(24)
    cart.cpu_write(0xA000, 0x85, 0)  # mode: always volume 5
    cart.cpu_write(0xA002, 0x80, 0)
    assert set(levels(cart, 20)) == {5}
    cart.cpu_write(0xA002, 0x00, 0)
    assert cart.pulses[1].step == 15 and levels(cart, 3) == [0, 0, 0]


def test_vrc6_saw_adds_on_even_steps_and_clears_on_the_fourteenth() -> None:
    cart = build(24)
    cart.cpu_write(0xB000, 0x08, 0)  # rate 8: the wiki's example
    cart.cpu_write(0xB002, 0x80, 0)
    assert levels(cart, 16) == [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 0, 0, 1]


def test_vrc6_frequency_control_halts_and_shifts() -> None:
    cart = build(24)
    cart.cpu_write(0x9000, 0x8F, 0)
    cart.cpu_write(0x9001, 0x10, 0)
    cart.cpu_write(0x9002, 0x80, 0)
    cart.cpu_write(0x9003, 0x01, 0)  # halt
    before = cart.pulses[0].counter
    levels(cart, 40)
    assert cart.pulses[0].counter == before
    cart.cpu_write(0x9003, 0x02, 0)  # 16x: the period $010 becomes 1
    levels(cart, 1)
    assert cart.pulses[0].counter <= 1


def test_vrc6b_swaps_a0_and_a1() -> None:
    cart = build(26)
    cart.cpu_write(0x9002, 0x34, 0)  # VRC6b: $9002 is the period's low byte
    cart.cpu_write(0x9001, 0x81, 0)  # ... and $9001 the high one with enable
    assert cart.pulses[0].period == 0x134 and cart.pulses[0].enabled


def test_vrc6_banks_prg_and_chr() -> None:
    cart = build(24, prg_kib=256, chr_kib=256)
    cart.cpu_write(0x8000, 0x03, 0)  # 16 KiB bank 3 at $8000
    cart.cpu_write(0xC000, 0x09, 0)  # 8 KiB bank 9 at $C000
    assert cart.cpu_read(0x8000, 0) == 48 and cart.cpu_read(0xA000, 0) == 56
    assert cart.cpu_read(0xC000, 0) == 72 and cart.cpu_read(0xE000, 0) == 248
    cart.cpu_write(0xE003, 0x77, 0)  # R7 at $1C00 in mode 0
    assert cart.ppu_read(0x1C00, 0) == 0x77
    cart.cpu_write(0xB003, 0x21, 0)  # mode 1, PPU A10 through: R3 as 2 KiB at $1800
    cart.cpu_write(0xD003, 0x45, 0)
    assert cart.ppu_read(0x1800, 0) == 0x44 and cart.ppu_read(0x1C00, 0) == 0x45


def test_the_level_is_the_measured_db_against_an_apu_square() -> None:
    gain = expansion_gain(VRC6_DB, 15)
    assert abs(15 * gain / APU_SQUARE - 10 ** (VRC6_DB / 20)) < 1e-12


def vrc6_rom() -> bytes:
    """A VRC6 image whose program holds a full-volume pulse (mode bit) on."""
    program = bytes(
        (0xA9, 0x8F, 0x8D, 0x00, 0x90,  # LDA #$8F; STA $9000
         0xA9, 0x80, 0x8D, 0x02, 0x90,  # LDA #$80; STA $9002
         0x4C, 0x0A, 0x80)  # JMP *
    )  # fmt: skip
    data = bytearray(nrom_image(program))
    data[6] = (24 & 0x0F) << 4
    data[7] = 24 & 0xF0
    return bytes(data)


def test_the_famicom_mixes_the_cartridge_and_the_nes_does_not() -> None:
    rom = vrc6_rom()
    famicom = System(load(rom, use_database=False).cartridge, FAMICOM)
    famicom.run_frames(2)
    assert famicom.board.apu.expansion > 0.1
    nes = System(load(rom, use_database=False).cartridge, NES_001)
    nes.run_frames(2)
    assert nes.board.apu.expansion == 0.0
    assert isinstance(nes.cartridge.audio_out, Unplugged)


def test_mmc5_pulse_has_no_sweep_mute_and_counts_its_length_at_the_fixed_rate() -> None:
    cart = build(5)
    sound = cart.sound
    cart.cpu_write(0x5015, 0x01, 0)
    cart.cpu_write(0x5000, 0x9F, 0)  # 50 %, constant volume 15, halt clear
    cart.cpu_write(0x5002, 0x02, 0)  # period 2: under 8, still heard
    cart.cpu_write(0x5003, 0x18, 0)  # length index 3: 2
    seen = set()
    for i in range(40):
        cart.m2(i * TICKS)
        seen.add(sound.pulses[0].output())
    assert seen == {0, 15}
    assert cart.cpu_read(0x5015, 0) == 1
    for i in range(2 * 7424):  # two length clocks
        cart.m2(i * TICKS)
    assert cart.cpu_read(0x5015, 0) == 0


def test_mmc5_pcm_zero_trips_the_irq_and_read_mode_feeds_the_dac() -> None:
    cart = build(5)
    cart.cpu_write(0x5010, 0x80, 0)  # IRQ enabled, write mode
    cart.cpu_write(0x5011, 0x40, 0)
    assert cart.sound.pcm == 0x40 and not cart.irq
    cart.cpu_write(0x5011, 0x00, 0)  # zero: no change, IRQ
    assert cart.sound.pcm == 0x40 and cart.irq
    assert cart.cpu_read(0x5010, 0) == 0x80 and not cart.irq  # read acknowledges
    cart.cpu_write(0x5010, 0x01, 0)  # read mode
    cart.cpu_write(0x5011, 0x22, 0)  # ignored in read mode
    assert cart.sound.pcm == 0x40
    value = cart.cpu_read(0x8000, 0)
    assert cart.sound.pcm == (value or 0x40)


def n163_with_wave(submapper: int = 5):
    cart = build(19, submapper)
    cart.cpu_write(0xF800, 0x80, 0)  # chip RAM address 0, auto-increment
    for value in (0x00, 0xFF):  # samples 0, 0, F, F
        cart.cpu_write(0x4800, value, 0)
    return cart


def poke(cart, address: int, value: int) -> None:
    cart.cpu_write(0xF800, address, 0)
    cart.cpu_write(0x4800, value, 0)


def test_n163_channels_take_turns_every_15_cycles() -> None:
    cart = n163_with_wave()
    poke(cart, 0x7C, 0xFC)  # channel 8: 4 samples, frequency 0
    poke(cart, 0x7E, 0x00)
    poke(cart, 0x7F, 0x1F)  # two channels (8, 7), channel 8 at volume 15
    poke(cart, 0x77, 0x0F)  # channel 7 at volume 15, phase 0 too
    poke(cart, 0x74, 0xFC)
    poke(cart, 0x76, 0x02)  # its wave starts at sample 2: F
    out = []
    for i in range(60):
        cart.m2(i * TICKS)
        out.append(round(cart.audio_out.expansion / cart.gain))
    # Channel 8 (sample 0: -8 x 15) and channel 7 (sample F: +7 x 15) in turn.
    assert out[14] == -120 and out[29] == 105 and out[44] == -120 and out[59] == 105
    assert out[15:29] == [105] * 14 or out[15:29] == [-120] * 14


def test_n163_phase_steps_through_the_wave() -> None:
    cart = n163_with_wave()
    poke(cart, 0x7C, 0xFD)  # 4 samples, frequency $10000: one sample per update
    poke(cart, 0x7F, 0x0F)  # one channel
    out = []
    for i in range(15 * 4):
        cart.m2(i * TICKS)
        if i % 15 == 14:
            out.append(round(cart.audio_out.expansion / cart.gain))
    assert out == [-120, 105, 105, -120]  # samples 1, 2, 3, 0


def test_n163_submapper_sets_the_level_or_silence() -> None:
    assert build(19, 3).gain < build(19, 4).gain < build(19, 5).gain
    assert not build(19, 2).expansion_audio and build(19, 0).expansion_audio
