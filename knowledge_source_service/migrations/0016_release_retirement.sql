-- Ordinary retirement keeps deprecation history and makes the Release non-queryable.
ALTER TABLE knowledge_base_releases
    DROP CONSTRAINT knowledge_base_releases_deprecation_time_check;

ALTER TABLE knowledge_base_releases
    ADD COLUMN retired_at timestamptz,
    ADD CONSTRAINT knowledge_base_releases_lifecycle_time_check CHECK (
        (state = 'queryable' AND deprecated_at IS NULL AND retired_at IS NULL)
        OR (state = 'deprecated' AND deprecated_at IS NOT NULL AND retired_at IS NULL)
        OR (
            state = 'retired'
            AND (
                (deprecated_at IS NULL AND retired_at IS NULL)
                OR (
                    deprecated_at IS NOT NULL
                    AND retired_at IS NOT NULL
                    AND retired_at >= deprecated_at
                )
            )
        )
    );

-- Use the existing lifecycle sequence so deprecation and retirement audits share order.
CREATE TABLE knowledge_base_release_retirement_commands (
    event_sequence bigint UNIQUE NOT NULL DEFAULT nextval(
        'knowledge_base_release_lifecycle_commands_event_sequence_seq'
    ),
    operator_id text NOT NULL,
    key_digest text NOT NULL CHECK (key_digest ~ '^sha256:[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action = 'retire'),
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    knowledge_base_release_id text NOT NULL,
    retention_policy_id text NOT NULL,
    deprecated_at timestamptz NOT NULL,
    retention_eligible_at timestamptz NOT NULL,
    retired_at timestamptz NOT NULL,
    result_json jsonb NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    PRIMARY KEY (operator_id, key_digest),
    CONSTRAINT knowledge_base_release_retirement_exact_release_fk
        FOREIGN KEY (knowledge_base_release_id, knowledge_space_id, knowledge_base_id)
        REFERENCES knowledge_base_releases (
            knowledge_base_release_id,
            knowledge_space_id,
            knowledge_base_id
        ) ON DELETE RESTRICT,
    CHECK (retention_eligible_at >= deprecated_at),
    CHECK (retired_at >= retention_eligible_at),
    CHECK (result_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK (result_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (result_json ->> 'knowledge_base_release_id' = knowledge_base_release_id),
    CHECK (result_json ->> 'state' = 'retired'),
    CHECK (result_json ->> 'retention_policy_id' = retention_policy_id),
    CHECK ((result_json ->> 'deprecated_at')::timestamptz = deprecated_at),
    CHECK (
        (result_json ->> 'retention_eligible_at')::timestamptz = retention_eligible_at
    ),
    CHECK ((result_json ->> 'retired_at')::timestamptz = retired_at)
);

CREATE INDEX knowledge_base_release_retirement_commands_audit_idx
    ON knowledge_base_release_retirement_commands (
        knowledge_base_release_id,
        event_sequence
    );
