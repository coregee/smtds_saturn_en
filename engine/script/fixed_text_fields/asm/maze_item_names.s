maze_found_item:
    mov     #0, r4
    bra     maze_item_message
    nop

maze_full_item:
    mov     #1, r4

maze_item_message:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r4, r13
    mov     r8, r14

    mov.l   =BUFFER, r8
    mov     r8, r1
    mov     #0, r0
    mov     #BUFFER_WORDS, r2
item_clear:
    mov.w   r0, @r1
    add     #2, r1
    dt      r2
    bf      item_clear

    tst     r13, r13
    bf      item_name
    mov.l   =FOUND_PREFIX, r1
    mov     #FOUND_WORDS, r2
copy_found_prefix:
    mov.w   @r1+, r0
    mov.w   r0, @r8
    add     #2, r8
    dt      r2
    bf      copy_found_prefix

item_name:
    mov     r14, r1
    add     #ITEM_FULL_NAME_OFFSET, r1
    mov.w   @r1, r0
    extu.w  r0, r0
    mov.l   =ITEM_BASE, r12
    add     r0, r12
    mov     #ITEM_NAME_LIMIT, r11

item_name_loop:
    mov.b   @r12+, r0
    extu.b  r0, r0
    mov     #-1, r1
    extu.b  r1, r1
    cmp/eq  r1, r0
    bt      item_name_done
    mov.l   =TOKEN_MAP, r1
    shll    r0
    mov.w   @(r0,r1), r0
    extu.w  r0, r0
    tst     r0, r0
    bt      item_name_done
    mov.w   r0, @r8
    add     #2, r8
item_name_next:
    dt      r11
    bf      item_name_loop

item_name_done:
item_suffix:
    tst     r13, r13
    bt      item_message_done
    mov.l   =FULL_SUFFIX, r1
    mov     #FULL_WORDS, r2
copy_full_suffix:
    mov.w   @r1+, r0
    mov.w   r0, @r8
    add     #2, r8
    dt      r2
    bf      copy_full_suffix

item_message_done:
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
