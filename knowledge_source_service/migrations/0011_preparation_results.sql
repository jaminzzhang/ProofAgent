-- Fenced build results only. Ready candidates remain non-queryable and one-use publication is absent.
ALTER TABLE knowledge_release_preparations
    DROP CONSTRAINT knowledge_release_preparations_state_check,
    DROP CONSTRAINT knowledge_release_preparations_lease_check,
    ADD COLUMN candidate_json jsonb CHECK (
        candidate_json IS NULL OR jsonb_typeof(candidate_json) = 'object'
    ),
    ADD COLUMN terminal_at timestamptz,
    ADD COLUMN candidate_expires_at timestamptz,
    ADD CONSTRAINT knowledge_release_preparations_state_check CHECK (
        state IN ('queued', 'running', 'ready', 'failed')
    ),
    ADD CONSTRAINT knowledge_release_preparations_lease_check CHECK (
        (state = 'queued'
            AND lease_worker_id IS NULL
            AND lease_fencing_token = 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NULL
            AND terminal_at IS NULL
            AND candidate_expires_at IS NULL)
        OR (state = 'running'
            AND lease_worker_id IS NOT NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NOT NULL
            AND candidate_json IS NULL
            AND terminal_at IS NULL
            AND candidate_expires_at IS NULL)
        OR (state = 'ready'
            AND lease_worker_id IS NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NOT NULL
            AND terminal_at IS NOT NULL
            AND candidate_expires_at > terminal_at)
        OR (state = 'failed'
            AND lease_worker_id IS NULL
            AND lease_fencing_token > 0
            AND lease_expires_at IS NULL
            AND candidate_json IS NULL
            AND terminal_at IS NOT NULL
            AND candidate_expires_at IS NULL)
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
        OR state IN ('queued', 'running')
    );
