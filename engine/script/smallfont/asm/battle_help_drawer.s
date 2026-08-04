battle_help_packed_vwf:
    mov.l   @r15, r0
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r4, r8
    mov     r5, r9
    mov     r6, r10
    mov     r7, r11
    mov     r0, r12
    mov     #0, r13

    mov     r11, r14
    shlr8   r14
    mov     #8, r0
    cmp/hs  r0, r14
    bf      battle_help_raw
    mov.w   =PACKED_LIMIT, r0
    cmp/hs  r0, r14
    bt      battle_help_raw

    add     #-8, r14
    bsr     battle_help_latin
    nop
    mov     r11, r14
    extu.b  r14, r14
    tst     r14, r14
    bt      battle_help_done
    add     #-8, r14
    bsr     battle_help_latin
    nop
    bra     battle_help_done
    nop

battle_help_raw:
    mov     r11, r14
    bsr     battle_help_draw
    nop
    bra     battle_help_done
    nop

battle_help_latin:
    tst     r14, r14
    bf      battle_help_draw
    mov.w   =SPACE_CODE, r14

battle_help_draw:
    sts.l   pr, @-r15
    mov     r8, r4
    mov     r9, r5
    mov     r10, r6
    add     r13, r6
    mov     r14, r7
    mov.l   r12, @-r15
    mov.l   =DRAWER, r0
    jsr     @r0
    nop
    add     #4, r15
    add     r0, r13
    lds.l   @r15+, pr
    rts
    nop

battle_help_done:
    mov     r13, r0
    lds.l   @r15+, pr
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8
    .pool
