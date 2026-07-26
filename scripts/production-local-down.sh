#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.production-local.yml"
ENV_FILE="$ROOT_DIR/.env.production-local"
DOCKER_CONFIG="$ROOT_DIR/docker/production-local/runtime/docker-cli"
export DOCKER_CONFIG

if [ ! -f "$ENV_FILE" ]; then
  printf 'Nothing to stop: %s does not exist.\n' "$ENV_FILE"
  exit 0
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
