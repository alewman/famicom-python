#!/usr/bin/env python3
"""Compare the board's channel balance with an NES-001 recording of volume_tests.

Damian Yerrick's ``volume_tests`` plays 12 tones near 1 kHz (pulse 1 at four
duties, both pulses at four duties, triangle, long and short noise, DMC
amplitude 30), three times, with the DMC held at 0, 48 and 96, once A is
pressed. Its ``recordings/nes-001.ogg`` is the program on an NES-001 (with a
PowerPak), so it is **hardware-captured**, through an analogue path and sound
card nobody has characterised: relative levels are evidence, absolute ones are
not. Each tone's RMS (middle 60 %) is divided by tone 3's (pulse 1, 1/2 duty) in
the same pass, on both sides; the board's output passes its fitted NES-001
stage first.

    python scripts/volume_levels.py

Needs ffmpeg to decode the fetched recording; nothing it writes is committed.
"""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

from famicom_python.joypad import A
from famicom_python.system import System

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests" / "test_roms" / "nes-test-roms" / "volume_tests"
RATE = 44100
TONES = (
    "pulse 1, 1/8",
    "pulse 1, 1/4",
    "pulse 1, 1/2",
    "pulse 1, 3/4",
    "pulses 1+2, 1/8",
    "pulses 1+2, 1/4",
    "pulses 1+2, 1/2",
    "pulses 1+2, 3/4",
    "triangle",
    "noise, long",
    "noise, short",
    "DMC, 30",
)


def tone_levels(samples: list[float]) -> list[float]:
    """The RMS of each tone: runs of 50 ms windows above 5 % of the loudest."""
    window = RATE // 20
    envelope = []
    for start in range(0, len(samples) - window, window):
        part = samples[start : start + window]
        mean = sum(part) / window
        envelope.append(math.sqrt(sum((x - mean) ** 2 for x in part) / window))
    threshold = max(envelope) * 0.05
    runs, on = [], None
    for i, level in enumerate([*envelope, 0.0]):
        if level > threshold and on is None:
            on = i
        elif level <= threshold and on is not None:
            if i - on >= 8:  # at least 0.4 s: a tone, not a DMC level step
                runs.append((on * window, i * window))
            on = None
    levels = []
    for start, end in runs:
        middle = samples[start + (end - start) // 5 : end - (end - start) // 5]
        mean = sum(middle) / len(middle)
        levels.append(math.sqrt(sum((x - mean) ** 2 for x in middle) / len(middle)))
    return levels


def recording() -> list[float]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "nes-001.wav"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(TESTS / "recordings" / "nes-001.ogg"),
             "-ac", "1", "-ar", str(RATE), str(out)],
            check=True,
        )  # fmt: skip
        with wave.open(str(out)) as w:
            return [s / 32768 for s in array("h", w.readframes(w.getnframes()))]


def board_run(seconds: float = 46) -> list[float]:
    system = System.from_rom(TESTS / "volumes.nes")
    system.board.set_sample_rate(RATE)
    system.run_frames(60)
    system.take_samples()
    system.board.pads[0].buttons = A
    system.run_frames(6)
    system.board.pads[0].buttons = 0
    samples: list[float] = []
    for _ in range(round(60 * seconds)):
        system.run_frames(1)
        samples += system.take_samples()
    return samples


def main() -> int:
    hardware, board = tone_levels(recording()), tone_levels(board_run())
    if len(hardware) != 36 or len(board) != 36:
        print(f"expected 36 tones, found {len(hardware)} (NES-001) and {len(board)} (board)")
        return 1
    print("| DMC held at | tone | NES-001 | board | board - NES-001 |")
    print("| ---: | --- | ---: | ---: | ---: |")
    for k, (h, b) in enumerate(zip(hardware, board, strict=True)):
        held, tone = divmod(k, 12)
        rh, rb = h / hardware[held * 12 + 2], b / board[held * 12 + 2]
        print(
            f"| {48 * held} | {TONES[tone]} | {rh:.3f} | {rb:.3f} | "
            f"{20 * math.log10(rb / rh):+.2f} dB |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
