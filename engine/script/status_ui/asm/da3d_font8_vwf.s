da3d_font8_vwf:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r4, r8
    mov     r6, r9
    mov     r7, r10
    mov.l   @(32,r15), r11
    mov.l   @(36,r15), r12
    mov.l   @(40,r15), r13
    mov     r5, r14
da3d_font8_loop:
    tst     r14, r14
    bt      da3d_font8_done
    mov.b   @r8, r1
    extu.b  r1, r1
    tst     r1, r1
    bt      da3d_font8_done
    mov     #0xfe, r0
    extu.b  r0, r0
    cmp/hs  r0, r1
    bt      da3d_font8_done
    mov     #63, r0
    cmp/hs  r0, r1
    bf      da3d_font8_done
    mov.w   =230, r0
    cmp/hs  r0, r1
    bt      da3d_font8_done
    bsr     da3d_font8_width
    nop
    tst     r2, r2
    bt      da3d_font8_done
    mov.b   @r8, r1
    extu.b  r1, r1

    mov     r10, r0
    tst     #1, r0
    bt      da3d_font8_draw
    mov.l   =FONT_BITMAP, r0
    mov     r1, r3
    shll2   r3
    shll    r3
    add     r3, r0
    mov     #8, r3
da3d_shift_right:
    mov.b   @r0, r1
    extu.b  r1, r1
    shlr    r1
    mov.b   r1, @r0
    add     #1, r0
    dt      r3
    bf      da3d_shift_right
da3d_font8_draw:
    mov.b   @r8, r4
    extu.b  r4, r4
    mov     r9, r5
    mov     r10, r6
    mov     r11, r7
    mov     r10, r0
    tst     #1, r0
    bt      da3d_font8_call
    add     #-1, r6
da3d_font8_call:
    mov.l   r13, @-r15
    mov.l   r12, @-r15
    mov.l   =GLYPH, r0
    jsr     @r0
    nop
    add     #8, r15
    mov     r10, r0
    tst     #1, r0
    bt      da3d_font8_advance
    mov.l   =FONT_BITMAP, r0
    mov.b   @r8, r1
    extu.b  r1, r1
    shll2   r1
    shll    r1
    add     r1, r0
    mov     #8, r3
da3d_shift_left:
    mov.b   @r0, r1
    extu.b  r1, r1
    shll    r1
    mov.b   r1, @r0
    add     #1, r0
    dt      r3
    bf      da3d_shift_left
da3d_font8_advance:
    mov.b   @r8, r1
    extu.b  r1, r1
    bsr     da3d_font8_width
    nop
    add     #1, r2
    add     r2, r10
    add     #1, r8
    add     #-1, r14
    bra     da3d_font8_loop
    nop
da3d_font8_done:
    lds.l   @r15+, pr
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8

da3d_font8_width:
    mov     #118, r0
    cmp/hs  r0, r1
    bf      da3d_font8_width_low
    add     #-128, r1
    bra     da3d_font8_width_ready
    add     #-22, r1
da3d_font8_width_low:
    add     #-63, r1
da3d_font8_width_ready:
    mov.l   =WIDTHS, r0
    mov.b   @(r0,r1), r2
    extu.b  r2, r2
    rts
    nop
    .pool
    .align 4
