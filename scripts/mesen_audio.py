#!/usr/bin/env python3
"""Compare the board's sound with Mesen2's (a detector, docs/validation.md).

Mesen2 records its mixed output with ``WaveRecord`` (its WAV recorder, after
its own mixer and resampler); the board's APU produces its mixer output at the
same sample rate, before the analogue stage. The two are not expected to be
equal sample for sample: Mesen2 mixes with integer volume tables, band-limited
synthesis and its own output level and DC filtering. So both streams pass the
same first-order 90 Hz high-pass (the NES-001's first corner), are aligned by
cross-correlation, and each window gets one fitted gain; the report is how
much of the board's signal the difference leaves (``residual``, dB below the
signal) window by window, with each stream's level so a silence-or-not
divergence shows.

    python scripts/mesen_audio.py ROM --frames 600 [--window 0.1]

Needs the hand-built MesenCore.so of scripts/mesen_run.py; nothing it writes is
committed.
"""

from __future__ import annotations

import argparse
import ctypes
import math
import sys
import time
import wave
from array import array
from pathlib import Path

from mesen_run import CONSOLE_MODE, MAXIMUM_SPEED, ROOT, configure_for_comparison, load_library

from famicom_python.machine import MACHINES, Machine
from famicom_python.system import System

HOME = ROOT / "tests" / "mame_traces" / "mesen-home"

# NesConfig.ChannelVolumes (uint32[11]); measured with offsetof against Mesen2
# 2.1.1's Core/Shared/SettingTypes.h, as mesen_run.py's other offsets were. Its
# default is all 0 (the UI sets 100), so headless Mesen2 records silence.
NES_CONFIG_CHANNEL_VOLUMES = 14072

STOP_LUA = """
local target, frame = %d, 0
emu.addEventCallback(function()
  frame = frame + 1
  if frame == target then emu.log("DONE") end
end, emu.eventType.endFrame)
"""


def mesen_wave(rom: Path, frames: int, out: Path, seconds: float = 300) -> tuple[list[float], int]:
    """Mesen2's output for its first ``frames`` frames, left channel, as floats."""
    m = load_library()
    m.WaveRecord.argtypes = [ctypes.c_char_p]
    HOME.mkdir(parents=True, exist_ok=True)
    m.InitDll()
    m.InitializeEmu(str(HOME.resolve()).encode(), None, None, True, True, True, True)
    m.Pause()
    m.SetEmulationFlag(CONSOLE_MODE, True)
    configure_for_comparison(m)
    config = m.GetNesConfig()
    for i in range(11):
        at = NES_CONFIG_CHANNEL_VOLUMES + 4 * i
        config.raw[at : at + 4] = list((100).to_bytes(4, "little"))
    m.SetNesConfig(config)
    if not m.LoadRom(str(rom.resolve()).encode(), b""):
        raise SystemExit("LoadRom failed")
    m.InitializeDebugger()
    script = m.LoadScript(
        b"stop.lua", str(HOME.resolve()).encode(), (STOP_LUA % frames).encode(), -1
    )
    m.WaveRecord(str(out.resolve()).encode())
    m.SetEmulationFlag(MAXIMUM_SPEED, True)
    m.Resume()
    began = time.monotonic()
    buf = ctypes.create_string_buffer(1 << 16)
    while time.monotonic() - began < seconds:
        time.sleep(0.02)
        m.GetScriptLog(script, buf, len(buf))
        if b"DONE" in buf.value:
            break
    m.Pause()
    m.WaveStop()
    m.Stop()
    m.Release()
    with wave.open(str(out)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = array("h", w.readframes(w.getnframes()))
    left = [s / 32768 for s in pcm[::channels]]
    return left[: round(frames * rate / 60.0988)], rate


def board_wave(rom: Path, frames: int, rate: int, machine: Machine) -> list[float]:
    """The board's mixer output (before the analogue stage) at ``rate``."""
    system = System.from_rom(rom, machine)
    apu = system.board.apu
    system.board.set_sample_rate(rate)
    samples: list[float] = []
    for _ in range(frames):
        system.run_frames(1)
        samples += apu.take_samples()
    return samples


def high_pass(xs: list[float], rate: int, hz: float = 90.0) -> list[float]:
    rc = 1 / (2 * math.pi * hz)
    alpha = rc / (rc + 1 / rate)
    out, last_in, last_out = [], 0.0, 0.0
    for x in xs:
        last_out = alpha * (last_out + x - last_in)
        last_in = x
        out.append(last_out)
    return out


def best_lag(x: list[float], y: list[float], max_lag: int) -> int:
    """The shift of ``y`` against ``x`` (both DC-free, ``y`` padded by
    ``max_lag`` either side) that correlates best: coarse, then fine."""
    n = len(x)

    def score(lag: int, step: int) -> float:
        base = max_lag + lag
        return sum(x[i] * y[base + i] for i in range(0, n, step))

    coarse = max(range(-max_lag, max_lag + 1, 4), key=lambda lag: score(lag, 4))
    fine = range(max(-max_lag, coarse - 4), min(max_lag, coarse + 4) + 1)
    return max(fine, key=lambda lag: score(lag, 1))


def compare(board: list[float], mesen: list[float], rate: int, window: float) -> list[str]:
    """Window by window: align (within 1 ms: the streams start together, and a
    wider search only finds other periods of a steady tone), fit a gain,
    measure the residual."""
    board, mesen = high_pass(board, rate), high_pass(mesen, rate)
    size = max(1, int(window * rate))
    max_lag = rate // 1000
    n = min(len(board), len(mesen)) - max_lag
    rows = ["| window s | board rms | Mesen2 rms | lag | gain | residual dB |"]
    rows.append("| ---: | ---: | ---: | ---: | ---: | ---: |")
    worst = -math.inf
    for start in range(max_lag, n - size + 1, size):
        x = board[start : start + size]
        padded = mesen[start - max_lag : start + size + max_lag]
        xx = sum(v * v for v in x)
        rx = math.sqrt(xx / size)
        ry = math.sqrt(sum(v * v for v in padded[max_lag:-max_lag]) / size)
        if rx < 1e-6 or ry < 1e-6:
            rows.append(f"| {start / rate:.2f} | {rx:.5f} | {ry:.5f} | - | - | - |")
            continue
        lag = best_lag(x, padded, max_lag)
        y = padded[max_lag + lag : max_lag + lag + size]
        yy = sum(v * v for v in y)
        gain = sum(p * q for p, q in zip(x, y, strict=True)) / yy
        residual = sum((p - gain * q) ** 2 for p, q in zip(x, y, strict=True))
        db = 10 * math.log10(max(residual, 1e-30) / xx)
        worst = max(worst, db)
        rows.append(f"| {start / rate:.2f} | {rx:.5f} | {ry:.5f} | {lag} | {gain:.3f} | {db:.1f} |")
    rows.append(f"worst residual {worst:.1f} dB (lag: Mesen2 later if positive)")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--window", type=float, default=0.5, help="seconds per row")
    parser.add_argument("--wav", type=Path, default=HOME / "mesen.wav")
    parser.add_argument(
        "--machine",
        choices=sorted(MACHINES),
        default="nes",
        help="the board's console: expansion sound needs a Famicom (famicom)",
    )
    args = parser.parse_args()
    mesen, rate = mesen_wave(args.rom, args.frames, args.wav)
    board = board_wave(args.rom, args.frames, rate, MACHINES[args.machine])
    print(f"{args.rom.name}: {args.frames} frames at {rate} Hz")
    for row in compare(board, mesen, rate, args.window):
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
