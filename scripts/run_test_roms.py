"""Run a milestone's test ROMs in parallel and print the certification record.

Each ROM runs in its own process (under ``nice``; at most ``--jobs``, 16 by
the shared machine's rule) and is reported with its SHA-256, verdict, emulated
CPU cycles, instructions, wall time and interpreter:

    nice python scripts/run_test_roms.py --suite cpu
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from famicom_python.testrom import (
    APU_ROMS,
    CPU_ROMS,
    FDS_ROMS,
    MAPPER_ROMS,
    PAL_ROMS,
    PPU_ROMS,
    RomCase,
    RomOutcome,
    rom_bytes,
    run_case,
)

ROOT = Path(__file__).resolve().parents[1]
ROMS = ROOT / "tests" / "test_roms" / "nes-test-roms"
SUITES = {
    "cpu": CPU_ROMS,
    "ppu": PPU_ROMS,
    "apu": APU_ROMS,
    "mappers": MAPPER_ROMS,
    "fds": FDS_ROMS,
    "pal": PAL_ROMS,
}


def _run(case: RomCase) -> tuple[RomOutcome, float]:
    start = time.perf_counter()
    outcome = run_case(case, ROMS)
    return outcome, time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=sorted(SUITES), default="cpu")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    cases = SUITES[args.suite]
    interpreter = f"{platform.python_implementation()} {platform.python_version()}"
    print(
        "| ROM | SHA-256 (first 12) | Result | CPU cycles | Instructions "
        f"| Wall s ({interpreter}) |"
    )
    print("| --- | --- | --- | ---: | ---: | ---: |")
    failures = 0
    with ProcessPoolExecutor(max_workers=min(args.jobs, 16)) as pool:
        for outcome, wall in pool.map(_run, cases):
            case = outcome.case
            digest = hashlib.sha256(rom_bytes(ROMS, case.path)).hexdigest()[:12]
            verdict = {True: "pass", False: "FAIL", None: "no verdict"}[outcome.passed]
            failures += outcome.passed is not True
            print(
                f"| `{case.label}` | `{digest}` | {verdict} | {outcome.cycles:,} | "
                f"{outcome.instructions:,} | {wall:.1f} |"
            )
            if outcome.passed is not True:
                print(f"<!-- {outcome.detail!r} -->", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
