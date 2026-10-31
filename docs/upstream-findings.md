# Findings for other projects

What this work found in the projects it leans on, how sure we are, and whether
anyone has been told. Nothing here is posted without the owner's approval of the
exact text, and posts name the model that wrote them. "Evidence" uses
[validation.md](validation.md)'s tiers: a finding counts only where something
above the project in question says so.

## Reported

| Project | Where | What | State (checked 2026-10-30) |
| --- | --- | --- | --- |
| Breaknes | #529 | PPUSim's `$2002` bit 7 inverted | fixed upstream (#530) |
| Breaknes | #535 | Temp (OAM2) counter misses its last step at H=321 | open, no reply |
| Breaknes | #536 | `$2004` in sprite evaluation's OAM2 write cycles | open, no reply |
| Breaknes | #537 | the I/O latch never decays | open, no reply |
| Breaknes | #538 | the H decoder sees VB and BLNK a dot late | open, no reply |
| Breaknes | #533, #534, #196, #475 | comments with findings | open |

Each project's AI policy is checked by the owner before anything further goes out.

## Mesen2: not reported

Against `b9fa69d`, 2.1.1, which is the end of SourMesen/Mesen2: that repository is
archived, and development moved to
[nesdev-org/MesenCE](https://github.com/nesdev-org/MesenCE) (2.2.1 and on). MesenCE is built here (`reference/build-mesence`, `MESEN_LIB`), run as a
binary only; its results are below as they come in. `scripts/mesen2-detector-fixes.patch` holds the
fixes we carry; that file is GPL-3.0 as a patch to Mesen2.

**MesenCE's CONTRIBUTING.md (read 2026-10-30) rules out sending these as code**:
"AI-generated code is prohibited", all submissions must be MIT-compatible and not
based on GPL code, and GitHub issues are off, so the route to the team needs
finding. Our patches are AI-written and GPL-derived: they must not be submitted.
Anything we send is a report, with evidence and a test ROM, by a route the
project accepts, and a person decides whether to send it.

"On MesenCE" is `4b8a196`, unpatched, with the same frames and settings as the
sweeps (`MESEN_LIB`).

| Finding | Evidence | On MesenCE |
| --- | --- | --- |
| A DMC rate written in the timer's reload cycle is the one it reloads with | AccuracyCoin "DMC Reload Timing" (hardware key) | **still fails** |
| PAL VBL race at (241, 1): `$2002` reads the flag set | PPUSim's 2C07, all 40 phases (validation.md, milestone 10) | **still differs** on *Bayou Billy*, *Burai Fighter*, *Guerrilla War*, *Bigfoot*, *Blue Shadow* |
| Mapper 224 has no GNROM mode: *Sanguo Fengyun* loops on a blank screen | the page and the game (C57) | **still differs** |
| Mapper 163: an older model boots the wrong bank | the page; the titles appear on the board (C54) | **still differs**, 3 of 4 dumps sampled |
| Mapper 195: a write to a CHR-ROM bank selects the RAM by the bank's number | the page's `CHRB~`, and the games: *Tianshi Zhi Yi 2*, *Zuqiu Xiaojiang* reach their scenes on the board and stay black there | **still differs** |
| AccuracyCoin's ALE + Read, Hybrid Addresses, Frozen OAM2 Increment | hardware keys; the board passes all three | **still fails**, known to its leaderboard |
| A taken same-page branch delays NMI as it delays IRQ | perfect6502 (die), C29 | not tested: no ROM isolates it |

Fixed or moot on MesenCE, so nothing to report: `$4015` bit 5 and the internal bus (the test
passes); the single-pixel differences on 59, 62, 112, 134, 215, 216, 219 and *Chiyonofuji*,
and 513's *Mei Shaonu*, all now identical to the board, so those were Mesen2's; Bandai FCG
(6 dumps identical). 172's power-on state was never a Mesen matter: it agreed
all along, and the gap is the wiki's. 115's older model does not show: 8 of 9 dumps
identical. Coolboy (268) remains to be looked at: 8 of 11 identical.

MesenCE matches the board less well than our patched Mesen2 on some small things (*100 Man
Dollar Kid*, *Blue Shadow* line counts, *Racermate*), which may be the patches
or its four AccuracyCoin failures: not diagnosed, and not findings.

**Not findings yet**: Mesen2 blank on 27, 304, 513, 519, 313.3 and *Super
Hang-On*, cause unknown, each may be a header or harness matter. N163 summing is a
choice the wiki itself mentions. C48 and the other open entries have no answer.

## NESdev wiki: not reported

Most rest on what a game does, not on hardware; an edit should say so.

| Page | What it lacks | Evidence |
| --- | --- | --- |
| Mapper 42 | submapper 2's `$8000`/`$8001` registers | both *Green Beret* dumps (C65) |
| Mapper 530 | A3 stands in for A12 | the game, MAME (C66) |
| Mapper 112 | the arrangement powers on 0, whatever the header says | the game (C67) |
| Mapper 123 | D3 of `$5800` is a bank line | *Earthworm Jim 2* (C64) |
| Mapper 221 | A6 is PRG A18 | NTDEC 400-in-1 (C63) |
| Mapper 172 | Invert powers on set | *Venice Beach Volleyball* (C56) |
| Mappers 170, 216, 238, 244 | registers: the pages name only games | the games, MAME for three (C68, C69) |
| Mapper 258 | the protection table, row 7 at power-on | MAME, the games boot |
| Mapper 446 | the state before a mapper is chosen; `$5003` on submapper 3 | the games (C70) |
| Mappers 252, 253 | the GAL that moves the RAM | MAME, *Shenhua Jian Yun* (C71) |
| Taito X1-005, X1-017 | the words of `$7EF6` D0 contradict the pins | C47 |
| Mapper 286 | the CHR banks are 2 KiB, not 8 | 10 dumps (C55) |

## Others

- **MAME**: 222 is marked unsupported with a guessed IRQ; the forum's schematic reading
  (t=12654) and the code here run both dumps' known boards. Low priority.
- **Breaknes APUSim**: `$4015` bits 0-3 do not reach its 6502 on our stub board, which
  may be the cause: check further before saying anything (undocumented-behavior.md,
  open item 2).
- **Visual 2C02**: wrong in the sprite overflow scan, through its `spr_d` conflict hack.
