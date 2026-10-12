---
name: pcfx-character-animation
description: Build and run an animated skinned mesh on PC-FX from one shared COLLADA base rig plus compatible animation-only COLLADA clips - influence-seam preservation, offline skinning to object-space vertex clips, the PCA1 container and raw LZ4 blocks, manifest-driven conversion, CD-appended archives, KING DMA bounce loading, clip-selection controls, freestanding validation and profiler measurement. Use whenever a PC-FX character or prop must move, animate, change clips, translate in 3D, or accept future skeletal exports without baking screen poses.
---

# Shared rig and compressed animation clips

Use this skill when the visible state is **not** a closed finite set. Anything that can
translate, zoom, change animation, receive new clips, or use a moving camera must remain a
live 3D renderer; it cannot be replaced by cached screen images ([pcfx-character-8bpp] §11).

Every count, name and hash below is from **one worked example** and is marked as such.
Take your own from your manifest and generated metadata — never assert another project's
numbers. What generalizes is the *structure*:

```text
one authoring COLLADA base rig
  mesh + UVs + skin controller + inverse bind matrices + joint hierarchy

many compatible COLLADA animation exports
  same mesh/controller/rig, different matrix tracks

PC-FX runtime
  one animation-safe base mesh
  one compressed object-space clip resident at a time
  live world transform, projection, cull, sort, texture raster, outline, KING upload
```

*Worked example:* a no-spin, Idle-default viewer over an 11.5k-face skinned mesh measured
**2.800 presented FPS** at native 256×240. That is one emulator-measured baseline for one
asset — not a target, not a hardware claim, and not a number to assert in your build.

## 1. Asset directory contract

Use a stable shared base plus a manifest:

```text
assets/source/character/
├── base/
│   ├── character_base_source.dae   # authoritative authoring export
│   ├── character_base.dae          # generated base with animation libraries removed
│   └── textures/
│       └── ...
└── animations/
    ├── manifest.json
    ├── Walk.dae
    ├── Run.dae
    └── ...
```

Example manifest:

```json
{
  "clips": [
    {"name": "Walking", "file": "Walking.dae", "slug": "walking",
     "root_motion": "loop_in_place"},
    {"name": "Fast Run", "file": "Fast Run.dae", "slug": "fast_run",
     "root_motion": "loop_in_place"},
    {"name": "Victory", "file": "Victory.dae", "slug": "victory",
     "root_motion": "preserve"}
  ]
}
```

The manifest defines runtime order and display names. Reject duplicate names/slugs and
missing files. An optional auto-discovery mode may sort `*.dae`, but a committed manifest
is preferable because adding a filename must not silently reorder controller inputs.

## 2. Reject incompatible clips; do not silently retarget

For every clip, compare the following with the base:

```text
geometry topology and triangle material assignment
position/normal/UV source layout
skin-controller vertex-weight indices and values
joint name/order
inverse bind matrices
bind-shape matrix
joint hierarchy IDs/SIDs
```

Hash the normalized topology/controller data and fail conversion on any mismatch:

```python
base_hash = base.topology_hash()
for clip in clips:
    if clip.topology_hash() != base_hash:
        raise ValueError(f"{clip.name}: skeleton/controller/topology differs from base")
```

Do not infer that two DAEs are compatible merely because the rendered mesh looks alike or
joint names overlap. Automatic retargeting is a separate tool with explicit bind-space
math and validation; it must not happen inside this packer.

Record the rig's shape in the generated metadata so a later clip can be checked against it.
*Worked example* (one rig, twelve clips including Idle and a generated T-pose fallback):

```text
joint nodes:       163
skin joints:       162
animated channels: 87 matrix tracks
source rate:       30 Hz
```

Your rig will differ in every one of those numbers. What must hold is that **all clips
agree with the base** on all of them.

## 3. Preserve skin-influence seams

A static renderer may deduplicate vertices by object-space position. That is unsafe for
skinning. Two coincident bind vertices can have different joint indices or weights and
therefore move apart in an animation.

Build the runtime vertex key from at least:

```text
source position index
UV/material seam identity
complete normalized influence signature
```

Representative Python:

```python
def influence_signature(controller, source_vertex):
    pairs = controller.influences[source_vertex]
    return tuple((joint_index, quantized_weight) for joint_index, quantized_weight in pairs)

key = (position_index, uv_index, material_lane,
       influence_signature(controller, position_index))
```

**The skinned vertex count is therefore normally higher than the static one**, and that is
correct. *Worked example:*

```text
old static position-only mesh:  5,563 vertices / 10,628 faces
animation-safe shared mesh:     6,246 vertices / 11,508 faces
```

The increase is not added visual complexity; it preserves seams the authoring asset already
contains. Never force the animated mesh through a static-era count to satisfy an obsolete
assertion — regenerate the contract from the animation-safe manifest instead
([pcfx-character-8bpp] §1).

## 4. Preserve animated root/body motion

A common COLLADA-converter bug is to normalize every frame with the inverse of the
**current animated root**:

```python
root_inverse = np.linalg.inv(frame_globals[animated_root])
skin = root_inverse @ frame_globals[joint] @ inverse_bind[joint] @ bind_shape
```

That removes the entire authored root transform.  Limb joints still move relative to the
root, so arms and legs animate, but vertices dominated by the root/hip/waist/chest joints
remain nearly fixed — the characteristic "the body is frozen but the limbs work" symptom.
It is easy to write and easy to miss, and it happened here.

Use frame zero as the constant authoring-space basis instead:

```python
root0_inverse = np.linalg.inv(frame_globals_at_zero[animated_root])
skin = root0_inverse @ frame_globals[joint] @ inverse_bind[joint] @ bind_shape
```

Expose a per-clip manifest policy:

```text
preserve       keep the complete root transform
loop_in_place  keep rotation/bob/sway, subtract only linear end-to-end translation
strip          legacy diagnostic mode only; never a release default
```

For a looping locomotion clip, compute `end_delta = inverse(root0) @ root(last)` and
pre-multiply every frame by a translation of
`-end_delta.translation * frame/(frame_count-1)`.  Do not remove the root rotation or
per-frame deviations; otherwise the body becomes rigid again.

Add an automated regression gate that:

```text
counts Root-dominant and torso vertices
measures their maximum movement across each clip
compares it with the legacy stripped result
requires walk/run first-last closure within one quantized coordinate unit
recomputes the generated vertex-stream SHA-256
```

The gate is a *ratio*, not a threshold you can copy: a clip with real body motion must move
root-dominant vertices by orders of magnitude more than the stripped version does. *Worked
example:* the corrected breakdance clip moved root-dominant vertices 53.30 engine units,
while the broken current-root inverse produced about 1.41 units of leaked secondary motion.

## 5. What is compressed

**Do not evaluate the bone palette on the V810.** Skinning hundreds of joints per frame is
not affordable at any useful frame rate on a 21 MHz CPU with no FPU. The offline tool
evaluates the shared skin for each source animation frame and stores the resulting
**object-space int16 XYZ vertices**.

This is not screen-pose baking. The V810 still performs, every rendered frame:

```text
object translation
object Y rotation
camera-relative depth
perspective and user zoom
viewport clipping
backface culling
exact depth ordering
8bpp texture rasterization
black outline
native 256x240 affine KING presentation
```

Therefore the same clip remains valid when the object moves in world space, spins, or
zooms. A new animation only adds another object-space clip.

Tradeoff: skeletal blending, procedural IK, or per-bone runtime reactions are not present
in this format. Those require a bone-palette runtime or a hybrid representation. State
this limitation accurately.

## 6. PCA1 clip format

All fields are little-endian. Each clip is an independently loadable file inside one
sector-padded archive.

```c
struct PcaHeader {                 /* 40 bytes */
    char     magic[4];             /* "PCA1" */
    uint16_t version;              /* 1 */
    uint16_t header_size;
    uint16_t vertex_count;
    uint16_t frame_count;
    uint16_t fps_num;
    uint16_t fps_den;
    uint16_t flags;
    uint16_t reserved;
    uint32_t directory_offset;
    uint32_t data_offset;
    uint32_t file_size;
    uint32_t max_decoded_frame_bytes;
    uint32_t max_compressed_frame_bytes;
};

struct PcaFrameEntry {             /* 8 bytes */
    uint32_t offset;
    uint16_t decoded_bytes;
    uint8_t  kind;                 /* 0 absolute, 1 delta-i8 */
    uint8_t  reserved;
};
```

Frame representation:

```text
frame 0: interleaved absolute int16 x,y,z for all vertices
frame N kind 1: interleaved XYZ signed-byte deltas from frame N-1
frame N kind 2: component-planar X..., Y..., Z... signed-byte deltas
                byte 0x80 escapes to a following signed int16 delta
```

The escape keeps the format valid for future clips with larger motion. The supplied clips
used no escapes, but the decoder must support them and the validator must test them.

After root motion is preserved, per-vertex deltas may vary smoothly by component but not
compress well when XYZ values are interleaved.  Generate both exact layouts, raw-LZ4
compress both, and choose the smaller block per frame.  The V810 planar decoder walks
three component planes and scatters into the same interleaved `CharacterVertex` array.
This changes storage only; decoded vertex bytes and rendered output must be identical.
Avoid division in the decoder: use nested `component` and `vertex` loops with a destination
index incremented by three.

Each frame payload is stored as:

```text
uint16 little-endian compressed_byte_count
raw LZ4 block bytes
```

It is a raw block, not an LZ4 frame. The decoder contract is a block of at most 64 KiB,
with the two-byte compressed length supplied outside the block. When the host `lz4` tool
chooses an uncompressed frame block, synthesize a legal literal-only raw block instead.
Never pass a frame header to the V810 depacker.

## 7. Deterministic converter workflow

The converter should accept explicit paths rather than hard-coded clip names:

```sh
python3 tools/build_character_animation_assets.py \
  --base-source assets/source/character/base/character_base_source.dae \
  --animations-dir assets/source/character/animations \
  --clips-manifest assets/source/character/animations/manifest.json \
  --texture-dir assets/source/character/base/textures \
  --out-assets src/assets \
  --out-generated assets/generated/character \
  --base-dae assets/source/character/base/character_base.dae
```

Generated outputs should include:

```text
character_model.h               animation-safe mesh and faces
character_animations.h          clip LBA/length/rate table
character_animations.pca        sector-padded clip archive
character_animations.json       hashes, counts, compression and validation metadata
scene_textures.h / palette      deterministic runtime art
character_base.dae              shared rig without animation libraries
```

Commit generated metadata and hashes. A rebuild from the same source must produce the
same archive SHA-256.

Record the RAM headroom explicitly: the largest resident clip plus the largest decoded
frame plus the program must fit in 2 MiB, and the check belongs in the converter, not in
your head. *Worked example* (twelve clips):

```text
archive bytes:             3,229,696
largest resident clip:       827,392 bytes
largest decoded frame:        37,476 bytes
linked RAM headroom:          194,400 bytes below 2 MiB
archive SHA-256:
645bf542b43948cc2051d30cfe94c889a1d4657a17de66afe07cad903b3d5928
```

## 8. Archive validator

Do not validate only headers. Decode every frame and prove the cumulative delta stream:

```python
for clip in archive:
    vertices = None
    digest = hashlib.sha256()
    for frame in clip.frames:
        raw = decode_raw_lz4(frame.block)
        if frame.kind == ABSOLUTE:
            vertices = unpack_i16_xyz(raw)
        elif frame.kind == DELTA_I8:
            apply_interleaved_component_deltas(vertices, raw)
        elif frame.kind == DELTA_PLANAR_I8:
            apply_planar_component_deltas(vertices, raw)
        else:
            raise AssertionError("unknown frame kind")
        digest.update(pack_i16_xyz(vertices))
    assert digest.hexdigest() == report[clip.slug]["frame_vertices_sha256"]
```

Also assert:

```text
clip offsets and sizes are inside the archive
clip starts are sector aligned
frame entries and compressed lengths remain inside the clip
vertex count matches the animation-safe base
absolute frame decoded size is vertex_count * 6
all frames are reachable in order
manifest order equals generated runtime order
manifest root-motion mode equals generated metadata
animated top-root motion reaches Root/Hip/Waist/Chest-dominant vertices
loop-in-place clips return to their frame-zero root position
```

## 9. Keep the animation archive off the BIOS-loaded image

Do not concatenate a multi-megabyte archive into the program passed to `pcfx-cdlink`.
That consumes the shared 2 MiB main RAM before runtime and delays boot.

Correct layout:

```text
base disc built by pcfx-cdlink: boot program only
fixed/published asset start LBA: after the base-disc sector count
final disc image: base disc + sector-padded PCA archive
runtime header: generated archive LBA
```

Use a deterministic packager and rebuild once if the generated LBA changes. *Worked
example:* archive at LBA 300, BIOS loading 237,568 bytes of code/data, `pcfx-cdlink`
reporting 1,824,768 bytes free for stack/heap before BSS/runtime allocation. Read your own
LBA and free-space figures out of the packager and `pcfx-cdlink` output every build.

Never assume the previous LBA after code size changes. The packager must compare the base
disc sector count with the generated header and trigger the second compile/link pass.

## 10. Load one clip with KING SCSI DMA

Keep only one compressed clip resident. Loading on clip selection is preferable to making
all clips resident in 2 MiB RAM.

The verified path uses `eris_cd_read_dma` through a high page-1 KRAM bounce window:

```c
#define KRAM_PHYS_PAGE1                    0x80000000u
#define CHARACTER_CD_DMA_SCRATCH_WORD      0x30000u
#define CHARACTER_CD_DMA_SCRATCH_WORDS     0x10000u  /* 128 KiB */

king_set_page_setting(SCSI_PAGE_SETTING |
                      RAINBOW_PAGE_SETTING | ADPCM_PAGE_SETTING);

int ok = eris_cd_read_dma(archive_lba + clip->relative_lba,
                          clip_buffer,
                          clip->file_bytes,
                          KRAM_PHYS_PAGE1 | CHARACTER_CD_DMA_SCRATCH_WORD,
                          CHARACTER_CD_DMA_SCRATCH_WORDS);

king_set_page_setting(RAINBOW_PAGE_SETTING | ADPCM_PAGE_SETTING);
```

The bit-31 page qualifier is mandatory. Without it, DMA can write page 1 while the SDK
verification probe reads page 0, falsely reports failure, and retries indefinitely.
This appears as a frozen initialized background rather than an obvious CD error.

After a successful load:

```text
decode frame 0
invalidate software dirty bounds
invalidate all three KING page dirty histories
invalidate raster upload shadows
request a full first redraw
keep the last completed display page visible during the load
```

Do not leave stale pixels from the previous clip on a newly selected animation.

Check which archive actually provides the DMA entry point before setting `LDLIBS`: in this
workspace it lives in the newer PC-FX archive while other established APIs remain in the
Eris archive, so the strict build links `-leris -lpcfx`. Audit the
map/ELF and reject timer/IRQ infrastructure if the project contract forbids handlers.

## 11. Runtime decoder

Absolute frame:

```c
if (lz4_depack(block_with_u16_length, vertices) != vertex_count * 6u)
    fail();
```

Delta frame:

```c
if (lz4_depack(block_with_u16_length, scratch) != decoded_bytes)
    fail();

int16_t *dst = (int16_t *)vertices;
const uint8_t *src = scratch;
for (uint32_t i = 0; i < vertex_count * 3u; ++i) {
    uint8_t code = *src++;
    int16_t delta;
    if (code == 0x80) {
        delta = (int16_t)(src[0] | ((uint16_t)src[1] << 8));
        src += 2;
    } else {
        delta = (int16_t)(int8_t)code;
    }
    dst[i] = (int16_t)(dst[i] + delta);
}
```

Frame wrap must reload/decode frame 0 because the last frame's deltas are not defined as a
transition back to the first frame.

The simplest playback policy advances one source animation frame per **rendered** frame. This
preserves every source frame but plays below the original 30 Hz when rendering is slow.
For time-correct playback, add a field-based accumulator and allow deterministic frame
skips while preserving cumulative state by decoding intervening deltas or using periodic
absolute keyframes. Do not simply jump into a delta chain.

## 12. Viewer controls

Use edge-triggered selection/reset and level-triggered zoom/rotation. Determine
which object yaw is actually front-facing from the imported rig; do not assume
yaw 0 means the character faces the camera. In the reference asset, yaw 0 shows
the back and yaw 128 is the front-facing default:

```c
uint32_t pad = eris_pad_read(0);
uint32_t pressed = pad & ~previous_pad;
previous_pad = pad;

if (pressed & JOY_LEFT)       select_relative(-1);
else if (pressed & JOY_RIGHT) select_relative(+1);
else if (pressed & JOY_UP)    select_relative(-5);
else if (pressed & JOY_DOWN)  select_relative(+5);

if ((pad & JOY_II) && !(pad & JOY_III))
    object.pos_z = clamp(object.pos_z + 8, -680, -480);
else if ((pad & JOY_III) && !(pad & JOY_II))
    object.pos_z = clamp(object.pos_z - 8, -680, -480);

if ((pad & JOY_V) && !(pad & JOY_VI))
    object_yaw = (object_yaw - 2) & 255;
else if ((pad & JOY_VI) && !(pad & JOY_V))
    object_yaw = (object_yaw + 2) & 255;

if (pressed & JOY_IV) {
    object.pos_z = DEFAULT_Z;
    object_yaw = FRONT_YAW;       /* 128 for this imported rig */
    load_clip(IDLE_CLIP);
}
```

Verified mapping:

```text
D-pad Left/Right: previous/next animation
D-pad Up/Down:    minus/plus five animations
Button II:        zoom in while held
Button III:       zoom out while held
Button IV:        reset to Idle, default zoom, frame zero and front yaw
Button V:         rotate toward decreasing Y yaw while held
Button VI:        rotate toward increasing Y yaw while held
V + VI together:  neutral
```

Clip index wrapping must work for negative steps. Do not use unsigned `%` on a negative
intermediate.

## 13. Performance result and interpretation

*Worked example.* Two identical 600-field profiler captures of one corrected
animation-enabled dynamic renderer (6,246 vertices / 11,508 faces, native 256×240):

```text
presented FPS:                  2.800
DRAM penalty cycles/field:     40,959
  data:                        40,104
  code refill:                    854
i-cache misses/field:             683
i-cache miss rate:              0.320%
CPI:                            2.167
instructions/field:           165,070
```

Clip changes incur CD DMA and decompression outside ordinary per-frame playback; report
that load latency separately if you are optimizing transitions.

The generalizable reading of a profile like this: an i-cache miss rate of 0.3% means the
remaining cost is **not** a self-thrashing hot loop, so realigning code will not help —
the DRAM data penalty (here 98% of the penalty cycles) is where the frame is going.
Profile per-symbol and per-stage cycles and fix access order before adding tables or unpack
cleverness. Compression ratio does not predict frame rate. See [pcfx-self-improve] §3.


## 14. Idle, T-pose, HUD timing, and no-spin viewer defaults

A viewer must distinguish a user-facing default from a diagnostic fallback:

```text
clip 0: IDLE      ordinary startup/reset animation
clip 1: T POSE    one-frame bind-pose fallback and rig diagnostic
```

Do not call a dance clip “base”. The base is the shared rig/mesh asset, not an
animation. Keep automatic object yaw disabled by default so users can inspect the
actual animation.

**Do not assume yaw 0 faces the camera.** Establish a named `FRONT_YAW` constant by
rendering the rig at several yaws and looking at the images ([pcfx-vision-assets]); in the
worked-example rig the front is yaw **128** and yaw 0 shows the character's back. Game code
and Button V/VI may still set yaw or translation explicitly, and reset must restore
`FRONT_YAW`.

Display the manifest name beneath the numeric clip/frame row. Keep names uppercase or
pre-generate glyph-safe display strings so the V810 does not allocate or case-fold.

Do not compute a HUD frame rate by sampling TETSU only when long rendering stages return.
A 3 FPS renderer can miss nine of ten raster wraps and falsely display 30 FPS. If timer or
IRQ infrastructure is forbidden, embed a profiler-qualified build value:

```c
#ifndef PCFX_PROFILED_FPS_X10
#define PCFX_PROFILED_FPS_X10 28
#endif

static uint16_t hud_fps_x10(void)
{
    return PCFX_PROFILED_FPS_X10;  /* 2.8, measured externally */
}
```

The authoritative measurement remains `(nframe delta * 60) / profiler_fields` from two
RAM dumps started from the same warmed savestate. Label the HUD value as a profiled build
average; never call it a live timer.

## 15. PAS1 face schedules for predetermined animations

A useful middle ground exists between a fully dynamic renderer and cached screen images.
For each known animation frame, precompute only the exact visible source-face order for a
validated default yaw. Store no pixels and no projected vertices. The runtime can skip
backface culling and stable depth sorting while retaining live translation, zoom,
perspective, rasterization, textures, outline, and native 256x240 output.

```text
PAS1 global directory
  per-clip PSC1 directory
    per-frame raw-LZ4 block of uint16 source face indices
```

Mandatory fallback conditions:

```text
object yaw differs from the schedule yaw
clip/frame absent from the archive
visibility or viewport assumptions are violated
animated topology/controller differs from the validated base
```

*Worked example:* a twelve-clip cache covering 714 source frames, generated for
front-facing yaw 128, using the same per-clip root-motion policy as PCA1, occupying
4,881,191 bytes and storing no framebuffer data. Note the size — a face schedule is
typically **larger** than the vertex clips it accelerates, which is why it streams.

Do not load an entire largest schedule clip beside the largest PCA1 clip unless RAM math
proves it fits. Prefer one-frame CD/KRAM streaming, a small schedule window, or delta-coded
face-order changes. Keep the dynamic cull/sort path as the authoritative fallback.

## 16. Implementation checklist

Execute these in order and stop on the first failed assertion. Every count referenced here
comes from your own manifest and generated metadata.

```text
[ ] Read the base DAE and every manifest clip.
[ ] Hash and compare topology, controller, bind matrices, joint order and hierarchy.
[ ] Build runtime vertices with UV/material plus complete influence signature.
[ ] Never force the old static vertex count onto the animated mesh.
[ ] Evaluate skinning offline into object-space int16 XYZ frames.
[ ] Normalize against frame-zero root, never the current animated root.
[ ] Select preserve or loop_in_place root motion explicitly in the manifest.
[ ] Validate Root/Hip/Waist/Chest movement against the legacy stripped result.
[ ] Store frame 0 absolute; store later signed-byte deltas with 0x80/int16 escape.
[ ] Compress both interleaved and planar delta layouts; keep the smaller exact block.
[ ] Compress each frame as one raw LZ4 block with a two-byte LE length.
[ ] Sector-align each clip and generate relative LBA/size/rate metadata.
[ ] Decode every frame on the host and compare cumulative frame SHA-256 values.
[ ] Strip animation libraries from the generated shared base DAE.
[ ] Keep the PCA archive outside the BIOS-loaded program image.
[ ] Rebuild if the archive start LBA changes.
[ ] Load one clip with KING DMA through a non-overlapping page-1 bounce window.
[ ] Include bit 31 in the KRAM DMA scratch address.
[ ] Decode frame 0 after load and invalidate all dirty/upload histories.
[ ] Map D-pad and II-VI with edge/level behavior exactly as specified.
[ ] Put Idle first and T-pose second; do not use a dance as the base/default clip.
[ ] Disable automatic world yaw; establish and validate the rig-specific FRONT_YAW.
[ ] Display the manifest animation name beneath the numeric clip/frame HUD.
[ ] Never derive HUD FPS from sparse raster-wrap observations around long hot loops.
[ ] Treat PAS1 face schedules as optional acceleration with a dynamic fallback, not as screen-frame caching.
[ ] Test every control from one warmed savestate and inspect RAM state, not only screenshots.
[ ] Clean-build and audit the final ELF for forbidden runtime helpers.
[ ] Profile two runs from the same warm state and report FPS, DRAM and i-cache counters.
[ ] Do not call object-space vertex clips screen-pose caching.
```

## 17. Acceptance gates

A release is not complete until all are true:

```text
[ ] shared base DAE retains mesh, skeleton, skin controller and inverse binds
[ ] generated base DAE contains no animation libraries
[ ] every clip passes exact rig/controller hash checks
[ ] animation-safe vertex/face counts are recorded and stable
[ ] every decoded clip frame matches its committed SHA-256
[ ] animated root motion reaches Root/Hip/Waist/Chest-dominant vertices
[ ] walk/run loop-in-place clips close within one quantized coordinate unit
[ ] archive regeneration is byte-identical
[ ] archive is CD-resident, not BIOS-loaded
[ ] all manifest clips load with load_failed == 0
[ ] D-pad selection, zoom, V/VI opposite yaw and reset pass scripted input tests
[ ] native 256x240, textures and black outline remain enabled
[ ] arbitrary object translation/yaw/zoom remains available at runtime even though viewer auto-spin defaults off
[ ] final map/ELF passes the freestanding dependency audit
[ ] profiler result is reproducible and labeled emulator-only
```

## Related

`pcfx-character-8bpp` for native raster/texture/outline fidelity ·
`pcfx-cd-assets` for disc layout and DMA · `pcfx-kram-layout` for bounce-window planning ·
`pcfx-input` for pad semantics · `pcfx-v810-profiling` · `pcfx-freestanding-runtime`
