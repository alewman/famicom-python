/* perfect6502 (die-derived): an NMI that falls while RDY halts a read, as DMA
 * halts the 2A03's CPU (undocumented-behavior.md C30, validation.md milestone 6).
 * Loops: LDA $10 (= 0), then a taken same-page BEQ $0200 or a JMP $0200. Cycle
 * `cycle` of the BEQ/JMP (1 = its operand read, 2 = the next read) is held by
 * RDY for `halt` cycles on the 20th pass; /NMI falls k half-cycles after RDY
 * does. Result: the address of the interrupt sequence's first read: $0200 =
 * the NMI was taken right after the BEQ/JMP, $0202 = after the next LDA.
 * Build against the pinned checkout:
 *
 *   P=reference/src/perfect6502
 *   gcc -O2 -I$P -o p6502_nmi_dma scripts/perfect6502_nmi_dma.c \
 *       $P/netlist_sim.c $P/perfect6502.c && ./p6502_nmi_dma
 */
#include <stdio.h>
#include <string.h>
#include "types.h"
#include "netlist_sim.h"
#include "perfect6502.h"

enum { NODE_NMI = 1297, NODE_SYNC = 539, NODE_CLK0 = 1171, NODE_RW = 1156, NODE_RDY = 89 };

static int trial(int k, int halt, int jmp, int cycle) {
    memset(memory, 0, sizeof memory);
    memory[0xFFFC] = 0x00; memory[0xFFFD] = 0x02;
    memory[0xFFFA] = 0x00; memory[0xFFFB] = 0x03;
    memory[0x0300] = 0x40; /* RTI */
    memory[0x0200] = 0xA5; memory[0x0201] = 0x10;
    if (jmp) { memory[0x0202] = 0x4C; memory[0x0203] = 0x00; memory[0x0204] = 0x02; }
    else { memory[0x0202] = 0xF0; memory[0x0203] = 0xFC; }
    state_t *s = initAndResetChip();
    int fetches = 0, rdy_low_at = -1, rdy_high_at = -1, nmi_at = -1, prev = -1, result = -1;
    for (int h = 0; h < 4000 && result < 0; h++) {
        if (h == rdy_low_at) setNode(s, NODE_RDY, 0), recalcNodeList(s);
        if (h == rdy_high_at) setNode(s, NODE_RDY, 1), recalcNodeList(s);
        if (h == nmi_at) setNode(s, NODE_NMI, 0), recalcNodeList(s);
        step(s);
        if (!isNodeHigh(s, NODE_CLK0)) continue; /* sample each cycle in phi2 */
        unsigned short a = readAddressBus(s);
        int write = !isNodeHigh(s, NODE_RW);
        if (rdy_low_at < 0 && isNodeHigh(s, NODE_SYNC) && a == 0x0202 && ++fetches == 20) {
            rdy_low_at = h + 1 + 2 * (cycle - 1); /* in the phi1 of that cycle */
            rdy_high_at = rdy_low_at + 2 * halt;
            nmi_at = rdy_low_at + k;
        }
        if (nmi_at >= 0 && h > nmi_at && write && (a & 0xFF00) == 0x0100 && result < 0)
            result = prev;
        prev = a;
    }
    destroyChip(s);
    return result;
}

int main(void) {
    printf("k   BEQ c1 held  BEQ c2 held  JMP c1 held  JMP c2 held  JMP c1 free  JMP c2 free\n");
    for (int k = 0; k <= 12; k++)
        printf("%2d  %04X         %04X         %04X         %04X         %04X         %04X\n", k,
               trial(k, 4, 0, 1), trial(k, 4, 0, 2), trial(k, 4, 1, 1), trial(k, 4, 1, 2),
               trial(k, 0, 1, 1), trial(k, 0, 1, 2));
    return 0;
}
