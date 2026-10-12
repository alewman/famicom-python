#!/usr/bin/env python3
"""Build Breaknes's APUSim with our shim into reference/build-apusim/libapusim.so.

APUSim (gate-level RP2A03, its M6502Core 6502 included; CC0-1.0) comes from the
pinned breaknes checkout in reference/src/breaknes (scripts/pinned_repos.json);
the shim, scripts/apusim/apusim_shim.cpp, is ours. The result is a build
product under reference/, never committed. Needs g++ with C++20.

    python scripts/build_apusim.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BREAKNES = ROOT / "reference" / "src" / "breaknes"
OUT = ROOT / "reference" / "build-apusim"
LIBRARY = OUT / "libapusim.so"
SHIM = ROOT / "scripts" / "apusim" / "apusim_shim.cpp"
FLAGS = ["-std=c++20", "-O2", "-fPIC", "-w"]


def main() -> int:
    apusim = BREAKNES / "Chips" / "APUSim"
    core = BREAKNES / "Chips" / "M6502Core"
    logic = BREAKNES / "Common" / "BaseLogicLib"
    if not (apusim.exists() and core.exists()):
        print(
            "breaknes APUSim/M6502Core missing: python scripts/fetch_references.py", file=sys.stderr
        )
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    sources = [
        *sorted(apusim.glob("*.cpp")),
        *sorted(core.glob("*.cpp")),
        *sorted(logic.glob("*.cpp")),
    ]

    def compile_one(source: Path) -> Path:
        obj = OUT / f"{source.parent.name}_{source.stem}.o"
        if not obj.exists() or obj.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                ["g++", *FLAGS, "-I", str(source.parent), "-c", str(source), "-o", str(obj)],
                check=True,
            )
        return obj

    with ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as pool:
        objects = list(pool.map(compile_one, sources))
    shim = OUT / "apusim_shim.o"
    subprocess.run(["g++", *FLAGS, "-I", str(apusim), "-c", str(SHIM), "-o", str(shim)], check=True)
    subprocess.run(
        ["g++", "-shared", "-o", str(LIBRARY), *map(str, objects), str(shim)], check=True
    )
    print(f"built {LIBRARY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
