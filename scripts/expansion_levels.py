#!/usr/bin/env python3
"""The board's expansion-sound levels against the measured ones (docs/undocumented-behavior.md).

rainwarrior's ``nes-audio-tests`` ``db_*`` ROMs play a full-volume 440 Hz APU
square for two seconds, then the expansion chip's full-volume square (the 5B
at volume 12), and repeat. On hardware the ratio of the two tones' RMS was
measured on many consoles and cartridges (nesdev-forum/17741.html); here
each ROM runs on a Famicom and the same ratio is taken from the APU mixer's
output, before the analogue stage.

    python scripts/expansion_levels.py [db_vrc6a ...]

The ROMs are in the fetched ``reference/src/nes-audio-tests/build``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from volume_levels import RATE, tone_levels

from famicom_python.machine import FAMICOM
from famicom_python.system import System

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "reference" / "src" / "nes-audio-tests" / "build"

#: Each ROM and the level rainwarrior measured on his AV Famicom (dB, the
#: chip's square against the APU's: undocumented-behavior.md's table).
MEASURED = {
    "db_vrc6a": 0.2,
    "db_vrc6b": 0.2,
    "db_mmc5": 1.0,
    # The N163's level is its board's: db_n163 has no submapper (0), which
    # the board takes as the measured games' median.
    "db_n163": 18.0,
    "db_vrc7": 11.3,
    "db_fds": 6.6,  # a disk: needs the BIOS (FAMICOM_FDS_BIOS or NO_INTRO_DIR)
}


NO_BUZZ = {"db_fds"}


def levels(name: str, seconds: float = 16) -> list[float]:
    path = BUILD / f"{name}.nes"
    if not path.exists():
        path = path.with_suffix(".fds")
    system = System.from_rom(path, FAMICOM)
    system.board.set_sample_rate(RATE)
    samples: list[float] = []
    for _ in range(round(60 * seconds)):
        system.run_frames(1)
        samples += system.board.apu.take_samples()
    return tone_levels(samples)


def main(argv: list[str]) -> int:
    print("| ROM | tones | board (dB) | measured (dB) |")
    print("| --- | ---: | ---: | ---: |")
    worst = 0.0
    for name in argv or list(MEASURED):
        tones = levels(name)
        # The DMC buzz (the second merges with the APU square's run), then
        # APU square, chip square, APU square, ...
        # On the disk (db_fds) the buzz falls inside the BIOS's boot and no
        # tone comes before the APU square.
        first = 0 if name in NO_BUZZ else 1
        squares = tones[first : first + 4]
        if len(squares) < 2:
            print(f"| {name} | {len(tones)} | - | {MEASURED.get(name, '-')} |")
            worst = math.inf
            continue
        db = 20 * math.log10(squares[1] / squares[0])
        print(f"| {name} | {len(tones)} | {db:+.2f} | {MEASURED.get(name, math.nan):+.2f} |")
        worst = max(worst, abs(db - MEASURED.get(name, db)))
    return 0 if worst < 0.05 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
