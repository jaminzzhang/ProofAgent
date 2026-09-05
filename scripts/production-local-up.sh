#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.production-local.yml"
ENV_FILE="$ROOT_DIR/.env.production-local"
DOCKER_CONFIG="$ROOT_DIR/docker/production-local/runtime/docker-cli"
export DOCKER_CONFIG

KSS_IMAGE=${KSS_IMAGE:?set KSS_IMAGE to an externally built immutable name@sha256 reference}
case "$KSS_IMAGE" in
  *@sha256:*) ;;
  *)
    printf 'KSS_IMAGE must be an immutable name@sha256 reference.\n' >&2
    exit 2
    ;;
esac
KSS_IMAGE_NAME=${KSS_IMAGE%@sha256:*}
if [ -z "$KSS_IMAGE_NAME" ]; then
  printf 'KSS_IMAGE must include a non-empty image name before @sha256.\n' >&2
  exit 2
fi
KSS_DIGEST=${KSS_IMAGE##*@sha256:}
case "$KSS_DIGEST" in
  ""|*[!0-9a-f]*)
    printf 'KSS_IMAGE digest must be 64 lowercase hexadecimal characters.\n' >&2
    exit 2
    ;;
esac
if [ "${#KSS_DIGEST}" -ne 64 ]; then
  printf 'KSS_IMAGE digest must be 64 lowercase hexadecimal characters.\n' >&2
  exit 2
fi
export KSS_IMAGE

"$ROOT_DIR/scripts/production-local-prepare.sh"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
PROOF_AGENT_IMAGE_DIGEST=$(docker image inspect \
  --format '{{.Id}}' proof-agent:production-local)
PROOF_AGENT_IMAGE_DIGEST=${PROOF_AGENT_IMAGE_DIGEST#sha256:}
export PROOF_AGENT_IMAGE_DIGEST
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --no-build --wait
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
