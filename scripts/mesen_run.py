#!/usr/bin/env python3
"""Drive a locally built MesenCore.so (Mesen2 2.1.1 archive) headless via ctypes.

Feasibility probe for docs/validation.md ("Mesen2 as a second detector"): mirrors
UI/Utilities/TestRunner.cs
(no .NET needed) and adds the built-in trace logger, which prints the PPU
scanline/dot and the CPU cycle count before every instruction.

    python scripts/mesen_run.py rom.nes --seconds 2 --trace out.trace --lua script.lua
Exit code: the Lua script's emu.stop(code), or -1 on timeout.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Built by hand as docs/validation.md "Mesen2 as a second detector" describes; never committed.
# ``MESEN_LIB`` picks another build: MesenCE, Mesen2's successor, has the same NesConfig layout
# (measured from the running library), in reference/build-mesence (validation.md).
LIB = Path(
    os.environ.get(
        "MESEN_LIB", ROOT / "reference/build-mesen2/Mesen2/InteropDLL/obj.linux-x64/MesenCore.so"
    )
)
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


# Mesen2 2.1.1's NesConfig (Core/Shared/SettingTypes.h), measured with
# offsetof() against that header: its size, and where the fields this script
# touches lie. run_mesen checks two known defaults before trusting them.
NES_CONFIG_SIZE = 14184
NES_CONFIG_PORT1_TYPE = 988  # ControllerType (int32) of Port1
NES_CONFIG_PORT2_TYPE = 1980
# ControllerType::NesController: 6 on Mesen2, 10 on MesenCE (found by which value gives a pad
# of eight buttons: its list was renumbered, and with 6 no controller is plugged in).
NES_CONTROLLER = 10 if "mesence" in str(LIB).lower() else 6
NES_CONFIG_AUTO_CONFIGURE_INPUT = 11908  # bool, default true
NES_CONFIG_REGION = 11912  # ConsoleRegion (int32): 0 auto, 1 NTSC, 2 PAL, 3 Dendy
REGIONS = {"NTSC": 1, "PAL": 2, "Dendy": 3}  # by machine.Timing.name
NES_CONFIG_SPRITES_ENABLED = 11932  # bool, default true
NES_CONFIG_OAM_ROW_CORRUPTION = 11982  # bool: EnablePpuOamRowCorruption, default false
NES_CONFIG_RESTRICT_FIRST_FRAME = 11989  # bool: RestrictPpuAccessOnFirstFrame
NES_CONFIG_RAM_POWER_ON = 11996  # RamState: 0 random, 1 zeros, 2 ones
NES_CONFIG_INPUT_SCANLINE = 12016  # int32, default 241
NES_CONFIG_FULL_COLOR_PALETTE = 12020  # bool
NES_CONFIG_USER_PALETTE = 12024  # uint32[512]


class NesConfig(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_ubyte * NES_CONFIG_SIZE)]


def load_library() -> ctypes.CDLL:
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
    m.GetNesConfig.restype = NesConfig
    m.SetNesConfig.argtypes = [NesConfig]
    return m


def configure_for_comparison(m: ctypes.CDLL, region: int = 1) -> None:
    """Make Mesen2's frames comparable with the board's, pixel value for pixel value.

    - A 512-entry identity palette: headless, nothing loads a palette (the UI
      normally does), so frames come out black; with entry i = i,
      ``emu.getScreenBuffer()`` returns palette value | emphasis << 6, the
      board's own pixel format.
    - The PPU ignores $2000/$2001/$2005/$2006 writes until the first pre-render
      line, as hardware does (PPU_power_up_state.wiki); Mesen2 does not by default.
    - Work RAM powers on as zeros, the board's default ``PowerOn.ram_fill``;
      Mesen2's default is random.
    - A standard controller in each port, as the board has, and no input
      configured from Mesen2's game database (which plugs a Zapper into
      port 2 for The Adventures of Bayou Billy, and the Zapper's light
      sense reads 1 on $4017 D3); headless, the ports are otherwise empty.
    - The board's region whatever the dump's (``region``, NTSC by default):
      Mesen2 would otherwise run a PAL dump on a PAL console.
    - OAM row corruption on (rendering re-enabled with the secondary OAM
      address frozen), which the board always models (C26, AccuracyCoin's
      hardware answer key); off by default in Mesen2. Found by lockstep:
      The Legend of Zelda turns rendering off mid-frame on its title screen.
    """
    config = m.GetNesConfig()
    raw = config.raw
    if (
        raw[NES_CONFIG_SPRITES_ENABLED] != 1
        or int.from_bytes(
            bytes(raw[NES_CONFIG_INPUT_SCANLINE : NES_CONFIG_INPUT_SCANLINE + 4]), "little"
        )
        != 241
    ):
        raise SystemExit("NesConfig layout does not match Mesen2 2.1.1; re-measure the offsets")
    raw[NES_CONFIG_REGION : NES_CONFIG_REGION + 4] = [region, 0, 0, 0]
    raw[NES_CONFIG_AUTO_CONFIGURE_INPUT] = 0
    for port in (NES_CONFIG_PORT1_TYPE, NES_CONFIG_PORT2_TYPE):
        raw[port : port + 4] = [NES_CONTROLLER, 0, 0, 0]
    raw[NES_CONFIG_RESTRICT_FIRST_FRAME] = 1
    raw[NES_CONFIG_RAM_POWER_ON] = 1
    raw[NES_CONFIG_OAM_ROW_CORRUPTION] = 1
    raw[NES_CONFIG_FULL_COLOR_PALETTE] = 1
    for i in range(512):
        at = NES_CONFIG_USER_PALETTE + 4 * i
        raw[at : at + 4] = list(i.to_bytes(4, "little"))
    m.SetNesConfig(config)


# Frames travel through the script log, which keeps its last 500 lines and which MesenCE wraps
# at 300 characters: two characters a pixel, in numbered lines of 280, read as they appear.
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/"
FRAMES_LUA = """
local wanted, frame, last = {%s}, 0, %d
local alphabet = "ALPHABET"
local digit = {}
for i = 1, 64 do digit[i - 1] = alphabet:sub(i, i) end
emu.addEventCallback(function()
  frame = frame + 1
  if wanted[frame] then
    local buffer = emu.getScreenBuffer()
    local parts = {}
    for i = 1, #buffer do
      local v = buffer[i]
      parts[i] = digit[(v // 64) %% 64] .. digit[v %% 64]
    end
    local all = table.concat(parts)
    local count = 0
    for at = 1, #all, 280 do
      emu.log("L" .. frame .. "." .. count .. " " .. all:sub(at, at + 279))
      count = count + 1
    end
    emu.log("E" .. frame .. " " .. count)
  end
  if frame == last then emu.log("DONE") end
end, emu.eventType.endFrame)
""".replace("ALPHABET", ALPHABET)


def decode_frames(lines: dict[str, str]) -> dict[int, list[int]]:
    """The complete frames among the log lines ``run_mesen`` collected."""
    frames = {}
    for key, text in lines.items():
        if key.startswith("E"):
            frame, count = int(key[1:]), int(text)
            parts = [lines.get(f"L{frame}.{n}") for n in range(count)]
            if None in parts:
                continue
            data = "".join(parts)
            frames[frame] = [
                ALPHABET.index(data[i]) << 6 | ALPHABET.index(data[i + 1])
                for i in range(0, len(data), 2)
            ]
    return frames


def run_mesen(
    rom: Path,
    *,
    lua: bytes | None = None,
    lua_name: str = "script.lua",
    seconds: float = 2.0,
    home: Path = Path("mesen-home"),
    trace: Path | None = None,
    until: str | None = None,
    max_speed: bool = True,
    for_comparison: bool = False,
    region: int = 1,
    collect: dict[str, str] | None = None,
) -> tuple[int, str, float]:
    """Run ``rom`` at maximum speed until the Lua script stops it or ``seconds`` pass.

    Mesen2 discards a script's log when ``emu.stop`` ends emulation, so a script
    that reports through its log prints ``until`` as its last line instead and
    keeps running; this polls for it and then stops (stop code 0). Returns the
    stop code (-1 on timeout), the script's log and the wall time. ``collect`` gathers
    lines ``KEY text`` as they pass through the log, which keeps only its last 500.
    """
    m = load_library()
    home.mkdir(parents=True, exist_ok=True)
    m.InitDll()
    m.InitializeEmu(str(home.resolve()).encode(), None, None, True, True, True, True)
    m.Pause()
    m.SetEmulationFlag(CONSOLE_MODE, True)
    if for_comparison:
        configure_for_comparison(m, region)
    if not m.LoadRom(str(rom.resolve()).encode(), b""):
        raise SystemExit("LoadRom failed")
    m.InitializeDebugger()
    script_id = -1
    if lua is not None:
        script_id = m.LoadScript(lua_name.encode(), str(home.resolve()).encode(), lua, -1)
    if trace:
        opts = TraceLoggerOptions(
            True,
            False,
            False,
            b"",
            b"[PC,4h] A:[A,2h] X:[X,2h] Y:[Y,2h] S:[SP,2h] P:[P,h] "
            b"CYC:[CycleCount] SL:[Scanline] DOT:[Cycle] FR:[FrameCount]",
        )
        m.SetTraceOptions(CPU_NES, opts)
        m.StartLogTraceToFile(str(trace.resolve()).encode())
    m.SetEmulationFlag(MAXIMUM_SPEED, max_speed)
    began = time.monotonic()
    m.Resume()
    result = -1
    log = ""
    buf = ctypes.create_string_buffer(1 << 22)
    while time.monotonic() - began < seconds:
        time.sleep(0.05)
        if until is not None:
            m.GetScriptLog(script_id, buf, len(buf))
            log = buf.value.decode(errors="replace")
            if collect is not None:
                for line in log.splitlines():
                    key, _, text = line.partition(" ")
                    if key[:1] in ("L", "E") and text:
                        collect[key] = text
            if until in log:
                result = 0
                break
        if not m.IsRunning():
            result = m.GetStopCode()
            break
    if trace:
        m.StopLogTraceToFile()
    if script_id >= 0 and until is None:
        m.GetScriptLog(script_id, buf, len(buf))
        log = buf.value.decode(errors="replace")
    m.Stop()
    m.Release()
    return result, log, time.monotonic() - began


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("rom", type=Path)
    p.add_argument("--seconds", type=float, default=2.0, help="wall-clock timeout")
    p.add_argument("--trace", type=Path)
    p.add_argument("--lua", type=Path)
    p.add_argument("--home", type=Path, default=Path("mesen-home"))
    a = p.parse_args()
    result, log, wall = run_mesen(
        a.rom,
        lua=a.lua.read_bytes() if a.lua else None,
        lua_name=a.lua.name if a.lua else "script.lua",
        seconds=a.seconds,
        home=a.home,
        trace=a.trace,
    )
    if log:
        print(log)
    print(f"stop code {result} after {wall:.1f} s")
    return result


if __name__ == "__main__":
    raise SystemExit(main() & 0xFF)
