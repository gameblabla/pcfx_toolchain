	.file	"codegen_probe.c"
	.section .text
	.align 2
	.global _load_s8
	.type	_load_s8, @function
_load_s8:
	ld.b 0[r6],r10
	jmp [r31]
	.size	_load_s8, .-_load_s8
	.align 2
	.global _load_u8
	.type	_load_u8, @function
_load_u8:
	ld.b 0[r6],r10
	andi 255,r10,r10
	jmp [r31]
	.size	_load_u8, .-_load_u8
	.align 2
	.global _load_s16
	.type	_load_s16, @function
_load_s16:
	ld.h 0[r6],r10
	jmp [r31]
	.size	_load_s16, .-_load_s16
	.align 2
	.global _load_u16
	.type	_load_u16, @function
_load_u16:
	ld.h 0[r6],r10
	andi 65535,r10,r10
	jmp [r31]
	.size	_load_u16, .-_load_u16
	.align 2
	.global _add_s16
	.type	_add_s16, @function
_add_s16:
	mov r6,r10
	shl 16,r7 ; sar 16,r7
	shl 16,r10 ; sar 16,r10
	add r7,r10
	jmp [r31]
	.size	_add_s16, .-_add_s16
	.align 2
	.global _add_u16
	.type	_add_u16, @function
_add_u16:
	andi 65535,r6,r10
	andi 65535,r7,r7
	add r7,r10
	jmp [r31]
	.size	_add_u16, .-_add_u16
	.align 2
	.global _wrap_u8
	.type	_wrap_u8, @function
_wrap_u8:
	andi 255,r6,r10
	andi 255,r7,r7
	add r7,r10
	jmp [r31]
	.size	_wrap_u8, .-_wrap_u8
	.align 2
	.global _less_s32
	.type	_less_s32, @function
_less_s32:
	cmp r7,r6
	setf lt,r10
	jmp [r31]
	.size	_less_s32, .-_less_s32
	.align 2
	.global _less_u32
	.type	_less_u32, @function
_less_u32:
	cmp r7,r6
	setf l,r10
	jmp [r31]
	.size	_less_u32, .-_less_u32
	.align 2
	.global _in_bounds
	.type	_in_bounds, @function
_in_bounds:
	cmp r7,r6
	setf l,r10
	jmp [r31]
	.size	_in_bounds, .-_in_bounds
	.align 2
	.global _mul_s32
	.type	_mul_s32, @function
_mul_s32:
	mov r6,r10
	mul r7,r10
	jmp [r31]
	.size	_mul_s32, .-_mul_s32
	.align 2
	.global _mul_u32
	.type	_mul_u32, @function
_mul_u32:
	mov r6,r10
	mul r7,r10
	jmp [r31]
	.size	_mul_u32, .-_mul_u32
	.align 2
	.global _div_s32
	.type	_div_s32, @function
_div_s32:
	mov r6,r10
	div r7,r10
	jmp [r31]
	.size	_div_s32, .-_div_s32
	.align 2
	.global _div_u32
	.type	_div_u32, @function
_div_u32:
	mov r6,r10
	divu r7,r10
	jmp [r31]
	.size	_div_u32, .-_div_u32
	.align 2
	.global _rem_s32
	.type	_rem_s32, @function
_rem_s32:
	div r7,r6
	mov r30,r10
	jmp [r31]
	.size	_rem_s32, .-_rem_s32
	.align 2
	.global _rem_u32
	.type	_rem_u32, @function
_rem_u32:
	divu r7,r6
	mov r30,r10
	jmp [r31]
	.size	_rem_u32, .-_rem_u32
	.align 2
	.global _div_u10
	.type	_div_u10, @function
_div_u10:
	mov 10,r10
	divu r10,r6
	mov r6,r10
	jmp [r31]
	.size	_div_u10, .-_div_u10
	.align 2
	.global _rem_u10
	.type	_rem_u10, @function
_rem_u10:
	mov 10,r10
	divu r10,r6
	mov r30,r10
	jmp [r31]
	.size	_rem_u10, .-_rem_u10
	.align 2
	.global _div_s10
	.type	_div_s10, @function
_div_s10:
	mov 10,r10
	div r10,r6
	mov r6,r10
	jmp [r31]
	.size	_div_s10, .-_div_s10
	.align 2
	.global _shift_s32
	.type	_shift_s32, @function
_shift_s32:
	mov r6,r10
	sar r7,r10
	jmp [r31]
	.size	_shift_s32, .-_shift_s32
	.align 2
	.global _shift_u32
	.type	_shift_u32, @function
_shift_u32:
	mov r6,r10
	shr r7,r10
	jmp [r31]
	.size	_shift_u32, .-_shift_u32
	.align 2
	.global _sum_u8
	.type	_sum_u8, @function
_sum_u8:
	mov 0,r10
	cmp 0,r7
	be .L23
	add r6,r7
.L24:
	ld.b 0[r6],r11
	add 1,r6
	andi 255,r11,r11
	add r11,r10
	cmp r7,r6
	bne .L24
.L23:
	jmp [r31]
	.size	_sum_u8, .-_sum_u8
	.align 2
	.global _sum_s16
	.type	_sum_s16, @function
_sum_s16:
	cmp 0,r7
	be .L31
	add r7,r7
	mov 0,r10
	add r6,r7
.L30:
	ld.h 0[r6],r11
	add 2,r6
	add r11,r10
	cmp r7,r6
	bne .L30
	jmp [r31]
.L31:
	mov 0,r10
	jmp [r31]
	.size	_sum_s16, .-_sum_s16
	.global ___muldi3
	.align 2
	.global _mul_wide_u32
	.type	_mul_wide_u32, @function
_mul_wide_u32:
	add -4,sp
	st.w lp,0[sp]
	mov 0,r9
	mov r7,r8
	mov 0,r7
	jal ___muldi3
	ld.w 0[sp],lp
	add 4,sp
	jmp [r31]
	.size	_mul_wide_u32, .-_mul_wide_u32
	.align 2
	.global _mul_s64
	.type	_mul_s64, @function
_mul_s64:
	add -4,sp
	st.w lp,0[sp]
	jal ___muldi3
	ld.w 0[sp],lp
	add 4,sp
	jmp [r31]
	.size	_mul_s64, .-_mul_s64
	.align 2
	.global _advance_wrap
	.type	_advance_wrap, @function
_advance_wrap:
	mov r6,r10
	add r7,r10
	and r8,r10
	jmp [r31]
	.size	_advance_wrap, .-_advance_wrap
	.ident	"GCC: (GNU) 4.9.4"
