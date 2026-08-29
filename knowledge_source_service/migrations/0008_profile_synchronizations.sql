-- Explicit v1 (static) / v2 (managed) migration boundary. Existing jobs and
-- idempotency fingerprints are not rewritten or upgraded to a mutable profile.
ALTER TABLE knowledge_source_synchronizations
    ALTER COLUMN connection_id DROP NOT NULL,
    ADD COLUMN connection_profile_id text,
    ADD COLUMN connection_profile_revision bigint,
    ADD COLUMN connection_profile_digest text,
    ADD CONSTRAINT knowledge_sync_connection_authority CHECK (
        (connection_id IS NOT NULL AND connection_profile_id IS NULL
         AND connection_profile_revision IS NULL AND connection_profile_digest IS NULL)
        OR (connection_id IS NULL AND connection_profile_id IS NOT NULL
            AND connection_profile_revision IS NOT NULL AND connection_profile_digest IS NOT NULL)
    ),
    ADD CONSTRAINT knowledge_sync_profile_scope FOREIGN KEY (
        connection_profile_id, knowledge_space_id, knowledge_source_id
    ) REFERENCES knowledge_connection_profiles (
        connection_profile_id, knowledge_space_id, knowledge_source_id
    ) ON DELETE RESTRICT,
    ADD CONSTRAINT knowledge_sync_exact_profile FOREIGN KEY (
        connection_profile_id, connection_profile_revision, connection_profile_digest
    ) REFERENCES knowledge_connection_profile_revisions (
        connection_profile_id, revision, configuration_digest
    ) ON DELETE RESTRICT;
