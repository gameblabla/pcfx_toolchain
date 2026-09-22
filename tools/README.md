# Toolkit-local tools

- `hu_exe.py` bridges V810 ELF `PT_LOAD` segments to the `HuEXE001` PC-FXGA format
  accepted by the imported `pcfxemu` headless loader.
- `pcfx_large_game.py` generates streamed-CD manifests and deterministic test assets.
- `large-game/pcfxtools/pcfx-cdlink.c` is the enhanced CD linker copied from the
  local Doom PC-FX workspace. It supports `append`/`asset`, `lbaheader`, `cddadir`,
  and `cddaheader` directives while keeping the boot `sect_count` separate from
  external data.
- `large-game/doom/` contains the local Doom asset, LZ4, checksum, CD, and profiling
  scripts that are useful beyond Doom. Read each script's header before reusing it.
