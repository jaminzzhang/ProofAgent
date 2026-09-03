#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  printf 'Usage: %s <private-session-json-file>\n' "$0" >&2
  exit 2
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SESSION_FILE=$1
case "$SESSION_FILE" in
  /*) ;;
  *) SESSION_FILE="$(pwd)/$SESSION_FILE" ;;
esac

cd "$ROOT_DIR"
exec .venv/bin/python -m scripts.deployment.agent_rollback_gate_probe \
  https://proof-agent.localhost:8443 \
  "$ROOT_DIR/docker/production-local/runtime/tls/ca.crt" \
  "$SESSION_FILE"
