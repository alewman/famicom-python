"""Changing FDS disks without a player: for scripted runs and the window's default.

Not part of the console. A player ejects the disk when a game asks for
another side and puts that side in; this does the same from what the
program does on the bus, as Mesen2's automatic insertion does:

- A game asking for another side polls the drive status ($4032) with the
  motor stopped, waiting for the disk to come out. After ``EJECT_POLLS`` such
  reads with no disk access for ``IDLE_FRAMES`` frames, the disk is ejected,
  and after ``SWAP_FRAMES`` frames side 0 goes back in as a placeholder.
- Before reading, the BIOS checks the disk with CheckDiskHeader ($E445): its
  pointer at $00-$01 names the 10 bytes of the disk ID it wants (licensee,
  game name, type, version, side, disk number, disk type, ...; $FF matches
  anything; FDS_BIOS.wiki). At that call the side whose disk info block
  matches is put in, if exactly one does.

It watches the bus through ``Board.bus_observers`` and reads the request from
console RAM, which a cartridge may not do (the connector rule), so it lives
here, beside the system, not in ``cartridge/fds.py``.
"""

from __future__ import annotations

from collections.abc import Callable

from .cartridge.fds import FDS
from .cartridge.fds_disk import blocks, fds_side
from .system import System

CHECK_DISK_HEADER = 0xE445
# A prompt to change sides waits as long as it takes; between the accesses of
# one load a game also checks the disk is in (Zelda's "please wait"), for up
# to a second or two. So be slow to decide.
EJECT_POLLS = 40
IDLE_FRAMES = 180
SWAP_FRAMES = 60


class AutoDisk:
    """Swap disk sides for ``system`` as its program asks for them."""

    def __init__(self, system: System, log: Callable[[str], None] | None = None) -> None:
        cartridge = system.cartridge
        if not isinstance(cartridge, FDS):
            raise TypeError("not a disk system")
        self.system = system
        self.fds = cartridge
        self.log = log or (lambda message: None)
        self.ids = [_disk_id(raw) for raw in cartridge.sides]
        self.polls = 0
        self.last_access = 0  # frame of the last disk transfer
        self.eject_frame: int | None = None
        system.board.bus_observers.append(self.observe)

    def observe(self, kind: str, address: int, value: int, t: int) -> None:
        if kind != "read":
            if address == 0x4025 and value & 0x01 and not value & 0x02:
                self._touched()  # the program started the motor: a transfer
            return
        frame = self.system.board.ppu.frame
        if address == 0x4032:
            if self.fds.side is not None and not self.fds.scanning:
                self.polls += 1
                if self.polls >= EJECT_POLLS and frame - self.last_access >= IDLE_FRAMES:
                    self._insert(None, "ejected")
                    self.eject_frame = frame
            elif self.fds.side is None and self.eject_frame is not None:
                if frame - self.eject_frame >= SWAP_FRAMES:
                    self._insert(0, "placeholder")
                    self.eject_frame = None
        elif address == CHECK_DISK_HEADER:
            wanted = bytes(self._peek(self._pointer() + i) for i in range(10))
            matches = [i for i, disk_id in enumerate(self.ids) if _matches(wanted, disk_id)]
            if len(matches) == 1 and matches[0] != self.fds.side:
                self._insert(matches[0], "asked for")
            self._touched()

    def _touched(self) -> None:
        self.polls = 0
        self.last_access = self.system.board.ppu.frame
        self.eject_frame = None

    def _insert(self, side: int | None, why: str) -> None:
        self.fds.insert(side)
        self.polls = 0
        self.log(f"FDS: {self.fds.side_name(side)} ({why})")

    def _pointer(self) -> int:
        ram = self.system.board.ram
        return ram[0] | ram[1] << 8

    def _peek(self, address: int) -> int:
        address &= 0xFFFF
        if address < 0x2000:
            return self.system.board.ram[address & 0x7FF]
        if 0x6000 <= address < 0xE000:
            return self.fds.prg_ram[address - 0x6000]
        if address >= 0xE000:
            return self.fds.bios[address - 0xE000]
        return 0xFF  # registers: treated as "any"


def _disk_id(raw: bytes | bytearray) -> bytes:
    """A side's disk ID: its disk info block's bytes after *NINTENDO-HVC*."""
    found = blocks(fds_side(raw))
    return bytes(found[0][15:25]) if found else bytes(10)


def _matches(wanted: bytes, disk_id: bytes) -> bool:
    return all(w == 0xFF or w == d for w, d in zip(wanted, disk_id, strict=True))
