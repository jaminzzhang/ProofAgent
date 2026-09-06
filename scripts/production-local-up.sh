#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.production-local.yml"
ENV_FILE="$ROOT_DIR/.env.production-local"
DOCKER_CONFIG="$ROOT_DIR/docker/production-local/runtime/docker-cli"
export DOCKER_CONFIG

"$ROOT_DIR/scripts/production-local-prepare.sh"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
PROOF_AGENT_IMAGE_DIGEST=$(docker image inspect \
  --format '{{.Id}}' proof-agent:production-local)
PROOF_AGENT_IMAGE_DIGEST=${PROOF_AGENT_IMAGE_DIGEST#sha256:}
export PROOF_AGENT_IMAGE_DIGEST
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --no-build --wait
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
