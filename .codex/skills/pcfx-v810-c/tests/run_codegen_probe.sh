#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
toolchain=$(printenv PCFX_V810_GCC || true)
if [[ -z "$toolchain" ]]; then toolchain=$(printenv V810_GCC || true); fi
if [[ -z "$toolchain" ]]; then toolchain=$(printenv V810GCC || true); fi
if [[ -z "$toolchain" ]]; then toolchain="$repo_root/toolchain/v810-gcc"; fi
compiler="$toolchain/bin/v810-gcc"
out=$(printenv PCFX_PROBE_OUT || true)
if [[ -z "$out" ]]; then
    tmpdir=$(printenv TMPDIR || true)
    if [[ -z "$tmpdir" ]]; then tmpdir=/tmp; fi
    out="$tmpdir/pcfx-v810-c-probe.s"
fi

[[ -x "$compiler" ]] || {
    printf 'V810 GCC not found or not executable: %s\n' "$compiler" >&2
    exit 1
}

"$compiler" -O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function \
    -S "$script_dir/codegen_probe.c" -o "$out"

function_body() {
    awk -v label="_$1:" '$0 == label {inside = 1; next} inside && $1 == ".size" {exit} inside {print}' "$out"
}

expect_has() {
    local name=$1 pattern=$2 body
    body=$(function_body "$name")
    if [[ -z "$body" ]] || ! printf '%s\n' "$body" | rg -q "$pattern"; then
        printf 'FAIL %s should contain /%s/ (see %s)\n' "$name" "$pattern" "$out" >&2
        exit 1
    fi
    printf 'PASS %s contains %s\n' "$name" "$pattern"
}

expect_absent() {
    local name=$1 pattern=$2 body
    body=$(function_body "$name")
    if [[ -z "$body" ]] || printf '%s\n' "$body" | rg -q "$pattern"; then
        printf 'FAIL %s should not contain /%s/ (see %s)\n' "$name" "$pattern" "$out" >&2
        exit 1
    fi
    printf 'PASS %s omits %s\n' "$name" "$pattern"
}

# Check each function independently; register allocation and instruction order
# beyond these semantic patterns are not part of the probe contract.
expect_has load_s8 'ld[.]b'
expect_absent load_s8 'andi'
expect_has load_u8 'ld[.]b'
expect_has load_u8 'andi[[:space:]]+255'
expect_has load_s16 'ld[.]h'
expect_absent load_s16 'andi'
expect_has load_u16 'ld[.]h'
expect_has load_u16 'andi[[:space:]]+65535'
expect_has add_s16 'shl[[:space:]]+16'
expect_has add_s16 'sar[[:space:]]+16'
expect_has add_u16 'andi[[:space:]]+65535'
expect_absent add_u16 'shl|sar'
expect_has less_s32 'setf[[:space:]]+lt([[:space:],]|$)'
expect_has less_u32 'setf[[:space:]]+l([[:space:],]|$)'
expect_has in_bounds 'setf[[:space:]]+l([[:space:],]|$)'
expect_has shift_s32 'sar'
expect_has shift_u32 'shr'
expect_has mul_s32 '(^|[[:space:]])mul([[:space:]]|$)'
expect_has mul_u32 '(^|[[:space:]])mul([[:space:]]|$)'
expect_has div_s32 '(^|[[:space:]])div([[:space:]]|$)'
expect_has div_u32 '(^|[[:space:]])divu([[:space:]]|$)'
expect_has rem_s32 '(^|[[:space:]])div([[:space:]]|$)'
expect_has rem_s32 'mov[[:space:]]+r30'
expect_has rem_u32 '(^|[[:space:]])divu([[:space:]]|$)'
expect_has rem_u32 'mov[[:space:]]+r30'
expect_has div_u10 'divu'
expect_has rem_u10 'divu'
expect_has rem_u10 'mov[[:space:]]+r30'
expect_has div_s10 '(^|[[:space:]])div([[:space:]]|$)'
expect_has sum_u8 'ld[.]b'
expect_has sum_u8 'andi[[:space:]]+255'
expect_has sum_s16 'ld[.]h'
expect_absent sum_s16 'andi'
expect_has mul_wide_u32 '___muldi3'
expect_has mul_s64 '___muldi3'
expect_has advance_wrap 'add'
expect_has advance_wrap '(^|[[:space:]])and([[:space:]]|$)'
expect_has wrap_u8 'andi[[:space:]]+255'

version=$("$compiler" --version | sed -n '1p')
printf 'V810 GCC: %s\n' "$version"
printf 'assembly: %s\n' "$out"
