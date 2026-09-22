# PC-FX homebrew toolkit

This repository is a reproducible PC-FX/V810 development bundle. Read
`PCFX_Skills/AGENTS.md` and `PCFX_Skills/SKILLS.md` before making hardware claims or
changing a sample. The copied skills are the measured local reference for KING,
Tetsu, VDC, KRAM, timing, fixed-point math, V810 performance, CD assets, and
headless testing.

## Layout

- `vendor/v810-gcc/` — pinned GCC 4.9.4/binutils/newlib build source.
- `vendor/libpcfx/` — pinned PC-FX SDK, linker script, runtime, and examples.
- `vendor/pcfxtools/` — original small host tools, retained for compatibility.
- `vendor/pcfxemu/` — pinned `seek_improvements` emulator source and headless build.
- `vendor/doompcfx/` — ambitious Doom PC-FX reference implementation.
- `PCFX_Skills/` — copied local AI skill bundle, including the `pi` wrapper and evals.
- `tools/large-game/doom/` — imported larger-game asset/profiling scripts from the
  local Doom workspace.
- `tools/large-game/pcfxtools/` — enhanced `pcfx-cdlink` source used for streamed
  `append` assets, LBA headers, and optional CD-DA tracks.
- `examples/` — small bring-up, HuEXE, and large-CD-asset projects.
- `scripts/` — dependency checks, builds, emulator execution, and release packaging.

## Non-negotiable facts

- Do not invent PC-FX register semantics. Use the copied skills, `libpcfx`, the
  manuals in `DOCUMENTATION/`, and the emulator source.
- The V810 has no FPU. Performance-critical code uses fixed-point arithmetic.
- A clean emulator run is not proof of retail hardware correctness.
- Do not put a PC-FX or PC-FXGA BIOS in this repository or in a release tarball.
  Supply a legally obtained dump through `PCFX_BIOS_DIR` or `--bios-dir` locally.
- A HuEXE/PC-FXGA executable bypasses the normal bootable-CD path and is the useful
  fallback when a project cannot make a standard disc image. The current headless
  emulator still needs a compatible BIOS image to initialize its machine; it is not
  a BIOS-free emulator.

## Normal workflow

```sh
git submodule update --init --recursive
./scripts/doctor.sh
./scripts/build-host-tools.sh
./scripts/build-sdk.sh
./scripts/build-headless.sh
make -C examples/hello cd
PCFX_BIOS_DIR=/path/to/bios ./scripts/run-headless.sh \
    --pcfx --frames 1800 --screenshot build/hello.png examples/hello/game.cue
```

For a new project, use `scripts/new-project.sh NAME DEST` and begin from the verified
bring-up template. For a large game, keep only the boot program in the BIOS-loaded
region and put large data behind `append` in `cdlink.txt`; inspect the generated LBA
header before writing a loader.
