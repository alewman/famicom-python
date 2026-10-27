"""Run a cartridge headless: ``python -m famicom_python ROM [--frames N]``.

``famicom-python play ROM`` opens a window instead (frontend.py, pygame-ce).

Prints how the cartridge was identified, runs it, and reports what a test ROM
says: blargg's $6000 text if present, else the first nametable as text.
``--png`` saves the last frame; ``--wav`` saves the sound of the whole run.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from array import array

from .machine import MACHINES
from .system import System
from .testrom import SIGNATURE, blargg_text, peek, run_blargg, screen_text
from .video import load_palette, palette_for, to_rgb, write_png


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["play"]:
        from .frontend import main as play

        return play(argv[1:])
    parser = argparse.ArgumentParser(prog="famicom-python", description=__doc__.splitlines()[0])
    parser.add_argument("rom", help="an iNES/NES 2.0 file, an FDS disk, or a .zip holding one")
    parser.add_argument(
        "--machine",
        choices=["auto", *sorted(MACHINES)],
        default="nes",
        help="the console (default nes; auto: as the cartridge's header or nes20db says)",
    )
    parser.add_argument("--frames", type=int, default=600, help="frames to run (default 600)")
    parser.add_argument(
        "--blargg", action="store_true", help="run to blargg's $6000 result instead of --frames"
    )
    parser.add_argument("--png", help="save the last frame as a PNG")
    parser.add_argument("--wav", help="save the run's audio as a 16-bit mono WAV")
    parser.add_argument(
        "--palette", help="a 64- or 512-colour .pal file (default: the machine's, from pally)"
    )
    args = parser.parse_args(argv)

    machine = System.machine_for(args.rom) if args.machine == "auto" else MACHINES[args.machine]
    system = System.from_rom(args.rom, machine)
    loaded = system.loaded
    assert loaded is not None
    board = loaded.image.board
    print(
        f"mapper {board.mapper}.{board.submapper}, mirroring {board.mirroring}, "
        f"PRG {len(loaded.image.prg) // 1024} KiB, CHR {len(loaded.image.chr) // 1024} KiB "
        f"({loaded.source})"
    )
    for line in loaded.disagreements:
        print(f"  disagreement: {line}")
    if loaded.mame:
        print(f"  MAME: {loaded.mame.get('software')} {loaded.mame.get('pcb', '')}")

    start = time.perf_counter()
    if args.blargg:
        result = run_blargg(system)
        status = "no result" if result.status is None else f"status {result.status}"
        print(f"{status}\n{result.text}")
    else:
        if args.wav:
            samples: list[float] = []
            for _ in range(args.frames):
                system.run_frames(1)
                samples += system.take_samples()
            write_wav(args.wav, samples, system.board.apu.sample_rate)
            print(f"{len(samples):,} samples written to {args.wav}")
        else:
            system.run_frames(args.frames)
        if bytes(peek(system, 0x6001 + i) for i in range(3)) == SIGNATURE:
            print(f"$6000 = {peek(system, 0x6000):02X}\n{blargg_text(system)}")
        else:
            print(screen_text(system))
    wall = time.perf_counter() - start
    print(f"{system.cycles:,} CPU cycles, {system.instructions:,} instructions, {wall:.1f} s")
    if args.png:
        timing = machine.timing
        palette = load_palette(args.palette or palette_for(timing), timing.swapped_emphasis)
        write_png(args.png, to_rgb(system.board.ppu.picture, palette))
        print(f"frame {system.board.ppu.frame} written to {args.png}")
    return 0


def write_wav(path: str, samples: list[float], rate: int) -> None:
    """Samples (about -1.0 to 1.0 after the analogue stage) as 16-bit PCM, clipped."""
    pcm = array("h", (max(-32768, min(32767, round(sample * 32767))) for sample in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


if __name__ == "__main__":
    sys.exit(main())
