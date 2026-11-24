<!-- SPDX-License-Identifier: MIT -->
# Third-party notices

famicom-python is MIT licensed (LICENSE). It contains no code from the GPL emulators its
documents cite (Mesen2 and MesenCE are run as closed boxes; see `docs/provenance.md` for the
rule and the check). Fetched references and test ROMs are not part of the repository and keep
their own terms, recorded per file in `scripts/pinned_files.json` and `scripts/pinned_repos.json`.

## MAME (BSD-3-Clause)

MAME's NES driver, Vs. System, PlayChoice-10, PPU and cartridge files named below are
BSD-3-Clause: the first line of each file, `// license:BSD-3-Clause`, checked on 2026-11-23 in
the pinned copies (`reference/mame-nes/`, MAME `e31391f`; `reference/src/mame/`, MAME
`f379cd0`). They were read as a permissive emulator's description of the hardware. Where a
table or a value was taken from them, the file holding it says so on its SPDX line
(`MIT AND BSD-3-Clause`) and the line below names the source; where only facts were read, the
file stays `MIT` and the fact is cited where it is used. In both cases MAME's notice is kept
here.

**Tables and values taken** (the files carry `MIT AND BSD-3-Clause`):

- `src/famicom_python/cartridge/namco.py`: the Vs. System's protection bytes, `VS_SEQUENCES`
  (the 32-byte answers of the chips on *Vs. Atari R.B.I. Baseball* and *Vs. T.K.O. Boxing*)
  and `VS_XEVIOUS` (*Vs. Super Xevious*'s four addresses and their answers), as MAME's
  `src/mame/nintendo/vsnes.cpp` holds them. Copyright Pierpaolo Prazzoli, Brad Oliver, Fabio
  Priuli.
- `src/famicom_python/machine.py`: the RC2C05-01's `$2002` identifier, `$1B`, which no
  document gives (its one game never reads it): MAME's choice in
  `src/devices/video/ppu2c0x.cpp`. Copyright Ernesto Corvi, Brad Oliver, Fabio Priuli.
- `src/famicom_python/supervisor.py`: the PlayChoice-10 BIOS files' names and SHA-1s
  (`BIOS_PROGRAMS`, `BIOS_CHARACTERS`, `BIOS_PROMS`) and the screen's resistor weights (`0x0E`,
  `0x1F`, `0x43`, `0x8F`), as MAME's `src/mame/nintendo/playch10.cpp` holds them (copyright
  Ernesto Corvi, Brad Oliver); the RP5H01's behaviour as MAME's `src/devices/machine/rp5h01.cpp`
  models it (copyright Nicola Salmoria).
- `src/famicom_python/peripherals.py`: the Subor Keyboard's matrix, `SUBOR_MATRIX`, as MAME's
  `src/devices/bus/nes_ctrl/suborkey.cpp` holds it. Copyright Fabio Priuli.
- `src/famicom_python/cartridge/waixing.py`: the GAL table of mappers 252/253, `WAIXING_GAL`,
  as MAME's `src/devices/bus/nes/vrc_clones.cpp` holds it. Copyright kmg.

**Facts read** (the files stay `MIT`; each fact cited where it is used):

- `src/famicom_python/vs.py`, `src/famicom_python/dual.py`, `src/famicom_python/playchoice.py`:
  the Vs. System's and the PlayChoice-10's port wiring, coin timing, panel and watchdog, as
  `vsnes.cpp` and `playch10.cpp` describe them.
- `src/famicom_python/peripherals.py`: the Turbo File (`src/devices/bus/nes_ctrl/turbofile.cpp`)
  and Exciting Boxing's bag (`src/devices/bus/nes_ctrl/konamibag.cpp`), copyright Fabio Priuli.
- Mappers whose behaviour was read in MAME's cartridge files (`mmc3_clones.cpp`,
  `multigame.cpp`, `cne.cpp`, `bootleg.cpp`, `kaiser.cpp`, `rcm.cpp`, `batlab.cpp`,
  `event.cpp`, and mappers 413, 418, 549, 555, 557), copyright Fabio Priuli, kmg and others
  named in each file's `copyright-holders:` line; `docs/mappers.md` cites each.
- `scripts/vs_images.py`, `scripts/pc10_images.py`: where each EPROM of a set lies and MAME's
  default DIP switches, read from `mame -listxml` (MAME run as a program).

The licence of those files:

```
Copyright (c) the copyright holders named above (MAME, https://www.mamedev.org)

Redistribution and use in source and binary forms, with or without modification, are permitted
provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of
   conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of
   conditions and the following disclaimer in the documentation and/or other materials provided
   with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to
   endorse or promote products derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## MAME's software list (CC0-1.0)

`src/famicom_python/cartridge/database.py` reads MAME's `hash/nes.xml` (CC0-1.0) where it is
installed; nothing from it is committed.
