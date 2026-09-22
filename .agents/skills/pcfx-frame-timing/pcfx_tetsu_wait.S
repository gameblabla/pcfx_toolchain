/* pcfx_tetsu_wait.S -- wait for the start of the next video frame, in asm.
 *
 * Adapted from the Hudson/7up hardware notes ("Reading the Tetsu raster
 * position and waiting for the next frame", the same source the C6661
 * workaround commentary in pcfx.h cites): the Tetsu (HuC6261) display-status
 * port 0x300 holds the raster counter in bits 14..5 (line << 5), and the chip
 * has a hardware bug where a single read can latch a transitional value --
 * mednafen only ever returns the raster from the first OR the last cycle of
 * the read. So the raster is read TWICE and the two reads must agree before
 * the value is trusted.
 *
 * The wait itself is two phases (see the notes): first wait until the raster
 * is the LAST line of the current frame (261 in the 262-line mode this port
 * programs -- TETSU_LINES_262 in wolf_video.c), then wait until it is no
 * longer that line, i.e. the counter has wrapped into the next frame's
 * blanking. Returning exactly on that wrap is the leading edge of vertical
 * blanking, which is what the C-side callers (video_wait_vsync, via
 * pcfx_time.c) contract on: a 256-entry VCE palette burst, a KING page flip
 * or an MPSW stop/start must begin at the start of blanking with the whole
 * interval ahead of it, not "somewhere past a threshold" (C6261 2.1.3(5)).
 *
 * Notes only cover 262-line modes; the constants here are for that mode.
 *
 * C signature: void pcfx_tetsu_wait_frame(void);
 * Leaf, no frame. r6-r15 are caller-saved on this ABI (see lz4_depack.S), so
 * the scratch registers used here (r10-r13) need no preservation.
 */
	.text
	.align 2
	.global	_pcfx_tetsu_wait_frame

_pcfx_tetsu_wait_frame:
	/* Last raster and raster mask, in the raw (line << 5) units the status
	 * port delivers them: 0x20A0 = 261 << 5, 0x3FE0 selects bits 14..5. */
	movea	0x20A0, r0, r12		/* last raster of the frame */
	movea	0x3FE0, r0, r13		/* raster bit mask */

	/* First, wait until Tetsu is finished with the current frame. */
.Lwf_prev_done:
	in.h	0x300[r0], r10
	in.h	0x300[r0], r11		/* read twice: hardware bug */
	and	r13, r10		/* get the raster */
	and	r13, r11
	cmp	r10, r11
	bne	.Lwf_prev_done
	cmp	r10, r12
	bne	.Lwf_prev_done

	/* Then wait until it starts the next frame. */
.Lwf_next_start:
	in.h	0x300[r0], r10
	in.h	0x300[r0], r11
	and	r13, r10
	and	r13, r11
	cmp	r10, r11
	bne	.Lwf_next_start
	cmp	r10, r12
	be	.Lwf_next_start		/* still the last raster: keep waiting */

	jmp	[r31]
