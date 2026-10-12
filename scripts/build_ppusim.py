#!/usr/bin/env python3
"""Build Breaknes's PPUSim with our shim into reference/build-ppusim/libppusim.so.

PPUSim (gate-level RP2C02G, CC0-1.0) comes from the pinned breaknes checkout in
reference/src/breaknes (scripts/pinned_repos.json); the shim,
scripts/ppusim/ppusim_shim.cpp, is ours. The result is a build product under
reference/, never committed. Needs g++ with C++20; about a minute with -j.

    python scripts/build_ppusim.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BREAKNES = ROOT / "reference" / "src" / "breaknes"
OUT = ROOT / "reference" / "build-ppusim"
LIBRARY = OUT / "libppusim.so"
SHIM = ROOT / "scripts" / "ppusim" / "ppusim_shim.cpp"
FLAGS = ["-std=c++20", "-O2", "-fPIC", "-w"]


def main() -> int:
    if not BREAKNES.exists():
        print("reference/src/breaknes missing: python scripts/fetch_references.py", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    ppusim = BREAKNES / "Chips" / "PPUSim"
    logic = BREAKNES / "Common" / "BaseLogicLib"
    sources = sorted(ppusim.glob("*.cpp")) + sorted(logic.glob("*.cpp"))
    includes = ["-I", str(ppusim), "-I", str(logic)]

    def compile_one(source: Path) -> Path:
        obj = OUT / f"{source.parent.name}_{source.stem}.o"
        if not obj.exists() or obj.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                ["g++", *FLAGS, *includes, "-c", str(source), "-o", str(obj)], check=True
            )
        return obj

    with ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as pool:
        objects = list(pool.map(compile_one, sources))
    shim = OUT / "ppusim_shim.o"
    subprocess.run(["g++", *FLAGS, *includes, "-c", str(SHIM), "-o", str(shim)], check=True)
    subprocess.run(
        ["g++", "-shared", "-o", str(LIBRARY), *map(str, objects), str(shim)], check=True
    )
    print(f"built {LIBRARY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
