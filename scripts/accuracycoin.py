#!/usr/bin/env python3
"""Run all of AccuracyCoin on the board and print every test's result.

AccuracyCoin (100th_Coin, MIT; pinned in scripts/pinned_repos.json) runs all
147 tests when Start is pressed on its page index and leaves one result byte
per test in $0400-$04FF: low 2 bits 1 pass, 2 fail, the bits above the error
code (the README lists each test's codes), $FF skipped. Test names and result
addresses are read from the pinned AccuracyCoin.asm.

    python scripts/accuracycoin.py [--failures]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from famicom_python.system import System
from famicom_python.testrom import accuracycoin_tests, run_accuracycoin, run_accuracycoin_test

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "tests" / "test_roms" / "AccuracyCoin"


def verdict(value: int) -> str:
    if value == 0xFF:
        return "skipped"
    # Error codes count 0-9 then A-Z (the README's lists).
    code = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[value >> 2] if value >> 2 < 36 else "?"
    return {1: "pass", 2: f"FAIL {code}"}.get(value & 3, f"no result (${value:02X})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--failures", action="store_true", help="print only what did not pass")
    parser.add_argument("--seconds", type=float, default=300, help="emulated seconds at most")
    parser.add_argument("--test", action="append", help="run only tests whose name contains this")
    args = parser.parse_args()
    tests = accuracycoin_tests((HOME / "AccuracyCoin.asm").read_text())
    if args.test:
        for test in tests:
            if any(want.lower() in test.name.lower() for want in args.test):
                system = System.from_rom(HOME / "AccuracyCoin.nes")
                value = run_accuracycoin_test(system, test)
                print(f"{test.page} / {test.name}: {verdict(value)}", flush=True)
        return 0
    system = System.from_rom(HOME / "AccuracyCoin.nes")
    began = time.monotonic()
    results = run_accuracycoin(system, tests, max_seconds=args.seconds)
    wall = time.monotonic() - began
    passed = sum(1 for value in results.values() if value != 0xFF and value & 3 == 1)
    print("| Page | Test | Result |")
    print("| --- | --- | --- |")
    for test, value in results.items():
        text = verdict(value)
        if not args.failures or text != "pass":
            print(f"| {test.page} | {test.name} | {text} |")
    print(
        f"\n{passed} of {len(tests)} pass; {system.cycles:,} CPU cycles, "
        f"{system.board.ppu.frame:,} frames, {wall:.0f} s wall"
    )
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
