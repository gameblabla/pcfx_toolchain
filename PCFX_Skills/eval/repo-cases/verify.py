#!/usr/bin/env python3
"""Objective pass/fail for a repo case: build the disc, run it, judge the picture.

Deliberately dumb and mechanical, so a model cannot argue with the result:
  - the build must succeed (exit status, not the last line of a pipe)
  - the program must draw a cube: a screenshot past BIOS boot must contain a
    non-background pixel count inside the reference band
  - with --flip, screenshots at an odd and an even frame count must BOTH draw,
    which is what a broken page flip fails

  verify.py <workdir> [--flip] [--json]

Exit status 0 = pass. Everything it prints is something a command produced.
"""
import argparse, json, os, subprocess, sys
from pathlib import Path

# Reference: the unmodified template draws 15,680 cube pixels of rgb(32,32,32)
# on black at 1800 frames. Accept a wide band -- the cube's orientation depends
# on where in its rotation the run happens to stop.
MIN_DRAWN = 3000
MAX_DRAWN = 40000

TOOLKIT_ROOT = Path(os.environ.get("PCFX_TOOLKIT_ROOT",
                                   Path(__file__).resolve().parents[3])).resolve()
EMU = os.environ.get("PCFXEMU", str(TOOLKIT_ROOT / "toolchain/bin/pcfx-headless"))
BIOS = os.environ.get("PCFX_BIOS_DIR", os.environ.get("BIOSDIR", ""))
V810GCC = os.environ.get(
    "V810_GCC", os.environ.get("V810GCC", str(TOOLKIT_ROOT / "toolchain/v810-gcc"))
)


def run(cmd, cwd, **kw):
    env = dict(os.environ, PATH=f"{V810GCC}/bin:" + os.environ["PATH"],
               V810_GCC=V810GCC, V810GCC=V810GCC)
    return subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str),
                          capture_output=True, text=True, **kw)


def drawn_pixels(png):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    return sum(n for n, c in im.getcolors(1 << 20) if c != (0, 0, 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--flip", action="store_true",
                    help="also require the odd-frame screenshot to draw")
    ap.add_argument("--hosttest", action="store_true",
                    help="also require `make hosttest` to report PASS")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not BIOS:
        ap.error("set PCFX_BIOS_DIR (the BIOS is intentionally external)")
    wd = os.path.abspath(a.workdir)
    r = {"workdir": wd}

    run("make clean", wd)
    b = run("make cd", wd)
    r["build_ok"] = (b.returncode == 0)
    if not r["build_ok"]:
        r["build_tail"] = (b.stdout + b.stderr)[-1500:]
        return report(r, a)

    cue = next((f for f in os.listdir(wd) if f.endswith(".cue")), None)
    if not cue:
        r["error"] = "no .cue produced"
        return report(r, a)

    for label, frames in (("even", 1800), ("odd", 1801)):
        if label == "odd" and not a.flip:
            continue
        shot = os.path.join(wd, f"verify-{label}.png")
        run([EMU, "--bios-dir", BIOS, "--pcfx", "--frames", str(frames),
             "--screenshot", shot, cue], wd)
        r[f"drawn_{label}"] = drawn_pixels(shot) if os.path.exists(shot) else -1

    if a.hosttest:
        h = run("make hosttest", wd)
        r["hosttest_pass"] = ("PASS (" in h.stdout)
        if not r["hosttest_pass"]:
            r["hosttest_tail"] = (h.stdout + h.stderr)[-800:]

    checks = [k for k in r if k.startswith("drawn_")]
    r["pass"] = (r["build_ok"]
                 and all(MIN_DRAWN <= r[k] <= MAX_DRAWN for k in checks)
                 and r.get("hosttest_pass", True))
    return report(r, a)


def report(r, a):
    r.setdefault("pass", False)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        for k, v in r.items():
            print(f"{k}: {v}")
        print("PASS" if r["pass"] else "FAIL")
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
