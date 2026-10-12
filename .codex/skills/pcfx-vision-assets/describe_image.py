#!/usr/bin/env python3
"""Send an image to a local llama.cpp vision endpoint and print the description.

Auto-detects which endpoint can actually see: tries the main model on :8080
(native mmproj) and the vision sidecar on :8081, in that order, and uses the
first that reports multimodal support.

  describe_image.py shot.png
  describe_image.py shot.png --prompt "List every distinct colour region."
  describe_image.py before.png after.png --prompt "What changed?"
"""
import argparse, base64, json, mimetypes, sys, urllib.error, urllib.request

CANDIDATES = ["http://127.0.0.1:8080", "http://127.0.0.1:8081", "http://0.0.0.0:8080"]

DEFAULT_PROMPT = (
    "This is a screenshot from a PC-FX (1994 console, 256x240, 8-bit paletted YUV) "
    "program. Describe exactly what is on screen: layout, distinct regions, colours, "
    "and any text. If something looks like a rendering defect -- torn edges, swapped "
    "pixel pairs, colour banding, garbage blocks, a black screen -- say so explicitly "
    "and where it is. Do not speculate about code."
)


def can_see(base):
    try:
        with urllib.request.urlopen(base + "/v1/models", timeout=3) as r:
            json.load(r)
    except Exception:
        return False
    try:
        with urllib.request.urlopen(base + "/props", timeout=3) as r:
            p = json.load(r)
        if p.get("modalities", {}).get("vision"):
            return True
        return "mmproj" in json.dumps(p).lower()
    except Exception:
        return False          # reachable but no /props -> assume text-only


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--endpoint", help="skip auto-detection, use this base URL")
    ap.add_argument("--max-tokens", type=int, default=600)
    a = ap.parse_args()

    base = a.endpoint
    if not base:
        for c in CANDIDATES:
            if can_see(c):
                base = c
                break
    if not base:
        sys.exit(
            "No vision-capable endpoint found on :8080 or :8081.\n"
            "Start a vision-capable OpenAI-compatible server and set "
            "PCFX_LLM_ENDPOINT if needed. Check the endpoint's /props response "
            "to confirm that a vision projector is loaded."
        )

    content = [{"type": "text", "text": a.prompt}]
    for img in a.images:
        content.append({"type": "image_url", "image_url": {"url": data_uri(img)}})

    body = {"messages": [{"role": "user", "content": content}],
            "max_tokens": a.max_tokens, "temperature": 0.2}
    req = urllib.request.Request(base + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{base}: HTTP {e.code}: {e.read()[:500].decode('utf-8','replace')}")

    print(f"[endpoint: {base}]", file=sys.stderr)
    print(d["choices"][0]["message"]["content"])


if __name__ == "__main__":
    main()
