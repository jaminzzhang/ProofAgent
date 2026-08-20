CREATE TABLE knowledge_queries (
    knowledge_query_id text PRIMARY KEY,
    client_id text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL CHECK (
        request_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    knowledge_space_id text NOT NULL,
    client_grant_id text NOT NULL,
    effective_access_scope_digest text NOT NULL CHECK (
        effective_access_scope_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    knowledge_base_release_id text NOT NULL,
    state text NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')
    ),
    state_version bigint NOT NULL DEFAULT 1 CHECK (state_version > 0),
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    lease_owner text,
    lease_expires_at timestamptz,
    request_json jsonb NOT NULL CHECK (jsonb_typeof(request_json) = 'object'),
    query_json jsonb NOT NULL CHECK (jsonb_typeof(query_json) = 'object'),
    admission_json jsonb NOT NULL CHECK (jsonb_typeof(admission_json) = 'object'),
    submitted_at timestamptz NOT NULL,
    deadline_at timestamptz NOT NULL CHECK (deadline_at > submitted_at),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (client_id, idempotency_key),
    CHECK (
        (lease_owner IS NULL AND lease_expires_at IS NULL)
        OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND fencing_token > 0)
    )
);

CREATE INDEX knowledge_queries_claim_idx
    ON knowledge_queries (submitted_at, knowledge_query_id)
    WHERE state IN ('queued', 'running');

CREATE TABLE knowledge_query_outbox (
    event_id text PRIMARY KEY,
    knowledge_query_id text NOT NULL REFERENCES knowledge_queries(knowledge_query_id),
    event_type text NOT NULL,
    payload_json jsonb NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz
);

CREATE INDEX knowledge_query_outbox_unpublished_idx
    ON knowledge_query_outbox (created_at, event_id)
    WHERE published_at IS NULL;
