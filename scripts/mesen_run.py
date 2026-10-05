#!/usr/bin/env python3
"""Drive a locally built MesenCore.so (Mesen2 2.1.1 archive) headless via ctypes.

Feasibility probe for docs/validation.md ("Mesen2 as a second detector"): mirrors UI/Utilities/TestRunner.cs
(no .NET needed) and adds the built-in trace logger, which prints the PPU
scanline/dot and the CPU cycle count before every instruction.

    python scripts/mesen_run.py rom.nes --seconds 2 --trace out.trace --lua script.lua
Exit code: the Lua script's emu.stop(code), or -1 on timeout.
"""

from __future__ import annotations

import argparse
import ctypes
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Built by hand as docs/validation.md "Mesen2 as a second detector" describes; never committed.
LIB = ROOT / "reference/build-mesen2/Mesen2/InteropDLL/obj.linux-x64/MesenCore.so"
CPU_NES = 8  # CpuType::Nes
MAXIMUM_SPEED, CONSOLE_MODE = 0x04, 0x10


class TraceLoggerOptions(ctypes.Structure):
    _fields_ = [
        ("Enabled", ctypes.c_bool),
        ("IndentCode", ctypes.c_bool),
        ("UseLabels", ctypes.c_bool),
        ("Condition", ctypes.c_char * 1000),
        ("Format", ctypes.c_char * 1000),
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("rom", type=Path)
    p.add_argument("--seconds", type=float, default=2.0, help="wall-clock timeout")
    p.add_argument("--frames", type=int, default=0, help="stop at this frame (via Lua)")
    p.add_argument("--trace", type=Path)
    p.add_argument("--lua", type=Path)
    p.add_argument("--home", type=Path, default=Path("mesen-home"))
    a = p.parse_args()
    m = ctypes.CDLL(str(LIB))
    m.InitializeEmu.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p] + [
        ctypes.c_bool
    ] * 4
    m.LoadRom.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    m.LoadRom.restype = ctypes.c_bool
    m.IsRunning.restype = ctypes.c_bool
    m.GetStopCode.restype = ctypes.c_int32
    m.SetEmulationFlag.argtypes = [ctypes.c_uint32, ctypes.c_bool]
    m.LoadScript.argtypes = [ctypes.c_char_p] * 3 + [ctypes.c_int32]
    m.LoadScript.restype = ctypes.c_int32
    m.GetScriptLog.argtypes = [ctypes.c_int32, ctypes.c_char_p, ctypes.c_uint32]
    m.SetTraceOptions.argtypes = [ctypes.c_uint8, TraceLoggerOptions]
    m.StartLogTraceToFile.argtypes = [ctypes.c_char_p]

    a.home.mkdir(parents=True, exist_ok=True)
    m.InitDll()
    m.InitializeEmu(str(a.home.resolve()).encode(), None, None, True, True, True, True)
    m.Pause()
    m.SetEmulationFlag(CONSOLE_MODE, True)
    if not m.LoadRom(str(a.rom.resolve()).encode(), b""):
        raise SystemExit("LoadRom failed")
    m.InitializeDebugger()
    script_id = -1
    if a.lua:
        script_id = m.LoadScript(
            a.lua.name.encode(), str(a.lua.parent).encode(), a.lua.read_bytes(), -1
        )
    if a.trace:
        opts = TraceLoggerOptions(
            True,
            False,
            False,
            b"",
            b"[PC,4h] A:[A,2h] X:[X,2h] Y:[Y,2h] S:[SP,2h] P:[P,h] "
            b"CYC:[CycleCount] SL:[Scanline] DOT:[Cycle] FR:[FrameCount]",
        )
        m.SetTraceOptions(CPU_NES, opts)
        m.StartLogTraceToFile(str(a.trace.resolve()).encode())
    m.SetEmulationFlag(MAXIMUM_SPEED, True)
    began = time.monotonic()
    m.Resume()
    result = -1
    while time.monotonic() - began < a.seconds:
        time.sleep(0.05)
        if not m.IsRunning():
            result = m.GetStopCode()
            break
    if a.trace:
        m.StopLogTraceToFile()
    if script_id >= 0:
        buf = ctypes.create_string_buffer(1 << 20)
        m.GetScriptLog(script_id, buf, len(buf))
        print(buf.value.decode(errors="replace"))
    m.Stop()
    m.Release()
    print(f"stop code {result} after {time.monotonic() - began:.1f} s")
    return result


if __name__ == "__main__":
    raise SystemExit(main() & 0xFF)
