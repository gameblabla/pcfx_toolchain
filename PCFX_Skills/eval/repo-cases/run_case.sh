#!/usr/bin/env bash
# Repo-level regression: break a working PC-FX project, hand it to the local
# agent, and judge the result by building and looking at the screen.
#
#   ./run_case.sh mul-high-word skills     # pi with the PCFX_Skills bundle
#   ./run_case.sh mul-high-word none       # pi with no bundle (control arm)
#   ./run_case.sh mul-high-word manual     # just set up the broken tree, no agent
#
# The point of the `none` arm is that a case only proves something about the
# bundle if the unaided model fails it.
set -uo pipefail

CASE="${1:?usage: run_case.sh <case> [skills|none|manual]}"
ARM="${2:-skills}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BUNDLE="$(cd "$HERE/../.." && pwd)"
TEMPLATE="$BUNDLE/pcfx-3d-pipeline/template"
CASEDIR="$HERE/cases/$CASE"
[ -d "$CASEDIR" ] || { echo "no such case: $CASE" >&2; exit 2; }

WORK="${PCFX_CASE_WORKDIR:-$BUNDLE/../build/eval/cases/$CASE-$ARM}"

# Two runs sharing a workdir silently corrupt each other's tree and queue on the
# server's single slot, which looks exactly like a hung agent. mkdir is atomic, so
# it is a lock; pgrep is not -- it also matches this run's own `timeout` parent.
LOCK="$WORK.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "another run of '$CASE $ARM' holds $LOCK; wait for it, or set PCFX_CASE_WORKDIR" >&2
  exit 2
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# A case is either against the bundled cube template, or -- if it ships a
# case.env -- against a real project in the workspace, compared to a reference
# screenshot. Real-project cases catch the bugs that still draw most of the picture.
if [ -f "$CASEDIR/case.env" ]; then
  SOURCE="$(sed -n 's/^SOURCE=//p' "$CASEDIR/case.env")"
  SOURCE="${SOURCE:-${PCFX_EVAL_SOURCE:-}}"
  [ -d "$SOURCE" ] || { echo "case.env SOURCE does not exist: $SOURCE" >&2; exit 2; }
  VERIFIER=("$HERE/verify_reference.py" "$WORK" --config "$CASEDIR/case.env")
else
  SOURCE="$TEMPLATE"
  VERIFY_ARGS=()
  if [ -f "$CASEDIR/flags" ]; then
    grep -qx 'flip'     "$CASEDIR/flags" && VERIFY_ARGS+=(--flip)
    grep -qx 'hosttest' "$CASEDIR/flags" && VERIFY_ARGS+=(--hosttest)
  fi
  VERIFIER=("$HERE/verify.py" "$WORK" "${VERIFY_ARGS[@]}")
fi

rm -rf "$WORK"; mkdir -p "$WORK"
cp -r "$SOURCE/." "$WORK/"
rm -f "$WORK"/*.elf "$WORK"/*.map "$WORK"/src/*.o

python3 "$CASEDIR/break.py" "$WORK" || exit 2

echo "=== confirming the case is actually broken ==="
if python3 "${VERIFIER[@]}"; then
  echo "SETUP ERROR: the broken tree still passes; the case proves nothing." >&2
  exit 2
fi

[ "$ARM" = "manual" ] && { echo "broken tree ready: $WORK"; exit 0; }

echo "=== running the agent ($ARM arm) in $WORK ==="
PROMPT="$(cat "$CASEDIR/task.md")"
START=$(date +%s)
# The agent gets its own budget so the verdict is always computed. An agent that
# reaches a working fix and then keeps going must not be scored as a failure --
# that happened, and it is a different result from never finding the fix.
AGENT_TIMEOUT="${PCFX_AGENT_TIMEOUT:-1800}"
if [ "$ARM" = "skills" ]; then
  ( cd "$WORK" && timeout "$AGENT_TIMEOUT" "$BUNDLE/pi_pcfx.sh" "$PROMPT" ) 2>&1 | tee "$WORK/agent.log"
  AGENT_RC=${PIPESTATUS[0]}
else
  ENDPOINT="${PCFX_LLM_ENDPOINT:-http://localhost:8080}"
  MODEL="${PCFX_LLM_MODEL:-$(curl -sf "$ENDPOINT/v1/models" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])')}"
  ( cd "$WORK" && timeout "$AGENT_TIMEOUT" pi --provider "${PCFX_LLM_PROVIDER:-local-llm}" \
       --model "$MODEL" --tools bash,read,edit,write,grep,find,ls -p "$PROMPT" ) \
    2>&1 | tee "$WORK/agent.log"
  AGENT_RC=${PIPESTATUS[0]}
fi
ELAPSED=$(( $(date +%s) - START ))
[ "${AGENT_RC:-0}" = "124" ] && echo "NOTE: the agent hit its ${AGENT_TIMEOUT}s budget; the verdict below still reflects the tree it left behind."


echo "=== verdict ==="
python3 "${VERIFIER[@]}" --json | tee "$WORK/verdict.json"
RC=${PIPESTATUS[0]}
echo "case=$CASE arm=$ARM seconds=$ELAPSED agent_rc=${AGENT_RC:-0} result=$([ $RC -eq 0 ] && echo PASS || echo FAIL)"
echo "tree: $WORK"
exit $RC
