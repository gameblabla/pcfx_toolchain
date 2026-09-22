#!/usr/bin/env python3
"""Minimal client for the local llama.cpp server (Qwen 3.6 27B).

Usage:
  ask_qwen.py --system sys.md --user prompt.md --out result.md [--max-tokens N]
"""
import argparse, json, os, sys, urllib.request

ENDPOINT = os.environ.get("PCFX_LLM_ENDPOINT", "http://127.0.0.1:8080").rstrip("/") + "/v1/chat/completions"


def ask(system, user, max_tokens=4096, temperature=0.3):
    body = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "stream": False,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.load(r)
    msg = data["choices"][0]["message"]
    out = ""
    if msg.get("reasoning_content"):
        out += "<reasoning>\n" + msg["reasoning_content"] + "\n</reasoning>\n\n"
    out += msg.get("content") or ""
    usage = data.get("usage", {})
    return out, usage


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--system", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--temperature", type=float, default=0.3)
    a = p.parse_args()

    system = open(a.system).read()
    user = open(a.user).read()
    out, usage = ask(system, user, a.max_tokens, a.temperature)
    open(a.out, "w").write(out)
    print(f"tokens: prompt={usage.get('prompt_tokens')} "
          f"completion={usage.get('completion_tokens')} -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
