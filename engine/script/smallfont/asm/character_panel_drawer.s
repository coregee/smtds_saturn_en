; The NORMCOM, COMBAT, and MAZE party panels pass direct CHARNAME records as
; r4=string, r5=bitmap, r6=palette.  Record zero is the live player codename
; and must keep using the ordinary eight-byte path.  Resolve the other five
; fixed records to the generated full English pool before drawing, so
; over-capacity names such as Rei Reiho are not forced through the untranslated
; eight-byte source field.
character_panel_vwf:
    mov     r4, r0
    mov.l   =CHAR_FIRST, r1
    cmp/hs  r1, r0
    bf      character_panel_fallback
    mov.l   =CHAR_END, r1
    cmp/hs  r1, r0
    bt      character_panel_fallback
    mov.l   =CHAR_BASE, r1
    sub     r1, r0
    mov     r0, r2
    mov     #7, r1
    and     r1, r2
    tst     r2, r2
    bf      character_panel_fallback
    shlr2   r0
    shlr    r0
    shll    r0
    mov.l   =OFFSETS, r1
    mov.w   @(r0,r1), r0
    extu.w  r0, r0
    mov.l   =POOL, r1
    add     r1, r0

    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r0, r8
    mov     r5, r9
    mov     r6, r10
    mov     #0, r11
    mov     #32, r12
character_panel_loop:
    mov.b   @r8+, r13
    extu.b  r13, r13
    tst     r13, r13
    bt      character_panel_done
    mov.l   =WIDTHS, r0
    mov     r13, r1
    mov.b   @(r0,r1), r14
    extu.b  r14, r14
    tst     r14, r14
    bt      character_panel_done
    mov     r11, r0
    add     r14, r0
    mov     #80, r1
    cmp/hi  r1, r0
    bt      character_panel_done
    mov     r9, r4
    mov.w   =STRIDE, r5
    mov     r11, r6
    mov     r13, r7
    mov.l   r10, @-r15
    mov.l   =PIXEL, r0
    jsr     @r0
    nop
    add     #4, r15
    add     r14, r11
    dt      r12
    bf      character_panel_loop
character_panel_done:
    lds.l   @r15+, pr
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8

character_panel_fallback:
    mov.l   =FALLBACK, r0
    jmp     @r0
    nop
    .pool
    .align 4
