Read `PCFX_Skills/pcfx-v810-c/SKILL.md` and analyze the C cases in
`PCFX_Skills/pcfx-v810-c/tests/codegen_probe.c`. The target is the bundled V810 GCC
4.9.4 with the standard SDK `-O2 -mv810 -msda=256 -mno-prolog-function` flags.

For each group below, predict the important assembly distinction and say what must be
checked in the generated output. Do not write inline assembly or `.S` code.

1. `load_s8` versus `load_u8`, and `load_s16` versus `load_u16`.
2. `add_s16` versus `add_u16`; explain C integer promotions.
3. `less_s32` versus `less_u32`; and `shift_s32` versus `shift_u32`.
4. `mul_s32` versus `mul_u32`; `div_s32`/`rem_s32` versus their unsigned forms.
5. `div_u10`/`rem_u10` versus variable division.
6. `mul_wide_u32` versus `mul_s64`; explain how to verify helper calls.
7. Give two safe C-level optimization rules for the sum loops, without claiming a speedup
   that was not measured.

Be precise about what is a common code-generation result versus what depends on expression
shape, calling convention, link, or profile. If a claim is not derivable from the skill,
name the compiler or profile check that would settle it.
