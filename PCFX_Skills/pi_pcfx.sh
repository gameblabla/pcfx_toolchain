#!/usr/bin/env bash
# Run the `pi` coding agent against the local Qwen server with the PC-FX skill
# bundle loaded.
#
#   ./pi_pcfx.sh                          interactive
#   ./pi_pcfx.sh "why is my screen black" one-shot (non-interactive)
#   ./pi_pcfx.sh -- --thinking high ...   pass extra flags through to pi
#
# Two ways to carry the bundle, chosen with PCFX_SKILL_MODE:
#
#   router (default)  only ROUTER_PROMPT.md + SKILLS.md go in the system prompt;
#                     the agent opens individual modules with its `read` tool.
#                     ~3k tokens instead of ~60k, so every tool round trip is
#                     cheap -- which matters a lot on a local 27B.
#   full              every SKILL.md preloaded via pi's --skill. Use for a
#                     one-shot question where you do not want a lookup step.
#
# Requires any OpenAI-compatible local server. Set PCFX_LLM_ENDPOINT when it is
# not listening at the default http://localhost:8080.
set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "$0")" && pwd)"
ENDPOINT="${PCFX_LLM_ENDPOINT:-http://localhost:8080}"
PROVIDER="${PCFX_LLM_PROVIDER:-local-llm}"

if ! curl -sf -m 5 "$ENDPOINT/v1/models" >/dev/null 2>&1; then
  echo "No LLM server on $ENDPOINT" >&2
  echo "Start an OpenAI-compatible server and set PCFX_LLM_ENDPOINT if needed." >&2
  exit 1
fi

# pi's image read tool checks the selected model's declared `input` types.
# A server can advertise a vision model under its GGUF filename while pi's
# models.json registers the same endpoint as a short id with input=[text,image].
# Passing the unknown filename makes pi create a text-only fallback model and
# silently omit image pixels. Prefer the matching configured id in that case.
SERVER_INFO="$(curl -sf -m 5 "$ENDPOINT/v1/models")"
MODEL="${PCFX_LLM_MODEL:-$(printf '%s' "$SERVER_INFO" | python3 -c '
import json, os, pathlib, sys
server = json.load(sys.stdin)
entry = server["data"][0]
served_id = entry["id"]
capabilities = set(entry.get("capabilities", []))
for item in server.get("models", []):
    if item.get("model") == served_id:
        capabilities.update(item.get("capabilities", []))
config_path = pathlib.Path.home() / ".pi/agent/models.json"
try:
    providers = json.loads(config_path.read_text()).get("providers", {})
except (OSError, ValueError):
    providers = {}
provider = providers.get(os.environ.get("PCFX_LLM_PROVIDER", "local-llm"), {})
models = provider.get("models", [])
configured = next((m for m in models if m.get("id") == served_id), None)
if configured:
    print(served_id)
elif "multimodal" in capabilities:
    matches = [m for m in models if "image" in m.get("input", [])
               and served_id.lower().startswith(m.get("id", "").lower())]
    print(matches[0]["id"] if len(matches) == 1 else served_id)
else:
    print(served_id)
')}"

MODE="${PCFX_SKILL_MODE:-router}"

echo "model    : $MODEL" >&2
echo "endpoint : $ENDPOINT" >&2
echo "skills   : $SKILLS_DIR ($MODE)" >&2

ARGS=(
  --provider "$PROVIDER"
  --model    "$MODEL"
  --append-system-prompt "$SKILLS_DIR/ROUTER_PROMPT.md"
  --tools    bash,read,edit,write,grep,find,ls
)

if [ "$MODE" = "full" ]; then
  ARGS+=(--skill "$SKILLS_DIR")
else
  # Router mode: ship the symptom->module table and tell the agent where the
  # modules live, so it fetches only what the task needs.
  LOOKUP="$(mktemp -t pcfx-lookup.XXXXXX.md)"
  trap 'rm -f "$LOOKUP"' EXIT
  {
    echo "## Where the modules are"
    echo
    echo "The router below names modules. Each one is a file you must open before"
    echo "acting on it, with your read tool:"
    echo
    echo "    $SKILLS_DIR/<module-name>/SKILL.md"
    echo
    echo "Read the whole module and copy its code blocks verbatim. If you did not"
    echo "open the module, you do not know what it says -- do not answer from memory."
    echo
    cat "$SKILLS_DIR/SKILLS.md"
  } > "$LOOKUP"
  ARGS+=(--append-system-prompt "$LOOKUP")
fi

# Everything after `--` goes to pi verbatim; a bare first argument is a prompt.
PASSTHRU=()
PROMPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --) shift; PASSTHRU+=("$@"); break ;;
    *)  if [ -z "$PROMPT" ]; then PROMPT="$1"; else PASSTHRU+=("$1"); fi; shift ;;
  esac
done

if [ -n "$PROMPT" ]; then
  exec pi "${ARGS[@]}" "${PASSTHRU[@]}" -p "$PROMPT"
else
  exec pi "${ARGS[@]}" "${PASSTHRU[@]}"
fi
