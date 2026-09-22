#!/usr/bin/env python3
"""Read SERIAL_LOG render-profile counters from a pcfx-headless RAM dump."""

import argparse
import pathlib
import struct
import subprocess
import sys


NM = "/opt/v810-gcc/bin/v810-nm"
# The interval timer is clocked at 1.4318 MHz and reloaded every 1 ms.
# itu_ticks() accumulates one PCFX_TIMER_PERIOD-sized epoch per interrupt.
TICKS_PER_MS = 1432.0


def symbols(elf):
    output = subprocess.check_output([NM, "-n", str(elf)], text=True)
    result = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3:
            name = fields[2].removeprefix("_")
            if name.startswith(("g_rpa_", "g_rpm_")):
                result[name] = int(fields[0], 16)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ram", type=pathlib.Path, help="2 MiB --dump ram output")
    parser.add_argument("--elf", type=pathlib.Path,
                        default=pathlib.Path("build/doom_pcfx.elf"))
    parser.add_argument("--before", type=pathlib.Path,
                        help="earlier RAM dump; report accumulator deltas")
    parser.add_argument("--raw", action="store_true", help="also print raw counters")
    args = parser.parse_args()

    ram = args.ram.read_bytes()
    before_ram = args.before.read_bytes() if args.before else None
    syms = symbols(args.elf)

    def read_from(image, name):
        try:
            address = syms[name]
        except KeyError:
            sys.exit(f"missing {name}; build the ELF with -DCOARSE_RENDER_PROFILE "
                     "or -DSERIAL_LOG")
        if address + 4 > len(image):
            sys.exit(f"{name} address 0x{address:x} is outside the RAM dump")
        return struct.unpack_from("<I", image, address)[0]

    def value(name):
        after = read_from(ram, name)
        if before_ram is not None and name.startswith("g_rpa_"):
            return (after - read_from(before_ram, name)) & 0xFFFFFFFF
        return after

    frames = value("g_rpa_n")
    if not frames:
        sys.exit("g_rpa_n is zero; the capture did not reach rendered frames")

    def per_frame(name):
        return value(name) / frames

    def phase_ms(name):
        return per_frame(name) / TICKS_PER_MS

    def sampled_ms(ticks, samples, events):
        sample_count = value(samples)
        if not sample_count:
            return 0.0
        ticks_per_event = value(ticks) / sample_count
        return ticks_per_event * per_frame(events) / TICKS_PER_MS

    detailed = "g_rpa_seg" in syms

    print(f"profile: {'detailed SERIAL_LOG' if detailed else 'coarse release-like'}")
    print(f"frames: {frames}" + (" (delta)" if before_ram is not None else ""))
    print("phase ms/frame:")
    phases = (("walls/BSP", "g_rpa_bsp"),
              ("planes", "g_rpa_plane"),
              ("sprites/masked", "g_rpa_spr"))
    for label, name in phases:
        print(f"  {label:18s} {phase_ms(name):8.3f}")
    core = sum(phase_ms(name) for _, name in phases)
    print(f"  {'render core':18s} {core:8.3f}")
    print(f"  {'game tics':18s} {phase_ms('g_rpa_tic'):8.3f}")
    if "g_rpa_pad_calls" in syms and value("g_rpa_pad_calls"):
        calls = value("g_rpa_pad_calls")
        us = value("g_rpa_pad") / calls / TICKS_PER_MS * 1000.0
        print(f"  {'  .. FX-Pad read':18s} {phase_ms('g_rpa_pad'):8.3f}"
              f"   ({per_frame('g_rpa_pad_calls'):.2f}/frame, {us:.0f} us each)")
    if "g_rpa_tt_wait" in syms:
        for label, name in (("  .. TryRunTics wait", "g_rpa_tt_wait"),
                            ("  .. M_Ticker", "g_rpa_tt_mticker"),
                            ("  .. G_Ticker", "g_rpa_tt_gticker")):
            print(f"  {label:18s} {phase_ms(name):8.3f}")
        print(f"  {'  .. tics/frame':18s} {per_frame('g_rpa_tt_runtics'):8.2f}")
    if "g_rpa_th_thinkers" in syms:
        for label, name in (("  .. player", "g_rpa_th_player"),
                            ("  .. thinkers", "g_rpa_th_thinkers"),
                            ("  .. specials", "g_rpa_th_specials")):
            print(f"  {label:18s} {phase_ms(name):8.3f}")
        print(f"  {'  .. thinkers/frame':18s} {per_frame('g_rpa_th_count'):8.1f}")
    print(f"  {'presentation':18s} {phase_ms('g_rpa_blit'):8.3f}")
    display_overhead = max(0.0, phase_ms("g_rpa_display") - core -
                           phase_ms("g_rpa_blit"))
    print(f"  {'display overhead':18s} {display_overhead:8.3f}")
    print(f"  {'render setup/clear':18s} "
          f"{max(0.0, phase_ms('g_rpa_view') - core):8.3f}")
    print(f"  {'HUD construction':18s} {phase_ms('g_rpa_hud'):8.3f}")
    print(f"  {'sound positioning':18s} {phase_ms('g_rpa_sound'):8.3f}")
    frame_ms = phase_ms("g_rpa_frame")
    other_ms = max(0.0, frame_ms - core - phase_ms("g_rpa_tic") -
                   phase_ms("g_rpa_blit"))
    print(f"  {'other loop work':18s} {other_ms:8.3f}")
    print(f"  {'whole frame':18s} {frame_ms:8.3f}")

    if not detailed:
        if args.raw:
            print("raw:")
            for name in sorted(syms):
                print(f"  {name:40s} {value(name)}")
        return

    wall_draw_ms = 0.0
    if value("g_rpa_draw_pixels"):
        ticks_per_pixel = value("g_rpa_draw") / value("g_rpa_draw_pixels")
        wall_draw_ms = ticks_per_pixel * per_frame("g_rpa_wall_pixels") / TICKS_PER_MS
    wall_fetch_ms = sampled_ms("g_rpa_fetch", "g_rpa_fetch_samples",
                               "g_rpa_wall_columns")
    seg_remainder_ms = max(0.0, phase_ms("g_rpa_seg") - wall_fetch_ms - wall_draw_ms)

    print(f"  {'render-seg total':18s} {phase_ms('g_rpa_seg'):8.3f}")
    print(f"  {'seg remainder':18s} {seg_remainder_ms:8.3f}")

    print("logical pixels/frame:")
    for label, name in (("wall", "g_rpa_wall_pixels"),
                        ("plane", "g_rpa_plane_pixels"),
                        ("masked wall", "g_rpa_masked_wall_pixels"),
                        ("sprite", "g_rpa_sprite_pixels")):
        print(f"  {label:18s} {per_frame(name):8.1f}")

    print("dense-wall tuples/frame:")
    max_note = "global max"
    print(f"  page+colormap      avg {per_frame('g_rpa_wall_page_cmaps'):6.1f}  "
          f"{max_note} {value('g_rpm_wall_page_cmaps'):4d}")
    print(f"  page+column+cmap   avg {per_frame('g_rpa_wall_column_cmaps'):6.1f}  "
          f"{max_note} {value('g_rpm_wall_column_cmaps'):4d}")
    print(f"  hash overflows         {value('g_rpa_wall_page_cmap_overflow')} / "
          f"{value('g_rpa_wall_column_cmap_overflow')}")

    print("sampled structural estimates, ms/frame:")
    print(f"  {'plane setup':18s} "
          f"{sampled_ms('g_rpa_plane_setup', 'g_rpa_plane_samples', 'g_rpa_plane_spans'):8.3f}")
    print(f"  {'plane pixel drawer':18s} "
          f"{sampled_ms('g_rpa_plane_draw', 'g_rpa_plane_samples', 'g_rpa_plane_spans'):8.3f}")
    print(f"  {'BSP bbox checks':18s} "
          f"{sampled_ms('g_rpa_bbox', 'g_rpa_bbox_samples', 'g_rpa_bbox_calls'):8.3f}")
    print(f"  {'line projection':18s} "
          f"{sampled_ms('g_rpa_addline', 'g_rpa_addline_samples', 'g_rpa_addline_calls'):8.3f}")
    print(f"  {'solid-column clip':18s} "
          f"{sampled_ms('g_rpa_clip', 'g_rpa_clip_samples', 'g_rpa_clip_calls'):8.3f}")
    print(f"  {'wall-range setup':18s} "
          f"{sampled_ms('g_rpa_store', 'g_rpa_store_samples', 'g_rpa_store_calls'):8.3f}")
    print(f"  {'wall fetch':18s} {wall_fetch_ms:8.3f}")
    print(f"  {'wall pixel drawer':18s} {wall_draw_ms:8.3f}")

    print("BSP traversal events/frame:")
    for label, name in (("internal nodes", "g_rpa_bsp_nodes"),
                        ("subsectors", "g_rpa_bsp_subsectors"),
                        ("full-screen exits", "g_rpa_bsp_earlyouts")):
        print(f"  {label:18s} {per_frame(name):8.1f}")

    print("wall pre-light cache totals:")
    for label, name in (("hits", "g_rpa_wall_lit_hits"),
                        ("misses", "g_rpa_wall_lit_misses"),
                        ("bakes", "g_rpa_wall_lit_bakes"),
                        ("evictions", "g_rpa_wall_lit_evictions")):
        print(f"  {label:18s} {value(name):8d}")

    if args.raw:
        print("raw:")
        for name in sorted(syms):
            print(f"  {name:40s} {value(name)}")


if __name__ == "__main__":
    main()
