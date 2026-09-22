#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

pcfx_need_command bash
pcfx_need_command python3
pcfx_need_command rg

for script_path in "$PCFX_REPO_ROOT"/scripts/*.sh "$PCFX_REPO_ROOT"/PCFX_Skills/pi_pcfx.sh; do
    bash -n "$script_path"
done

python3 - "$PCFX_REPO_ROOT/tools/hu_exe.py" "$PCFX_REPO_ROOT/tools/pcfx_large_game.py" <<'PY'
import ast
import pathlib
import sys
for name in sys.argv[1:]:
    ast.parse(pathlib.Path(name).read_text(), filename=name)
    print("python syntax ok:", name)
PY

if rg -n --hidden -g '!**/.git/**' -g '!*.pyc' \
    -e '/home/' -e '/tmp/' -e '/mnt/' -e '/opt/' -e '/usr/local/' -e '/root/' \
    -e '\$HOME' -e '~/' -e 'DoomPCFX' -e '3dcar' -e 'dirty_pair' \
    "$PCFX_REPO_ROOT/PCFX_Skills" >/dev/null; then
    pcfx_die "PCFX_Skills contains a machine-specific or hardcoded workspace path"
fi

nested_git_dir="$(find "$PCFX_REPO_ROOT/PCFX_Skills" -type d -name .git -print -quit)"
[[ -z "$nested_git_dir" ]] || pcfx_die "copied PCFX_Skills contains embedded Git metadata: $nested_git_dir"
echo "VERIFY  PCFX_Skills paths and copied-folder metadata passed"

for required_path in \
    "$PCFX_REPO_ROOT/.gitmodules" \
    "$PCFX_REPO_ROOT/PCFX_Skills/SKILLS.md" \
    "$PCFX_REPO_ROOT/vendor/libpcfx/ldscripts/v810.x" \
    "$PCFX_REPO_ROOT/vendor/pcfxemu/Makefile.headless" \
    "$PCFX_REPO_ROOT/tools/large-game/pcfxtools/pcfx-cdlink.c"; do
    [[ -e "$required_path" ]] || pcfx_die "missing required path: $required_path"
done

git -C "$PCFX_REPO_ROOT" submodule status
echo "VERIFY  repository structure and shell/Python syntax passed"

if [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" &&
      -x "$PCFX_TOOLCHAIN_DIR/v810-gcc/bin/v810-gcc" ]]; then
    echo "VERIFY  Linux x86_64 V810 toolchain present"
fi

if [[ -n "${1:-}" ]]; then
    archive_path="$1"
    [[ -f "$archive_path" ]] || pcfx_die "release archive not found: $archive_path"
    tar -tzf "$archive_path" >/dev/null
    if tar -tzf "$archive_path" | rg '(^|/)\.git($|/)|(^|/)PCFX_Skills/(home($|/)|\.git($|/))' >/dev/null; then
        pcfx_die "release archive contains Git metadata or copied source-path artifacts"
    fi
    if tar -tzf "$archive_path" | rg -i '(^|/)(pcfx\.rom|pcfxga\.rom|pcfxbios\.bin|pcfxv101\.bin|pcfx_bios\.bin|pcfxga\.bin)$' >/dev/null; then
        pcfx_die "release archive appears to contain a BIOS-like file"
    fi
    if [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" &&
          -x "$PCFX_TOOLCHAIN_DIR/v810-gcc/bin/v810-gcc" ]]; then
        if ! tar -tzf "$archive_path" | rg -Fx './toolchain/v810-gcc/bin/v810-gcc' >/dev/null; then
            pcfx_die "release archive is missing the Linux V810 toolchain"
        fi
    fi
    echo "VERIFY  release archive readable and BIOS scan passed: $archive_path"
fi
