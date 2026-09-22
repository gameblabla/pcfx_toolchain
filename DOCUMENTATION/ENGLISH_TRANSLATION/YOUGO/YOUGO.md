# PC-FXGA Authoring Software

## “GMAKER” Starter Kit (Ver. 1.0)

# Device Manual Glossary

NEC Home Electronics, Ltd.  
November 10, 1995

Copyright © 1995 NEC Home Electronics, Ltd.

## General PC-FXGA Device Overview (`PCFXGABOAD.WRI`)

**Gate array** — A device made from standardized logic-circuit blocks whose interconnections are customized to the user’s specification.

**Signature** — The device number of a device connected to the K port. Examples: pad → `F(h)`, mouse → `D(h)`.

**Borrow** — A borrow from a higher-order digit during subtraction.

## HuC6230 Device Description (`C6230.WRI`)

**Address counter** — A counter that selects the write address in the waveform register. Software can only reset it; because it increments whenever waveform data is written, it is called a counter.

**Underflow saturation** — A function that clamps an arithmetic result to the minimum representable value when the result would otherwise be smaller.

**Initial reset** — Setting the device to its initial state.

**Overflow saturation** — A function that clamps an arithmetic result to the maximum representable value when the result would otherwise be larger.

**Audio-output disable** — Disabling audio output.

**Sampling frequency** — The rate per unit time at which audio is digitized or reproduced.

**Sampling rate** — Sampling frequency.

**Output-level hold** — When data does not arrive at the specified interval, this function holds the current output voltage, producing silence. Correct playback resumes when the next continuous sequence of data arrives.

**Channel address** — A channel number.

**Channel-volume register** — A register that sets the volume independently for each channel.

**Intermediate arithmetic precision** — The number of bits used during intermediate calculations.

**Stopped channel** — A channel to which the HuC6272 is not transferring data.

**Electronic volume control** — A function for independently setting the PSG, ADPCM, and CD-DA volumes.

**Transfer cycle** — The interval at which data is received from the HuC6272.

**ADPCM linear-interpolation mode** — When the transfer rate is low, this mode linearly interpolates between output samples by inserting evenly spaced intermediate values, thereby smoothing the waveform.

**PCM input volume (VCA)** — The volume control for the CD-DA audio source.

## HuC6261 Device Description (`C6261.WRI`)

**Address register** — A register that selects the number of the register to be read or written.

**Interlace** — See Section 2.6 of `C6261.WRI`.

**All blanking** — A state in which no image planes are displayed.

**Color palette** — Storage containing display colors, where a color is selected for display by its palette index.

**Chroma-key function** — A function that makes a specified color in an image transparent.

**Constant-color register (CCR)** — A register that sets the uniform color used when a cellophane operation overlays the entire screen or the rearmost screen plane.

**Control register (CR)** — A register that switches HuC6261 modes and selects the planes to display.

**Auto-increment function** — A function that automatically increments an address when data is read or written.

**Status register (SR)** — A register indicating HuC6261 state: the address-register value, the raster currently being processed, even/odd field state, and display/blanking state.

**Cellophane** — A technique for displaying a blend of two images.

**Multiple cellophane** — Applying cellophane processing to multiple image planes, up to four on the HuC6261.

**Dot clock** — The time required to display one dot.

**Non-interlace mode** — See Section 2.6 of `C6261.WRI`.

**Palette** — See “Color palette.”

**Back cellophane** — A function that cellophane-blends a constant-color plane behind all displayed planes.

**Front cellophane** — A function that cellophane-blends a constant-color plane in front of all displayed planes.

**Priority function** — A function that assigns display priority to image planes.

**Blanking** — A period during which no image is displayed.

**Raster count** — A function that counts the currently displayed line number.

**Raster-count value** — The number of the currently displayed line.

**1/2-dot shift function** — See Section 2.6.3 of `C6261.WRI`.

**BG color palette** — The color palette used for BG planes.

**BGM** — A BG screen supplied by the HuC6272.

**YUV** — The color representation handled by the HuC6261, expressing color as luminance and color difference. See Section 2.8 of `C6261.WRI`.

## HuC6272 Device Description (`C6272.WRI`)

**Affine transformation** — A method used to rotate, enlarge, or reduce a BG plane.

**Initial refresh operation** — The initial DRAM refresh performed after power-on.

**Interlaced display mode** — See Section 2.6 of `C6261.WRI`.

**External dot-sequential mode** — See Reference (b) in `C6272_3.WRI`.

**External block-sequential mode** — See Reference (b) in `C6272_3.WRI`.

**Pseudo-DMA transfer mode** — See Section 3.3.6 of `C6272_2.WRI`.

**Character code** — The number of a character relative to the character’s CG address.

**Subcode-block period** — The time from the transfer of one subcode item until the transfer of the next.

**Sequential DMA mode** — A mode in which a large quantity of data is requested at once and transferred in portions.

**Sequential-buffer mode** — A mode that plays the HuC6230 data buffer once from its start address to its end address and then stops.

**Natural-image background (BG image)** — A BG image held within the HuC6272.

**Start-raster register** — A register that specifies the raster on which transfer begins.

**Tiled display** — Displaying images side by side as though laying tiles.

**Transfer period** — The interval at which data is transferred to the HuC6230.

**Transparent-paste mode** — A mode that makes portions with no image data transparent.

**Internal dot-sequential mode** — See Reference (b) in `C6272_3.WRI`.

**Background image** — A BG image. See Section 3.6 of `C6272_2.WRI`.

**Palette bank** — A group of palettes. A palette-grouping unit is defined for each color mode; specifying a different palette-bank number for each character permits a larger number of colors to be represented.

**Non-rotation mode** — A mode that does not use rotation, enlargement, or reduction.

**Bitmap image** — Data in which every dot is specified individually; this is the CG-data structure used in internal dot-sequential mode.

**Priority determination** — Determining which BG plane takes precedence in the output.

**Read-address pointer** — The data-transfer address used for the HuC6230.

**Refresh function** — After transferring a DRAM data buffer through its end address, this mode automatically continues transfer again from the start address.

**Continuous-playback timing** — A state in which data is transferred to the HuC6230 at a fixed interval.

**ADPCM** — A data format that the HuC6230 can play: Adaptive Differential Pulse Code Modulation.

**BAT (Background Attribute Table)** — A table containing background character numbers and palette-bank numbers. The character number is read from this table and the actual character data is then loaded and displayed. In external block-sequential mode the number identifies a character; in external dot-sequential mode it identifies dot data.

**BG** — Background image.

**CG (Character Generator)** — An area of VRAM that defines character patterns.

**CPU-to-KRAM write** — A write from the CPU to KRAM.

**CPU-to-KRAM read** — A read from KRAM by the CPU. *(The Japanese source repeats “write”; this translation follows the heading’s apparent intent.)*

**DMA transfer** — A data transfer performed without direct CPU control.

**KRAM** — RAM dedicated to the HuC6272, used for loading data, ADPCM, BG display, and other functions.

**KRAM access** — Reading from or writing to KRAM.
