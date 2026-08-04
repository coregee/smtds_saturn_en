maze_item_hook:
    mov.l   =TARGET, r0
    jsr     @r0
    nop
    bra     hook_ready
    nop
    .pool
hook_ready:
