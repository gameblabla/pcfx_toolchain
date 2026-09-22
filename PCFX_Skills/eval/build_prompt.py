#!/usr/bin/env python3
"""Assemble a system prompt for the local model from the PCFX_Skills bundle.

Modes:
  --mode none    : no skills at all (control / baseline)
  --mode all     : AGENTS.md + every SKILL.md concatenated
  --mode select  : AGENTS.md + only the named skills (--skills a,b,c)
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PREAMBLE = """You are a PC-FX homebrew engineer working on a C/V810-assembly port.
You have been given a bundle of hard-won, project-specific knowledge below.
It is authoritative: it records what was measured on real PC-FX hardware.
When it contradicts your prior assumptions about the hardware, the bundle is right.

Answer the user's task by following the bundle's procedures exactly.
"""


def read(p):
    with open(p) as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="all", choices=["none", "all", "select"])
    ap.add_argument("--skills", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    parts = [PREAMBLE]
    if a.mode != "none":
        parts.append("# Project conventions (AGENTS.md)\n\n" + read(os.path.join(ROOT, "AGENTS.md")))
        names = sorted(
            d for d in os.listdir(ROOT)
            if os.path.isdir(os.path.join(ROOT, d)) and os.path.exists(os.path.join(ROOT, d, "SKILL.md"))
        )
        if a.mode == "select":
            want = [s.strip() for s in a.skills.split(",") if s.strip()]
            missing = [w for w in want if w not in names]
            if missing:
                sys.exit(f"unknown skills: {missing}")
            names = want
        for n in names:
            parts.append(f"\n\n===== KNOWLEDGE MODULE: {n} =====\n\n" + read(os.path.join(ROOT, n, "SKILL.md")))

    out = "\n".join(parts)
    with open(a.out, "w") as f:
        f.write(out)
    print(f"{a.out}: {len(out)} chars (~{len(out)//4} tokens)", file=sys.stderr)


if __name__ == "__main__":
    main()
