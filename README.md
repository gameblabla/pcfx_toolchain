# PC-FX homebrew toolkit

This is a self-contained working bundle for making NEC PC-FX/V810 homebrew: compiler
source, `libpcfx`, CD tools, a headless emulator, a large-game asset pipeline, working
examples, and the local PC-FX skill bundle for AI-assisted development.

The source dependencies are pinned as submodules:

| Component | Location | Role |
|---|---|---|
| V810 GCC | `vendor/v810-gcc` | GCC 4.9.4, binutils, newlib, and build scripts |
| libpcfx | `vendor/libpcfx` | runtime, linker script, hardware APIs, examples |
| pcfxtools | `vendor/pcfxtools` | original `bincat`, `pcfx-cdlink`, `huobj`, `hulib` |
| pcfxemu | `vendor/pcfxemu` | `seek_improvements` headless emulator and PC-FXGA support |
| Doom PC-FX | `vendor/doompcfx` | ambitious game/reference implementation |

## Quick start

```sh
git submodule update --init --recursive
./scripts/doctor.sh
./scripts/build-host-tools.sh
./scripts/build-sdk.sh
./scripts/build-headless.sh

make -C examples/hello cd
PCFX_BIOS_DIR="$PWD/bios" \
  ./scripts/run-headless.sh --pcfx --frames 1800 \
  --screenshot build/hello.png examples/hello/game.cue
```

### BIOS and emulator locations

The toolkit does not include a PC-FX BIOS. Put your legally obtained standard BIOS at
`bios/pcfx.rom` relative to the toolkit root. `bios/` is ignored locally and is never
committed or packaged. Then point the emulator at that directory:

```sh
mkdir -p bios
# Copy your legally obtained dump to: bios/pcfx.rom
export PCFX_BIOS_DIR="$PWD/bios"
```

`pcfx-headless` accepts either this BIOS directory or the BIOS file itself through
`--bios-dir`. If no directory is supplied, the emulator also searches its normal
`$HOME/.pcfxemu` and `$HOME/.pcfxemu/bios` locations. The PC-FXGA BIOS may be placed in
the same directory under an accepted PC-FXGA name when using `--pcfxga`.

The expected bundled emulator path is
`$PCFX_TOOLKIT_ROOT/prebuilt/bin/pcfx-headless`; run `./scripts/build-headless.sh` to
create it. `scripts/run-headless.sh` uses that staged binary automatically, or you can
override it with `PCFX_HEADLESS=/path/to/pcfx-headless`. A source-tree build may also
exist at `vendor/pcfxemu/pcfx-headless`, but the staged `prebuilt/bin` path is the
release and script default.

`/opt/v810-gcc` is detected when present. Otherwise build or copy a toolchain into
`prebuilt/v810-gcc`, or export `V810GCC=/path/to/v810-gcc`. The scripts never download
a BIOS, and the ignored local `bios/` directory is never committed or packaged.

The copied `PCFX_Skills/` folder is the AI-facing reference. Start with
`PCFX_Skills/SKILLS.md`, then open the named `SKILL.md` in full. For a local `pi`
server, use `PCFX_LLM_ENDPOINT=http://127.0.0.1:8080 PCFX_SKILL_MODE=router PCFX_Skills/pi_pcfx.sh "..."`
(the wrapper accepts the existing `PCFX_LLM_*`
variables; `0.0.0.0` is a bind address, so `127.0.0.1` is normally the client URL).
If `pi` is unavailable, generate a prompt with:

```sh
python3 PCFX_Skills/eval/build_prompt.py --mode select \
  --skills pcfx-bringup,pcfx-emulator-testing --out build/pcfx-system.md
```

## Large games

The original `bincat` is useful for small examples but is not the default large-asset
path. It reads whole files into memory and has 32-bit bookkeeping. The local Doom
workspace supplied an enhanced `pcfx-cdlink` with streamed `append`/`asset` files,
generated LBA headers, and optional CD-DA track handling. That source is preserved at
`tools/large-game/pcfxtools/` and is built as `prebuilt/bin/pcfx-cdlink-large`.

The imported Doom scripts are under `tools/large-game/doom/`; the most generally useful
ones are `bake_wad.py`, `gen_pcfx_packs.py`, `gen_pcfx_cdassets.py`, `lz4_block.py`,
`pcfx_sum32.py`, and the V810/KING profiler readers. See
`examples/large-cd-assets/README.md` for a minimal streamed-data build.

## PC-FXGA / HuEXE

`tools/hu_exe.py` converts V810 ELF `PT_LOAD` segments into the `HuEXE001` executable
container understood by the imported `pcfxemu` branch. `examples/hello-huexe/` shows
the build. Run it with `--pcfxga` and a compatible BIOS. This avoids the standard
PC-FX disc boot path; it does not magically provide a missing BIOS to the emulator.

## Release bundle

Build the host tools, SDK, and emulator, then create a source-plus-binaries archive:

```sh
./scripts/build-host-tools.sh
./scripts/build-toolchain.sh
./scripts/build-sdk.sh
./scripts/build-headless.sh
./scripts/package-release.sh
./scripts/verify-release.sh dist/*.tar.gz
```

The tarball contains the initialized source submodules, copied skills, examples,
Python scripts, host binaries, `pcfx-headless`, and (when a toolchain is available)
the prebuilt V810 toolchain. It excludes Git metadata, build scratch files, and BIOSes.

## References

- [v810-gcc](https://github.com/jbrandwood/v810-gcc)
- [pcfxtools](https://github.com/jbrandwood/pcfxtools)
- [libpcfx](https://github.com/gameblabla/libpcfx)
- [doompcfx](https://github.com/gameblabla/doompcfx)
- [pcfxemu](https://github.com/gameblabla/pcfxemu/tree/seek_improvements)
