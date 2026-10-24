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

// PPUSim's classes befriend this one for tests; the shim uses it to read
// internal signals into the trace (``inner``).
namespace PPUSimUnitTest {
class UnitTest {
public:
    static void inner(PPU &ppu, uint8_t out[5]) {
        auto one = [](TriState t) { return t == One ? 1 : 0; };
        out[0] = (uint8_t)(one(ppu.fsm.BLNK) | one(ppu.fsm.ZHPOS) << 1 | one(ppu.fsm.nVIS) << 2
                           | one(ppu.fsm.OBJ_READ) << 3 | one(ppu.wire.PCLK) << 4
                           | one(ppu.fsm.nFO) << 5 | one(ppu.wire.n_SPR0HIT) << 6
                           | one(ppu.fsm.n_EVAL) << 7);
        out[1] = (uint8_t)ppu.fifo->lane[0]->get_Counter();
        uint8_t active = 0, enabled = 0;
        for (int n = 0; n < 8; n++) {
            active |= (uint8_t)(one(ppu.fifo->lane[n]->ZH_FF.get()) << n);
            enabled |= (uint8_t)((ppu.fifo->lane[n]->n_EN == Zero ? 1 : 0) << n);
        }
        out[2] = active;
        out[3] = enabled;
        out[4] = (uint8_t)(one(ppu.wire.BLACK) | one(ppu.fsm.SCCNT) << 1
                           | (ppu.fifo->lane[0]->nZ_COL0 == Zero ? 1 : 0) << 2
                           | (ppu.fifo->lane[0]->nZ_COL1 == Zero ? 1 : 0) << 3
                           | one(ppu.fifo->lane[0]->LOAD) << 4 | one(ppu.fifo->lane[0]->STEP) << 5);
    }

    // The background attribute path (bgcol.cpp): BGC_SRBit keeps its latches
    // private and befriends no one, so read them through a mirror of its layout.
    struct SRBitView {
        DLatch in_latch;
        DLatch out_latch;
    };
    static TriState bit_out(BGC_SRBit &bit) {
        return reinterpret_cast<SRBitView &>(bit).out_latch.nget();
    }
    static void background(PPU &ppu, uint8_t out[8]) {
        auto one = [](TriState t) { return t == One ? 1 : 0; };
        BGCol &bg = *ppu.data_reader->bgcol;
        out[0] = (uint8_t)(one(bg.SRLOAD) | one(bg.STEP2) << 1 | one(bg.PD_SEL) << 2
                           | one(bg.NEXT) << 3 | one(bg.H01) << 4
                           | one(bit_out(bg.BGC2_SRBit1)) << 5 | one(bit_out(bg.BGC3_SRBit1)) << 6
                           | one(bg.STEP) << 7);
        uint8_t sr2 = 0, sr3 = 0, at = 0, sr0 = 0, lo2 = 0, lo1 = 0, hi1 = 0;
        for (int n = 0; n < 8; n++) {
            sr2 |= (uint8_t)(one(bit_out(bg.BGC2_SR1.sr[n])) << n);
            sr3 |= (uint8_t)(one(bit_out(bg.BGC3_SR1.sr[n])) << n);
            at |= (uint8_t)(one(bg.pd_latch[n].get()) << n);
            sr0 |= (uint8_t)(one(bit_out(bg.BGC1_SR2.sr[n])) << n);
            lo2 |= (uint8_t)(one(bit_out(bg.BGC0_SR2.sr[n])) << n);  // inverted plane
            lo1 |= (uint8_t)(one(bit_out(bg.BGC0_SR1.sr[n])) << n);  // inverted plane
            hi1 |= (uint8_t)(one(bit_out(bg.BGC1_SR1.sr[n])) << n);
        }
        out[1] = sr2;
        out[2] = sr3;
        out[3] = at;
        out[4] = (uint8_t)(one(ppu.wire.BGC[0]) | one(ppu.wire.BGC[1]) << 1
                           | one(ppu.wire.BGC[2]) << 2 | one(ppu.wire.BGC[3]) << 3
                           | one(ppu.wire.TVO[1]) << 4 | one(ppu.wire.THO[1]) << 5);
        out[5] = sr0;
        out[6] = (uint8_t)~lo2;
        out[7] = (uint8_t)~lo1;
        out[2] = hi1;  // (BGC3's shifter, bit 1 of the attribute, gives way)
    }
};
}  // namespace PPUSimUnitTest

namespace {

// One master half-cycle as the pins and counters show it, for comparisons
// with famicom-python's PPU (scripts/ppusim_compare.py).
struct TraceEntry {
    uint64_t half;
    uint16_t h, v;
    uint16_t address;   // PA0-13: the octal latch and PA8-13
    uint16_t video;     // RAW: eeellcccc, 0 outside the picture
    uint8_t pins;       // bit 0 ALE, 1 /RD low, 2 /WR low, 3 /INT low
    // Internal signals (PPUSimUnitTest::UnitTest::inner): 0 BLNK, ZHPOS,
    // nVIS, OBJ_READ, PCLK, nFO, /SPR0HIT, /EVAL; 1 lane 0's X counter;
    // 2 each lane's "active" flip-flop (ZH_FF); 3 each lane's shifter enable;
    // 4 BLACK, SCCNT, lane 0's pixel bits 0-1, LOAD, STEP.
    uint8_t inner[5];
    // The background path (PPUSimUnitTest::UnitTest::background): 0 SRLOAD,
    // STEP2, PD_SEL, NEXT, H01, the attribute latches' outputs (bits 0, 1),
    // STEP; 1 the attribute's bit-0 shifter; 3 the attribute byte latch;
    // 4 BGC0-3, TVO1, THO1; 5, 6 the high and low planes' second (current
    // tile) shifters, 2 and 7 their first (next tile) ones; bit n is the
    // pixel n dots on.
    uint8_t background[8];
};
static_assert(sizeof(TraceEntry) == 32);

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
    std::vector<TraceEntry> trace;   // filled while tracing (ppusim_trace)
    bool tracing = false;

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
        if (tracing) {
            TraceEntry e{};
            e.half = half;
            e.h = (uint16_t)ppu.GetHCounter();
            e.v = (uint16_t)ppu.GetVCounter();
            e.address = address();
            e.video = (uint16_t)(video.RAW.raw & 0x1FF);
            e.pins = (uint8_t)((out[(size_t)OutputPad::ALE] == One)
                               | (out[(size_t)OutputPad::n_RD] == Zero) << 1
                               | (out[(size_t)OutputPad::n_WR] == Zero) << 2
                               | (out[(size_t)OutputPad::n_INT] == Zero) << 3);
            PPUSimUnitTest::UnitTest::inner(ppu, e.inner);
            PPUSimUnitTest::UnitTest::background(ppu, e.background);
            trace.push_back(e);
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
// Start (clearing) or stop recording a TraceEntry per half-cycle.
void ppusim_trace(void *h, int on) {
    auto *b = (Board *)h;
    if (on) b->trace.clear();
    b->tracing = on != 0;
}
uint64_t ppusim_trace_len(void *h) { return ((Board *)h)->trace.size(); }
const void *ppusim_trace_data(void *h) { return ((Board *)h)->trace.data(); }
// Secondary ("temp") OAM, 32 bytes, as the evaluation left it.
int ppusim_temp_oam(void *h, int index) {
    return ((Board *)h)->ppu.Dbg_TempOAMReadByte((size_t)(index & 31));
}
int ppusim_raw_video(void *h) { return ((Board *)h)->video.RAW.raw; }

}  // extern "C"
