-- Durable executable-client references. Registration only; lifecycle commands follow later.
ALTER TABLE knowledge_base_releases
    ADD CONSTRAINT knowledge_base_releases_exact_identity_key
    UNIQUE (knowledge_base_release_id, knowledge_space_id, knowledge_base_id);

CREATE TABLE knowledge_base_release_references (
    release_reference_id text PRIMARY KEY,
    authenticated_client_id text NOT NULL,
    external_resource_kind text NOT NULL CHECK (
        external_resource_kind = 'published_agent_version'
    ),
    external_resource_id text NOT NULL,
    purpose text NOT NULL CHECK (purpose = 'execution_or_rollback'),
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    knowledge_base_release_id text NOT NULL,
    state text NOT NULL CHECK (state = 'active'),
    registered_at timestamptz NOT NULL,
    reference_json jsonb NOT NULL CHECK (jsonb_typeof(reference_json) = 'object'),
    CONSTRAINT knowledge_base_release_references_external_resource_key
        UNIQUE (authenticated_client_id, external_resource_kind, external_resource_id),
    CONSTRAINT knowledge_base_release_references_exact_release_fk
        FOREIGN KEY (knowledge_base_release_id, knowledge_space_id, knowledge_base_id)
        REFERENCES knowledge_base_releases (
            knowledge_base_release_id,
            knowledge_space_id,
            knowledge_base_id
        ) ON DELETE RESTRICT,
    CHECK (reference_json ->> 'release_reference_id' = release_reference_id),
    CHECK (reference_json ->> 'authenticated_client_id' = authenticated_client_id),
    CHECK (reference_json ->> 'external_resource_kind' = external_resource_kind),
    CHECK (reference_json ->> 'external_resource_id' = external_resource_id),
    CHECK (reference_json ->> 'purpose' = purpose),
    CHECK (reference_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK (reference_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (reference_json ->> 'knowledge_base_release_id' = knowledge_base_release_id),
    CHECK (reference_json ->> 'state' = state),
    CHECK ((reference_json ->> 'registered_at')::timestamptz = registered_at)
);

-- One row is both the permanent command receipt and the append-only success audit.
CREATE TABLE knowledge_base_release_reference_commands (
    event_sequence bigserial UNIQUE NOT NULL,
    authenticated_client_id text NOT NULL,
    key_digest text NOT NULL CHECK (key_digest ~ '^sha256:[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action = 'register'),
    release_reference_id text NOT NULL,
    knowledge_base_release_id text NOT NULL,
    result_json jsonb NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    PRIMARY KEY (authenticated_client_id, key_digest),
    FOREIGN KEY (release_reference_id)
        REFERENCES knowledge_base_release_references (release_reference_id) ON DELETE RESTRICT,
    CHECK (result_json ->> 'release_reference_id' = release_reference_id),
    CHECK (result_json ->> 'knowledge_base_release_id' = knowledge_base_release_id)
);

CREATE INDEX knowledge_base_release_reference_commands_audit_idx
    ON knowledge_base_release_reference_commands (
        knowledge_base_release_id,
        event_sequence
    );
