CREATE TABLE knowledge_spaces (
    knowledge_space_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE knowledge_sources (
    knowledge_source_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL REFERENCES knowledge_spaces(knowledge_space_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (knowledge_source_id, knowledge_space_id)
);

CREATE TABLE knowledge_bases (
    knowledge_base_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL REFERENCES knowledge_spaces(knowledge_space_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (knowledge_base_id, knowledge_space_id)
);

CREATE TABLE knowledge_source_versions (
    knowledge_source_version_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL,
    knowledge_source_id text NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN ('document', 'dataset')),
    media_type text NOT NULL,
    original_artifact_json jsonb NOT NULL CHECK (
        jsonb_typeof(original_artifact_json) = 'object'
    ),
    canonical_artifact_json jsonb NOT NULL CHECK (
        jsonb_typeof(canonical_artifact_json) = 'object'
    ),
    evidence_manifest_artifact_json jsonb NOT NULL CHECK (
        jsonb_typeof(evidence_manifest_artifact_json) = 'object'
    ),
    processing_lineage_digest text NOT NULL CHECK (
        processing_lineage_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (knowledge_source_version_id, knowledge_space_id),
    FOREIGN KEY (knowledge_source_id, knowledge_space_id)
        REFERENCES knowledge_sources(knowledge_source_id, knowledge_space_id)
);

CREATE TABLE knowledge_base_releases (
    knowledge_base_release_id text PRIMARY KEY,
    knowledge_space_id text NOT NULL,
    knowledge_base_id text NOT NULL,
    knowledge_base_version_id text NOT NULL,
    release_manifest_digest text NOT NULL CHECK (
        release_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    release_manifest_artifact_json jsonb NOT NULL CHECK (
        jsonb_typeof(release_manifest_artifact_json) = 'object'
    ),
    state text NOT NULL DEFAULT 'queryable' CHECK (state IN ('queryable', 'retired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (knowledge_base_release_id, knowledge_space_id),
    FOREIGN KEY (knowledge_base_id, knowledge_space_id)
        REFERENCES knowledge_bases(knowledge_base_id, knowledge_space_id)
);

CREATE TABLE knowledge_base_release_members (
    knowledge_base_release_id text NOT NULL,
    knowledge_space_id text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    knowledge_source_version_id text NOT NULL,
    PRIMARY KEY (knowledge_base_release_id, ordinal),
    UNIQUE (knowledge_base_release_id, knowledge_source_version_id),
    FOREIGN KEY (knowledge_base_release_id, knowledge_space_id)
        REFERENCES knowledge_base_releases(
            knowledge_base_release_id,
            knowledge_space_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (knowledge_source_version_id, knowledge_space_id)
        REFERENCES knowledge_source_versions(
            knowledge_source_version_id,
            knowledge_space_id
        ) ON DELETE RESTRICT
);

CREATE INDEX knowledge_source_versions_source_idx
    ON knowledge_source_versions (knowledge_space_id, knowledge_source_id, created_at);

CREATE INDEX knowledge_base_releases_base_idx
    ON knowledge_base_releases (knowledge_space_id, knowledge_base_id, created_at);
