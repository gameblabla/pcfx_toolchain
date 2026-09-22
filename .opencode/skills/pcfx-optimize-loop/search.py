#!/usr/bin/env python3
"""Brute-force / hill-climb search over PC-FX build knobs, scored by the V810 profiler.

The contract: your build must accept knobs as environment variables (Makefile
`?=` variables work directly), and the program must be runnable headless. This
script never edits your source -- it only varies knobs, rebuilds, measures, and
keeps a ledger. That is what makes the search safe to leave running.

  ./search.py --config search.json [--strategy hill|grid|random] [--budget N]

search.json:
{
  "build":   "make -j8 cd",
  "clean":   "make clean",
  "run":     "$PCFXEMU/pcfx-headless-prof --frames 1800 game.cue",
  "workdir": ".",
  "knobs": {
    "PCFX_HOT_SPAN_LIT_OFFSET":    {"type":"hex", "min":0, "max":4096, "step":64, "default":2624},
    "PCFX_HOT_COLUMN_LIT_OFFSET":  {"type":"hex", "min":0, "max":4096, "step":64, "default":2820},
    "PCFX_UNROLL":                 {"type":"int", "choices":[1,2,4,8], "default":4}
  }
}
"""
import argparse, itertools, json, os, random, re, subprocess, sys, time

# ---------------------------------------------------------------- measurement

METRICS = {
    "field_pct":  re.compile(r"Cycles attributed.*?=\s*([\d.]+)% of a field"),
    "cpi":        re.compile(r"CPI \(mean\)\s*:\s*([\d.]+)"),
    "icache_mpf": re.compile(r"misses/field=(\d+)"),
    "flag_pct":   re.compile(r"stall cost=\d+ cyc/field \(([\d.]+)% of a field\)"),
    "dram_pct":   re.compile(r"penalty cyc/field=\d+ \(([\d.]+)% of a field\)"),
}


def measure(cfg, env):
    """Build with `env` applied, run, and parse the profile. Returns (score, metrics)."""
    e = dict(os.environ, **{k: str(v) for k, v in env.items()})
    wd = cfg.get("workdir", ".")

    b = subprocess.run(cfg["build"], shell=True, cwd=wd, env=e,
                       capture_output=True, text=True)
    if b.returncode != 0:
        return None, {"error": "build failed", "log": b.stderr[-2000:]}

    r = subprocess.run(cfg["run"], shell=True, cwd=wd, env=e,
                       capture_output=True, text=True, timeout=cfg.get("timeout", 900))
    out = r.stderr + r.stdout

    m = {}
    for name, rx in METRICS.items():
        hit = rx.search(out)
        if hit:
            m[name] = float(hit.group(1))
    if "field_pct" not in m:
        return None, {"error": "no profile in output", "log": out[-2000:]}
    return m["field_pct"], m            # lower is better


# ------------------------------------------------------------------- knob space

def values_for(spec):
    if "choices" in spec:
        return list(spec["choices"])
    step = spec.get("step", 1)
    return list(range(spec["min"], spec["max"] + 1, step))


def fmt(spec, v):
    return hex(v) if spec.get("type") == "hex" else str(v)


# ------------------------------------------------------------------ strategies

def run_search(cfg, strategy, budget, ledger_path):
    knobs = cfg["knobs"]
    names = list(knobs)
    base = {n: knobs[n]["default"] for n in names}
    ledger, seen = [], {}

    def trial(point, note=""):
        key = tuple(point[n] for n in names)
        if key in seen:
            return seen[key]
        env = {n: fmt(knobs[n], point[n]) for n in names}
        t0 = time.time()
        score, m = measure(cfg, env)
        rec = {"knobs": env, "score": score, "metrics": m,
               "note": note, "secs": round(time.time() - t0, 1)}
        ledger.append(rec)
        with open(ledger_path, "w") as f:
            json.dump(ledger, f, indent=1)
        seen[key] = score
        status = f"{score:.2f}% field" if score is not None else f"FAIL ({m.get('error')})"
        print(f"[{len(ledger):3d}] {status}  {env}  {note}", flush=True)
        return score

    print("=== baseline ===", flush=True)
    best_score = trial(base, "baseline")
    if best_score is None:
        sys.exit("baseline does not build/run -- fix that before searching")
    best = dict(base)

    if strategy == "grid":
        space = [values_for(knobs[n]) for n in names]
        combos = list(itertools.product(*space))
        random.shuffle(combos)
        for combo in combos[:budget]:
            p = dict(zip(names, combo))
            s = trial(p, "grid")
            if s is not None and s < best_score:
                best_score, best = s, dict(p)

    elif strategy == "random":
        for _ in range(budget):
            p = {n: random.choice(values_for(knobs[n])) for n in names}
            s = trial(p, "random")
            if s is not None and s < best_score:
                best_score, best = s, dict(p)

    else:  # hill climb: one knob at a time, keep improvements, repeat until stable
        used, improved = 1, True
        while improved and used < budget:
            improved = False
            for n in names:
                for v in values_for(knobs[n]):
                    if v == best[n] or used >= budget:
                        continue
                    p = dict(best); p[n] = v
                    used += 1
                    s = trial(p, f"climb {n}")
                    if s is not None and s < best_score - 0.02:   # noise floor
                        best_score, best, improved = s, dict(p), True

    print("\n=== best ===")
    print(json.dumps({n: fmt(knobs[n], best[n]) for n in names}, indent=1))
    print(f"score {best_score:.2f}% of a field "
          f"(baseline {ledger[0]['score']:.2f}%)")
    print(f"ledger: {ledger_path}")
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--strategy", default="hill", choices=["hill", "grid", "random"])
    ap.add_argument("--budget", type=int, default=40)
    ap.add_argument("--ledger", default="search-ledger.json")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    random.seed(a.seed)
    run_search(json.load(open(a.config)), a.strategy, a.budget, a.ledger)


if __name__ == "__main__":
    main()
