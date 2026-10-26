"""The Famicom Disk System: the RAM adapter (RP2C33) and its disk drive.

On the connector the RAM adapter is a cartridge (Family_Computer_Disk_System.wiki):
32 KiB of PRG-RAM at $6000-$DFFF, the 8 KiB BIOS at $E000-$FFFF, 8 KiB of
CHR-RAM, the nametable arrangement, and the RP2C33's registers at
$4020-$4033, and its sound at $4040-$4097 (``fds_sound.py``). Registers follow
User:TakuikaNinja/FDS_Registers.wiki, the hardware-verified rewrite of the
wiki's section (die scan analysis and Twin Famicom tests), where it differs.

The drive is a serial stream (``fds_disk.py``): the RP2C33 moves a byte
every 1,792 master-clock ticks (149 1/3 CPU cycles), setting the byte
transfer flag and, with $4025 D7, /IRQ. Reading, it waits with $4025 D6 for
the 1 bit that ends a gap and then hands over each byte with the CRC run
over them; writing, it sends $4024's byte (or, with $4025 D4, the CRC). The
head's travel is modelled from the wiki's description of the Quick Disk:
with the motor on and scanning it runs from the start of the side to its
end, where the drive reports not-ready and the head returns, a whole cycle
taking about 7 seconds. How long the drive takes to become ready after the
scan starts is not measured: Mesen2's 50,000 CPU cycles (a detector's
choice) here.
"""

from __future__ import annotations

from .banked import HORIZONTAL, VERTICAL, Banked
from .fds_disk import crc16, raw_side, split_sides
from .fds_sound import GAIN, FDSSound
from .ines import RomImage

BYTE_TICKS = 1792  # master-clock ticks per disk byte (FDS_Registers.wiki)
MASTER_HZ = 236_250_000 / 11  # NTSC: the RP2C33 is a Famicom part
SPIN_UP_BYTES = round(50_000 * 12 / BYTE_TICKS)  # scan start to ready (unmeasured)
REVOLUTION_BYTES = round(7.0 * MASTER_HZ / BYTE_TICKS)  # "about 7 seconds" a side
WATCHDOG_RELOAD = 3245  # CPU cycles the DRAM refresh watchdog allows (FDS_Registers.wiki)

# $4025 bits
SCAN, MOTOR_STOP, READ, ARRANGEMENT, CRC_SEND, CRC_ENABLE, DISK_IRQ = 1, 2, 4, 8, 16, 64, 128


class FDS(Banked):
    """The RAM adapter with a disk image in its drive (``image.misc``: the ``.fds`` data)."""

    snoops_cpu_reads = True  # the DRAM refresh watchdog counts every cycle's address
    counts_m2 = True
    expansion_audio = True

    def __init__(self, image: RomImage, cpu_cycle_ticks: int) -> None:
        super().__init__(image, cpu_cycle_ticks)
        # The adapter's memory is fixed, whatever the board description says.
        self.prg_ram = bytearray(0x8000)
        self.chr = bytearray(0x2000)
        self.chr_writable = True
        self.map_chr(0, 8, 0)  # unbanked (Banked's windows all start at 0)
        self.bios = image.prg
        self.sound = FDSSound()
        self.sides = [raw_side(side) for side in split_sides(image.misc)]
        self.written = [False] * len(self.sides)
        self.side: int | None = 0 if self.sides else None  # the side in the drive
        self.write_protected = False
        # The timer IRQ ($4020-$4022).
        self.reload = 0
        self.counter = 0
        self.timer_enabled = False
        self.timer_repeat = False
        self.timer_irq = False
        # $4023
        self.disk_io = False
        self.sound_io = False
        self.watchdog_enabled = False
        # The DRAM refresh watchdog: a 7-bit refresh counter, a 12-bit cycle timer.
        self.refresh = 0
        self.watchdog = 4095
        self.watchdog_irq = False
        self._prg_ram_cycle = False
        # The disk interface ($4024-$4026, $4030-$4033).
        self.control = 0x06
        self.write_latch = 0
        self.read_latch = 0
        self.external = 0x7F
        self.byte_flag = False
        self.crc = 0
        self.crc_error = False
        self.synced = False  # reading: the gap's 1 bit has gone by
        self.crc_sent = 0  # writing with $4025 D4: CRC bytes sent
        self._byte_ticks = 0
        # The head: None while returning or spinning up, else its byte on the side.
        self.head: int | None = None
        self.spin_up = SPIN_UP_BYTES
        self._apply_control()

    # -- the disk ----------------------------------------------------------

    def insert(self, side: int | None) -> None:
        """Put disk side ``side`` in the drive (None: eject)."""
        self.side = side
        self.head = None
        self.spin_up = SPIN_UP_BYTES

    @property
    def scanning(self) -> bool:
        """The motor turns and the head scans: $4025 D1 clear and D0 set, a disk in."""
        return self.side is not None and self.control & (SCAN | MOTOR_STOP) == SCAN

    def _byte(self) -> None:
        """One byte time of the serial interface."""
        control = self.control
        raw = self.sides[self.side] if self.side is not None else None
        value: int | None = None  # the byte under the head, if on the side
        position = -1  # where on the side, if within its data
        if raw is not None and self.scanning:
            if self.head is None:
                self.spin_up -= 1
                if self.spin_up <= 0:
                    self.head = 0
            else:
                head = self.head
                if head < len(raw):
                    value, position = raw[head], head
                else:
                    value = 0  # blank disk past the side's data
                self.head = head + 1 if head + 1 < max(len(raw), REVOLUTION_BYTES) else 0
        else:
            self.head = None
            self.spin_up = SPIN_UP_BYTES
        if control & READ:
            if value is None or not control & CRC_ENABLE:
                return
            if not self.synced:
                if value:  # the 1 bit ending the gap, counted in the CRC
                    self.synced = True
                    self.crc = crc16(bytes([value]))
                return
            self.read_latch = value
            self.crc = crc16(bytes([value]), self.crc)
            if control & CRC_SEND:
                self.crc_error = self.crc != 0
            self.byte_flag = True
        else:
            if not control & CRC_ENABLE:
                out = 0
            elif control & CRC_SEND:
                out = (self.crc >> 8 * self.crc_sent) & 0xFF if self.crc_sent < 2 else 0
                self.crc_sent += 1
            else:
                out = self.write_latch
                self.crc = crc16(bytes([out]), self.crc)
            if control & CRC_ENABLE:
                self.byte_flag = True
            if raw is not None and position >= 0 and not self.write_protected:
                raw[position] = out
                self.written[self.side] = True  # type: ignore[index]

    # -- the CPU side ------------------------------------------------------

    def cpu_read(self, address: int, t: int) -> int | None:
        if address >= 0xE000:
            return self.bios[address - 0xE000]
        if address >= 0x6000:
            self._prg_ram_cycle = True
            return self.prg_ram[address - 0x6000]
        if address == 0x4030:
            value = (
                self.timer_irq
                | self.watchdog_irq << 1
                | (self.control & ARRANGEMENT)
                | self.crc_error << 4
                | self.end_of_head << 6
                | self.byte_flag << 7
            )
            self.timer_irq = self.watchdog_irq = False
            self._update_irq()
            return value | 0x24 << 8  # bits 5 and 2 undriven
        if address == 0x4031:
            self.byte_flag = False
            self._update_irq()
            return self.read_latch
        if address == 0x4032:
            if self.side is None:
                status = 0x07
            else:
                ready = self.head is not None and self.scanning and not self.end_of_head
                status = (not ready) << 1 | self.write_protected << 2
            return status | 0xF8 << 8
        if address == 0x4033:
            battery = 0x80 if self.side is not None and not self.control & MOTOR_STOP else 0
            return battery | (self.external & 0x7F)
        if address >= 0x4040:
            return self.sound.read(address)
        return None

    @property
    def end_of_head(self) -> bool:
        """$4030 D6: the head past the side's data, on its way back."""
        head = self.head
        return head is not None and self.side is not None and head >= len(self.sides[self.side])

    def cpu_write(self, address: int, value: int, t: int) -> None:
        if address >= 0x6000:
            if address < 0xE000:
                self._prg_ram_cycle = True
                self.prg_ram[address - 0x6000] = value
            return
        if 0x4040 <= address <= 0x408A:
            self.sound.write(address, value)
            return
        if address == 0x4020:
            self.reload = (self.reload & 0xFF00) | value
        elif address == 0x4021:
            self.reload = (self.reload & 0x00FF) | value << 8
        elif address == 0x4023:
            self._write_io_enable(value)
        elif not self.disk_io:
            return  # $4022, $4024-$4026 are held in reset
        elif address == 0x4022:
            self.timer_repeat = bool(value & 1)
            self.timer_enabled = bool(value & 2)
            if self.timer_enabled:
                self.counter = self.reload
            else:
                self.timer_irq = False
        elif address == 0x4024:
            self.write_latch = value
            self.byte_flag = False
        elif address == 0x4025:
            self.control = value
            self._apply_control()
        elif address == 0x4026:
            self.external = value
        else:
            return
        self._update_irq()

    def _write_io_enable(self, value: int) -> None:
        self.disk_io = bool(value & 1)
        self.sound_io = bool(value & 2)
        self.sound.set_enabled(self.sound_io)
        self.watchdog_enabled = bool(value & 0x80)
        if not self.watchdog_enabled:
            self.watchdog_irq = False
        if not self.disk_io:
            # FDS_Registers.wiki "Disk I/O reset": $4025 = $06, the timer, the
            # byte transfer flag and the watchdog stopped and acknowledged,
            # $4026 = $7F.
            self.control = 0x06
            self._apply_control()
            self.timer_enabled = self.timer_irq = False
            self.byte_flag = False
            self.watchdog, self.refresh, self.watchdog_irq = 4095, 0, False
            self.external = 0x7F

    def _apply_control(self) -> None:
        control = self.control
        self.set_mirroring(HORIZONTAL if control & ARRANGEMENT else VERTICAL)
        if not self.scanning:
            # The drive follows the lines, not the byte clock: the BIOS's
            # StopMotor/StartMotor pulse lasts a few cycles and resets the scan.
            self.head = None
            self.spin_up = SPIN_UP_BYTES
        if not control & CRC_ENABLE:
            self.synced = False
            self.crc = 0
            self.crc_error = False
        if not control & CRC_SEND:
            self.crc_sent = 0

    def _update_irq(self) -> None:
        self.irq = (
            self.timer_irq
            or (self.watchdog_irq and self.watchdog_enabled)
            or (self.byte_flag and bool(self.control & DISK_IRQ))
        )

    def m2(self, t: int) -> None:
        if self.timer_enabled:
            if self.counter == 0:
                self.timer_irq = True
                self.counter = self.reload
                if not self.timer_repeat:
                    self.timer_enabled = False
            else:
                self.counter -= 1
        if self.disk_io:
            reload = False
            if not self._prg_ram_cycle:
                self.refresh = (self.refresh + 1) & 0x7F
                reload = self.refresh == 0
            if reload:
                self.watchdog = WATCHDOG_RELOAD
            elif self.watchdog:
                self.watchdog -= 1
            else:
                self.watchdog = 4095
                if self.watchdog_enabled:
                    self.watchdog_irq = True
        self._prg_ram_cycle = False
        self.audio_out.expansion = self.sound.clock() * GAIN
        self._byte_ticks += self.cpu_cycle_ticks
        if self._byte_ticks >= BYTE_TICKS:
            self._byte_ticks -= BYTE_TICKS
            self._byte()
        self._update_irq()
