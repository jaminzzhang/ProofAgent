-- KSS owns non-secret profile revisions, permanent command receipts and audit.
-- No automatic expiry or cascading deletion: pinned revisions remain replayable.
CREATE TABLE knowledge_connection_profiles (
    connection_profile_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL,
    knowledge_source_id text NOT NULL,
    head_revision bigint NOT NULL CHECK (head_revision > 0),
    state_version bigint NOT NULL CHECK (state_version > 0),
    UNIQUE (connection_profile_id, knowledge_space_id, knowledge_source_id),
    FOREIGN KEY (knowledge_source_id, knowledge_space_id)
        REFERENCES knowledge_sources(knowledge_source_id, knowledge_space_id)
        ON DELETE RESTRICT
);

CREATE TABLE knowledge_connection_profile_revisions (
    connection_profile_id text NOT NULL REFERENCES knowledge_connection_profiles
        ON DELETE RESTRICT,
    revision bigint NOT NULL CHECK (revision > 0),
    state text NOT NULL CHECK (state IN ('draft', 'validated', 'published')),
    state_version bigint NOT NULL CHECK (state_version > 0),
    configuration_digest text NOT NULL CHECK (configuration_digest ~ '^sha256:[0-9a-f]{64}$'),
    configuration_json jsonb NOT NULL CHECK (jsonb_typeof(configuration_json) = 'object'),
    view_json jsonb NOT NULL CHECK (jsonb_typeof(view_json) = 'object'),
    validation_policy_revision text,
    PRIMARY KEY (connection_profile_id, revision),
    UNIQUE (connection_profile_id, revision, configuration_digest),
    CHECK (state = 'draft' OR validation_policy_revision IS NOT NULL),
    CHECK (view_json ->> 'state' = state),
    CHECK (view_json ->> 'connection_profile_id' = connection_profile_id),
    CHECK ((view_json ->> 'revision')::bigint = revision),
    CHECK (view_json ->> 'configuration_digest' = configuration_digest)
);

-- A command receipt is also the append-only success audit event. Its response
-- is the original safe projection, not the mutable current revision view.
CREATE TABLE knowledge_connection_profile_commands (
    event_sequence bigserial UNIQUE NOT NULL,
    operator_id text NOT NULL,
    key_digest text NOT NULL CHECK (key_digest ~ '^sha256:[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action IN ('create', 'revise', 'validate', 'publish')),
    connection_profile_id text NOT NULL,
    revision bigint NOT NULL,
    view_json jsonb NOT NULL CHECK (jsonb_typeof(view_json) = 'object'),
    PRIMARY KEY (operator_id, key_digest),
    FOREIGN KEY (connection_profile_id, revision)
        REFERENCES knowledge_connection_profile_revisions ON DELETE RESTRICT
);

CREATE INDEX knowledge_connection_profile_commands_audit_idx
    ON knowledge_connection_profile_commands (connection_profile_id, event_sequence);

-- Denials have no execution authority and may name a missing profile or an
-- unauthenticated caller. Never retain headers, request bodies or raw errors.
CREATE TABLE knowledge_connection_profile_rejections (
    event_sequence bigserial PRIMARY KEY,
    connection_profile_id text,
    event_json jsonb NOT NULL CHECK (jsonb_typeof(event_json) = 'object')
);
CREATE INDEX knowledge_connection_profile_rejections_profile_idx
    ON knowledge_connection_profile_rejections (connection_profile_id, event_sequence);
