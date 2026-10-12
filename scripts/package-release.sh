#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

pcfx_need_command tar
pcfx_need_command sha256sum

mkdir -p "$PCFX_TOOLCHAIN_DIR" "$PCFX_REPO_ROOT/dist"

if [[ -x "$PCFX_BIN_DIR/pcfx-headless" ]]; then
    echo "PACKAGE using bundled binaries from $PCFX_TOOLCHAIN_DIR"
else
    echo "PACKAGE warning: no pcfx-headless bundled; archive will remain source-only for that component" >&2
fi

if [[ -d "$PCFX_TOOLCHAIN_DIR/v810-gcc" ]]; then
    echo "PACKAGE including bundled V810 toolchain"
else
    echo "PACKAGE warning: no toolchain/v810-gcc; run scripts/build-toolchain.sh to include it" >&2
fi

(cd "$PCFX_TOOLCHAIN_DIR" && find . -type f ! -name 'SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum) \
    > "$PCFX_TOOLCHAIN_DIR/SHA256SUMS"

release_version="${PCFX_RELEASE_VERSION:-$(date -u +%Y%m%d)}"
release_name="pcfx-toolkit-$release_version"
release_path="$PCFX_REPO_ROOT/dist/$release_name.tar.gz"
rm -f "$release_path"

release_paths=(
    .agents/skills
    .gitignore
    .gitmodules
    .opencode/skills
    AGENTS.md
    DOCUMENTATION
    LICENSES.md
    Makefile
    PCFX_Skills
    README.md
    examples
    scripts
    toolchain
    tools
    vendor
)

tar -czf "$release_path" \
    --exclude='.git' --exclude='*/.git' --exclude='*/.git/*' \
    --exclude='*/build' --exclude='*/build/*' \
    --exclude='*/__pycache__' --exclude='*/__pycache__/*' \
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
    --exclude='vendor/pcfx_rainbow_mp2_adpcm/*.bin' \
    --exclude='vendor/pcfx_rainbow_mp2_adpcm/*.cue' \
    --exclude='vendor/pcfx_rainbow_mp2_adpcm/assets' \
    --exclude='vendor/pcfx_rainbow_mp2_adpcm/assets/*' \
    --exclude='vendor/pcfx_rainbow_mp2_adpcm/validation' \
    --exclude='vendor/pcfx_rainbow_mp2_adpcm/validation/*' \
    --exclude='pcfx.rom' --exclude='*/pcfx.rom' \
    --exclude='pcfxbios.bin' --exclude='*/pcfxbios.bin' \
    --exclude='pcfxv101.bin' --exclude='*/pcfxv101.bin' \
    --exclude='pcfx_bios.bin' --exclude='*/pcfx_bios.bin' \
    --exclude='pcfxga.rom' --exclude='*/pcfxga.rom' \
    --exclude='pcfxga.bin' --exclude='*/pcfxga.bin' \
    -C "$PCFX_REPO_ROOT" \
    "${release_paths[@]}"

sha256sum "$release_path" > "$release_path.sha256"
echo "PACKAGE wrote $release_path"
echo "PACKAGE wrote $release_path.sha256"
