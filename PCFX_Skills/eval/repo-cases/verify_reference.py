#!/usr/bin/env python3
"""Verify a real project by building it and comparing the screen to a reference.

For a project whose correct output is a specific picture, "some pixels were
drawn" is far too weak a gate -- the interesting bugs here draw *most* of the
picture. pcfx-headless is deterministic for a fixed frame count (verified: two
runs of the same disc produce byte-identical PNGs), so exact comparison against
a reference screenshot taken from the pristine tree is a valid oracle.

  verify_reference.py <workdir> --config case.env [--json]

case.env supplies BUILD_CMD, CUE, FRAMES, REFERENCE and optional MAX_DIFF_PIXELS.
"""
import argparse, json, os, subprocess, sys
from pathlib import Path

TOOLKIT_ROOT = Path(os.environ.get("PCFX_TOOLKIT_ROOT",
                                   Path(__file__).resolve().parents[3])).resolve()
EMU = os.environ.get("PCFXEMU", str(TOOLKIT_ROOT / "toolchain/bin/pcfx-headless"))
BIOS = os.environ.get("PCFX_BIOS_DIR", os.environ.get("BIOSDIR", ""))
V810GCC = os.environ.get(
    "V810_GCC", os.environ.get("V810GCC", str(TOOLKIT_ROOT / "toolchain/v810-gcc"))
)


def load_env(path):
    cfg = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"')
    return cfg


def diff_pixels(a, b):
    from PIL import Image, ImageChops
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return -1
    return sum(1 for p in ImageChops.difference(ia, ib).convert("L").getdata() if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--config", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not BIOS:
        ap.error("set PCFX_BIOS_DIR (the BIOS is intentionally external)")

    wd = os.path.abspath(a.workdir)
    cfg = load_env(a.config)
    r = {"workdir": wd}

    env = dict(os.environ, PATH=f"{V810GCC}/bin:" + os.environ["PATH"],
               V810_GCC=V810GCC, V810GCC=V810GCC)
    b = subprocess.run(cfg["BUILD_CMD"], cwd=wd, env=env, shell=True,
                       capture_output=True, text=True)
    r["build_ok"] = (b.returncode == 0)
    if not r["build_ok"]:
        r["build_tail"] = (b.stdout + b.stderr)[-1500:]
        return report(r, a)

    shot = os.path.join(wd, "verify.png")
    subprocess.run([EMU, "--bios-dir", BIOS, "--pcfx", "--frames", cfg["FRAMES"],
                    "--screenshot", shot, cfg["CUE"]], cwd=wd, capture_output=True)
    if not os.path.exists(shot):
        r["error"] = "no screenshot produced"
        return report(r, a)

    ref = cfg["REFERENCE"]
    if not os.path.isabs(ref):
        ref = os.path.join(os.path.dirname(os.path.abspath(a.config)), ref)
    r["diff_pixels"] = diff_pixels(shot, ref)
    r["max_diff_pixels"] = int(cfg.get("MAX_DIFF_PIXELS", 0))
    r["pass"] = r["build_ok"] and 0 <= r["diff_pixels"] <= r["max_diff_pixels"]
    return report(r, a)


def report(r, a):
    r.setdefault("pass", False)
    print(json.dumps(r, indent=2) if a.json else
          "\n".join(f"{k}: {v}" for k, v in r.items()) +
          ("\nPASS" if r["pass"] else "\nFAIL"))
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
