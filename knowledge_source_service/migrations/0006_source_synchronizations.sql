CREATE TABLE knowledge_source_synchronizations (
    knowledge_source_synchronization_id text PRIMARY KEY,
    operator_id text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL CHECK (
        request_fingerprint ~ '^sha256:[0-9a-f]{64}$'
    ),
    knowledge_space_id text NOT NULL,
    knowledge_source_id text NOT NULL,
    connection_id text NOT NULL,
    state text NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed')
    ),
    state_version bigint NOT NULL DEFAULT 1 CHECK (state_version > 0),
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    lease_owner text,
    lease_expires_at timestamptz,
    request_json jsonb NOT NULL CHECK (jsonb_typeof(request_json) = 'object'),
    resource_json jsonb NOT NULL CHECK (jsonb_typeof(resource_json) = 'object'),
    materialized_knowledge_source_version_id text,
    submitted_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (operator_id, idempotency_key),
    FOREIGN KEY (knowledge_source_id, knowledge_space_id)
        REFERENCES knowledge_sources(knowledge_source_id, knowledge_space_id),
    FOREIGN KEY (materialized_knowledge_source_version_id, knowledge_space_id)
        REFERENCES knowledge_source_versions(
            knowledge_source_version_id,
            knowledge_space_id
        ) ON DELETE RESTRICT,
    CHECK (resource_json ->> 'state' = state),
    CHECK (
        resource_json ->> 'knowledge_source_synchronization_id'
            = knowledge_source_synchronization_id
    ),
    CHECK (
        (lease_owner IS NULL AND lease_expires_at IS NULL)
        OR (
            lease_owner IS NOT NULL
            AND lease_expires_at IS NOT NULL
            AND fencing_token > 0
        )
    ),
    CHECK (
        (state = 'succeeded' AND materialized_knowledge_source_version_id IS NOT NULL)
        OR (state <> 'succeeded' AND materialized_knowledge_source_version_id IS NULL)
    )
);

CREATE INDEX knowledge_source_synchronizations_claim_idx
    ON knowledge_source_synchronizations (submitted_at, knowledge_source_synchronization_id)
    WHERE state IN ('queued', 'running');

CREATE TABLE knowledge_source_synchronization_outbox (
    event_id text PRIMARY KEY,
    knowledge_source_synchronization_id text NOT NULL REFERENCES
        knowledge_source_synchronizations(knowledge_source_synchronization_id),
    event_type text NOT NULL,
    payload_json jsonb NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz
);

CREATE INDEX knowledge_source_synchronization_outbox_unpublished_idx
    ON knowledge_source_synchronization_outbox (created_at, event_id)
    WHERE published_at IS NULL;
