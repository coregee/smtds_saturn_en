maze_message_display:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    sts.l   pr, @-r15
    mov     r4, r8
    mov     r5, r9
    mov     r6, r10
    mov     r7, r11
    mov.l   =MAPPING_TABLE, r12
    mov     #MAPPING_COUNT, r13

mapping_loop:
    mov.l   @r12+, r0
    cmp/eq  r10, r0
    bt      mapping_found
    add     #4, r12
    dt      r13
    bf      mapping_loop
    mov.l   =BUFFER, r0
    cmp/eq  r10, r0
    bt      compose_message
    bra     call_original
    nop

mapping_found:
    mov.l   @r12, r10

compose_message:
    mov     r10, r4
    mov.l   =COMPOSITOR, r0
    jsr     @r0
    nop
    mov.l   =ROW, r10

call_original:
    mov     r8, r4
    mov     r9, r5
    mov     r10, r6
    mov     r11, r7
    mov.l   =ORIGINAL, r0
    jsr     @r0
    nop
    lds.l   @r15+, pr
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8
    .pool
