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

# pi's model catalogue is keyed by model id; use whatever the server is serving
# so this keeps working when the loaded model changes.
MODEL="${PCFX_LLM_MODEL:-$(curl -sf "$ENDPOINT/v1/models" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])')}"

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
