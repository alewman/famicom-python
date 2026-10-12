// A board around Breaknes's PPUSim (gate-level RP2C02G, CC0) for co-simulation
// with famicom-python's CPU: see scripts/ppusim_board.py and docs/validation.md
// ("PPUSim as a judge"). Our code; PPUSim itself is fetched, never committed.
//
// The shim owns what sits on the PPU's side of the NES-001: the octal latch that
// holds AD0-7 on ALE, the cartridge's CHR (ROM or RAM) on PA13 = 0, and the
// 2 KiB CIRAM on PA13 = 1 with A10 from PA10 (vertical) or PA11 (horizontal).
// The CPU side is driven one master half-cycle at a time: R/W, RS0-2, /DBE and
// the data bus, with /INT read back.

#include "pch.h"

#include <cstring>
#include <vector>

using namespace BaseLogic;
using namespace PPUSim;

namespace {

struct Board {
    PPU ppu{Revision::RP2C02G};
    TriState in[(size_t)InputPad::Max]{};
    TriState out[(size_t)OutputPad::Max]{};
    uint8_t ext = 0, db = 0, ad = 0, ahi = 0;
    VideoOutSignal video{};
    uint8_t latch = 0;           // the octal latch (74LS373) on AD0-7
    std::vector<uint8_t> chr;
    bool chr_writable = false;
    int a10_bit = 11;            // 11: horizontal arrangement, 10: vertical
    uint8_t ciram[0x800]{};
    uint64_t half = 0;           // master half-cycles simulated
    uint8_t clk = 0;
    uint16_t pixels[256 * 240]{};

    uint16_t address() const { return (uint16_t)(((ahi & 0x3F) << 8) | latch); }

    uint8_t *cell(uint16_t a) {
        if (a & 0x2000) {
            int a10 = (a >> a10_bit) & 1;
            return &ciram[(a10 << 10) | (a & 0x3FF)];
        }
        return &chr[a % chr.size()];
    }

    // One master half-cycle: the CLK pin toggles, the chip settles, then the
    // memories answer the strobes it raised.
    void step() {
        in[(size_t)InputPad::CLK] = clk ? One : Zero;
        clk ^= 1;
        ppu.sim(in, out, &ext, &db, &ad, &ahi, video);
        if (out[(size_t)OutputPad::ALE] == One) latch = ad;
        if (out[(size_t)OutputPad::n_RD] == Zero) ad = *cell(address());
        if (out[(size_t)OutputPad::n_WR] == Zero) {
            uint16_t a = address();
            if ((a & 0x2000) || chr_writable) *cell(a) = ad;
        }
        half++;
    }
};

}  // namespace

extern "C" {

void *ppusim_new(const uint8_t *chr, int chr_len, int chr_writable, int vertical) {
    auto *b = new Board();
    b->chr.assign(chr, chr + (chr_len > 0 ? chr_len : 0x2000));
    if (chr_len <= 0) std::memset(b->chr.data(), 0, b->chr.size());
    b->chr_writable = chr_writable != 0;
    b->a10_bit = vertical ? 10 : 11;
    for (auto &x : b->in) x = One;
    b->in[(size_t)InputPad::RnW] = One;
    b->in[(size_t)InputPad::n_DBE] = One;
    b->ppu.SetRAWOutput(true);
    return b;
}

void ppusim_free(void *h) { delete (Board *)h; }

// Hold /RES low for `halves` half-cycles, then release it.
void ppusim_reset(void *h, int halves) {
    auto *b = (Board *)h;
    b->in[(size_t)InputPad::n_RES] = Zero;
    for (int i = 0; i < halves; i++) b->step();
    b->in[(size_t)InputPad::n_RES] = One;
}

// Run with the CPU interface idle (/DBE high).
void ppusim_run(void *h, uint64_t halves) {
    auto *b = (Board *)h;
    b->in[(size_t)InputPad::n_DBE] = One;
    for (uint64_t i = 0; i < halves; i++) b->step();
}

// One CPU access: `before` idle half-cycles, then /DBE low for `during` with
// R/W and RS0-2 set and, for a write, the data bus driven (with `early` the
// value the bus holds for the first `early_halves` of the window: the "early
// write" open-bus value, PPU_glitches.wiki). Returns the data bus at the end of
// the window (what the CPU latches at M2's fall).
int ppusim_access(void *h, int rnw, int reg, int value, int early, int early_halves,
                  int before, int during) {
    auto *b = (Board *)h;
    b->in[(size_t)InputPad::n_DBE] = One;
    for (int i = 0; i < before; i++) b->step();
    b->in[(size_t)InputPad::RnW] = rnw ? One : Zero;
    b->in[(size_t)InputPad::RS0] = (reg & 1) ? One : Zero;
    b->in[(size_t)InputPad::RS1] = (reg & 2) ? One : Zero;
    b->in[(size_t)InputPad::RS2] = (reg & 4) ? One : Zero;
    b->in[(size_t)InputPad::n_DBE] = Zero;
    for (int i = 0; i < during; i++) {
        if (!rnw) b->db = (uint8_t)(i < early_halves ? early : value);
        b->step();
    }
    int result = b->db;
    b->in[(size_t)InputPad::n_DBE] = One;
    b->in[(size_t)InputPad::RnW] = One;
    return result;
}

int ppusim_int(void *h) { return ((Board *)h)->out[(size_t)OutputPad::n_INT] == Zero; }
int ppusim_h(void *h) { return (int)((Board *)h)->ppu.GetHCounter(); }
int ppusim_v(void *h) { return (int)((Board *)h)->ppu.GetVCounter(); }
int ppusim_vbl(void *h) { return ((Board *)h)->ppu.Dbg_GetVBLFlag() == One; }
uint64_t ppusim_halves(void *h) { return ((Board *)h)->half; }
int ppusim_ciram(void *h, int index) { return ((Board *)h)->ciram[index & 0x7FF]; }
int ppusim_chr(void *h, int index) {
    auto *b = (Board *)h;
    return b->chr[index % b->chr.size()];
}
int ppusim_raw_video(void *h) { return ((Board *)h)->video.RAW.raw; }

}  // extern "C"
