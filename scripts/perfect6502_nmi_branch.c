/* perfect6502 (die-derived): when is an NMI taken around a taken same-page
 * branch, against a JMP of the same cycle shape? (validation.md, milestone 6;
 * undocumented-behavior.md C29.) Build against the pinned checkout:
 *
 *   P=reference/src/perfect6502
 *   gcc -O2 -I$P -o p6502_nmi_branch scripts/perfect6502_nmi_branch.c \
 *       $P/netlist_sim.c $P/perfect6502.c && ./p6502_nmi_branch
 * /NMI is pulled low k half-cycles after the BEQ/JMP opcode
 * fetch (SYNC high, address $0202) and held; the result is the address the
 * interrupt sequence's first (dummy) read uses: $0200 = taken after the
 * BEQ/JMP, $0202 = after the next LDA. */
#include <stdio.h>
#include <string.h>
#include "types.h"
#include "netlist_sim.h"
#include "perfect6502.h"

enum { NODE_NMI = 1297, NODE_SYNC = 539, NODE_CLK0 = 1171, NODE_RW = 1156 };

static int trial(int jmp, int k) {
    memset(memory, 0, sizeof memory);
    memory[0xFFFC] = 0x00; memory[0xFFFD] = 0x02;
    memory[0xFFFA] = 0x00; memory[0xFFFB] = 0x03;
    memory[0x0300] = 0x40; /* RTI */
    memory[0x0200] = 0xA5; memory[0x0201] = 0x10;           /* LDA $10 (= 0) */
    if (jmp) { memory[0x0202] = 0x4C; memory[0x0203] = 0x00; memory[0x0204] = 0x02; }
    else     { memory[0x0202] = 0xF0; memory[0x0203] = 0xFC; } /* BEQ $0200 */
    state_t *s = initAndResetChip();
    int fetches = 0, armed = -1, prev_addr = -1, result = -1;
    for (int h = 0; h < 4000 && result < 0; h++) {
        step(s);
        int phi2 = isNodeHigh(s, NODE_CLK0);
        if (armed >= 0 && h == armed) setNode(s, NODE_NMI, 0), recalcNodeList(s);
        if (!phi2) continue;            /* sample each cycle in phi2 */
        unsigned short a = readAddressBus(s);
        int write = !isNodeHigh(s, NODE_RW);
        if (armed < 0 && isNodeHigh(s, NODE_SYNC) && a == 0x0202 && ++fetches == 20)
            armed = h + k;
        if (armed >= 0 && h > armed && write && (a & 0xFF00) == 0x0100 && result < 0)
            result = prev_addr;
        prev_addr = a;
    }
    destroyChip(s);
    return result;
}

int main(void) {
    printf("k(half-cycles after the BEQ/JMP fetch)  BEQ    JMP\n");
    for (int k = 1; k <= 10; k++)
        printf("%3d                                     %04X   %04X\n", k, trial(0, k), trial(1, k));
    return 0;
}
