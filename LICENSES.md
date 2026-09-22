# Source and license notes

The top-level orchestration scripts and examples in this repository are provided
under the MIT license unless a file says otherwise.

The five `vendor/` directories are Git submodules and retain their upstream license
files and histories. In particular:

- `vendor/v810-gcc/` contains the GNU toolchain sources and patches.
- `vendor/libpcfx/` is MIT-licensed PC-FX library code.
- `vendor/pcfxtools/` is MIT-licensed.
- `vendor/pcfxemu/` retains its Mednafen and dependency license notices.
- `vendor/doompcfx/` retains the reference port's license/readme information.

`tools/large-game/pcfxtools/` is the enhanced `pcfx-cdlink` source copied from the
local Doom PC-FX workspace. Its `LICENSE` and attribution remain next to the source.
The Python tooling under `tools/large-game/doom/` is likewise kept as a source
snapshot with its original file headers.

No PC-FX, PC-FXGA, commercial game, or other copyrighted BIOS image is distributed
by this repository.
