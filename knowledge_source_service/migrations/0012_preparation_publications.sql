-- One-use core publication authority only. No HTTP command, reaper or production wiring.
ALTER TABLE knowledge_release_preparations
    DROP CONSTRAINT knowledge_release_preparations_state_check,
    DROP CONSTRAINT knowledge_release_preparations_lease_check,
    DROP CONSTRAINT knowledge_release_preparations_terminal_json_check,
    ADD COLUMN consumed_at timestamptz,
    ADD COLUMN expired_at timestamptz,
    ADD COLUMN published_release_id text,
    ADD CONSTRAINT knowledge_release_preparations_published_release_fk
        FOREIGN KEY (published_release_id, knowledge_space_id)
        REFERENCES knowledge_base_releases (knowledge_base_release_id, knowledge_space_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT knowledge_release_preparations_state_check CHECK (
        state IN ('queued', 'running', 'ready', 'failed', 'expired', 'consumed')
    ),
    ADD CONSTRAINT knowledge_release_preparations_lease_check CHECK (
        (state = 'queued'
            AND lease_worker_id IS NULL
            AND lease_fencing_token = 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NULL
            AND terminal_at IS NULL
            AND candidate_expires_at IS NULL
            AND consumed_at IS NULL
            AND expired_at IS NULL
            AND published_release_id IS NULL)
        OR (state = 'running'
            AND lease_worker_id IS NOT NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NOT NULL
            AND candidate_json IS NULL
            AND terminal_at IS NULL
            AND candidate_expires_at IS NULL
            AND consumed_at IS NULL
            AND expired_at IS NULL
            AND published_release_id IS NULL)
        OR (state = 'ready'
            AND lease_worker_id IS NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NOT NULL
            AND terminal_at IS NOT NULL
            AND candidate_expires_at > terminal_at
            AND consumed_at IS NULL
            AND expired_at IS NULL
            AND published_release_id IS NULL)
        OR (state = 'failed'
            AND lease_worker_id IS NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NULL
            AND terminal_at IS NOT NULL
            AND candidate_expires_at IS NULL
            AND consumed_at IS NULL
            AND expired_at IS NULL
            AND published_release_id IS NULL)
        OR (state = 'expired'
            AND lease_worker_id IS NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NOT NULL
            AND terminal_at IS NOT NULL
            AND candidate_expires_at IS NOT NULL
            AND expired_at = terminal_at
            AND expired_at >= candidate_expires_at
            AND consumed_at IS NULL
            AND published_release_id IS NULL)
        OR (state = 'consumed'
            AND lease_worker_id IS NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NOT NULL
            AND terminal_at IS NOT NULL
            AND candidate_expires_at > terminal_at
            AND consumed_at = terminal_at
            AND expired_at IS NULL
            AND published_release_id IS NOT NULL)
    ),
    ADD CONSTRAINT knowledge_release_preparations_terminal_json_check CHECK (
        (state = 'ready'
            AND (resource_json ->> 'completed_at')::timestamptz = terminal_at
            AND (resource_json ->> 'expires_at')::timestamptz = candidate_expires_at
            AND candidate_json -> 'release' ->> 'knowledge_base_release_id'
                = resource_json ->> 'knowledge_base_release_id'
            AND candidate_json -> 'release' ->> 'release_manifest_digest'
                = resource_json ->> 'release_manifest_digest')
        OR (state = 'failed'
            AND (resource_json ->> 'failed_at')::timestamptz = terminal_at)
        OR (state = 'expired'
            AND (resource_json ->> 'expired_at')::timestamptz = expired_at
            AND (resource_json ->> 'expires_at')::timestamptz = candidate_expires_at
            AND candidate_json -> 'release' ->> 'knowledge_base_release_id'
                = resource_json ->> 'knowledge_base_release_id'
            AND candidate_json -> 'release' ->> 'release_manifest_digest'
                = resource_json ->> 'release_manifest_digest')
        OR (state = 'consumed'
            AND (resource_json ->> 'consumed_at')::timestamptz = consumed_at
            AND (resource_json ->> 'expires_at')::timestamptz = candidate_expires_at
            AND published_release_id = resource_json ->> 'knowledge_base_release_id'
            AND published_release_id
                = candidate_json -> 'release' ->> 'knowledge_base_release_id'
            AND candidate_json -> 'release' ->> 'release_manifest_digest'
                = resource_json ->> 'release_manifest_digest')
        OR state IN ('queued', 'running')
    );

CREATE INDEX knowledge_release_preparations_expiry_idx
    ON knowledge_release_preparations (candidate_expires_at, release_preparation_id)
    WHERE state = 'ready';

CREATE TABLE knowledge_preparation_publication_events (
    event_sequence bigserial PRIMARY KEY,
    release_preparation_id text NOT NULL UNIQUE
        REFERENCES knowledge_release_preparations ON DELETE RESTRICT,
    knowledge_base_id text NOT NULL REFERENCES knowledge_bases ON DELETE RESTRICT,
    action text NOT NULL CHECK (action IN ('expired', 'consumed')),
    recorded_at timestamptz NOT NULL,
    event_json jsonb NOT NULL CHECK (jsonb_typeof(event_json) = 'object'),
    CHECK (event_json ->> 'release_preparation_id' = release_preparation_id),
    CHECK (event_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (event_json ->> 'action' = action),
    CHECK ((event_json ->> 'recorded_at')::timestamptz = recorded_at)
);

CREATE INDEX knowledge_preparation_publication_events_audit_idx
    ON knowledge_preparation_publication_events (knowledge_base_id, event_sequence);
