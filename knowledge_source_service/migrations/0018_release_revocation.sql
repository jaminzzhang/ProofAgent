-- Emergency containment is distinct from ordinary retirement and preserves references.
ALTER TABLE knowledge_base_releases
    DROP CONSTRAINT knowledge_base_releases_state_check,
    DROP CONSTRAINT knowledge_base_releases_lifecycle_time_check;

ALTER TABLE knowledge_base_releases
    ADD COLUMN revoked_at timestamptz,
    ADD COLUMN revocation_reason_code text,
    ADD CONSTRAINT knowledge_base_releases_state_check CHECK (
        state IN ('queryable', 'deprecated', 'retired', 'revoked')
    ),
    ADD CONSTRAINT knowledge_base_releases_revocation_reason_check CHECK (
        revocation_reason_code IS NULL
        OR revocation_reason_code IN (
            'security_incident',
            'severe_data_integrity_failure'
        )
    ),
    ADD CONSTRAINT knowledge_base_releases_lifecycle_time_check CHECK (
        (
            state = 'queryable'
            AND deprecated_at IS NULL
            AND retired_at IS NULL
            AND revoked_at IS NULL
            AND revocation_reason_code IS NULL
        )
        OR (
            state = 'deprecated'
            AND deprecated_at IS NOT NULL
            AND retired_at IS NULL
            AND revoked_at IS NULL
            AND revocation_reason_code IS NULL
        )
        OR (
            state = 'retired'
            AND revoked_at IS NULL
            AND revocation_reason_code IS NULL
            AND (
                (deprecated_at IS NULL AND retired_at IS NULL)
                OR (
                    deprecated_at IS NOT NULL
                    AND retired_at IS NOT NULL
                    AND retired_at >= deprecated_at
                )
            )
        )
        OR (
            state = 'revoked'
            AND retired_at IS NULL
            AND revoked_at IS NOT NULL
            AND revocation_reason_code IS NOT NULL
            AND (deprecated_at IS NULL OR revoked_at >= deprecated_at)
        )
    );

-- Use the shared lifecycle sequence so every successful transition has one total order.
CREATE TABLE knowledge_base_release_revocation_commands (
    event_sequence bigint UNIQUE NOT NULL DEFAULT nextval(
        'knowledge_base_release_lifecycle_commands_event_sequence_seq'
    ),
    operator_id text NOT NULL,
    key_digest text NOT NULL CHECK (key_digest ~ '^sha256:[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action = 'revoke'),
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    knowledge_base_release_id text NOT NULL,
    reason_code text NOT NULL CHECK (
        reason_code IN ('security_incident', 'severe_data_integrity_failure')
    ),
    affected_active_reference_count bigint NOT NULL CHECK (
        affected_active_reference_count >= 0
    ),
    revoked_at timestamptz NOT NULL,
    result_json jsonb NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    PRIMARY KEY (operator_id, key_digest),
    CONSTRAINT knowledge_base_release_revocation_exact_release_fk
        FOREIGN KEY (knowledge_base_release_id, knowledge_space_id, knowledge_base_id)
        REFERENCES knowledge_base_releases (
            knowledge_base_release_id,
            knowledge_space_id,
            knowledge_base_id
        ) ON DELETE RESTRICT,
    CHECK (result_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK (result_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (result_json ->> 'knowledge_base_release_id' = knowledge_base_release_id),
    CHECK (result_json ->> 'state' = 'revoked'),
    CHECK (result_json ->> 'reason_code' = reason_code),
    CHECK (result_json ->> 'confirmation' = 'fail_closed_without_fallback'),
    CHECK (
        (result_json ->> 'affected_active_reference_count')::bigint
            = affected_active_reference_count
    ),
    CHECK ((result_json ->> 'revoked_at')::timestamptz = revoked_at)
);

CREATE INDEX knowledge_base_release_revocation_commands_audit_idx
    ON knowledge_base_release_revocation_commands (
        knowledge_base_release_id,
        event_sequence
    );
