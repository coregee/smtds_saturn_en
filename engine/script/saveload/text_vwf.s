text_vwf:
    mov     r4, r0
    extu.w  r0, r0
    mov.w   =PADDING_CODE, r1
    extu.w  r1, r1
    cmp/eq  r1, r0
    bt      tv_padding          ; relocated records use a zero-width sentinel
    mov.l   =text_scratch, r0
    mov.l   r4, @r0             ; preserve the glyph code outside the stack
    sts     pr, r1
    mov.l   r1, @(4,r0)         ; preserve our caller's return address
    mov.l   =ORIGINAL_BLITTER, r0
    jsr     @r0                 ; keep the stock blitter's stack arguments intact
    nop

    mov.l   =text_scratch, r0
    mov.l   @(4,r0), r1
    lds     r1, pr
    mov.l   @r0, r3
    extu.w  r3, r3
    mov.l   =WIDTH_LIMIT, r1
    cmp/hs  r1, r3
    bt      tv_stock
    mov     r3, r0
    mov.l   =width_table, r1
    mov.b   @(r0,r1), r0
    extu.b  r0, r0
    tst     r0, r0
    bf      tv_return
tv_stock:
    mov     #16, r0             ; unmapped Japanese cells remain fixed-width
tv_return:
    rts
    nop
tv_padding:
    rts
    mov     #0, r0
    .pool

dungeon_draw_entry:
    sts.l   pr, @-r15
    mov.l   =DRAW_CONTEXT, r0
    mov.l   r0, @-r15
    mov.l   r4, @-r15          ; preserve the caller's surface argument
    mov     #4, r0
    mov.l   r0, @-r15

    mov.l   =DUNGEON_INDEX, r0
    mov.b   @r0, r0
    extu.b  r0, r0
    mov     #DUNGEON_RECORD_BYTES, r1
    mul.l   r1, r0
    sts     macl, r0
    mov.l   =dungeon_table, r4
    add     r0, r4
    mov     #DUNGEON_RECORD_CELLS, r5
    mov     #-1, r6
    mov.w   =0x00a4, r7
    mov.l   =DRAW_TEXT, r0
    jsr     @r0
    nop

    add     #12, r15
    lds.l   @r15+, pr
    rts
    nop
    .pool
