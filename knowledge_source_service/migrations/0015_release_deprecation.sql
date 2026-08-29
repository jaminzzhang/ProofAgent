-- One-way deprecation preserves queryability while blocking new adoption.
ALTER TABLE knowledge_base_releases
    DROP CONSTRAINT knowledge_base_releases_state_check;

ALTER TABLE knowledge_base_releases
    ADD COLUMN deprecated_at timestamptz,
    ADD CONSTRAINT knowledge_base_releases_state_check
        CHECK (state IN ('queryable', 'deprecated', 'retired')),
    ADD CONSTRAINT knowledge_base_releases_deprecation_time_check CHECK (
        (state = 'deprecated' AND deprecated_at IS NOT NULL)
        OR (state <> 'deprecated' AND deprecated_at IS NULL)
    );

-- One row is both the permanent command receipt and append-only success audit.
CREATE TABLE knowledge_base_release_lifecycle_commands (
    event_sequence bigserial UNIQUE NOT NULL,
    operator_id text NOT NULL,
    key_digest text NOT NULL CHECK (key_digest ~ '^sha256:[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action = 'deprecate'),
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    knowledge_base_release_id text NOT NULL,
    recorded_at timestamptz NOT NULL,
    result_json jsonb NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    PRIMARY KEY (operator_id, key_digest),
    CONSTRAINT knowledge_base_release_lifecycle_exact_release_fk
        FOREIGN KEY (knowledge_base_release_id, knowledge_space_id, knowledge_base_id)
        REFERENCES knowledge_base_releases (
            knowledge_base_release_id,
            knowledge_space_id,
            knowledge_base_id
        ) ON DELETE RESTRICT,
    CHECK (result_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK (result_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (result_json ->> 'knowledge_base_release_id' = knowledge_base_release_id),
    CHECK (result_json ->> 'state' = 'deprecated'),
    CHECK ((result_json ->> 'deprecated_at')::timestamptz = recorded_at)
);

CREATE INDEX knowledge_base_release_lifecycle_commands_audit_idx
    ON knowledge_base_release_lifecycle_commands (
        knowledge_base_release_id,
        event_sequence
    );
