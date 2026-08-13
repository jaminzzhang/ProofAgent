#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_DIR="$ROOT_DIR/docker/production-local/runtime"
TLS_DIR="$RUNTIME_DIR/tls"
DOCKER_CONFIG_DIR="$RUNTIME_DIR/docker-cli"
SECRETS_DIR="$RUNTIME_DIR/secrets"
MODEL_CREDENTIAL_KEYRING="$SECRETS_DIR/model-credential-keyring.json"
DEPLOYMENT_COMPATIBILITY_MANIFEST="$RUNTIME_DIR/deployment-compatibility-manifest.json"
ENV_FILE="$ROOT_DIR/.env.production-local"

umask 077
mkdir -p "$TLS_DIR" "$DOCKER_CONFIG_DIR" "$SECRETS_DIR"

# Public images do not require the host credential helper. Keeping a deployment-
# local CLI config also prevents a broken desktop keychain integration from
# blocking an otherwise anonymous pull.
if [ ! -f "$DOCKER_CONFIG_DIR/config.json" ]; then
  printf '{\n  "auths": {}\n}\n' > "$DOCKER_CONFIG_DIR/config.json"
fi
if [ -d "$HOME/.docker/cli-plugins" ] && [ ! -e "$DOCKER_CONFIG_DIR/cli-plugins" ]; then
  ln -s "$HOME/.docker/cli-plugins" "$DOCKER_CONFIG_DIR/cli-plugins"
fi

if [ ! -f "$ENV_FILE" ]; then
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  MINIO_ROOT_USER=proofagentlocal
  MINIO_ROOT_PASSWORD=$(openssl rand -hex 24)
  VAULT_ROOT_TOKEN=$(openssl rand -hex 24)
  SESSION_ENVELOPE_KEY=$(openssl rand -hex 16)
  CSRF_KEY=$(openssl rand -hex 16)
  OIDC_CLIENT_SECRET=$(openssl rand -hex 24)
  LOCAL_EVALUATION_TOKEN=$(openssl rand -hex 24)
  KEYCLOAK_BOOTSTRAP_PASSWORD=$(openssl rand -hex 16)
  PROOF_AGENT_ADMIN_PASSWORD=$(openssl rand -hex 12)

  {
    printf 'POSTGRES_PASSWORD=%s\n' "$POSTGRES_PASSWORD"
    printf 'MINIO_ROOT_USER=%s\n' "$MINIO_ROOT_USER"
    printf 'MINIO_ROOT_PASSWORD=%s\n' "$MINIO_ROOT_PASSWORD"
    printf 'VAULT_ROOT_TOKEN=%s\n' "$VAULT_ROOT_TOKEN"
    printf 'SESSION_ENVELOPE_KEY=%s\n' "$SESSION_ENVELOPE_KEY"
    printf 'CSRF_KEY=%s\n' "$CSRF_KEY"
    printf 'OIDC_CLIENT_SECRET=%s\n' "$OIDC_CLIENT_SECRET"
    printf 'LOCAL_EVALUATION_TOKEN=%s\n' "$LOCAL_EVALUATION_TOKEN"
    printf 'KEYCLOAK_BOOTSTRAP_PASSWORD=%s\n' "$KEYCLOAK_BOOTSTRAP_PASSWORD"
    printf 'PROOF_AGENT_ADMIN_PASSWORD=%s\n' "$PROOF_AGENT_ADMIN_PASSWORD"
  } > "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
fi

ensure_random_secret() {
  key=$1
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    value=$(openssl rand -hex 24)
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

# These credentials are intentionally generated after the initial file block so
# existing local-production environments can be upgraded without rotating any
# already-issued authority secret.
ensure_random_secret KSS_MODEL_BEARER_TOKEN
ensure_random_secret KSS_OPERATOR_BEARER_TOKEN
ensure_random_secret KSS_AGENT_CLIENT_BEARER_TOKEN
ensure_random_secret KSS_POSTGRES_PASSWORD
chmod 0600 "$ENV_FILE"

if [ ! -f "$MODEL_CREDENTIAL_KEYRING" ]; then
  MODEL_CREDENTIAL_KEY=$(openssl rand -base64 32 | tr -d '\n')
  {
    printf '{\n'
    printf '  "active_key_version": "v1",\n'
    printf '  "keys": {"v1": "%s"}\n' "$MODEL_CREDENTIAL_KEY"
    printf '}\n'
  } > "$MODEL_CREDENTIAL_KEYRING"
  chmod 0600 "$MODEL_CREDENTIAL_KEYRING"
fi

# This is a short-lived local harness fixture, regenerated on every prepare so
# the production composition can exercise its freshness checks. It is never a
# formal candidate-bound compatibility artifact or release Gate evidence.
python3 "$ROOT_DIR/docker/production-local/generate_deployment_compatibility_manifest.py" \
  "$DEPLOYMENT_COMPATIBILITY_MANIFEST"
chmod 0644 "$DEPLOYMENT_COMPATIBILITY_MANIFEST"

if [ ! -f "$TLS_DIR/ca.crt" ] || [ ! -f "$TLS_DIR/server.crt" ] || [ ! -f "$TLS_DIR/server.key" ]; then
  openssl genrsa -out "$TLS_DIR/ca.key" 3072 >/dev/null 2>&1
  openssl req -x509 -new -sha256 -days 825 \
    -key "$TLS_DIR/ca.key" \
    -subj '/CN=Proof Agent Local Production CA' \
    -out "$TLS_DIR/ca.crt"
  openssl genrsa -out "$TLS_DIR/server.key" 3072 >/dev/null 2>&1
  openssl req -new -sha256 \
    -key "$TLS_DIR/server.key" \
    -subj '/CN=proof-agent.localhost' \
    -out "$TLS_DIR/server.csr"
  {
    printf 'subjectAltName=DNS:proof-agent.localhost,DNS:vault.internal,DNS:opensearch.internal,DNS:models.internal\n'
    printf 'extendedKeyUsage=serverAuth\n'
    printf 'keyUsage=digitalSignature,keyEncipherment\n'
  } > "$TLS_DIR/server.ext"
  openssl x509 -req -sha256 -days 825 \
    -in "$TLS_DIR/server.csr" \
    -CA "$TLS_DIR/ca.crt" \
    -CAkey "$TLS_DIR/ca.key" \
    -CAcreateserial \
    -extfile "$TLS_DIR/server.ext" \
    -out "$TLS_DIR/server.crt" >/dev/null 2>&1
  chmod 0600 "$TLS_DIR/ca.key" "$TLS_DIR/server.key"
  chmod 0644 "$TLS_DIR/ca.crt" "$TLS_DIR/server.crt"
fi

printf 'Prepared local production secrets and TLS assets.\n'
printf 'Environment: %s\n' "$ENV_FILE"
printf 'CA certificate: %s\n' "$TLS_DIR/ca.crt"
printf 'Model credential keyring: %s\n' "$MODEL_CREDENTIAL_KEYRING"
printf 'Local compatibility fixture: %s\n' "$DEPLOYMENT_COMPATIBILITY_MANIFEST"
