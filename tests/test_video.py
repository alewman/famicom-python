"""The window's colours: palettes and the 2C07's red/green emphasis swap."""

from __future__ import annotations

from famicom_python.video import load_palette


def test_swapped_emphasis_exchanges_red_and_green(tmp_path) -> None:
    # A 512-colour file whose entry i is (i >> 6, i & 63, 0): its emphasis bits on display.
    path = tmp_path / "index.pal"
    path.write_bytes(b"".join(bytes((i >> 6, i & 63, 0)) for i in range(512)))
    plain, swapped = load_palette(path), load_palette(path, swapped_emphasis=True)
    assert plain[0x40 | 0x20][0] == 1  # $2001 bit 5 -> the file's index bit 6
    assert swapped[0x40 | 0x20][0] == 2  # on the 2C07 it tints as the file's bit 7
    assert swapped[0x80 | 0x20][0] == 1
    assert swapped[0x100 | 0x20] == plain[0x100 | 0x20]  # blue stays
