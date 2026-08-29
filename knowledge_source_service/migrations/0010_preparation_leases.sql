-- Lease coordination only. No ready candidate, Release visibility or automatic deletion.
ALTER TABLE knowledge_release_preparations
    DROP CONSTRAINT knowledge_release_preparations_state_check,
    ADD CONSTRAINT knowledge_release_preparations_state_check CHECK (state IN ('queued', 'running')),
    ADD COLUMN lease_worker_id text,
    ADD COLUMN lease_fencing_token bigint NOT NULL DEFAULT 0 CHECK (lease_fencing_token >= 0),
    ADD COLUMN lease_expires_at timestamptz,
    ADD CONSTRAINT knowledge_release_preparations_lease_check CHECK (
        (state = 'queued' AND lease_worker_id IS NULL AND lease_fencing_token = 0 AND lease_expires_at IS NULL)
        OR (state = 'running' AND lease_worker_id IS NOT NULL AND lease_fencing_token > 0 AND lease_expires_at IS NOT NULL)
    );

CREATE INDEX knowledge_release_preparations_claim_idx
    ON knowledge_release_preparations (submitted_at, release_preparation_id)
    WHERE state IN ('queued', 'running');

CREATE TABLE knowledge_preparation_worker_events (
    event_sequence bigserial PRIMARY KEY,
    release_preparation_id text NOT NULL REFERENCES knowledge_release_preparations ON DELETE RESTRICT,
    knowledge_base_id text NOT NULL REFERENCES knowledge_bases ON DELETE RESTRICT,
    event_json jsonb NOT NULL CHECK (jsonb_typeof(event_json) = 'object'),
    CHECK (event_json ->> 'release_preparation_id' = release_preparation_id),
    CHECK (event_json ->> 'knowledge_base_id' = knowledge_base_id)
);
CREATE INDEX knowledge_preparation_worker_events_audit_idx
    ON knowledge_preparation_worker_events (knowledge_base_id, event_sequence);
