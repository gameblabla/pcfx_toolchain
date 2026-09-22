# Large external CD asset example

This example demonstrates the safer layout for a game whose data is larger than
the boot program can leave in the 2 MiB main-RAM budget:

```text
main.c + libpcfx  -> build/large_assets_boot.bin  (BIOS-loaded)
assets/large_blob.dat                           (external CD sectors)
                         -> pcfx-cdlink-large -> large_assets_disc.cue/.bin
```

Build and inspect the generated LBA header:

```sh
../../scripts/build-host-tools.sh
make cd
make inspect
```

`pcfx-cdlink-large` streams the boot and appended files, pads them to 2048-byte
sectors, keeps external assets out of the boot header's `sect_count`, and writes
`build/lbas.h`. The generated macro for this example is
`BINARY_LBA_ASSETS_LARGE_BLOB_DAT`; a real game would include that header and add
the LBA to its CD read routine.

The fixture is generated rather than committed so this repository stays small. The
same manifest accepts a WAD, compressed map pack, video blob, or other large file.
For Doom-derived pipelines, see `../../tools/large-game/doom/` and the checked-in
`vendor/doompcfx` reference.
