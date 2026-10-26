"""Famicom Disk System disks: a ``.fds`` file's sides as the drive's head meets them.

FDS_file_format.wiki: a ``.fds`` file is an optional 16-byte header ("FDS",
$1A, the side count) and 65,500 bytes per side holding the blocks of
FDS_disk_format.wiki without their gaps or CRCs. The disk itself is one
serial stream: a gap of zeros before the first block (28,300 bits typical)
and between blocks (976 bits typical), each gap ended by a single 1 bit (a
byte $80, the bits going out least significant first), then the block and
its CRC-16/KERMIT (computed by the RP2C33 over the 1 bit and the block). The
drive model reads and writes that stream a byte at a time
(:class:`.fds.FDS`); :func:`raw_side` builds it from a ``.fds`` side and
:func:`fds_side` turns it back into one for a save.
"""

from __future__ import annotations

SIDE_BYTES = 65_500
HEADER = b"FDS\x1a"
VERIFY = b"*NINTENDO-HVC*"
MARK = 0x80  # the 1 bit that ends a gap
PREGAP = 28_300 // 8  # bytes of zeros before the first block (typical)
GAP = 976 // 8  # bytes of zeros between blocks (typical)

#: Block lengths without the CRC, by block code (FDS_disk_format.wiki); a file
#: data block (4) is 1 + the size in the file header before it.
BLOCK_LENGTHS = {1: 56, 2: 2, 3: 16}


def _crc_table() -> list[int]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
        table.append(crc)
    return table


CRC_TABLE = _crc_table()


def crc16(data: bytes | bytearray, crc: int = 0) -> int:
    """CRC-16/KERMIT (reflected 0x1021, initial 0), as the RP2C33 computes it."""
    for byte in data:
        crc = (crc >> 8) ^ CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def is_fds(data: bytes) -> bool:
    """A ``.fds`` file, with or without its header."""
    if data[:4] == HEADER:
        return True
    return len(data) >= SIDE_BYTES and len(data) % SIDE_BYTES == 0 and data[1:15] == VERIFY


def split_sides(data: bytes) -> list[bytes]:
    """The 65,500-byte sides of a ``.fds`` file; a short last side is padded with zeros."""
    if data[:4] == HEADER:
        data = data[16:]
    sides = [data[i : i + SIDE_BYTES] for i in range(0, len(data), SIDE_BYTES)]
    return [side.ljust(SIDE_BYTES, b"\0") for side in sides if side.strip(b"\0")]


def blocks(side: bytes) -> list[bytes]:
    """The blocks of a ``.fds`` side in order (without CRCs): the disk info and
    file amount blocks, then header and data pairs for as long as they follow
    (files past the file amount, "hidden" ones, included); the zeros after
    the last block are not a block."""
    found: list[bytes] = []
    pos, size = 0, 0
    while pos < len(side):
        code = side[pos]
        if not found:
            expected = 1
        elif len(found) == 1:
            expected = 2
        else:
            expected = 4 if found[-1][0] == 3 else 3
        if code != expected:
            break
        length = 1 + size if code == 4 else BLOCK_LENGTHS[code]
        if pos + length > len(side):
            break
        block = side[pos : pos + length]
        if code == 3:
            size = block[13] | block[14] << 8
        found.append(block)
        pos += length
    return found


def raw_side(side: bytes) -> bytearray:
    """A ``.fds`` side as the stream on the disk: gaps, marks, blocks and CRCs,
    then blank disk to the side's capacity (its 65,500 bytes plus the gaps,
    marks and CRCs its blocks occupy)."""
    found = blocks(side)
    raw = bytearray(PREGAP)
    for block in found:
        crc = crc16(block, crc16(bytes([MARK])))
        raw += bytes([MARK]) + block + bytes([crc & 0xFF, crc >> 8]) + bytes(GAP)
    capacity = PREGAP + SIDE_BYTES + len(found) * (3 + GAP)
    raw += bytes(max(0, capacity - len(raw)))
    return raw


def fds_side(raw: bytes | bytearray) -> bytes:
    """A disk stream back as a ``.fds`` side: each block found after a gap,
    without its mark and CRC, in order, padded with zeros to 65,500 bytes."""
    out = bytearray()
    pos, size, previous = 0, 0, 0
    while True:
        while pos < len(raw) and raw[pos] == 0:
            pos += 1
        if pos >= len(raw) or raw[pos] != MARK:
            break
        pos += 1
        code = raw[pos] if pos < len(raw) else 0
        if code == 4 and previous == 3:
            length = 1 + size
        elif code in BLOCK_LENGTHS:
            length = BLOCK_LENGTHS[code]
        else:
            break
        block = raw[pos : pos + length]
        if code == 3:
            size = block[13] | block[14] << 8
        out += block
        previous = code
        pos += length + 2  # the CRC
    return bytes(out[:SIDE_BYTES].ljust(SIDE_BYTES, b"\0"))
