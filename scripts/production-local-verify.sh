#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.production-local.yml"
ENV_FILE="$ROOT_DIR/.env.production-local"
CA_FILE="$ROOT_DIR/docker/production-local/runtime/tls/ca.crt"
DOCKER_CONFIG="$ROOT_DIR/docker/production-local/runtime/docker-cli"
export DOCKER_CONFIG

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

if [ ! -f "$ENV_FILE" ] || [ ! -f "$CA_FILE" ]; then
  printf 'Run scripts/production-local-up.sh first.\n' >&2
  exit 1
fi

compose config --quiet
curl --fail --silent --show-error --cacert "$CA_FILE" \
  https://proof-agent.localhost:8443/livez >/dev/null
printf 'PASS API livez\n'

curl --fail --silent --show-error --cacert "$CA_FILE" \
  https://proof-agent.localhost:8444/readyz \
  | python3 -c 'import json, sys; value=json.load(sys.stdin); assert value["status"] == "ready"; assert {item["name"]: item["status"] for item in value["dependencies"]} == {"postgresql":"ready","object_storage":"ready","search":"ready"}'
printf 'PASS Knowledge Source Service readyz\n'

curl --fail --silent --show-error --cacert "$CA_FILE" \
  https://proof-agent.localhost:8443/ \
  | grep -q '<title>Proof Agent Dashboard</title>'
printf 'PASS Dashboard SPA\n'

curl --fail --silent --show-error --cacert "$CA_FILE" \
  https://proof-agent.localhost:8443/oidc/realms/proof-agent/.well-known/openid-configuration \
  | python3 -c 'import json, sys; value=json.load(sys.stdin)["issuer"]; expected="https://proof-agent.localhost:8443/oidc/realms/proof-agent"; assert value == expected, (value, expected)'
printf 'PASS OIDC issuer\n'

compose exec -T api python /opt/proof-agent-local/verify_runtime.py
compose exec -T postgres psql -U proof -d proof -v ON_ERROR_STOP=1 \
  -c 'SELECT version_num AS alembic_version FROM alembic_version' \
  -c 'SELECT egress_policy_revision, permission_mapping_revision FROM security_configuration_state'
compose exec -T postgres psql -U proof -d knowledge_source_service -v ON_ERROR_STOP=1 \
  -c 'SELECT revision FROM kss_schema_migrations ORDER BY revision'
compose exec -T postgres psql -U proof -d postgres -v ON_ERROR_STOP=1 \
  -c "DO \$verify\$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'knowledge_source_service'
      AND rolcanlogin
      AND NOT rolsuper
  ) THEN
    RAISE EXCEPTION 'KSS login role is missing or over-privileged';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_database
    WHERE datname = 'knowledge_source_service'
      AND pg_get_userbyid(datdba) = 'knowledge_source_service'
  ) THEN
    RAISE EXCEPTION 'KSS database owner drifted';
  END IF;
END
\$verify\$;"
compose exec -T postgres psql -U proof -d knowledge_source_service -v ON_ERROR_STOP=1 \
  -c "DO \$verify\$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'public'
      AND pg_get_userbyid(nspowner) = 'knowledge_source_service'
  ) THEN
    RAISE EXCEPTION 'KSS public schema owner drifted';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tableowner <> 'knowledge_source_service'
  ) THEN
    RAISE EXCEPTION 'KSS table owner drifted';
  END IF;
END
\$verify\$;"
printf 'PASS KSS PostgreSQL authority isolation\n'
compose run --rm --no-deps --entrypoint mc minio-init \
  version info local/proof-agent-local
compose run --rm --no-deps --entrypoint mc minio-init \
  version info local/proof-agent-knowledge-local

printf '\nReadiness (HTTP 503 is expected until the sole production Agent is published):\n'
curl --silent --show-error --cacert "$CA_FILE" \
  --write-out '\nHTTP %{http_code}\n' \
  https://proof-agent.localhost:8443/readyz
printf '\nContainer state:\n'
compose ps -a
