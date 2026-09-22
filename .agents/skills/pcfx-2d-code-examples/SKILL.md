---
name: pcfx-2d-code-examples
description: Copy-pasteable PC-FX reference code for CD-DA, KING ADPCM, VDC sprites/tilemaps/scrolling, 16-colour two-layer VDC mode, 256-colour dual-VDC mode, the KING scrolling limitation, and KING/VDC microcode.
---

# PC-FX 2D code examples

This is a curated code-example library, not another chip-concepts chapter. The
snippets below were read from working projects and minimal reference programs
outside this repository:
`vendor/doompcfx/`,
and `vendor/libpcfx/`. Prefer these source
patterns verbatim when they fit; do not re-derive register values from memory.
Every excerpt is marked with the file it came from. The conceptual explanations
remain in [pcfx-audio], [pcfx-vdc-tiles-sprites], [pcfx-king-framebuffer], and
[pcfx-cd-assets].

## 1. CD-DA audio

### Command/status layer: libpcfx

`vendor/libpcfx/src/cdda.c` returns the drive status after consuming the SCSI status
phase. It disables and restores the timer IRQ around the KING/SCSI sequence;
that guard is part of the working implementation, not optional scaffolding.

```c
/* Source: vendor/libpcfx/src/cdda.c */
static int cdda_issue(u8 *cdb)
{
	u16 tcr = timer_read_control();
	int st;

	if (tcr & 1)
		timer_write_control(tcr & ~1);

	eris_scsi_command(cdb, CDDA_CDB_LEN);

	/* The drive ignores the second half of a D8/D9 pair that arrives too
	 * soon after the first, so the fixed settle stays exactly as it is. */
	cdda_wait();

	st = (int)eris_scsi_status();

	timer_write_control(tcr);
	return (st >= 0) ? st : CDDA_ST_TIMEOUT;
}
```

The command builder converts the track to BCD, and the status predicate treats
only an explicit CHECK CONDITION or BUSY as refusal. A bounded handshake timeout
does not prove that the drive rejected a command.

```c
/* Source: vendor/libpcfx/src/cdda.c */
static u8 cdda_track_bcd(u8 track)
{
	return (u8)(((track / 10u) << 4) | (track % 10u));
}

static int cdda_set_position(u8 op, u8 mode, u8 track)
{
	u8 cdb[CDDA_CDB_LEN];

	cdda_zero_cdb(cdb);
	cdb[0] = op;
	cdb[1] = mode;
	cdb[2] = cdda_track_bcd(track);
	cdb[9] = CDDA_ADDR_TRACK;
	return cdda_issue(cdb);
}

static int cdda_accepted(int st)
{
	return !(st == SCSI_STATUS_CHECK_CONDITION || st == SCSI_STATUS_BUSY);
}
```

The public play/stop path is small enough to reuse directly. The end track is
an exclusive end position, not necessarily the final audible track number.

```c
/* Source: vendor/libpcfx/src/cdda.c */
int eris_cdda_play(u8 start_track, u8 end_track, u8 mode)
{
	int ok;

	if (start_track == 0 || end_track == 0 ||
	    start_track > 99 || end_track > 99) {
		eris_cdda_stop();
		return 0;
	}

	ok = cdda_start_at(start_track);
	cdda_wait();
	(void)cdda_end_at(end_track, mode);
	return ok;
}

void eris_cdda_stop(void)
{
	u8 cdb[CDDA_CDB_LEN];

	cdda_zero_cdb(cdb);
	cdb[0] = CDDA_CMD_PAUSE;
	(void)cdda_issue(cdb);

	cdda_scsi_mode_idle();
}
```

### Frame-safe manager and Doom usage

The manager separates the desired track from the active track. It is initialized
once, accepts play requests without issuing a bus command immediately, and is
pumped once per frame after CD data reads have had time to settle.

```c
/* Source: vendor/libpcfx/src/cdda.c */
void eris_cdda_music_init(void)
{
	cdda_music.desired_track  = CDDA_TRACK_NONE;
	cdda_music.desired_loop   = CDDA_MODE_LOOP;
	cdda_music.active_track   = CDDA_TRACK_NONE;
	cdda_music.active_loop    = CDDA_MODE_LOOP;
	cdda_music.volume         = CDDA_VOLUME_MAX;
	cdda_music.applied_volume = 0;
	cdda_music.paused         = 0;
	cdda_music.stop_frames    = CDDA_SILENCE_STOP_FRAMES;
	cdda_music.play_pending   = 0;
	cdda_music.play_retries   = 0;
	cdda_music.play_wait      = 0;
	cdda_music.bound_pending  = 0;
	cdda_music.bound_retries  = 0;
	cdda_music.bound_wait     = 0;
	cdda_music.quiet_frames   = 0;
	cdda_music.active_seq     = 0;

	eris_cdda_set_volume(0, 0);
	eris_cdda_stop();

	cdda_music.last_read_seq = eris_cdda_read_seq();
}

void eris_cdda_music_play(u8 track, int loop)
{
	u8 mode = loop ? CDDA_MODE_LOOP : CDDA_MODE_NORMAL;

	if (cdda_music.desired_track == track &&
	    cdda_music.desired_loop == mode && !cdda_music.paused)
		return;

	cdda_music.paused       = 0;
	cdda_music.desired_track = track;
	cdda_music.desired_loop  = mode;
	if (track == CDDA_TRACK_NONE)
		cdda_music.stop_frames = CDDA_SILENCE_STOP_FRAMES;
}
```

The Doom port wires this manager into normal engine initialization and the
per-frame loop:

```c
/* Source: vendor/doompcfx/platform/i_sound_pcfx.c */
void I_InitSound(void)
{
	eris_cd_reset();
	adpcm_reset();
	adpcm_load_bank();
	eris_cdda_music_init();
}

void pcfx_cdda_pump(void)
{
	eris_cdda_music_pump();
}

void I_PlaySong(int handle, int looping)
{
	eris_cdda_music_play(music_track_for(handle), looping);
}
```

`src/i_video.c` calls `pcfx_cdda_pump()` from `I_StartFrame`, so the manager is
serviced in title, menu, gameplay, and intermission states:

```c
/* Source: vendor/doompcfx/src/i_video.c */
void I_StartFrame (void)
{
#ifdef __v810__
    pcfx_cdda_pump();
#endif
}
```

## 2. ADPCM sound effects

The Doom backend streams one generated ADPCM bank directly to KRAM page 1,
then programs one of KING's two voices for each sound. This is the concrete
counterpart to the layout and contention rules in [pcfx-audio].

### libpcfx low-level register writers

`vendor/libpcfx/src/sound.S` packs the rate/interpolation/reset fields and writes the
per-channel volume ports. These are the actual assembly entry points used by
the C API.

```asm
/* Source: vendor/libpcfx/src/sound.S */
	.global _adpcm_set_control
	.global	_adpcm_set_volume

_adpcm_set_control:
	ld.w	0[sp], r10
	shl	2, r7
	shl	3, r8
	shl	4, r9
	shl	5, r10
	or	r7, r6
	or	r8, r6
	or	r9, r6
	or	r10, r6
	out.b	r6, 0x120[r0]
	jmp	[lp]

_adpcm_set_volume:
	shl	2, r6
	out.b	r7, 0x122[r6]
	out.b	r8, 0x124[r6]
	jmp	[lp]
```

### Bank load, reset, and trigger: doom-pcfx

These register indices and the one-shot channel mode are from the Doom port's
`platform/i_sound_pcfx.c`; they are not values inferred from this skill.

```c
/* Source: vendor/doompcfx/platform/i_sound_pcfx.c */
#define ADPCM_CTRL   0x50u
#define ADPCM_CHCFG(ch) (0x51u + (unsigned)(ch))
#define ADPCM_CHCFG_ONESHOT 0x0002u
#define ADPCM_SAL(ch)   (0x58u + ((unsigned)(ch) << 2))
#define ADPCM_END(ch)   (0x59u + ((unsigned)(ch) << 2))
#define ADPCM_RATE   ADPCM_RATE_8000
#define ADPCM_RATEBITS (ADPCM_RATE << 2)
```

The reset is interrupt-atomic around KING register sequences and releases both
decoder resets only after a raster settle:

```c
/* Source: vendor/doompcfx/platform/i_sound_pcfx.c */
static void adpcm_reset(void)
{
    uint32_t psw = pcfx_irq_save();

    adpcm_set_volume(0, 0, 0);
    adpcm_set_volume(1, 0, 0);
    adpcm_set_control(ADPCM_RATE, 1, 1, 1, 1);
    king_reg16(ADPCM_CTRL, 0);
    for (int ch = 0; ch < 2; ch++)
    {
        king_reg16(ADPCM_CHCFG(ch), ADPCM_CHCFG_ONESHOT);
        king_reg16(ADPCM_SAL(ch), 0);
        king_reg32(ADPCM_END(ch), 0);
    }

    pcfx_irq_restore(psw);
    adpcm_reset_settle();

    psw = pcfx_irq_save();
    adpcm_set_control(ADPCM_RATE, 1, 1, 0, 0);
    pcfx_irq_restore(psw);

    for (int ch = 0; ch < 2; ch++)
    {
        g_hw_end_ms[ch] = g_ms_irq;
        g_hw_owner[ch]  = -1;
    }
}
```

The bank is loaded from CD straight into KRAM. `I_InitSound()` runs the reset,
load, and CD-DA initialization in that order:

```c
/* Source: vendor/doompcfx/platform/i_sound_pcfx.c */
static void adpcm_load_bank(void)
{
    if (PCFX_SFX_BANK_BYTES == 0) { g_adpcm_ready = 0; return; }
    if (!pcfx_king_dma_cd_to_kram(SFX_LBA, PCFX_SFX_KRAM_BASE_WORD,
                                  PCFX_SFX_BANK_BYTES)) {
        g_adpcm_ready = 0;
        return;
    }
    pcfx_boot_progress_tick();
    g_adpcm_ready = 1;
}

void I_InitSound(void)
{
    eris_cd_reset();
    adpcm_reset();
    adpcm_load_bank();
    eris_cdda_music_init();
}
```

`I_StartSound()` mutes and resets only the selected voice, waits for a real
HSYNC boundary, then writes the sample start/end and gives the channel its
0-to-1 enable edge:

```c
/* Source: vendor/doompcfx/platform/i_sound_pcfx.c */
{
    uint16_t keep = ctrl_keep(ch);
    uint32_t psw  = pcfx_irq_save();

    adpcm_set_control(ADPCM_RATE, 1, 1, 0, 0);
    king_reg16(ADPCM_CHCFG(ch), ADPCM_CHCFG_ONESHOT);
    king_reg16(ADPCM_SAL(ch), (uint16_t)(start >> 8));
    king_reg32(ADPCM_END(ch), end);
    adpcm_set_volume((uint8_t)ch, (uint8_t)v, (uint8_t)v);
    king_reg16(ADPCM_CTRL, (uint16_t)(keep | (1u << ch)));

    pcfx_irq_restore(psw);
}
```

`platform/pcfx_cdasset.c` does not program ADPCM registers; its relevant
working pattern is the same direct CD-to-KRAM asset flow, useful when adapting
the bank loader to other assets:

```c
/* Source: vendor/doompcfx/platform/pcfx_cdasset.c */
static void bg_cache_load(int idx)
{
    if (s_cache_pic == idx)
        return;
    const pcfx_cdasset_t *a = &pcfx_cdassets[idx];
    pcfx_king_dma_cd_to_fb(CDASSET_BASE_LBA + a->sector,
                           pcfx_fb_page_base(KFB_BG_CACHE_BUF),
                           (unsigned)a->words * 2u);
    s_cache_pic = idx;
}
```

## 3. VDC 16-colour two-layer mode: libpcfx examples

The minimal libpcfx VDC programs configure both HuC6270s and select
`TETSU_COLORS_16` for both VDC inputs. The tiny examples exercise one background
or sprite path at a time, so they are useful as clean bring-up pieces rather
than a large application-specific renderer. The same Tetsu mode is the
16-colour/two-layer composition mode.

### Bring-up and 16-colour Tetsu mode

```c
/* Source: vendor/libpcfx/examples/020_vdc_simple_background/vdc_simple_background.c */
vdc_init_5MHz(VDC0);
vdc_init_5MHz(VDC1);

king_init();
tetsu_init();

tetsu_set_priorities(0, 0, 1, 0, 0, 0, 0);
tetsu_set_vdc_palette(0, 0);
tetsu_set_king_palette(0, 0, 0, 0);
tetsu_set_rainbow_palette(0);
```

The display mode and VDC background enable are configured with the two 16-colour
inputs and the VDC scroll API:

```c
/* Source: vendor/libpcfx/examples/020_vdc_simple_background/vdc_simple_background.c */
tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz, TETSU_COLORS_16,
                     TETSU_COLORS_16, 1, 0, 1, 0, 0, 0, 0);
king_set_bat_cg_addr(KING_BG0, 0, 0);
king_set_bat_cg_addr(KING_BG0SUB, 0, 0);
king_set_scroll(KING_BG0, 0, 0);
king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                 KING_BGSIZE_256, KING_BGSIZE_256);

vdc_setreg(VDC0, VDC_REG_CR, VDC_CR_BB);
vdc_setreg(VDC0, VDC_REG_MWR, VDC_MWR_SCREEN_32x32);
vdc_set_scroll(VDC0, 0, 0);
```

### BAT/tilemap writes

The simple background example writes a BAT run and then the two 16-word tile
patterns it references. The values below are the source program's real VDC
word writes.

```c
/* Source: vendor/libpcfx/examples/020_vdc_simple_background/vdc_simple_background.c */
vdc_set_vram_write(VDC0, 0);
for(i = 0; i < (32 * 5); i++) {
    vdc_vram_write(VDC0, 0x80);
}
for(i = (32 * 5); i < 0x800; i++) {
    vdc_vram_write(VDC0, 0x81);
}

for(i = 0; i < 16; i++) {
    vdc_vram_write(VDC0, 0x00);
}
for(i = 0; i < 16; i++) {
    vdc_vram_write(VDC0, char_gfx[i]);
}
```

### Hardware scrolling and SAT/sprite writes

The raster example changes the VDC scroll registers at raster interrupts, while
the sprite example writes pattern words and creates a SAT entry. Both are small
enough to transplant into a larger 16-colour VDC renderer.

```c
/* Source: vendor/libpcfx/examples/022_vdc_raster/vdc_raster.c */
__attribute__ ((interrupt_handler)) void my_video_irq (void)
{
   int16_t vdc_stat = vdc_status(0);

   if (vdc_stat & VDC_STAT_RR )
   {
      if (scroll_band == 0) {
         vdc_set_scroll(VDC0, (scroll_x>>1), scroll_1_line - 1);
         vdc_set_raster(VDC0, scroll_2_line + 64);
      }
      else
         vdc_set_scroll(VDC0, scroll_x, scroll_2_line - 1);

      scroll_band++;
   }

   if (vdc_stat & VDC_STAT_VD )
   {
      sda_frame_count++;
      scroll_band = 0;
      vdc_set_scroll(VDC0, scroll_x, scroll_y);
      vdc_set_scroll(VDC0, 0, 0);
      vdc_set_raster(VDC0, scroll_1_line + 64);
   }
}
```

```c
/* Source: vendor/libpcfx/examples/021_vdc_simple_sprite/vdc_simple_sprite.c */
vdc_set_vram_write(VDC0, sprite_image_load_addr);
for(i = 0; i < 8*4; i++) {
    vdc_vram_write(VDC0, spr_data[i]);
}

vdc_set(VDC0);
vdc_spr_set(0);
vdc_spr_create(0, 0, VDC_SPR_PATTERN(sprite_image_load_addr), 0);
```

### Palette groups

The multi-sprite example writes palette entries at line-aligned offsets (`0x10`,
`0x20`, `0x30`, and `0x40`) and uses the same 16-colour Tetsu mode. Its sprite
creation loop passes the selected palette group as the SAT attribute argument.

```c
/* Source: vendor/libpcfx/examples/023_vdc_multi_sprite/vdc_multi_sprite.c */
tetsu_set_palette(0, 0x0088);
tetsu_set_palette(1, 0xE088);
tetsu_set_palette(2, 0xE0F0);
tetsu_set_palette(0x10, 0x0088);
tetsu_set_palette(0x11, 0xE088);
tetsu_set_palette(0x20, 0x0088);
tetsu_set_palette(0x21, 0xE08F);
tetsu_set_palette(0x30, 0x0088);
tetsu_set_palette(0x31, 0xE0F0);
tetsu_set_palette(0x40, 0x0088);
tetsu_set_palette(0x41, 0xFF39);

tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz, TETSU_COLORS_16,
                     TETSU_COLORS_16, 0, 1, 1, 0, 0, 0, 0);
```

```c
/* Source: vendor/libpcfx/examples/023_vdc_multi_sprite/vdc_multi_sprite.c */
initialize_pixels();
for (i = 0; i < 63; i++) {
    vdc_spr_set(i);
    vdc_spr_create((pixels[i].x>>8),
                   (pixels[i].y>>8),
                   VDC_SPR_PATTERN(sprite_image_load_addr),
                   pixels[i].palette);
}
```

### VDC register-level scroll primitive

The low-level wrapper used by these examples writes BXR and BYR for the selected
chip:

```asm
/* Source: vendor/libpcfx/src/vdc.S */
_vdc_set_scroll:
        shl     8, r6
        set_vreg_num    VDC_REG_BXR, r6, r10, r11
        out.h   r7, 4[r10]
        set_vreg_num    VDC_REG_BYR, r6, r10, r11
        out.h   r8, 4[r10]
        jmp     [lp]
```

## 4. VDC 256-colour dual-chip mode: Doom/libpcfx

Doom uses a different composition contract. Tetsu is configured with 256-colour
VDC depth on both inputs, and the two VDCs carry the high and low nibbles of one
combined 8-bit sprite pixel. This is not the independent two-layer 16-colour
setup above.

```c
/* Source: vendor/doompcfx/platform/i_system_pcfx.c */
static void tetsu_apply_layer_mix(int rainbow_on)
{
    tetsu_set_priorities(7, 6, 5, 4, 3, 2, 1);
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                              TETSU_COLORS_256, TETSU_COLORS_256,
                              1, 1, 1, 0, 0, 0, rainbow_on ? 1 : 0);
}
```

The weapon backend documents the combined-sprite contract and initializes both
chips with identical timing. The same SAT geometry must be present on both
chips for the nibbles to line up.

```c
/* Source: vendor/doompcfx/platform/pcfx_weapon.c */
static void vdc_init_chip(int chip)
{
    vdc_init_5MHz(chip);
    vdc_setreg(chip, VDC_REG_CR, VDC_CR_SB);
    vdc_setreg(chip, VDC_REG_MWR, VDC_MWR_SCREEN_32x32);
    vdc_setreg(chip, VDC_REG_HSR, 0x0202);
    vdc_setreg(chip, VDC_REG_HDR, 0x041F);
    vdc_setreg(chip, VDC_REG_VPR, 0x1102);
    vdc_setreg(chip, VDC_REG_VDR, PCFX_WEP_VDISPWID);
    vdc_setreg(chip, VDC_REG_VCR, 0x0002);
    vdc_set_scroll(chip, 0, 0);
}

void pcfx_weapon_init(void)
{
    vdc_init_chip(0);
    vdc_init_chip(1);
    tetsu_write_reg(4, 0x0000);

    pcfx_weapon_begin();
    pcfx_weapon_end();
    pcfx_weapon_present();

    vdc_setreg(0, VDC_REG_DCR, VDC_DCR_SATB_AUTO);
    vdc_setreg(1, VDC_REG_DCR, VDC_DCR_SATB_AUTO);
    vdc_set_satb_address(0, SATB_VRAM_ADDR);
    vdc_set_satb_address(1, SATB_VRAM_ADDR);
}
```

The source's contract says VDC0 supplies the high nibble and VDC1 the low
nibble, with matching x/y/pattern/size and a VDC1 palette-bank bit selecting the
combined path. The trade-off is direct: independent 16-colour mode gives two
separately useful VDC background/sprite engines; combined 256-colour mode gives
one 8bpp result but consumes both chips for each combined sprite, so it does
not provide the same independent sprite-per-scanline capacity.

## 5. KING has no hardware scrolling

> **KING has no hardware scrolling.**
> KING's BG0/BG1/BG2/BG3 bitmap/tile layers are positioned by writing base addresses or
> offsets each frame in software; there is no BXR/BYR-style scroll
> register like the VDC has. Hardware scrolling on PC-FX only exists on the two
> HuC6270 VDC chips (BXR/BYR). If a design wants free hardware-scrolled 2D
> layers, it must use the VDC(s), not KING.

There is an important evidence conflict in the exact libpcfx checkout inspected
for this skill. The requested “absence” check does **not** pass here: the header
declares `king_set_scroll`, the assembly exports it and writes registers 0x30+
for BSX/BSY, and `docs/KING_REGS.md` lists REG.30 through REG.37 as BG0..BG3
horizontal/vertical scroll fields. Do not replace that evidence with an invented
absence claim. For this project, keep the owner rule above as the design
restriction, and treat the following as the source-level discrepancy that must
be resolved before relying on KING offsets.

```c
/* Source: vendor/libpcfx/include/pcfx/king.h */
/* Set background scrolling.
 *
 * bg: Which background to scroll (BG0SUB is not allowed).
 * x:  Signed X value correlating to the upper-left corner of the BG.
 * y:  Signed Y value correlating to the upper-left corner of the BG.
 */
void king_set_scroll(king_bg bg, s16 x, s16 y);
```

```asm
/* Source: vendor/libpcfx/src/king.S */
_king_set_scroll:
	movea	0x30, r0, r10
	cmp	0, r6
	be	1f
	add	-1, r6
1:	shl	1, r6
	add	r10, r6
	set_rrg	r6
	out.h	r7, 0x604[r0]
	add	1, r6
	set_rrg	r6
	out.h	r8, 0x604[r0]
	jmp	[lp]
```

For contrast, the VDC header explicitly names BXR/BYR and the assembly wrapper
writes those registers. The docs also list the KING BSX/BSY rows noted above;
this is why the project policy and the checked-in low-level source currently
need to be kept separate in reviews.

```c
/* Source: vendor/libpcfx/include/pcfx/vdc.h */
#define VDC_REG_BXR     0x07      // BGX Scroll register
#define VDC_REG_BYR     0x08      // BGY Scroll register
```

## 6. Microcode: separate migration notes from actual schedules

### 4-colour to 16-colour migration (not a microcode example)

A reference implementation moved a KING layer from 4 colours to 16 colours and
made three coordinated changes: the palette/data width grew, each cell row
started writing two KRAM words instead of one, and the fetch count grew from one
CG word to two. The unused slots were still filled with `KING_CODE_NOP`. Those
are useful migration rules, but they are data-layout and mode-conversion work,
not a reusable microcode schedule; keep them separate from the actual examples
below.

The resulting microprogram fragment is useful on its own. It is shown without
diff markers or source line numbers; the project identity is intentionally
omitted so this remains a project-agnostic migration example:

```c
/* Source: external 16-colour KING migration excerpt; project identity omitted. */
mprog[0]=KING_CODE_BG0_CG_0;
mprog[1]=KING_CODE_BG0_CG_1;
for(i=2;i<16;++i)mprog[i]=KING_CODE_NOP;
```

### Actual microcode schedules

Doom's working 8bpp BG0 schedule explicitly fills every unused slot with
`KING_CODE_NOP` and mirrors the four fetches into the second bank:

```c
/* Source: vendor/doompcfx/platform/i_system_pcfx.c */
static uint16_t microprog[16];
for (int i = 0; i < 16; i++) microprog[i] = KING_CODE_NOP;
microprog[0]  = KING_CODE_BG0_CG_0;
microprog[1]  = KING_CODE_BG0_CG_1;
microprog[2]  = KING_CODE_BG0_CG_2;
microprog[3]  = KING_CODE_BG0_CG_3;
microprog[8]  = KING_CODE_BG0_CG_0;
microprog[9]  = KING_CODE_BG0_CG_1;
microprog[10] = KING_CODE_BG0_CG_2;
microprog[11] = KING_CODE_BG0_CG_3;
king_disable_microprogram();
king_write_microprogram(microprog, 0, 16);
king_enable_microprogram();
```

The minimal libpcfx benchmark keeps alternative schedules as real data tables:

```c
/* Source: vendor/libpcfx/examples/024_king_mprog_bench/king_mprog_bench.c */
#define NOPx4  KING_CODE_NOP, KING_CODE_NOP, KING_CODE_NOP, KING_CODE_NOP

static const u16 prog_nop[16] = { NOPx4, NOPx4, NOPx4, NOPx4 };

static const u16 prog_bg0_cg[16] = {
	KING_CODE_BG0_CG_0, KING_CODE_NOP, KING_CODE_NOP, KING_CODE_NOP,
	NOPx4, NOPx4, NOPx4
};

static const u16 prog_bg0_batcg_sep[16] = {
	KING_CODE_BG0_BAT_0, KING_CODE_BG0_CG_0, KING_CODE_NOP, KING_CODE_NOP,
	NOPx4, NOPx4, NOPx4
};
```

Its loader is deliberately independent of the selected table:

```c
/* Source: vendor/libpcfx/examples/024_king_mprog_bench/king_mprog_bench.c */
static void load_mprog(const u16* prog)
{
	king_disable_microprogram();
	king_write_microprogram((u16*)prog, 0, 16);
	king_enable_microprogram();
}
```

The small VDC background example shows the same complete write/enable sequence
without a benchmark harness:

```c
/* Source: vendor/libpcfx/examples/020_vdc_simple_background/vdc_simple_background.c */
for(i = 0; i < 16; i++) {
	microprog[i] = KING_CODE_NOP;
}

microprog[0] = KING_CODE_BG0_CG_0;
king_disable_microprogram();
king_write_microprogram(microprog, 0, 16);
king_enable_microprogram();
```

## Related

[pcfx-vdc-tiles-sprites] · [pcfx-king-framebuffer] · [pcfx-audio] ·
[pcfx-cd-assets]
