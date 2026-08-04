level_up_text_copy:
    mov     r15, r2
    mov     #WORD_COUNT, r13

level_up_text_copy_loop:
    mov.w   @r1+, r3
    mov.w   r3, @r2
    add     #2, r2
    dt      r13
    bf      level_up_text_copy_loop

    mov     #36, r13
