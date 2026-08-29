-- KSS-only management authority. No Release visibility, expiry or automatic deletion.
CREATE TABLE knowledge_base_drafts (
    knowledge_base_id text NOT NULL,
    knowledge_space_id text NOT NULL,
    revision bigint NOT NULL CHECK (revision > 0),
    draft_digest text NOT NULL CHECK (draft_digest ~ '^sha256:[0-9a-f]{64}$'),
    draft_json jsonb NOT NULL CHECK (jsonb_typeof(draft_json) = 'object'),
    PRIMARY KEY (knowledge_base_id, revision),
    UNIQUE (knowledge_base_id, knowledge_space_id, revision, draft_digest),
    FOREIGN KEY (knowledge_base_id, knowledge_space_id)
        REFERENCES knowledge_bases (knowledge_base_id, knowledge_space_id) ON DELETE RESTRICT,
    CHECK (draft_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (draft_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK ((draft_json ->> 'revision')::bigint = revision),
    CHECK (draft_json ->> 'draft_digest' = draft_digest)
);

CREATE TABLE knowledge_base_versions (
    knowledge_base_version_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    plan_digest text NOT NULL CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    version_json jsonb NOT NULL CHECK (jsonb_typeof(version_json) = 'object'),
    UNIQUE (knowledge_base_version_id, knowledge_space_id, knowledge_base_id),
    UNIQUE (knowledge_base_version_id, knowledge_space_id),
    FOREIGN KEY (knowledge_base_id, knowledge_space_id)
        REFERENCES knowledge_bases (knowledge_base_id, knowledge_space_id) ON DELETE RESTRICT,
    CHECK (version_json ->> 'knowledge_base_version_id' = knowledge_base_version_id),
    CHECK (version_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK (version_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK (version_json ->> 'plan_digest' = plan_digest)
);

-- Explicit Source association prevents a member from relabelling another Source's version.
ALTER TABLE knowledge_source_versions ADD CONSTRAINT knowledge_source_versions_exact_source_key
    UNIQUE (knowledge_source_version_id, knowledge_space_id, knowledge_source_id);

CREATE TABLE knowledge_base_version_members (
    knowledge_base_version_id text NOT NULL,
    knowledge_space_id text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    knowledge_source_id text NOT NULL,
    knowledge_source_version_id text NOT NULL,
    PRIMARY KEY (knowledge_base_version_id, ordinal),
    UNIQUE (knowledge_base_version_id, knowledge_source_id),
    UNIQUE (knowledge_base_version_id, knowledge_source_version_id),
    FOREIGN KEY (knowledge_base_version_id, knowledge_space_id)
        REFERENCES knowledge_base_versions (knowledge_base_version_id, knowledge_space_id) ON DELETE RESTRICT,
    FOREIGN KEY (knowledge_source_version_id, knowledge_space_id, knowledge_source_id)
        REFERENCES knowledge_source_versions (knowledge_source_version_id, knowledge_space_id, knowledge_source_id)
        ON DELETE RESTRICT
);

CREATE TABLE knowledge_release_preparations (
    release_preparation_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    draft_revision bigint NOT NULL,
    draft_digest text NOT NULL,
    knowledge_base_version_id text NOT NULL,
    state text NOT NULL CHECK (state = 'queued'),
    submitted_at timestamptz NOT NULL,
    resource_json jsonb NOT NULL CHECK (jsonb_typeof(resource_json) = 'object'),
    FOREIGN KEY (knowledge_base_id, knowledge_space_id, draft_revision, draft_digest)
        REFERENCES knowledge_base_drafts (knowledge_base_id, knowledge_space_id, revision, draft_digest)
        ON DELETE RESTRICT,
    FOREIGN KEY (knowledge_base_version_id, knowledge_space_id, knowledge_base_id)
        REFERENCES knowledge_base_versions (knowledge_base_version_id, knowledge_space_id, knowledge_base_id)
        ON DELETE RESTRICT,
    CHECK (resource_json ->> 'release_preparation_id' = release_preparation_id),
    CHECK (resource_json ->> 'state' = state),
    CHECK (resource_json ->> 'knowledge_space_id' = knowledge_space_id),
    CHECK (resource_json ->> 'knowledge_base_id' = knowledge_base_id),
    CHECK ((resource_json ->> 'draft_revision')::bigint = draft_revision),
    CHECK (resource_json ->> 'draft_digest' = draft_digest),
    CHECK (resource_json -> 'base_version' ->> 'knowledge_base_version_id' = knowledge_base_version_id)
);

-- Receipt is also the append-only success audit. It retains the original result.
CREATE TABLE knowledge_base_preparation_commands (
    event_sequence bigserial UNIQUE NOT NULL,
    operator_id text NOT NULL,
    key_digest text NOT NULL CHECK (key_digest ~ '^sha256:[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action IN ('save_draft', 'start')),
    knowledge_base_id text NOT NULL,
    draft_revision bigint NOT NULL,
    release_preparation_id text REFERENCES knowledge_release_preparations ON DELETE RESTRICT,
    result_json jsonb NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    PRIMARY KEY (operator_id, key_digest),
    FOREIGN KEY (knowledge_base_id, draft_revision)
        REFERENCES knowledge_base_drafts (knowledge_base_id, revision) ON DELETE RESTRICT,
    CHECK ((action = 'save_draft' AND release_preparation_id IS NULL)
        OR (action = 'start' AND release_preparation_id IS NOT NULL))
);
CREATE INDEX knowledge_base_preparation_commands_audit_idx
    ON knowledge_base_preparation_commands (knowledge_base_id, event_sequence);

-- Denials may name an absent resource or unauthenticated actor; no FK or raw input.
CREATE TABLE knowledge_base_preparation_rejections (
    event_sequence bigserial PRIMARY KEY,
    knowledge_base_id text,
    event_json jsonb NOT NULL CHECK (jsonb_typeof(event_json) = 'object')
);
CREATE INDEX knowledge_base_preparation_rejections_audit_idx
    ON knowledge_base_preparation_rejections (knowledge_base_id, event_sequence);
