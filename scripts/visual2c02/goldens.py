#!/usr/bin/env python3
"""Record Visual 2C02's OAM counter for the OAM-address cases, for the quick test.

    python scripts/visual2c02/goldens.py                 # run every case (about 3 min each)
    python scripts/visual2c02/goldens.py --jobs 4 NAME   # some of them
    python scripts/visual2c02/goldens.py --import NAME=DIR   # a run already made in DIR

Each case is a compare.py scenario with its environment (CASES). Visual 2C02's
OAM address on each odd dot of line 7's sprite evaluation (dots 65-255) is the
main counter, OAMADDR; those are kept in tests/visual2c02_goldens.json.gz, and
tests/test_visual2c02_goldens.py holds the board to them. Visual 2C02 is the
judge here, not PPUSim: on these counters the two disagree, and where
AccuracyCoin can tell (C73) the console sides with Visual 2C02.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOLDENS = ROOT / "tests" / "visual2c02_goldens.json.gz"
FIRST, LAST = 65, 255  # the odd dots of evaluation compared


def evalwrite(oam: str, register: int, dot: int) -> tuple[str, dict[str, str]]:
    return "evalwrite", {"EVAL_OAM": oam, "EVAL_REG": str(register), "EVAL_DOT": str(dot)}


# name: (scenario, environment)
CASES: dict[str, tuple[str, dict[str, str]]] = {
    "$2003 copy 66": evalwrite("dense", 3, 66),
    "$2003 copy 67": evalwrite("dense", 3, 67),
    "$2003 copy 78": evalwrite("dense", 3, 78),
    "$2003 copy 85": evalwrite("dense", 3, 85),
    "$2003 search 90": evalwrite("alt", 3, 90),
    "$2003 search 91": evalwrite("alt", 3, 91),
    "off copy 96": evalwrite("alt", 1, 96),
    "off copy 97": evalwrite("alt", 1, 97),
    "off search 100": evalwrite("alt", 1, 100),
    "off search 101": evalwrite("alt", 1, 101),
    "off overflow 210": evalwrite("dense", 1, 210),
    "off overflow 211": evalwrite("dense", 1, 211),
    "C73 X in range": ("c73", {"C73_X": "0x02"}),
    "C73 X out of range": ("c73", {"C73_X": "0x80"}),
}


def counter(probes: dict[str, list[int]]) -> dict[str, int]:
    return {str(h): probes[f"7:{h}"][0] for h in range(FIRST, LAST + 1, 2)}


def run(name: str) -> dict[str, int]:
    scenario, env = CASES[name]
    with tempfile.TemporaryDirectory(prefix="v2c02-") as work:
        subprocess.run(
            [sys.executable, str(HERE / "compare.py"), scenario, "v2c02"],
            cwd=work,
            env=os.environ | env | {"PYTHONPATH": str(ROOT / "src")},
            check=True,
            stdout=subprocess.DEVNULL,
        )
        probes = json.loads((Path(work) / f"{scenario}-v2c02-probes.json").read_text())
    return counter(probes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="cases to run (default: all)")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--import", dest="imports", action="append", default=[], metavar="NAME=DIR")
    args = parser.parse_args()
    goldens = json.loads(gzip.decompress(GOLDENS.read_bytes())) if GOLDENS.exists() else {}
    for item in args.imports:
        name, directory = item.split("=", 1)
        scenario = CASES[name][0]
        probes = json.loads((Path(directory) / f"{scenario}-v2c02-probes.json").read_text())
        goldens[name] = counter(probes)
        print(f"imported {name}")
    names = args.names or ([] if args.imports else list(CASES))
    with ThreadPoolExecutor(args.jobs) as pool:
        for name, result in zip(names, pool.map(run, names), strict=True):
            goldens[name] = result
            print(f"ran {name}", flush=True)
    GOLDENS.write_bytes(gzip.compress(json.dumps(goldens, sort_keys=True).encode(), mtime=0))
    print(f"{len(goldens)} cases in {GOLDENS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
