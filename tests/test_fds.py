"""The FDS RAM adapter and disk model on synthetic disks: statements of the
model (``cartridge/fds.py``), not judges; the judges are the test disks of
``tests/test_fds_test_roms.py``. No BIOS needed: a blank one stands in."""

from __future__ import annotations

from famicom_python.cartridge.fds import FDS, SPIN_UP_BYTES
from famicom_python.cartridge.fds_disk import (
    GAP,
    MARK,
    PREGAP,
    QD_SIDE_BYTES,
    SIDE_BYTES,
    VERIFY,
    blocks,
    crc16,
    disk_sides,
    fds_side,
    is_fds,
    is_qd,
    raw_side,
)
from famicom_python.cartridge.fds_sound import MASTER, FDSSound
from famicom_python.cartridge.ines import BoardInfo, RomImage
from famicom_python.fds_auto import AutoDisk
from famicom_python.machine import MACHINES
from famicom_python.system import System

TICKS = 12  # master ticks per CPU cycle


def side_with_one_file(payload: bytes = b"\xa5" * 32) -> bytes:
    info = bytes([1]) + VERIFY + bytes(56 - 15)
    amount = bytes([2, 1])
    header = bytes([3, 0, 0]) + b"FILENAME" + bytes([0, 0x60, len(payload), 0, 0])
    data = bytes([4]) + payload
    return (info + amount + header + data).ljust(SIDE_BYTES, b"\0")


def adapter(side: bytes | None = None) -> FDS:
    image = RomImage(
        b"", b"", bytes(0x2000), b"", side or side_with_one_file(), BoardInfo(20), False
    )
    return FDS(image, TICKS)


def cycles(fds: FDS, count: int) -> None:
    for _ in range(count):
        fds.cpu_read(0x0000, 0)  # a cycle outside PRG-RAM: it refreshes
        fds.m2(0)


def test_crc_is_kermit() -> None:
    assert crc16(b"123456789") == 0x2189


def test_a_side_round_trips_through_the_disk_stream() -> None:
    side = side_with_one_file()
    assert [block[0] for block in blocks(side)] == [1, 2, 3, 4]
    raw = raw_side(side)
    assert raw[:PREGAP] == bytes(PREGAP) and raw[PREGAP] == MARK
    info = raw[PREGAP + 1 : PREGAP + 57]
    assert crc16(bytes([MARK]) + info + raw[PREGAP + 57 : PREGAP + 59]) == 0
    assert raw[PREGAP + 59 : PREGAP + 59 + GAP] == bytes(GAP)
    assert fds_side(raw) == side


def test_timer_irq_with_reload_zero_fires_at_once_and_repeats() -> None:
    fds = adapter()
    fds.cpu_write(0x4023, 0x83, 0)
    fds.cpu_write(0x4020, 0, 0)
    fds.cpu_write(0x4021, 0, 0)
    fds.cpu_write(0x4022, 0x03, 0)  # enabled, repeat
    cycles(fds, 1)
    assert fds.irq and fds.timer_enabled
    fds.cpu_read(0x4030, 0)  # acknowledges
    assert not fds.timer_irq
    cycles(fds, 1)
    assert fds.timer_irq  # every cycle, as the wiki says


def test_timer_counts_reload_plus_one_cycles_and_stops_without_repeat() -> None:
    fds = adapter()
    fds.cpu_write(0x4023, 0x83, 0)
    fds.cpu_write(0x4020, 10, 0)
    fds.cpu_write(0x4021, 0, 0)
    fds.cpu_write(0x4022, 0x02, 0)
    cycles(fds, 10)
    assert not fds.timer_irq
    cycles(fds, 1)
    assert fds.timer_irq and not fds.timer_enabled


def test_disabling_disk_io_stops_and_acknowledges_the_timer() -> None:
    fds = adapter()
    fds.cpu_write(0x4023, 0x83, 0)
    fds.cpu_write(0x4022, 0x03, 0)
    cycles(fds, 1)
    fds.cpu_write(0x4023, 0x82, 0)
    assert not fds.timer_irq and not fds.timer_enabled and fds.control == 0x06
    fds.cpu_write(0x4022, 0x02, 0)  # ignored while disk I/O is off
    assert not fds.timer_enabled


def test_watchdog_fires_on_the_4096th_cycle_without_refresh() -> None:
    """From reset (4095) to its underflow: the count FDS-4030D1-Addr's first
    return address, $67FF, pins on hardware."""
    fds = adapter()
    fds.cpu_write(0x4023, 0x83, 0)
    for _ in range(4095):
        fds.cpu_read(0x6000, 0)  # PRG-RAM: no refresh
        fds.m2(0)
        assert not fds.watchdog_irq
    fds.cpu_read(0x6000, 0)
    fds.m2(0)
    assert fds.watchdog_irq and fds.irq
    assert fds.cpu_read(0x4030, 0) & 0x02  # and the read acknowledges it
    assert not fds.watchdog_irq


def read_block(fds: FDS) -> tuple[list[int], bool]:
    """Start the motor, wait for ready, then read the first block as the BIOS
    does: set $4025 D6 inside the gap, take bytes on the transfer flag, set D4
    after the first CRC byte, and report $4030's CRC error after the second."""
    fds.cpu_write(0x4023, 0x83, 0)
    fds.cpu_write(0x4025, 0x2E, 0)  # StopMotor: scan reset
    fds.cpu_write(0x4025, 0x2D, 0)  # motor on, scanning, read mode
    while fds.cpu_read(0x4032, 0) & 0x02:
        cycles(fds, 1)
    cycles(fds, 150 * 100)  # well into the pre-gap
    fds.cpu_write(0x4025, 0x6D, 0)  # CRC enable: wait for the gap's end
    got: list[int] = []
    while len(got) < 1 + 55 + 2:
        cycles(fds, 1)
        if fds.byte_flag:
            got.append(fds.cpu_read(0x4031, 0))
            if len(got) == 57:
                fds.cpu_write(0x4025, 0x7D, 0)  # CRC control before the last byte
    return got, bool(fds.cpu_read(0x4030, 0) & 0x10)


def test_reading_a_block_gives_its_bytes_and_a_good_crc() -> None:
    side = side_with_one_file()
    got, crc_error = read_block(adapter(side))
    assert bytes(got[:56]) == side[:56]
    assert not crc_error


def test_a_damaged_block_fails_its_crc() -> None:
    fds = adapter()
    fds.sides[0][PREGAP + 10] ^= 0xFF
    _, crc_error = read_block(fds)
    assert crc_error


def test_a_stop_pulse_shorter_than_a_byte_resets_the_scan() -> None:
    fds = adapter()
    fds.cpu_write(0x4023, 0x83, 0)
    fds.cpu_write(0x4025, 0x2D, 0)
    cycles(fds, 150 * (SPIN_UP_BYTES + 500))
    assert fds.head is not None and fds.head > 400
    fds.cpu_write(0x4025, 0x2E, 0)  # StopMotor
    fds.cpu_write(0x4025, 0x2F, 0)
    fds.cpu_write(0x4025, 0x2D, 0)  # StartMotor, all within a few cycles
    assert fds.head is None


# -- the sound (fds_sound.py) --------------------------------------------


def sound(**registers: int) -> FDSSound:
    unit = FDSSound()
    unit.set_enabled(True)
    for address, value in registers.items():
        unit.write(int(address[1:], 16), value)
    return unit


def test_loopys_mod_example_gives_a_wave_pitch_of_one() -> None:
    """pitch 1, counter 50, gain 62: "about 0.4Hz wave tick rate" (p232662)."""
    unit = sound(r4082=1, r4083=0, r4084=0x80 | 62, r4085=50, r4087=0x80)
    before = unit.accumulator
    unit._tick()
    assert unit.accumulator - before == 1


def test_unmodulated_pitch_steps_the_wave_by_pitch_times_64() -> None:
    unit = sound(r4082=0x34, r4083=0x02, r4084=0x80, r4085=0, r4087=0x80)
    unit._tick()
    assert unit.accumulator == 0x234 * 0x40


def test_mod_table_entries_step_twice_and_reset_counts() -> None:
    unit = sound(r4087=0x80)
    for entry in (1, 4) + (0,) * 30:
        unit.write(0x4088, entry)
    unit.write(0x4087, 0x40)  # running, a carry every tick
    steps = []
    for _ in range(4):
        unit._tick()
        steps.append(unit.mod_counter)
    assert steps == [1, 2, 0, 0]  # +1 twice, then reset twice


def test_master_volume_follows_the_ladder() -> None:
    assert MASTER == (1.0, 2 / 3, 1 / 2, 2 / 5)


def test_volume_takes_effect_at_wave_position_zero() -> None:
    unit = sound(r4089=0x80)
    for i in range(64):
        unit.write(0x4040 + i, 63)
    unit.write(0x4089, 0)
    unit.write(0x408A, 0xFF)
    unit.write(0x4080, 0x80 | 20)
    unit.write(0x4082, 0)
    unit.write(0x4083, 0x01)  # running (D7 clear), pitch $100
    unit.clock()
    assert unit.out_volume == 20  # position 0: latched
    unit.accumulator = 5 << 18
    unit.write(0x4080, 0x80 | 30)
    unit.clock()
    assert unit.out_volume == 20  # not at position 0: held
    unit.accumulator = 0
    unit.clock()
    assert unit.out_volume == 30


def test_audio_reset_holds_the_channel() -> None:
    unit = sound(r4080=0x80 | 40, r4085=10)
    unit.accumulator = 7 << 18
    unit.set_enabled(False)
    assert (unit.accumulator, unit.mod_counter, unit.volume.gain) == (0, 0, 0)
    unit.write(0x4085, 5)
    assert unit.mod_counter == 0  # $4085 is not mapped while reset


# -- saves and disk changes -------------------------------------------------


def two_sides() -> bytes:
    side_a = bytearray(side_with_one_file())
    side_b = bytearray(side_with_one_file(b"\x5a" * 16))
    side_b[0x15] = 1  # side number: B
    return bytes(side_a + side_b)


def test_written_sides_round_trip_through_the_save() -> None:
    fds = adapter(two_sides())
    assert fds.battery_ram() is None  # nothing written: no save
    raw = fds.sides[1]
    data_at = PREGAP + 1 + 56 + 2 + GAP + 1 + 2 + 2 + GAP + 1 + 16 + 2 + GAP + 1 + 1
    raw[data_at] = 0x77  # the file's first byte, as the drive would write it
    assert fds_side(raw) != two_sides()[SIDE_BYTES:]  # it landed in the file's data
    fds.written[1] = True
    save = fds.battery_ram()
    assert save is not None and save[:4] == b"FDSW" and save[4] == 1
    fresh = adapter(two_sides())
    assert fresh.restore_battery(save)
    assert fds_side(fresh.sides[1]) == fds_side(raw) and fresh.sides[0] == fds.sides[0]
    assert fresh.battery_ram() == save  # restored sides stay written


def test_a_foreign_save_is_refused() -> None:
    fds = adapter(two_sides())
    assert not fds.restore_battery(b"not a save")
    assert not fds.restore_battery(b"FDSW\x01\x05" + bytes(SIDE_BYTES))  # no side 5


def test_auto_disk_puts_in_the_side_the_bios_asks_for() -> None:
    system = System(adapter(two_sides()), MACHINES["famicom"])
    auto = AutoDisk(system)
    ram = system.board.ram
    ram[0], ram[1] = 0x00, 0x03  # CheckDiskHeader's pointer: $0300
    wanted = bytearray(b"\xff" * 10)
    wanted[6] = 1  # side B
    ram[0x300:0x30A] = wanted
    auto.observe("read", 0xE445, 0, 0)
    assert system.cartridge.side == 1


def test_clearing_d6_drops_a_byte_flag_left_from_writing() -> None:
    """Writing leaves the transfer flag set at each byte; clearing $4025 D6
    must drop it, or the next read's IRQ fires on a stale byte (Zelda's save)."""
    fds = adapter()
    fds.cpu_write(0x4023, 0x83, 0)
    fds.cpu_write(0x4025, 0x69, 0)  # write mode, D6 set, motor on, scanning
    cycles(fds, 150 * 4)
    assert fds.byte_flag
    fds.cpu_write(0x4025, 0x2D, 0)  # read mode, D6 clear
    assert not fds.byte_flag


def test_a_qd_side_reads_as_its_fds_side_with_its_stored_crcs() -> None:
    side = side_with_one_file()
    qd = bytearray()
    for block in blocks(side):
        crc = crc16(block, crc16(bytes([MARK])))
        qd += block + bytes([crc & 0xFF, crc >> 8])
    qd = bytes(qd.ljust(QD_SIDE_BYTES, b"\0"))
    assert is_qd(qd) and not is_fds(qd)
    assert disk_sides(qd) == [raw_side(side)]
    damaged = bytearray(qd)
    damaged[56] ^= 0xFF  # block 1's stored CRC, kept as it is
    raw = disk_sides(bytes(damaged))[0]
    assert raw[PREGAP + 1 + 56] == qd[56] ^ 0xFF
