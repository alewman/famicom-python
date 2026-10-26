#!/usr/bin/env python3
"""The board against NewRisingSun's expansion-audio recordings (open item 20).

NewRisingSun ran his 2018 test ROMs (``ExpAudio_testroms.7z``) on a Sharp
AN-505-BK Twin Famicom (C205 removed), hot-swapping the EverDrive for each
cartridge so its own chip played them, and recorded the console's Audio Out
at 96 kHz, 16 bits, one gain for all (nesdev-forum/16910.html, 2018-08-05):
two MMC5 carts, ten N163 carts and one VRC6 cart, each ending with some of the
game. Pinned as ``reference/nrs-expansion-audio/2018-08-06_ExpansionAudio.7z``
(an archive.org copy; the original URL is gone).

Each test plays fifteen volume steps of a 440 Hz square on the APU, then on
the chip (the VRC6 adds its saw; the N163 eight channels at once; the MMC5 its
DAC), about 3 s a step. Every step is the same pitch, so the console's filters
scale them alike: the report compares the fundamental's amplitude step by step.

    PYTHONPATH=src .venv-pypy/bin/python scripts/nrs_recordings.py render
    python3 scripts/nrs_recordings.py report     # needs numpy and scipy

``render`` runs the test ROMs on the board (Famicom, mixer output before the
analogue stage, 96 kHz, A pressed at 0.5 s) into ``board/`` beside the
archive; ``report`` reads them and the FLACs (unpacked with 7z, decoded with
ffmpeg). Nothing either writes is committed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "reference" / "nrs-expansion-audio"
ARCHIVE = HERE / "2018-08-06_ExpansionAudio.7z"
TEST_ROMS = ROOT / "tests" / "test_roms" / "nesdev-forum" / "ExpAudio_testroms.7z"
BOARD = HERE / "board"
FLAC = HERE / "flac"
RATE = 96_000
FRAMES = 12_000  # 200 s: every staircase of every test
TEST_FOR = {"MMC5": "MMC5TEST", "N163": "N163TEST", "VRC6": "VRC6TESA"}  # Madara is a VRC6b
#: N163 channel updates per second (Namco_163_audio.wiki: one every 15 CPU cycles).
N163_UPDATES = 236_250_000 / 11 / 12 / 15


def unpack(archive: Path, into: Path) -> None:
    if not into.exists():
        subprocess.run(
            ["7z", "x", "-y", f"-o{into}", str(archive)], check=True, capture_output=True
        )


def render() -> None:
    from famicom_python.machine import MACHINES
    from famicom_python.system import System

    unpack(TEST_ROMS, BOARD / "roms")
    for test in sorted(set(TEST_FOR.values())):
        system = System.from_rom(BOARD / "roms" / f"{test}.NES", MACHINES["famicom"])
        system.board.set_sample_rate(RATE)
        apu, out = system.board.apu, array("f")
        for frame in range(FRAMES):
            system.board.pads[0].buttons = 1 if 30 <= frame < 36 else 0  # A: start the test
            system.run_frames(1)
            out.extend(apu.take_samples())
        (BOARD / f"{test}.f32").write_bytes(out.tobytes())
        print(f"rendered {test}: {len(out) / RATE:.1f} s")


# -- the report (numpy) ----------------------------------------------------


def load(path: Path):
    import numpy as np

    if path.suffix == ".f32":
        return np.fromfile(path, np.float32).astype(np.float64)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.int16).astype(np.float64) / 32768


def tone(x, lo: float = 40, hi: float = 20_000, window: float = 0.1):
    """(start s, frequency, fundamental amplitude) of each ``window``."""
    import numpy as np

    n = int(RATE * window)
    t = np.arange(n) / RATE
    out = []
    for i in range(len(x) // n):
        s = x[i * n : (i + 1) * n]
        s = s - s.mean()
        spectrum = np.abs(np.fft.rfft(s * np.hanning(n), 8 * n))
        freqs = np.fft.rfftfreq(8 * n, 1 / RATE)
        f = freqs[np.argmax(np.where((freqs > lo) & (freqs < hi), spectrum, 0))]
        amplitude = 2 * np.hypot(s @ np.cos(2 * np.pi * f * t), s @ np.sin(2 * np.pi * f * t)) / n
        out.append((i * window, f, amplitude))
    return out


def staircases(x) -> list[list[float]]:
    """The volume steps: runs of windows within 3% at one pitch, at least 0.8 s,
    grouped into staircases (a new one where the level falls back or the pitch moves)."""
    import numpy as np

    plateaus, run = [], []
    for point in tone(x[: 200 * RATE]):
        if run:
            level = np.median([p[2] for p in run])
            if abs(point[2] - level) <= 0.03 * max(level, 1e-6) and abs(point[1] - run[-1][1]) < 5:
                run.append(point)
                continue
            if len(run) >= 8:
                plateaus.append(
                    (run[0][0], run[-1][0], run[-1][1], float(np.median([p[2] for p in run])))
                )
        run = [point]
    stairs: list[list[tuple]] = []
    for p in (p for p in plateaus if p[3] > 2e-4):
        last = stairs[-1][-1] if stairs else None
        if not last or p[3] < 0.9 * last[3] or p[0] - last[1] > 1.0 or abs(p[2] - last[2]) > 5:
            stairs.append([])
        stairs[-1].append(p)
    return [[p[3] for p in s] for s in stairs if len(s) >= 10]


def db(ratio: float) -> float:
    import math

    return 20 * math.log10(ratio)


def report_levels(name: str, board: list[list[float]], hardware: list[list[float]]) -> None:
    labels = {
        "MMC5": ["APU square", "MMC5 square"],
        "N163": ["APU square", "N163 1 ch", "N163 8 ch"],
    }
    labels["VRC6"] = ["APU square", "VRC6 square", "VRC6 saw"]
    print(f"{name}")
    for label, b, h in zip(labels[name[:4]], board, hardware, strict=False):
        n = min(len(b), len(h))
        curve = [db((hv / h[n - 1]) / (bv / b[n - 1])) for bv, hv in zip(b[:n], h[:n], strict=True)]
        print(
            f"  {label:12s} full step vs APU's: board {db(b[-1] / board[0][-1]):+6.2f} dB,"
            f" hardware {db(h[-1] / hardware[0][-1]):+6.2f} dB;"
            f" steps 1-{n} against step {n}, hardware - board:"
            f" {min(curve):+.2f} to {max(curve):+.2f} dB"
        )


def report_n163_lines(name: str, x) -> None:
    """Channel switching (Namco_163_audio.wiki): N channels taken in turn make a
    tone at N163_UPDATES / N. Calibrated on the test's eight-channel section."""
    import numpy as np

    def spectrum(s):
        s = s - s.mean()
        n = 1 << 21
        parts = [
            np.abs(np.fft.rfft(s[i : i + n] * np.hanning(n))) ** 2
            for i in range(0, len(s) - n + 1, n // 2)
        ]
        return np.fft.rfftfreq(n, 1 / RATE), np.mean(parts, 0)

    def peak(f, p, centre, span):
        k = np.argmax(np.where((f > centre - span) & (f < centre + span), p, 0))
        ring = p[(f > centre - 300) & (f < centre + 300) & ~((f > f[k] - 3) & (f < f[k] + 3))]
        return f[k], 10 * np.log10(p[k] / np.median(ring))

    f, p = spectrum(x[100 * RATE : 140 * RATE])
    f8, test_db = peak(f, p, N163_UPDATES / 8, 20)
    f, p = spectrum(x[146 * RATE :])
    _, game8 = peak(f, p, f8, 0.5)
    _, game4 = peak(f, p, 2 * f8, 0.5)
    print(
        f"  switching lines: test 8 ch {f8:.2f} Hz {test_db:+.0f} dB;"
        f" game {game8:+.0f} dB at 8 ch, {game4:+.0f} dB at 4 ch (a search's noise peak is ~+5)"
    )


def report_mmc5_dac(x) -> None:
    """The test feeds $22/$02 to the DMC ($4011, until A) and later, by the same
    loop, to the MMC5's DAC ($5011): the 1676 Hz square of each."""
    import numpy as np

    def level(t0, t1):
        return float(
            np.median(
                [a for _, f, a in tone(x[int(t0 * RATE) : int(t1 * RATE)]) if 1600 < f < 1750]
            )
        )

    windows = [t for t, f, a in tone(x[: 3 * RATE]) if 1600 < f < 1750 and a > 0.02]
    dmc = level(0.1, max(windows))
    dac = level(99.5, 104)
    square = staircases(x)[1][-1]
    print(
        f"  MMC5 DAC $02/$22: {db(dac / dmc):+.2f} dB against the DMC's,"
        f" {db(dac / square):+.2f} dB against a full MMC5 square"
    )


def report() -> None:
    unpack(ARCHIVE, FLAC)
    board = {test: load(BOARD / f"{test}.f32") for test in sorted(set(TEST_FOR.values()))}
    board_stairs = {test: staircases(x) for test, x in board.items()}
    print("board renders:")
    report_mmc5_dac(board["MMC5TEST"])
    for path in sorted(FLAC.glob("*.flac")):
        x = load(path)
        report_levels(path.stem, board_stairs[TEST_FOR[path.stem[:4]]], staircases(x))
        if path.stem.startswith("N163"):
            report_n163_lines(path.stem, x)
        if path.stem.startswith("MMC5"):
            report_mmc5_dac(x)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=["render", "report"])
    args = parser.parse_args()
    if args.step == "render":
        BOARD.mkdir(parents=True, exist_ok=True)
        render()
    else:
        report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
