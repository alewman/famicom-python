"""A desktop window: play a cartridge with picture, sound, keyboard and gamepads.

    famicom-python play "Super Mario Bros. (World).zip"
    famicom-python play game.nes --machine famicom --scale 4

The only module that needs a library beyond 6502-python: pygame-ce (the
``frontend`` extra), for SDL's window, audio and game controllers. Run it on
PyPy. This is the reference board, correct before fast
(docs/handoff-brief.md "Size and speed"): it runs at a fraction of real time,
so the window shows every frame it makes and the sound plays at the
console's pitch with gaps between the frames' worth it has, rather than
stretched. Where the machine is fast enough, sound sets the pace (SDL's
audio thread drains a short queue and a frame runs when it runs short), as
in sms-python's frontend.

Saves: a cartridge's battery memory (or a UNROM 512's flash, or the disk
sides an FDS game wrote) is read from ``<rom>.sav`` beside the file at
power-on and written there on quit and on power cycle.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from array import array
from collections.abc import Callable
from pathlib import Path

from .cartridge.fds import FDS
from .fds_auto import AutoDisk
from .joypad import DOWN, LEFT, RIGHT, SELECT, START, UP, A, B, StandardController
from .machine import MACHINES
from .ppu import DOTS, HEIGHT, WIDTH
from .system import System
from .video import DEFAULT_PALETTE, load_palette, to_rgb, write_png

SAMPLE_RATE = 44_100
#: Frames of sound kept queued ahead of the speaker when the board keeps up.
BUFFER_FRAMES = 3

HELP = """\
Arrows      D-pad            Z / J   B          X / K   A
Right Shift Select           Enter   Start
M (hold)    the Famicom's microphone (player 2's pad, --machine famicom)
Backspace   the reset button F5      power cycle  F3   pause
Tab (hold)  fast forward (no sound)                F11  fullscreen
F12         screenshot (PNG)                       Esc  quit
D           FDS: eject the disk, then put the next side in (sides change by
            themselves unless --manual-disk)
Gamepads: the first two are players 1 and 2; on a Famicom a third and fourth
are players 3 and 4 through the expansion port (a four-player adapter)."""

KEYS = (  # (button, pygame key names)
    (UP, ("K_UP",)),
    (DOWN, ("K_DOWN",)),
    (LEFT, ("K_LEFT",)),
    (RIGHT, ("K_RIGHT",)),
    (B, ("K_z", "K_j")),
    (A, ("K_x", "K_k")),
    (SELECT, ("K_RSHIFT",)),
    (START, ("K_RETURN", "K_KP_ENTER")),
)


# -- conversions (pure, tested without pygame) --------------------------------------


def palette_words(palette: list[bytes]) -> list[int]:
    """Each 9-bit pixel value as an opaque little-endian BGRA word (0xFFRRGGBB)."""
    return [0xFF000000 | rgb[0] << 16 | rgb[1] << 8 | rgb[2] for rgb in palette]


def frame_bytes(picture, words: list[int]) -> bytes:
    """A frame of 9-bit values as BGRA bytes."""
    pixels = array("I", [words[value] for value in picture])
    if sys.byteorder == "big":
        pixels.byteswap()
    return pixels.tobytes()


def samples_s16(samples: list[float], gain: float = 1.5) -> bytes:
    """The board's output (after its analogue stage: centred, a full square near 0.15)
    as signed 16-bit mono."""
    scale = gain * 32767
    out = array("h", (max(-32768, min(32767, int(x * scale))) for x in samples))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def save_path(rom: Path) -> Path:
    return rom.with_name(rom.name + ".sav")


class SoundBuffer:
    """Bytes queued for SDL's audio thread, which calls :meth:`fill`."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._data)

    def push(self, data: bytes) -> None:
        with self._lock:
            self._data += data

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def fill(self, _device: object, stream: memoryview) -> None:
        """SDL's audio callback: copy what is queued, then silence."""
        size = len(stream)
        with self._lock:
            chunk = bytes(self._data[:size])
            del self._data[:size]
        stream[: len(chunk)] = chunk
        if len(chunk) < size:
            stream[len(chunk) :] = bytes(size - len(chunk))


# -- the window ---------------------------------------------------------------------


class Frontend:
    """One console in one window. ``pygame`` is imported by :func:`main`."""

    def __init__(self, pygame, rom: Path, machine: str, palette: Path, scale: int,
                 audio: bool, fullscreen: bool, auto_disk: bool = True) -> None:  # fmt: skip
        self.pg = pygame
        self.rom, self.machine_name = rom, machine
        self.auto_disk = auto_disk
        self.last_side = -1  # the FDS side the D key last took out
        self.words = palette_words(load_palette(palette))
        self.palette = load_palette(palette)
        self.system = self._power_on()
        self.scale, self.fullscreen = scale, fullscreen
        self.window = self._open_window()
        pygame.display.set_caption(f"{rom.stem} — famicom-python")
        self.sound = SoundBuffer()
        self.device = self._open_audio() if audio else None
        self.paused = False
        self.fast = False
        self.controllers: dict[int, object] = {}
        self._frames = 0
        self._fps_since = time.perf_counter()

    def _open_window(self):
        """A window whose surface is one frame; SDL scales it on the GPU (SCALED) and
        presents it at the display's refresh where it can (vsync)."""
        pg = self.pg
        flags = pg.SCALED | pg.RESIZABLE | (pg.FULLSCREEN if self.fullscreen else 0)
        try:
            surface = pg.display.set_mode((WIDTH, HEIGHT), flags, vsync=1)
        except pg.error:
            surface = pg.display.set_mode((WIDTH, HEIGHT), flags)
        if not self.fullscreen:
            pg.Window.from_display_module().size = (WIDTH * self.scale, HEIGHT * self.scale)
        return surface

    # -- console --------------------------------------------------------------------

    def _power_on(self) -> System:
        system = System.from_rom(self.rom, MACHINES[self.machine_name])
        system.board.set_sample_rate(SAMPLE_RATE)
        path = save_path(self.rom)
        if path.exists() and not system.cartridge.restore_battery(path.read_bytes()):
            print(f"{path}: not this cartridge's save; ignored", file=sys.stderr)
        if MACHINES[self.machine_name].famicom_audio_through_cart:
            board = system.board
            board.expansion_pads = [StandardController(), StandardController()]
        if isinstance(system.cartridge, FDS) and self.auto_disk:
            AutoDisk(system, print)
        return system

    def change_disk(self) -> None:
        """D: out with the disk; pressed again, the next side in."""
        fds = self.system.cartridge
        if not isinstance(fds, FDS) or not fds.sides:
            return
        if fds.side is not None:
            self.last_side = fds.side
            fds.insert(None)
        else:
            fds.insert((self.last_side + 1) % len(fds.sides))
        print(f"FDS: {fds.side_name(fds.side)}")

    def save(self) -> None:
        data = self.system.cartridge.battery_ram()
        if data is not None:
            save_path(self.rom).write_bytes(data)

    def _open_audio(self):
        from pygame._sdl2.audio import AUDIO_S16, AudioDevice
        from pygame._sdl2.sdl2 import INIT_AUDIO, init_subsystem

        try:
            init_subsystem(INIT_AUDIO)
            device = AudioDevice(
                devicename=None, iscapture=False, frequency=SAMPLE_RATE,
                audioformat=AUDIO_S16, numchannels=1, chunksize=512, allowed_changes=0,
                callback=self.sound.fill,
            )  # fmt: skip
        except Exception as error:  # pygame._sdl2's own error type; no device, no sound
            print(f"no sound: {error}", file=sys.stderr)
            return None
        device.pause(0)
        return device

    @property
    def _rate(self) -> float:
        timing = self.system.machine.timing
        return timing.master_hz / (timing.dot_divider * DOTS * timing.lines)

    @property
    def _frame_bytes(self) -> int:
        return int(SAMPLE_RATE / self._rate) * 2

    def run_frame(self) -> None:
        self._apply_inputs()
        self.system.run_frames(1)
        samples = self.system.take_samples()
        if self.device is not None and not self.fast:
            self.sound.push(samples_s16(samples))
        self._frames += 1

    # -- input ----------------------------------------------------------------------

    def _keyboard(self) -> int:
        pg = self.pg
        keys = pg.key.get_pressed()
        buttons = 0
        for button, names in KEYS:
            if any(keys[getattr(pg, name)] for name in names):
                buttons |= button
        return buttons

    def _controller(self, controller) -> int:
        pg = self.pg
        buttons = 0
        stick_x = controller.get_axis(pg.CONTROLLER_AXIS_LEFTX) / 32768
        stick_y = controller.get_axis(pg.CONTROLLER_AXIS_LEFTY) / 32768
        for button, name, stick in (
            (UP, pg.CONTROLLER_BUTTON_DPAD_UP, stick_y < -0.5),
            (DOWN, pg.CONTROLLER_BUTTON_DPAD_DOWN, stick_y > 0.5),
            (LEFT, pg.CONTROLLER_BUTTON_DPAD_LEFT, stick_x < -0.5),
            (RIGHT, pg.CONTROLLER_BUTTON_DPAD_RIGHT, stick_x > 0.5),
            (B, pg.CONTROLLER_BUTTON_A, False),  # the pad's lower face button
            (A, pg.CONTROLLER_BUTTON_B, False),
            (SELECT, pg.CONTROLLER_BUTTON_BACK, False),
            (START, pg.CONTROLLER_BUTTON_START, False),
        ):
            if stick or controller.get_button(name):
                buttons |= button
        return buttons

    def _apply_inputs(self) -> None:
        board = self.system.board
        pads = [self._controller(c) for c in self.controllers.values()]
        pads += [0] * (4 - len(pads))
        board.pads[0].buttons = self._keyboard() | pads[0]
        board.pads[1].buttons = pads[1]
        for pad, buttons in zip(board.expansion_pads, pads[2:], strict=True):
            if pad is not None:
                pad.buttons = buttons
        board.microphone = bool(self.pg.key.get_pressed()[self.pg.K_m])

    # -- events ---------------------------------------------------------------------

    def _handle(self, event) -> bool:
        """Handle one event; False to quit."""
        pg = self.pg
        if event.type == pg.QUIT:
            return False
        if event.type == pg.CONTROLLERDEVICEADDED:
            controller = pg._sdl2.controller.Controller(event.device_index)
            self.controllers[controller.id] = controller
        elif event.type == pg.CONTROLLERDEVICEREMOVED:
            self.controllers.pop(event.instance_id, None)
        elif event.type == pg.KEYDOWN:
            if event.key == pg.K_ESCAPE:
                return False
            if event.key == pg.K_BACKSPACE:
                self.system.reset()
            elif event.key == pg.K_F3:
                self.paused = not self.paused
                self.sound.clear()
            elif event.key == pg.K_F5:
                self.save()
                self.system = self._power_on()
                self.sound.clear()
            elif event.key == pg.K_d:
                self.change_disk()
            elif event.key == pg.K_F11:
                pg.display.toggle_fullscreen()
            elif event.key == pg.K_F12:
                self._screenshot()
            elif event.key == pg.K_TAB:
                self.fast = True
                self.sound.clear()
        elif event.type == pg.KEYUP and event.key == pg.K_TAB:
            self.fast = False
        return True

    def _screenshot(self) -> None:
        folder = Path("screenshots")
        folder.mkdir(exist_ok=True)
        path = folder / f"{self.rom.stem}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        write_png(path, to_rgb(self.system.board.ppu.picture, self.palette))
        print(f"saved {path}")

    # -- drawing --------------------------------------------------------------------

    def draw(self) -> None:
        pg = self.pg
        image = frame_bytes(self.system.board.ppu.picture, self.words)
        self.window.blit(pg.image.frombuffer(image, (WIDTH, HEIGHT), "BGRA"), (0, 0))
        pg.display.flip()
        now = time.perf_counter()
        if now - self._fps_since >= 1.0:
            fps = self._frames / (now - self._fps_since)
            state = " (paused)" if self.paused else " (fast)" if self.fast else ""
            pg.display.set_caption(f"{self.rom.stem} — {fps:.1f} fps{state} — famicom-python")
            self._frames, self._fps_since = 0, now

    # -- the loop -------------------------------------------------------------------

    def run(self, max_frames: int | None = None, on_frame: Callable | None = None) -> None:
        pg = self.pg
        clock = pg.time.Clock()
        target = BUFFER_FRAMES * self._frame_bytes
        shown = 0
        while True:
            for event in pg.event.get():
                if not self._handle(event):
                    return
            ran = False
            if not self.paused and (self.device is None or len(self.sound) < target):
                for _ in range(4 if self.fast else 1):
                    self.run_frame()
                ran = True
            if ran:
                self.draw()
                shown += 1
                if on_frame is not None:
                    on_frame(self)
                if max_frames is not None and shown >= max_frames:
                    return
            if self.device is None and not self.fast:
                clock.tick_busy_loop(self._rate)
            elif not ran:
                time.sleep(0.002)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="famicom-python play",
        description="Play an NES or Famicom cartridge in a window.",
        epilog=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "rom", type=Path, help="an iNES/NES 2.0 file, an FDS disk, or a .zip holding one"
    )
    parser.add_argument("--machine", choices=sorted(MACHINES), default="nes")
    parser.add_argument("--palette", type=Path, default=DEFAULT_PALETTE)
    parser.add_argument("--scale", type=int, default=3, help="window scale (default 3)")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument(
        "--manual-disk", action="store_true", help="FDS: change sides only with the D key"
    )
    args = parser.parse_args(argv)
    try:
        import pygame
        import pygame._sdl2.controller
    except ImportError:
        parser.error("the window needs pygame-ce: pip install 'famicom-python[frontend]'")
    if sys.implementation.name != "pypy":
        print("note: CPython runs this board several times slower than PyPy.", file=sys.stderr)
    # Not pygame.init(): its mixer would take the audio device the frontend opens.
    pygame.display.init()
    pygame._sdl2.controller.init()
    print(HELP)
    frontend = Frontend(
        pygame, args.rom, args.machine, args.palette, max(1, args.scale),
        not args.no_audio, args.fullscreen, not args.manual_disk,
    )  # fmt: skip
    try:
        frontend.run()
    finally:
        frontend.save()
        pygame.quit()
    return 0
