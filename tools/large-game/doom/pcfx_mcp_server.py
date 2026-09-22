#!/usr/bin/env python3
"""PC-FX DOOM MCP server — exposes the V810/KING instrumentation, disassembly,
the Game Maker hardware reference, and source read/edit to an MCP client (e.g.
Claude Code / Claude Desktop). Stdio transport, newline-delimited JSON-RPC 2.0,
Python stdlib only.

Register with Claude Code:
  claude mcp add pcfx -- python3 /abs/path/doom-pcfx/tools/pcfx_mcp_server.py
or add to an MCP client config:
  {"mcpServers":{"pcfx":{"command":"python3","args":["/abs/path/tools/pcfx_mcp_server.py"]}}}

Tools:
  king_register    look up a KING (HuC6272) register by number or name
  v810_hotspots    top functions from a profiler CSV (cycles / misses / count)
  disasm_function  annotated V810 disassembly of a function (cycles + icache miss)
  read_source      read a file under the repo
  grep_source      ripgrep-style search of the repo
  build_and_profile  build the bench + run pcfx-headless-prof, return V810+KING report
  apply_edit       write file contents (live code editing; repo-scoped)

Paths are auto-derived from this file's location; override via env
PCFX_ROOT (doom-pcfx dir), PCFX_EMU_ROOT (pcfxemu dir), PCFX_ELF.
"""
import json, os, re, subprocess, sys, bisect, csv

ROOT = os.environ.get("PCFX_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMU = os.environ.get("PCFX_EMU_ROOT", os.path.join(os.path.dirname(ROOT), "pcfxemu"))
ELF = os.environ.get("PCFX_ELF", os.path.join(ROOT, "build", "doom_pcfx.elf"))
NM = os.environ.get("V810_NM", "/opt/v810-gcc/bin/v810-nm")
TOOLS = os.path.join(ROOT, "tools")

# --- KING register table (mirrors DEV72.H; see docs/pcfx-king-reference.md) ---
KING_REGS = {
    0x00: "SCSI_ODATA/CDATA", 0x01: "SCSI_ICMD", 0x02: "SCSI_MODE", 0x03: "SCSI_TCMD",
    0x04: "SCSI_SELECT/CBSTAT", 0x05: "SCSI_DMASEND/BUSSTAT", 0x06: "SCSI_TDMASEND/IDATA",
    0x07: "SCSI_DMARCV/IRQRESET", 0x08: "CDROM_SUBCTRL/DATA", 0x09: "SCSI_DMASTART",
    0x0a: "SCSI_DMACNT", 0x0b: "SCSI_DMACR", 0x0c: "KRAM_ARR(read addr)",
    0x0d: "KRAM_AWR(write addr)", 0x0e: "KRAM_DATA", 0x0f: "KRAM_PAGE",
    0x10: "BG_MODE", 0x12: "BG_PRI", 0x13: "BG_MPAR", 0x14: "BG_MPDR", 0x15: "BG_MPCR",
    0x16: "BG_SSCR", 0x20: "BG0_BAT", 0x21: "BG0_CG", 0x22: "BG0_SBAT", 0x23: "BG0_SCG",
    0x24: "BG1_BAT", 0x25: "BG1_CG", 0x28: "BG2_BAT", 0x29: "BG2_CG", 0x2a: "BG3_BAT",
    0x2b: "BG3_CG", 0x2c: "BG0_SIZE", 0x2d: "BG1_SIZE", 0x2e: "BG2_SIZE", 0x2f: "BG3_SIZE",
    0x30: "BG0_BSX", 0x31: "BG0_BSY", 0x32: "BG1_BSX", 0x33: "BG1_BSY", 0x34: "BG2_BSX",
    0x35: "BG2_BSY", 0x36: "BG3_BSX", 0x37: "BG3_BSY", 0x38: "BG_AFINA", 0x39: "BG_AFINB",
    0x3a: "BG_AFINC", 0x3b: "BG_AFIND", 0x3c: "BG_AFINX", 0x3d: "BG_AFINY",
    0x40: "KR_CR(rainbow xfer ctrl)", 0x41: "KR_TSA(src)", 0x42: "KR_TSR(start raster)",
    0x43: "KR_LEN(blocks)", 0x44: "RASTER_COUNT", 0x50: "KS_MODE(adpcm)", 0x51: "KS_CR0",
    0x52: "KS_CR1", 0x53: "KS_STAT", 0x58: "KS_START0", 0x59: "KS_END0", 0x5a: "KS_HALF0",
    0x5c: "KS_START1", 0x5d: "KS_END1", 0x5e: "KS_HALF1", 0x61: "KRAM_MODE",
}


def safe_path(rel):
    p = os.path.realpath(os.path.join(ROOT, rel))
    if not p.startswith(os.path.realpath(ROOT)):
        raise ValueError("path escapes repo root: %s" % rel)
    return p


# ---------------- tool implementations (return plain text) ----------------

def t_king_register(args):
    q = str(args.get("query", "")).strip()
    if not q:
        return "\n".join("0x%02x  %s" % (n, v) for n, v in sorted(KING_REGS.items()))
    try:
        n = int(q, 0)
        return "0x%02x = %s" % (n, KING_REGS.get(n & 0x7f, "(unknown / unmapped)"))
    except ValueError:
        hits = ["0x%02x  %s" % (n, v) for n, v in sorted(KING_REGS.items()) if q.lower() in v.lower()]
        return "\n".join(hits) if hits else "no KING register matches %r" % q


def t_v810_hotspots(args):
    csv_path = args["csv"]
    sort = args.get("sort", "cycles")
    top = str(args.get("top", 30))
    return subprocess.check_output(
        [sys.executable, os.path.join(TOOLS, "v810_prof_symbols.py"), csv_path,
         "--elf", args.get("elf", ELF), "--sort", sort, "--top", top],
        text=True, stderr=subprocess.STDOUT)


def t_disasm_function(args):
    cmd = [sys.executable, os.path.join(TOOLS, "v810_disasm.py"),
           "--elf", args.get("elf", ELF)]
    if args.get("csv"):
        cmd += ["--csv", args["csv"]]
    if args.get("top"):
        cmd += ["--top", str(args["top"])]
    else:
        cmd.append(args["func"])
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def t_read_source(args):
    p = safe_path(args["path"])
    with open(p, errors="replace") as f:
        data = f.read()
    lo = int(args.get("start", 1))
    hi = int(args.get("end", 0)) or None
    lines = data.splitlines()
    sel = lines[lo - 1:hi] if hi else lines[lo - 1:]
    return "\n".join("%6d\t%s" % (lo + i, s) for i, s in enumerate(sel))


def t_grep_source(args):
    pat = args["pattern"]
    sub = args.get("path", ".")
    try:
        return subprocess.check_output(
            ["grep", "-rniI", "--line-number", pat, safe_path(sub)],
            text=True, stderr=subprocess.STDOUT)[:20000]
    except subprocess.CalledProcessError:
        return "(no matches)"


def t_build_and_profile(args):
    mapn = str(args.get("map", 6))
    frames = str(args.get("frames", 6000))
    out_csv = os.path.join("/tmp", "pcfx_prof_e1m%s.csv" % mapn)
    wad = os.environ.get("DOOM1WAD", os.path.join(os.path.dirname(ROOT), "doom1.wad"))
    steps = []
    subprocess.run(["make", "clean"], cwd=ROOT, capture_output=True)
    b = subprocess.run(["make", "DOOM1WAD=" + wad,
                        "EXTRA=-DDEV_WARP -DDEV_WARP_MAP=%s -DCOARSE_RENDER_PROFILE -DDEV_BENCH_AUTOMOVE" % mapn],
                       cwd=ROOT, capture_output=True, text=True)
    if b.returncode:
        return "doom build failed:\n" + b.stdout[-3000:] + b.stderr[-3000:]
    steps.append("built E1M%s bench" % mapn)
    subprocess.run(["make", "-f", "Makefile.headless", "PROFILE=1", "PRGNAME=pcfx-headless-prof", "-j4"],
                   cwd=EMU, capture_output=True)
    env = dict(os.environ, V810_PROF_OUT=out_csv)
    r = subprocess.run([os.path.join(EMU, "pcfx-headless-prof"), "--bios-dir", os.path.dirname(ROOT),
                        "--pcfx", "--auto-run", "--frames", frames, "--dump", "ram", "/dev/null",
                        os.path.join(ROOT, "doom_pcfx.cue")],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    report = re.search(r"(#{4,}\s*V810 PROFILE.*)", r.stderr, re.S)
    body = report.group(1) if report else r.stderr[-6000:]
    return "steps: %s\nCSV: %s\n\n%s" % (", ".join(steps), out_csv, body)


def t_apply_edit(args):
    p = safe_path(args["path"])
    with open(p, "w") as f:
        f.write(args["content"])
    return "wrote %d bytes to %s" % (len(args["content"]), args["path"])


TOOLDEFS = [
    ("king_register", "Look up a KING (HuC6272) register by number (e.g. 0x0e) or name substring (e.g. 'ADPCM'). Empty = full map.",
     {"query": {"type": "string"}}, []),
    ("v810_hotspots", "Top functions from a pcfx-headless-prof PC-histogram CSV (written via V810_PROF_OUT).",
     {"csv": {"type": "string"}, "sort": {"type": "string", "enum": ["cycles", "misses", "count"]},
      "top": {"type": "integer"}, "elf": {"type": "string"}}, ["csv"]),
    ("disasm_function", "Annotated V810 disassembly of a function (per-32B-block cycles + icache miss if csv given). Use func OR top+csv.",
     {"func": {"type": "string"}, "csv": {"type": "string"}, "top": {"type": "integer"}, "elf": {"type": "string"}}, []),
    ("read_source", "Read a repo file (optionally start/end lines).",
     {"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, ["path"]),
    ("grep_source", "Case-insensitive recursive text search of the repo.",
     {"pattern": {"type": "string"}, "path": {"type": "string"}}, ["pattern"]),
    ("build_and_profile", "Build an E1M<map> automove bench, run pcfx-headless-prof, return the V810+KING report and a CSV path. Heavy (rebuilds).",
     {"map": {"type": "integer"}, "frames": {"type": "integer"}}, []),
    ("apply_edit", "Overwrite a repo file with new contents (live code editing; repo-scoped).",
     {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
]
HANDLERS = {
    "king_register": t_king_register, "v810_hotspots": t_v810_hotspots,
    "disasm_function": t_disasm_function, "read_source": t_read_source,
    "grep_source": t_grep_source, "build_and_profile": t_build_and_profile,
    "apply_edit": t_apply_edit,
}


def tools_list():
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": props, "required": req}}
            for (n, d, props, req) in TOOLDEFS]


def handle(req):
    m = req.get("method")
    if m == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "pcfx-doom", "version": "1.0"}}
    if m == "tools/list":
        return {"tools": tools_list()}
    if m == "tools/call":
        p = req.get("params", {})
        name, args = p.get("name"), p.get("arguments", {})
        fn = HANDLERS.get(name)
        if not fn:
            return {"content": [{"type": "text", "text": "unknown tool: %s" % name}], "isError": True}
        try:
            return {"content": [{"type": "text", "text": fn(args)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": "error: %s" % e}], "isError": True}
    return None  # notifications / unknown → no response


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = handle(req)
        if req.get("id") is None:      # notification
            continue
        resp = {"jsonrpc": "2.0", "id": req["id"]}
        if result is None:
            resp["error"] = {"code": -32601, "message": "method not found"}
        else:
            resp["result"] = result
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
