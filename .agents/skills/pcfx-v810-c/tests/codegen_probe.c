#include <stdint.h>

/* Narrow RAM reads: LD.B/LD.H sign-extend; unsigned C values need zero extension. */
int32_t load_s8(const int8_t *p) { return *p; }
uint32_t load_u8(const uint8_t *p) { return *p; }
int32_t load_s16(const int16_t *p) { return *p; }
uint32_t load_u16(const uint16_t *p) { return *p; }

/* C integer promotions and argument normalization. */
int32_t add_s16(int16_t a, int16_t b) { return a + b; }
uint32_t add_u16(uint16_t a, uint16_t b) { return a + b; }
uint8_t wrap_u8(uint8_t a, uint8_t b) { return (uint8_t)(a + b); }

/* Signed and unsigned comparison use different conditions. */
int less_s32(int32_t a, int32_t b) { return a < b; }
int less_u32(uint32_t a, uint32_t b) { return a < b; }
int in_bounds(int32_t y, uint32_t height) { return (uint32_t)y < height; }

/* Low-word multiplication and hardware signed/unsigned division. */
int32_t mul_s32(int32_t a, int32_t b) { return a * b; }
uint32_t mul_u32(uint32_t a, uint32_t b) { return a * b; }
int32_t div_s32(int32_t a, int32_t b) { return a / b; }
uint32_t div_u32(uint32_t a, uint32_t b) { return a / b; }
int32_t rem_s32(int32_t a, int32_t b) { return a % b; }
uint32_t rem_u32(uint32_t a, uint32_t b) { return a % b; }

/* Constant-divisor strength reduction is compiler/version/type dependent. */
uint32_t div_u10(uint32_t x) { return x / 10u; }
uint32_t rem_u10(uint32_t x) { return x % 10u; }
int32_t div_s10(int32_t x) { return x / 10; }

/* Signed and unsigned right shift have different C/compiler semantics. */
int32_t shift_s32(int32_t x, unsigned n) { return x >> n; }
uint32_t shift_u32(uint32_t x, unsigned n) { return x >> n; }

/* Common loops: narrow input, widened accumulator, and sequential addresses. */
uint32_t sum_u8(const uint8_t *p, uint32_t count)
{
    uint32_t sum = 0;
    for (uint32_t i = 0; i < count; ++i)
        sum += p[i];
    return sum;
}

int32_t sum_s16(const int16_t *p, uint32_t count)
{
    int32_t sum = 0;
    for (uint32_t i = 0; i < count; ++i)
        sum += p[i];
    return sum;
}

/* Distinguish a native-width product from long-long runtime work. */
uint64_t mul_wide_u32(uint32_t a, uint32_t b) { return (uint64_t)a * b; }
int64_t mul_s64(int64_t a, int64_t b) { return a * b; }

/* Modulo counters should use defined unsigned wrap, not signed overflow. */
uint32_t advance_wrap(uint32_t value, uint32_t step, uint32_t mask)
{
    return (value + step) & mask;
}
