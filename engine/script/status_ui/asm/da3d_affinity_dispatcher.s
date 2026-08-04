da3d_affinity_dispatcher:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    sts.l   pr, @-r15
    mov     r6, r12
    mov     r7, r13
    mov.l   =SELECTOR, r0
    mov.b   @r0, r0
    extu.b  r0, r0
    add     #-32, r0
    mov     #66, r1
    cmp/hs  r1, r0
    bt      da3d_affinity_fallback
    mov.l   =AFFINITY_TOKENS, r8
    tst     r0, r0
    bt      da3d_affinity_select_line
da3d_affinity_skip_record:
    mov.b   @r8+, r1
    tst     r1, r1
    bf      da3d_affinity_skip_record
    add     #-1, r0
    tst     r0, r0
    bf      da3d_affinity_skip_record
da3d_affinity_select_line:
    mov.l   @(28,r15), r0
    tst     r0, r0
    bt      da3d_affinity_compose
da3d_affinity_find_line:
    mov.b   @r8+, r0
    extu.b  r0, r0
    tst     r0, r0
    bt      da3d_affinity_empty
    cmp/eq  #30, r0
    bf      da3d_affinity_find_line

da3d_affinity_compose:
    add     #-32, r15
    mov     r15, r9
    mov     #0, r10
da3d_affinity_token:
    mov.b   @r8+, r0
    extu.b  r0, r0
    tst     r0, r0
    bt      da3d_affinity_draw
    cmp/eq  #30, r0
    bt      da3d_affinity_draw
    cmp/eq  #29, r0
    bt      da3d_affinity_comma
    cmp/eq  #31, r0
    bt      da3d_affinity_colon
    tst     r10, r10
    bt      da3d_affinity_word
    mov     #63, r1
    mov.b   r1, @r9
    add     #1, r9
da3d_affinity_word:
    add     #-1, r0
    mov.l   =WORD_OFFSETS, r1
    mov.b   @(r0,r1), r0
    extu.b  r0, r0
    mov.l   =WORD_POOL, r1
    add     r0, r1
da3d_affinity_copy_word:
    mov.b   @r1+, r0
    tst     r0, r0
    bt      da3d_affinity_word_done
    mov.b   r0, @r9
    add     #1, r9
    bra     da3d_affinity_copy_word
    nop
da3d_affinity_word_done:
    mov     #1, r10
    bra     da3d_affinity_token
    nop
da3d_affinity_comma:
    mov     #-27, r0
    bra     da3d_affinity_punctuation
    nop
da3d_affinity_colon:
    mov     #-42, r0
da3d_affinity_punctuation:
    mov.b   r0, @r9
    add     #1, r9
    mov     #63, r0
    mov.b   r0, @r9
    add     #1, r9
    mov     #0, r10
    bra     da3d_affinity_token
    nop

da3d_affinity_draw:
    cmp/eq  r15, r9
    bt      da3d_affinity_terminate
    mov     r9, r0
    add     #-1, r0
    mov.b   @r0, r0
    extu.b  r0, r0
    cmp/eq  #63, r0
    bf      da3d_affinity_terminate
    add     #-1, r9
da3d_affinity_terminate:
    mov     #0, r0
    mov.b   r0, @r9
    mov     r15, r4
    add     #32, r15
    mov.l   @(28,r15), r8
    mov.l   @(32,r15), r9
    mov.l   @(36,r15), r10
    add     #-32, r15
    mov     #32, r5
    mov     r12, r6
    mov     r13, r7
    mov.l   r10, @-r15
    mov.l   r9, @-r15
    mov.l   r8, @-r15
    mov.l   =FONT16_VWF, r0
    jsr     @r0
    nop
    add     #12, r15
    add     #32, r15
    bra     da3d_affinity_restore
    nop
da3d_affinity_empty:
    add     #-32, r15
    mov     r15, r9
    bra     da3d_affinity_draw
    mov     #0, r10
da3d_affinity_fallback:
    lds.l   @r15+, pr
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    mov.l   @r15+, r8
    mov.l   =STOCK, r0
    jmp     @r0
    nop
da3d_affinity_restore:
    lds.l   @r15+, pr
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8
    .pool
    .align 4
