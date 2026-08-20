CREATE TABLE knowledge_service_clients (
    client_id text PRIMARY KEY,
    bearer_token_digest text NOT NULL UNIQUE CHECK (
        bearer_token_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE knowledge_client_grants (
    client_grant_id text PRIMARY KEY,
    client_id text NOT NULL REFERENCES knowledge_service_clients(client_id),
    knowledge_space_id text NOT NULL,
    knowledge_base_release_id text NOT NULL,
    allowed_strategies text[] NOT NULL CHECK (
        cardinality(allowed_strategies) > 0
        AND allowed_strategies <@ ARRAY['single_pass', 'agentic']::text[]
    ),
    max_rounds integer NOT NULL CHECK (max_rounds > 0),
    max_model_calls integer NOT NULL CHECK (max_model_calls > 0),
    max_candidates integer NOT NULL CHECK (max_candidates > 0),
    max_model_tokens integer NOT NULL CHECK (max_model_tokens > 0),
    max_duration_ms integer NOT NULL CHECK (max_duration_ms > 0),
    effective_access_scope_digest text NOT NULL CHECK (
        effective_access_scope_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (client_id, knowledge_base_release_id),
    FOREIGN KEY (knowledge_base_release_id, knowledge_space_id)
        REFERENCES knowledge_base_releases(
            knowledge_base_release_id,
            knowledge_space_id
        ) ON DELETE RESTRICT
);

CREATE INDEX knowledge_client_grants_admission_idx
    ON knowledge_client_grants (client_id, knowledge_base_release_id)
    WHERE active;
