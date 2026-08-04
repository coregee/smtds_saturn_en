combat_result_label_vwf:
    tst     r6, r6
    bf      result_label_continuation

    mov     #0x5d, r0
    cmp/eq  r0, r7
    bt      result_label_life
    mov     #0x5c, r0
    cmp/eq  r0, r7
    bt      result_label_beads
    bra     result_label_fallback
    nop

result_label_continuation:
    mov     #0x4c, r0
    cmp/eq  r0, r7
    bt      result_label_suppress
    mov     #0x45, r0
    cmp/eq  r0, r7
    bt      result_label_suppress
    mov     #0x41, r0
    cmp/eq  r0, r7
    bt      result_label_suppress
    mov     #-0x32, r0
    extu.b  r0, r0
    cmp/eq  r0, r7
    bt      result_label_suppress
    mov     #0x75, r0
    cmp/eq  r0, r7
    bt      result_label_suppress
    mov     #0x46, r0
    cmp/eq  r0, r7
    bt      result_label_suppress
    bra     result_label_fallback
    nop

result_label_life:
    mov.l   =LIFE_STONES, r0
    bra     result_label_draw
    nop

result_label_beads:
    mov.l   =BEADS, r0

result_label_draw:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r0, r8
    mov     r4, r9
    mov     r5, r10
    ; Four 4bpp scanlines are 4 * (pixel stride / 2) = 2 * stride bytes.
    mov     r5, r0
    shll    r0
    add     r0, r9
    mov     #0, r11
    mov     #32, r12

result_label_loop:
    mov.b   @r8+, r13
    extu.b  r13, r13
    tst     r13, r13
    bt      result_label_done
    mov.l   =WIDTHS, r0
    mov     r13, r1
    mov.b   @(r0,r1), r14
    extu.b  r14, r14
    tst     r14, r14
    bt      result_label_done

    mov     r9, r4
    mov     r10, r5
    mov     r11, r6
    mov     r13, r7
    mov     #2, r0
    mov.l   r0, @-r15
    mov.l   =PIXEL, r0
    jsr     @r0
    nop
    add     #4, r15
    add     r14, r11
    dt      r12
    bf      result_label_loop

result_label_done:
    lds.l   @r15+, pr
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8

result_label_suppress:
    rts
    nop

result_label_fallback:
    mov.l   =STOCK, r0
    jmp     @r0
    nop
    .pool
