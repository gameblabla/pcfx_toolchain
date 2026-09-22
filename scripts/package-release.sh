#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

pcfx_need_command tar
pcfx_need_command sha256sum

mkdir -p "$PCFX_PREBUILT_DIR" "$PCFX_REPO_ROOT/dist"

if [[ -x "$PCFX_BIN_DIR/pcfx-headless" ]]; then
    echo "PACKAGE using staged binaries from $PCFX_PREBUILT_DIR"
else
    echo "PACKAGE warning: no pcfx-headless staged; archive will remain source-only for that component" >&2
fi

if [[ -d "$PCFX_PREBUILT_DIR/v810-gcc" ]]; then
    echo "PACKAGE including prebuilt V810 toolchain"
else
    echo "PACKAGE warning: no prebuilt/v810-gcc; run scripts/build-toolchain.sh to include it" >&2
fi

find "$PCFX_PREBUILT_DIR" -type f -print0 | sort -z | xargs -0 sha256sum \
    > "$PCFX_PREBUILT_DIR/SHA256SUMS"

release_version="${PCFX_RELEASE_VERSION:-$(date -u +%Y%m%d)}"
release_name="pcfx-toolkit-$release_version"
release_path="$PCFX_REPO_ROOT/dist/$release_name.tar.gz"
rm -f "$release_path"

tar -czf "$release_path" \
    --exclude='./.git' --exclude='./.git/*' \
    --exclude='*/.git' --exclude='*/.git/*' \
    --exclude='./dist' --exclude='./dist/*' \
    --exclude='./build' --exclude='./build/*' \
    --exclude='./bios' --exclude='./bios/*' \
    --exclude='./pcfx.rom' --exclude='./pcfxbios.bin' \
    --exclude='./pcfxv101.bin' --exclude='./pcfx_bios.bin' \
    --exclude='./pcfxga.rom' --exclude='./pcfxga.bin' \
    --exclude='*/build' --exclude='*/build/*' \
    --exclude='examples/*/*.o' \
    --exclude='examples/*/*.elf' \
    --exclude='examples/*/*.map' \
    --exclude='examples/*/*.bin' \
    --exclude='examples/*/*.cue' \
    --exclude='examples/*/*.ex' \
    --exclude='examples/*/out.bin' \
    --exclude='examples/*/lbas.h' \
    --exclude='examples/*/assets/*.dat' \
    --exclude='vendor/*/src/*.o' \
    --exclude='vendor/*/*.a' \
    --exclude='*/__pycache__' --exclude='*/__pycache__/*' \
    -C "$PCFX_REPO_ROOT" .

sha256sum "$release_path" > "$release_path.sha256"
echo "PACKAGE wrote $release_path"
echo "PACKAGE wrote $release_path.sha256"
