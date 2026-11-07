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
import json
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
from .peripherals import (
    DEVICE_NAMES,
    FAMILY_BASIC_KEYBOARD,
    VAUS_FAMICOM,
    VAUS_NES,
    DataRecorder,
    ExpansionPads,
    FamilyBasicKeyboard,
    FamilyTrainer,
    FourScore,
    HoriTrack,
    KonamiHyperShot,
    MacroWinnersMouse,
    PowerPad,
    SnesController,
    SnesMouse,
    SuborKeyboard,
    SuborMouse,
    TurboFile,
    Vaus,
    YuxingMouse,
    Zapper,
)
from .ppu import DOTS, HEIGHT, WIDTH
from .system import System
from .video import load_palette, palette_for, to_rgb, write_png

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
F6          the reset button too (when Backspace is the keyboard's DEL)
Gamepads: the first two are players 1 and 2; on a Famicom a third and fourth
are players 3 and 4 through the expansion port (a four-player adapter), and
with a Four Score (--device four-score) on the NES as well.
Devices (--device, default the cartridge's from nes20db or its NES 2.0 header):
  Zapper      the mouse aims, left button fires, right button points off screen
  Vaus        the mouse's left-right is the knob, left button fires
  Power Pad / Family Trainer   keys 1 2 3 4 / Q W E R / A S D F are its rows
  Family BASIC Keyboard        the host keyboard types on it (pads: gamepads)
  Hyper Shot  each gamepad's A is Run, B is Jump
  Mice, Hori Track   the mouse (left and right buttons)
  Subor Keyboard     the host keyboard, PC layout
  Super NES pads     gamepads (shoulders are L and R); keys C V = A X, A S = L R
  Data Recorder      F9 plays the tape from its start, F10 records; again stops
                     (<rom>.tape); the Turbo File keeps turbo-file.sav per folder"""

# --device names: NES 2.0 expansion numbers (peripherals.py); "vaus" is the
# console's own version.
DEVICES = {
    "auto": None,
    "pads": 0x01,
    "four-score": 0x02,
    "famicom-four-players": 0x03,
    "zapper": 0x08,
    "two-zappers": 0x09,
    "power-pad": 0x0C,
    "family-trainer": 0x0E,
    "vaus": VAUS_NES,
    "hyper-shot": 0x12,
    "keyboard": FAMILY_BASIC_KEYBOARD,
}

# A Super NES pad's extra buttons on the keyboard: A, X, L, R.
SNES_KEYS = ((8, "K_c"), (9, "K_v"), (10, "K_a"), (11, "K_s"))

# The host keyboard on the Subor Keyboard (a PC-style layout; peripherals.SUBOR_MATRIX).
SUBOR_HOST_KEYS = {
    **{f"K_{c.lower()}": c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{f"K_{d}": d for d in "0123456789"},
    **{f"K_F{n}": f"F{n}" for n in range(1, 13)},
    **{f"K_KP{d}": f"KP{d}" for d in "0123456789"},
    "K_KP_MINUS": "KP-", "K_KP_PLUS": "KP+", "K_KP_MULTIPLY": "KP*", "K_KP_DIVIDE": "KP/",
    "K_KP_PERIOD": "KP.", "K_NUMLOCK": "NUMLOCK", "K_NUMLOCKCLEAR": "NUMLOCK",
    "K_MINUS": "-", "K_EQUALS": "=", "K_LEFTBRACKET": "[", "K_RIGHTBRACKET": "]",
    "K_BACKSLASH": "\\", "K_SEMICOLON": ";", "K_QUOTE": "'", "K_COMMA": ",",
    "K_PERIOD": ".", "K_SLASH": "/", "K_BACKQUOTE": "`", "K_RETURN": "ENTER",
    "K_SPACE": "SPACE", "K_BACKSPACE": "BACKSPACE", "K_TAB": "TAB",
    "K_CAPSLOCK": "CAPSLOCK", "K_LSHIFT": "LSHIFT", "K_RSHIFT": "LSHIFT",
    "K_LCTRL": "LCTRL", "K_LALT": "LALT", "K_INSERT": "INSERT", "K_DELETE": "DELETE",
    "K_HOME": "HOME", "K_END": "END", "K_PAGEUP": "PAGEUP", "K_PAGEDOWN": "PAGEDOWN",
    "K_PAUSE": "PAUSE", "K_UP": "UP", "K_DOWN": "DOWN", "K_LEFT": "LEFT", "K_RIGHT": "RIGHT",
}  # fmt: skip

MAT_KEYS = ("K_1", "K_2", "K_3", "K_4", "K_q", "K_w", "K_e", "K_r", "K_a", "K_s", "K_d", "K_f")

# The host keyboard on the Family BASIC Keyboard, by position on a US layout.
KEYBOARD_KEYS = {
    **{f"K_{c.lower()}": c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{f"K_{d}": d for d in "0123456789"},
    **{f"K_F{n}": f"F{n}" for n in range(1, 9)},
    "K_MINUS": "-", "K_EQUALS": "^", "K_BACKQUOTE": "YEN", "K_END": "STOP",
    "K_LEFTBRACKET": "@", "K_RIGHTBRACKET": "[", "K_RETURN": "RETURN",
    "K_SEMICOLON": ";", "K_QUOTE": ":", "K_BACKSLASH": "]", "K_RALT": "KANA",
    "K_COMMA": ",", "K_PERIOD": ".", "K_SLASH": "/", "K_RCTRL": "_",
    "K_LSHIFT": "LSHIFT", "K_RSHIFT": "RSHIFT", "K_LCTRL": "CTR", "K_LALT": "GRPH",
    "K_SPACE": "SPACE", "K_HOME": "CLR", "K_INSERT": "INS", "K_DELETE": "DEL",
    "K_BACKSPACE": "DEL", "K_PAUSE": "ESC",
    "K_UP": "UP", "K_DOWN": "DOWN", "K_LEFT": "LEFT", "K_RIGHT": "RIGHT",
}  # fmt: skip

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


def tape_path(rom: Path) -> Path:
    """The cassette a Data Recorder plays: level changes, as JSON."""
    return rom.with_name(rom.name + ".tape")


def turbo_file_path(rom: Path) -> Path:
    """The Turbo File's 8 KiB: one per folder, as the device moves between games."""
    return rom.with_name("turbo-file.sav")


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

    def __init__(self, pygame, rom: Path, machine: str, palette: Path | None, scale: int,
                 audio: bool, fullscreen: bool, auto_disk: bool = True,
                 device: int | None = None, vaus_low: int = 0x62) -> None:  # fmt: skip
        self.pg = pygame
        self.rom, self.machine_name = rom, machine
        self.device_choice, self.vaus_low = device, vaus_low
        self.peripheral: object | None = None
        self.auto_disk = auto_disk
        self.last_side = -1  # the FDS side the D key last took out
        self.system = self._power_on()
        timing = self.system.machine.timing
        self.palette = load_palette(palette or palette_for(timing), timing.swapped_emphasis)
        self.words = palette_words(self.palette)
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
        if self.machine_name == "auto":
            machine = System.machine_for(self.rom)
            self.machine_name = next(k for k, m in MACHINES.items() if m is machine)
            print(f"machine: {self.machine_name} ({machine.name})", file=sys.stderr)
        system = System.from_rom(self.rom, MACHINES[self.machine_name])
        system.board.set_sample_rate(SAMPLE_RATE)
        path = save_path(self.rom)
        if path.exists() and not system.cartridge.restore_battery(path.read_bytes()):
            print(f"{path}: not this cartridge's save; ignored", file=sys.stderr)
        machine = MACHINES[self.machine_name]
        device = self.device_choice
        if device is None and system.loaded is not None:
            device = system.loaded.image.board.expansion
        if device == VAUS_NES and machine.famicom_expansion_port:
            device = VAUS_FAMICOM
        self.peripheral = system.plug(device)
        if self.peripheral is not None:
            print(f"device: {DEVICE_NAMES[device]}", file=sys.stderr)
        self._load_storage(system)
        if system.board.expansion is None and machine.famicom_expansion_port:
            system.board.expansion = ExpansionPads()  # players 3 and 4
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
        expansion = self.system.board.expansion
        if isinstance(expansion, TurboFile):
            turbo_file_path(self.rom).write_bytes(bytes(expansion.data))
        tape = self._recorder()
        if tape is not None and tape.tape:
            tape_path(self.rom).write_text(json.dumps(tape.tape))

    def _load_storage(self, system: System) -> None:
        """The Turbo File's RAM and the tape, from beside the cartridge."""
        expansion = system.board.expansion
        path = turbo_file_path(self.rom)
        if isinstance(expansion, TurboFile) and path.exists():
            expansion.data[:] = path.read_bytes()[:0x2000].ljust(0x2000, b"\0")
        tape = self._recorder()
        path = tape_path(self.rom)
        if tape is not None and path.exists():
            tape.tape = [
                (int(position), int(level)) for position, level in json.loads(path.read_text())
            ]

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

    def _players(self) -> list[StandardController]:
        """The standard pads plugged in, in player order."""
        board = self.system.board
        device = self.peripheral
        if isinstance(device, FourScore):
            players = list(device.pads)
        else:
            players = [pad for pad in board.pads if isinstance(pad, StandardController)]
        if isinstance(board.expansion, ExpansionPads):
            players += board.expansion.pads
        return players

    def _devices(self) -> list:
        device = self.peripheral
        if device is None:
            return []
        return list(device) if isinstance(device, list) else [device]

    def _apply_inputs(self) -> None:
        pg = self.pg
        board = self.system.board
        devices = self._devices()
        pads = [self._controller(c) for c in self.controllers.values()]
        pads += [0] * (4 - len(pads))
        typing = any(isinstance(d, (FamilyBasicKeyboard, SuborKeyboard)) for d in devices)
        pads[0] |= 0 if typing else self._keyboard()
        for pad, buttons in zip(self._players(), pads, strict=False):
            pad.buttons = buttons
        board.microphone = not typing and bool(pg.key.get_pressed()[pg.K_m])
        if not devices:
            return
        keys = pg.key.get_pressed()
        x, y = pg.mouse.get_pos()
        dx, dy = pg.mouse.get_rel()
        left, _, right = pg.mouse.get_pressed()[:3]
        zapped = vaused = False
        snes = 0
        for device in devices:
            if isinstance(device, Zapper) and not zapped:  # one mouse: the first gun
                zapped = True
                device.aim = (x, y) if pg.mouse.get_focused() and not right else None
                device.trigger = bool(left)
            elif isinstance(device, Vaus):
                if not vaused:
                    vaused = True
                    knob = self.vaus_low + min(max(x, 0), WIDTH - 1) * 0xA0 // WIDTH
                    device.position = knob & 0xFF
                    device.fire = bool(left)
                else:  # a second Vaus: gamepad 2's left and right turn it, A fires
                    step = 3 * (bool(pads[1] & RIGHT) - bool(pads[1] & LEFT))
                    device.position = (device.position + step) & 0xFF
                    device.fire = bool(pads[1] & A)
            elif isinstance(device, (PowerPad, FamilyTrainer)):
                device.buttons = sum(
                    1 << n for n, name in enumerate(MAT_KEYS) if keys[getattr(pg, name)]
                )
            elif isinstance(device, FamilyBasicKeyboard):
                device.keys = {
                    name for key, name in KEYBOARD_KEYS.items() if keys[getattr(pg, key)]
                }
            elif isinstance(device, SuborKeyboard):
                device.keys = {
                    name for key, name in SUBOR_HOST_KEYS.items()
                    if hasattr(pg, key) and keys[getattr(pg, key)]
                }  # fmt: skip
            elif isinstance(device, KonamiHyperShot):
                device.buttons = sum(
                    (bool(pads[p] & A) << (2 * p)) | (bool(pads[p] & B) << (2 * p + 1))
                    for p in (0, 1)
                )
            elif isinstance(device, (SnesMouse, SuborMouse, MacroWinnersMouse, YuxingMouse)):
                device.move(dx, dy)
                device.left, device.right = bool(left), bool(right)
            elif isinstance(device, HoriTrack):
                device.move(dx, dy)
                device.pad.buttons = pads[0]
            elif isinstance(device, SnesController):
                controllers = list(self.controllers.values())
                buttons = pads[snes]
                if snes < len(controllers):
                    buttons |= self._snes_extra(controllers[snes])
                if snes == 0 and not typing:
                    buttons |= sum(1 << bit for bit, name in SNES_KEYS if keys[getattr(pg, name)])
                device.buttons = buttons
                snes += 1

    def _snes_extra(self, controller) -> int:
        """A Super NES pad's buttons beyond the NES's: A, X, L, R (bits 8-11)."""
        pg = self.pg
        return sum(
            1 << bit
            for bit, name in (
                (8, pg.CONTROLLER_BUTTON_B),
                (9, pg.CONTROLLER_BUTTON_Y),
                (10, pg.CONTROLLER_BUTTON_LEFTSHOULDER),
                (11, pg.CONTROLLER_BUTTON_RIGHTSHOULDER),
            )
            if controller.get_button(name)
        )

    def _recorder(self) -> DataRecorder | None:
        for device in self._devices():
            if isinstance(device, DataRecorder):
                return device
            if isinstance(device, FamilyBasicKeyboard):
                return device.recorder
        return None

    def _tape_key(self, record: bool) -> None:
        """F9: play the tape from its start (again: stop); F10: record over it."""
        tape = self._recorder()
        if tape is None:
            return
        if tape.mode != "stop":
            tape.stop()
            self.save()
            print("tape: stopped")
        elif record:
            tape.record()
            print("tape: recording")
        else:
            tape.play()
            print("tape: playing")

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
            if event.key == pg.K_F6 or (
                event.key == pg.K_BACKSPACE and not isinstance(self.peripheral, FamilyBasicKeyboard)
            ):
                self.system.reset()
            elif event.key == pg.K_F3:
                self.paused = not self.paused
                self.sound.clear()
            elif event.key == pg.K_F5:
                self.save()
                self.system = self._power_on()
                self.sound.clear()
            elif event.key == pg.K_d and isinstance(self.system.cartridge, FDS):
                self.change_disk()
            elif event.key in (pg.K_F9, pg.K_F10):
                self._tape_key(event.key == pg.K_F10)
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
    parser.add_argument(
        "--machine",
        choices=["auto", *sorted(MACHINES)],
        default="auto",
        help="the console (default: PAL or Dendy as the cartridge's header or nes20db says,"
        " else the Famicom)",
    )
    parser.add_argument(
        "--palette", type=Path, help="a .pal file (default: the machine's, from pally)"
    )
    parser.add_argument("--scale", type=int, default=3, help="window scale (default 3)")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument(
        "--manual-disk", action="store_true", help="FDS: change sides only with the D key"
    )
    parser.add_argument(
        "--device",
        choices=sorted(DEVICES),
        default="auto",
        help="what is plugged in besides the pads (default auto: the cartridge's, as"
        " nes20db or its NES 2.0 header says)",
    )
    parser.add_argument(
        "--vaus-low",
        type=lambda text: int(text, 0),
        default=0x62,
        help="the Vaus knob's value at the window's left edge (default 0x62, Arkanoid's;"
        " Arkanoid II wants 0x4D)",
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
        DEVICES[args.device], args.vaus_low,
    )  # fmt: skip
    try:
        frontend.run()
    finally:
        frontend.save()
        pygame.quit()
    return 0
