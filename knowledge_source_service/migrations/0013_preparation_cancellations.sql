-- Cooperative queued/running cancellation only. No HTTP command, artifact deletion or quarantine.
ALTER TABLE knowledge_release_preparations
    DROP CONSTRAINT knowledge_release_preparations_state_check,
    DROP CONSTRAINT knowledge_release_preparations_lease_check,
    DROP CONSTRAINT knowledge_release_preparations_terminal_json_check,
    ADD COLUMN cancelled_at timestamptz,
    ADD CONSTRAINT knowledge_release_preparations_state_check CHECK (
        state IN ('queued', 'running', 'ready', 'failed', 'cancelled', 'expired', 'consumed')
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
        OR (state = 'cancelled'
            AND lease_worker_id IS NULL
            AND lease_fencing_token >= 0
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
    ADD CONSTRAINT knowledge_release_preparations_cancellation_time_check CHECK (
        (state = 'cancelled' AND cancelled_at = terminal_at)
        OR (state <> 'cancelled' AND cancelled_at IS NULL)
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
        OR (state = 'cancelled'
            AND (resource_json ->> 'cancelled_at')::timestamptz = terminal_at)
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

ALTER TABLE knowledge_base_preparation_commands
    DROP CONSTRAINT knowledge_base_preparation_commands_action_check,
    DROP CONSTRAINT knowledge_base_preparation_commands_check,
    ADD CONSTRAINT knowledge_base_preparation_commands_action_check CHECK (
        action IN ('save_draft', 'start', 'cancel')
    ),
    ADD CONSTRAINT knowledge_base_preparation_commands_resource_check CHECK (
        (action = 'save_draft' AND release_preparation_id IS NULL)
        OR (action IN ('start', 'cancel') AND release_preparation_id IS NOT NULL)
    ),
    ADD CONSTRAINT knowledge_base_preparation_commands_result_state_check CHECK (
        action = 'save_draft'
        OR (action = 'start' AND result_json ->> 'state' = 'queued')
        OR (action = 'cancel' AND result_json ->> 'state' = 'cancelled')
    );
