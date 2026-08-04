; Proportional FONT8 labels for the equipment action and comparison panels.
; @...@ values are supplied from equipment_ui.json by patch.py.

equip_draw_labels_vwf:
    mov     #4, r0
    cmp/eq  r0, r5
    bt      label_recommend
    mov     #3, r0
    cmp/eq  r0, r5
    bt      label_unequip
    mov.l   =STOCK_DRAW, r0
    jmp     @r0
    nop

label_recommend:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r6, r9
    mov     r7, r10
    @RECOMMEND_X_ADJUST@
    mov.l   @(0x20,r15), r11
    @RECOMMEND_Y_ADJUST@
    mov.l   =S_RECOMMEND, r8
    bsr     label_draw_one
    nop

    mov     #0, r9
    mov.l   =S_ST, r8
    mov     #@BASE_0_X@, r10
    mov     #@BASE_0_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_SWORD_ATTACK, r8
    mov     #@DERIVED_0_X@, r10
    mov     #@DERIVED_0_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_IN, r8
    mov     #@BASE_1_X@, r10
    mov     #@BASE_1_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_SWORD_ACCURACY, r8
    mov     #@DERIVED_1_X@, r10
    mov     #@DERIVED_1_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_MA, r8
    mov     #@BASE_2_X@, r10
    mov     #@BASE_2_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_GUN_ATTACK, r8
    mov     #@DERIVED_2_X@, r10
    mov     #@DERIVED_2_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_VI, r8
    mov     #@BASE_3_X@, r10
    mov     #@BASE_3_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_GUN_ACCURACY, r8
    mov     #@DERIVED_3_X@, r10
    mov     #@DERIVED_3_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_AG, r8
    mov     #@BASE_4_X@, r10
    mov     #@BASE_4_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_DEFENSE, r8
    mov     #@DERIVED_4_X@, r10
    mov     #@DERIVED_4_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_LU, r8
    mov     #@BASE_5_X@, r10
    mov     #@BASE_5_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_EVASION, r8
    mov     #@DERIVED_5_X@, r10
    mov     #@DERIVED_5_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_MAGIC_POWER, r8
    mov     #@DERIVED_6_X@, r10
    mov     #@DERIVED_6_Y@, r11
    bsr     label_draw_one
    nop
    mov.l   =S_MAGIC_EFFECT, r8
    mov     #@DERIVED_7_X@, r10
    mov     #@DERIVED_7_Y@, r11
    bsr     label_draw_one
    nop
    bra     labels_done
    nop

label_unequip:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov     r6, r9
    mov     r7, r10
    @UNEQUIP_X_ADJUST@
    mov.l   @(0x20,r15), r11
    @UNEQUIP_Y_ADJUST@
    mov.l   =S_UNEQUIP, r8
    bsr     label_draw_one
    nop

labels_done:
    lds.l   @r15+, pr
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    rts
    mov.l   @r15+, r8

label_draw_one:
    sts.l   pr, @-r15
    mov     #16, r12
label_loop:
    mov.b   @r8+, r14
    extu.b  r14, r14
    mov     #0xff, r0
    extu.b  r0, r0
    cmp/eq  r0, r14
    bt      label_one_done
    mov.l   =WIDTHS, r0
    mov     r14, r1
    mov.b   @(r0,r1), r1
    extu.b  r1, r1
    mov     r14, r4
    mov     r9, r5
    mov     r10, r6
    add     r1, r10
    mov     r11, r7
    mov.l   =GLYPH, r0
    jsr     @r0
    nop
    dt      r12
    bf      label_loop
label_one_done:
    lds.l   @r15+, pr
    rts
    nop
    .pool
    .align 4

S_RECOMMEND:      .byte @S_RECOMMEND@
S_UNEQUIP:        .byte @S_UNEQUIP@
S_ST:             .byte @S_ST@
S_IN:             .byte @S_IN@
S_MA:             .byte @S_MA@
S_VI:             .byte @S_VI@
S_AG:             .byte @S_AG@
S_LU:             .byte @S_LU@
S_SWORD_ATTACK:   .byte @S_SWORD_ATTACK@
S_SWORD_ACCURACY: .byte @S_SWORD_ACCURACY@
S_GUN_ATTACK:     .byte @S_GUN_ATTACK@
S_GUN_ACCURACY:   .byte @S_GUN_ACCURACY@
S_DEFENSE:        .byte @S_DEFENSE@
S_EVASION:        .byte @S_EVASION@
S_MAGIC_POWER:    .byte @S_MAGIC_POWER@
S_MAGIC_EFFECT:   .byte @S_MAGIC_EFFECT@
    .align 4
WIDTHS:
    .byte @WIDTHS@
    .align 4
