# Encrypt Production Model Credentials in PostgreSQL

Status: Accepted

Date: 2026-07-26

Supersedes: the production model-credential storage decision in ADR-0020

## Context

Production Shared Model Connections need centrally managed provider API keys. A
Secret Handle adds a second model-credential control plane and makes the model
connection lifecycle depend on Vault. Storing plaintext API keys in connection JSON,
API responses, audit events, traces, or backups would violate the Control Envelope.

## Decision

Proof Agent stores production model API keys in a separate PostgreSQL
`model_connection_credentials` table as AES-256-GCM authenticated ciphertext. The
connection JSON stores only a `postgres_encrypted` configured marker. Encryption uses
the immutable connection id as associated-data context, and every envelope records a
key version.

The key-encryption keyring is deployment-owned and must be mounted from
`PROOF_AGENT_MODEL_CREDENTIAL_KEYRING_FILE`; it is never stored in PostgreSQL and has
no environment-value fallback. API create and update accept `api_key` as a write-only
secret value. Responses, validation records, smoke records, configuration audit,
trace, and published contracts return only the configured marker.

Runtime model providers receive credential bytes only through the
`ModelCredentialResolver` port immediately before provider-client construction.
Production Agent admission requires an active Shared Model Connection with the
PostgreSQL marker and a resolvable envelope. Environment references and model Secret
Handles remain development/legacy contracts and are rejected by production Agent
admission.

Vault remains the authority for OIDC/session, Knowledge, evaluator, and tool secrets.
This decision changes only model-provider credentials.

## Rotation and recovery

To rotate the key-encryption key, operators add a new version to the keyring, make it
active, roll all model-capable processes, replace each model API key through the
write-only API so its row is re-encrypted, verify no row uses the retired version,
then remove the old key and roll again. Old versions must remain in the keyring until
that verification completes.

PostgreSQL backups and keyring backups are separate recovery assets. A database
backup without its retained key versions cannot recover model credentials; a lost
keyring requires operators to enter provider keys again. Suspected keyring compromise
requires both provider-key rotation and key-encryption-key rotation.

## Consequences

- Model connection and ciphertext writes commit in one PostgreSQL transaction.
- PostgreSQL operators can see ciphertext and key versions but not plaintext without
  the separately mounted keyring.
- Dashboard users can create or replace a key but cannot read it back.
- A missing or damaged keyring fails model-capable process startup. A missing row or
  retired key version fails validation, publication admission, and model execution
  closed.
- There is no automatic bulk rewrap command yet; retiring a key version is an
  explicit operational procedure.
