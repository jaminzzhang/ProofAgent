BEGIN;

CREATE TABLE IF NOT EXISTS hybrid_knowledge_source_authority (
  source_id text PRIMARY KEY,
  draft_version_id text NOT NULL,
  candidate_digest text NOT NULL CHECK (candidate_digest ~ '^[0-9a-f]{64}$'),
  next_publication_seq bigint NOT NULL DEFAULT 1 CHECK (next_publication_seq > 0),
  next_fencing_token bigint NOT NULL DEFAULT 1 CHECK (next_fencing_token > 0),
  live_attempt_id text,
  active_publication_id text,
  updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_generation (
  generation_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  identity_digest text NOT NULL CHECK (identity_digest ~ '^[0-9a-f]{64}$'),
  mapping_sha256 text NOT NULL CHECK (mapping_sha256 ~ '^[0-9a-f]{64}$'),
  generation_json jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (source_id, identity_digest),
  UNIQUE (source_id, generation_id)
);

CREATE TABLE IF NOT EXISTS hybrid_projection_operation (
  operation_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  generation_id text NOT NULL,
  operation_kind text NOT NULL CHECK (operation_kind IN ('PUBLICATION','REBUILD')),
  state text NOT NULL CHECK (state IN ('BUILDING','VALIDATED','COMMITTED','FAILED')),
  failure_code text,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL CHECK (updated_at >= created_at),
  CHECK ((state = 'FAILED') = (failure_code IS NOT NULL)),
  UNIQUE (source_id, operation_id),
  UNIQUE (source_id, generation_id, operation_id),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_retrieval_profile (
  profile_revision_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  profile_digest text NOT NULL CHECK (profile_digest ~ '^[0-9a-f]{64}$'),
  profile_json jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (source_id, profile_digest)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_artifact_reference (
  artifact_ref_id text PRIMARY KEY,
  artifact_uri text NOT NULL,
  version_id text NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  media_type text NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (artifact_uri, version_id),
  UNIQUE (artifact_uri, sha256, size_bytes, media_type)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_document_revision (
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  document_id text NOT NULL,
  revision_id text NOT NULL,
  original_artifact_ref_id text REFERENCES hybrid_knowledge_artifact_reference(artifact_ref_id),
  structured_build_ref_id text REFERENCES hybrid_knowledge_artifact_reference(artifact_ref_id),
  structured_build_id text NOT NULL,
  review_state text NOT NULL CHECK (review_state IN ('NOT_REQUIRED','REVIEW_REQUIRED','APPROVED','REJECTED')),
  created_at timestamptz NOT NULL,
  PRIMARY KEY (source_id, document_id, revision_id),
  UNIQUE (source_id, document_id, structured_build_id)
);

CREATE TABLE IF NOT EXISTS hybrid_approved_rule_metadata (
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  metadata_revision_id text NOT NULL,
  metadata_sha256 text NOT NULL CHECK (metadata_sha256 ~ '^[0-9a-f]{64}$'),
  metadata_json jsonb NOT NULL,
  approved_at timestamptz NOT NULL,
  PRIMARY KEY (source_id, metadata_revision_id),
  UNIQUE (source_id, metadata_sha256)
);

CREATE TABLE IF NOT EXISTS hybrid_approved_visibility_scope (
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  visibility_revision_id text NOT NULL,
  visibility_sha256 text NOT NULL CHECK (visibility_sha256 ~ '^[0-9a-f]{64}$'),
  visibility_json jsonb NOT NULL,
  approved_at timestamptz NOT NULL,
  PRIMARY KEY (source_id, visibility_revision_id),
  UNIQUE (source_id, visibility_sha256)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_rule_unit_revision (
  rule_unit_revision_id text PRIMARY KEY,
  source_id text NOT NULL,
  document_id text NOT NULL,
  revision_id text NOT NULL,
  structured_build_id text NOT NULL,
  metadata_revision_id text NOT NULL,
  visibility_revision_id text NOT NULL,
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  authority_sha256 text NOT NULL CHECK (authority_sha256 ~ '^[0-9a-f]{64}$'),
  rule_unit_json jsonb NOT NULL,
  approved_at timestamptz NOT NULL,
  FOREIGN KEY (source_id, document_id, revision_id)
    REFERENCES hybrid_knowledge_document_revision(source_id, document_id, revision_id),
  UNIQUE (source_id, document_id, revision_id, structured_build_id, rule_unit_revision_id),
  FOREIGN KEY (source_id, metadata_revision_id)
    REFERENCES hybrid_approved_rule_metadata(source_id, metadata_revision_id),
  FOREIGN KEY (source_id, visibility_revision_id)
    REFERENCES hybrid_approved_visibility_scope(source_id, visibility_revision_id)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_publication_validation (
  validation_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  source_draft_version_id text NOT NULL,
  candidate_digest text NOT NULL CHECK (candidate_digest ~ '^[0-9a-f]{64}$'),
  generation_id text NOT NULL,
  status text NOT NULL CHECK (status = 'passed'),
  validated_at timestamptz NOT NULL,
  validated_by text NOT NULL,
  UNIQUE (source_id, generation_id, validation_id),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_publication_attempt (
  attempt_id text PRIMARY KEY REFERENCES hybrid_projection_operation(operation_id),
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  reserved_sequence bigint NOT NULL CHECK (reserved_sequence > 0),
  fencing_token bigint NOT NULL CHECK (fencing_token > 0),
  source_draft_version_id text NOT NULL,
  candidate_digest text NOT NULL CHECK (candidate_digest ~ '^[0-9a-f]{64}$'),
  generation_id text NOT NULL,
  validation_id text NOT NULL UNIQUE,
  state text NOT NULL CHECK (state IN ('BUILDING','VALIDATED','PUBLISHED','FAILED')),
  started_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL CHECK (updated_at >= started_at),
  failure_code text,
  queue_time_ms double precision CHECK (queue_time_ms IS NULL OR queue_time_ms >= 0),
  service_time_ms double precision CHECK (service_time_ms IS NULL OR service_time_ms >= 0),
  CHECK ((state = 'FAILED') = (failure_code IS NOT NULL)),
  UNIQUE (source_id, reserved_sequence),
  UNIQUE (source_id, fencing_token),
  UNIQUE (source_id, attempt_id),
  UNIQUE (source_id, generation_id, attempt_id),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id),
  FOREIGN KEY (source_id, generation_id, validation_id)
    REFERENCES hybrid_knowledge_publication_validation(source_id, generation_id, validation_id)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_publication_validation_claim (
  validation_id text PRIMARY KEY,
  source_id text NOT NULL,
  generation_id text NOT NULL,
  attempt_id text NOT NULL UNIQUE,
  claimed_at timestamptz NOT NULL,
  FOREIGN KEY (source_id, generation_id, validation_id)
    REFERENCES hybrid_knowledge_publication_validation(source_id, generation_id, validation_id),
  FOREIGN KEY (source_id, generation_id, attempt_id)
    REFERENCES hybrid_knowledge_publication_attempt(source_id, generation_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS hybrid_projection_materialization (
  source_id text NOT NULL,
  generation_id text NOT NULL,
  projection_id text NOT NULL,
  rule_unit_revision_id text NOT NULL,
  embedding_sha256 text NOT NULL CHECK (embedding_sha256 ~ '^[0-9a-f]{64}$'),
  projection_material_sha256 text NOT NULL
    CHECK (projection_material_sha256 ~ '^[0-9a-f]{64}$'),
  immutable_projection_sha256 text NOT NULL
    CHECK (immutable_projection_sha256 ~ '^[0-9a-f]{64}$'),
  created_attempt_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (source_id, generation_id, projection_id),
  UNIQUE (source_id, generation_id, rule_unit_revision_id),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id),
  FOREIGN KEY (rule_unit_revision_id)
    REFERENCES hybrid_knowledge_rule_unit_revision(rule_unit_revision_id),
  FOREIGN KEY (source_id, generation_id, created_attempt_id)
    REFERENCES hybrid_knowledge_publication_attempt(source_id, generation_id, attempt_id)
);

ALTER TABLE hybrid_knowledge_source_authority
  DROP CONSTRAINT IF EXISTS hybrid_source_live_attempt_fk;
ALTER TABLE hybrid_knowledge_source_authority
  ADD CONSTRAINT hybrid_source_live_attempt_fk FOREIGN KEY (source_id, live_attempt_id)
  REFERENCES hybrid_knowledge_publication_attempt(source_id, attempt_id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS hybrid_rule_unit_manifest (
  root_sha256 text PRIMARY KEY CHECK (root_sha256 ~ '^[0-9a-f]{64}$'),
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  source_snapshot_id text NOT NULL,
  source_publication_seq bigint NOT NULL CHECK (source_publication_seq > 0),
  generation_id text NOT NULL,
  root_artifact_ref_id text NOT NULL REFERENCES hybrid_knowledge_artifact_reference(artifact_ref_id),
  manifest_json jsonb NOT NULL,
  document_count bigint NOT NULL CHECK (document_count > 0),
  rule_unit_count bigint NOT NULL CHECK (rule_unit_count > 0),
  created_at timestamptz NOT NULL,
  UNIQUE (source_id, source_publication_seq),
  UNIQUE (source_id, generation_id, root_sha256),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id)
);

CREATE TABLE IF NOT EXISTS hybrid_rule_unit_manifest_shard (
  shard_sha256 text PRIMARY KEY CHECK (shard_sha256 ~ '^[0-9a-f]{64}$'),
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  generation_id text NOT NULL,
  document_id text NOT NULL,
  artifact_ref_id text NOT NULL REFERENCES hybrid_knowledge_artifact_reference(artifact_ref_id),
  rule_unit_count bigint NOT NULL CHECK (rule_unit_count > 0),
  shard_json jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (source_id, generation_id, shard_sha256),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id)
);

CREATE TABLE IF NOT EXISTS hybrid_rule_unit_manifest_member (
  root_sha256 text NOT NULL REFERENCES hybrid_rule_unit_manifest(root_sha256),
  shard_sha256 text NOT NULL REFERENCES hybrid_rule_unit_manifest_shard(shard_sha256),
  source_id text NOT NULL,
  generation_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  PRIMARY KEY (root_sha256, shard_sha256),
  UNIQUE (root_sha256, ordinal),
  FOREIGN KEY (source_id, generation_id, root_sha256)
    REFERENCES hybrid_rule_unit_manifest(source_id, generation_id, root_sha256),
  FOREIGN KEY (source_id, generation_id, shard_sha256)
    REFERENCES hybrid_rule_unit_manifest_shard(source_id, generation_id, shard_sha256)
);

CREATE TABLE IF NOT EXISTS hybrid_projection_attestation (
  attestation_sha256 text PRIMARY KEY CHECK (attestation_sha256 ~ '^[0-9a-f]{64}$'),
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  generation_id text NOT NULL,
  publication_attempt_id text NOT NULL UNIQUE,
  index_uuid text NOT NULL,
  mapping_sha256 text NOT NULL CHECK (mapping_sha256 ~ '^[0-9a-f]{64}$'),
  manifest_root_sha256 text NOT NULL REFERENCES hybrid_rule_unit_manifest(root_sha256),
  parent_attestation_sha256 text REFERENCES hybrid_projection_attestation(attestation_sha256),
  attestation_json jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  CHECK (parent_attestation_sha256 IS NULL OR parent_attestation_sha256 <> attestation_sha256),
  UNIQUE (source_id, generation_id, attestation_sha256),
  UNIQUE (source_id, generation_id, publication_attempt_id, attestation_sha256),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id),
  FOREIGN KEY (source_id, publication_attempt_id)
    REFERENCES hybrid_projection_operation(source_id, operation_id),
  FOREIGN KEY (source_id, generation_id, manifest_root_sha256)
    REFERENCES hybrid_rule_unit_manifest(source_id, generation_id, root_sha256),
  FOREIGN KEY (source_id, generation_id, publication_attempt_id)
    REFERENCES hybrid_projection_operation(source_id, generation_id, operation_id),
  FOREIGN KEY (source_id, generation_id, parent_attestation_sha256)
    REFERENCES hybrid_projection_attestation(source_id, generation_id, attestation_sha256)
);

CREATE TABLE IF NOT EXISTS hybrid_knowledge_publication (
  publication_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  source_publication_seq bigint NOT NULL CHECK (source_publication_seq > 0),
  source_draft_version_id text NOT NULL,
  candidate_digest text NOT NULL CHECK (candidate_digest ~ '^[0-9a-f]{64}$'),
  generation_id text NOT NULL,
  validation_id text NOT NULL UNIQUE,
  attempt_id text NOT NULL UNIQUE REFERENCES hybrid_knowledge_publication_attempt(attempt_id),
  manifest_root_sha256 text NOT NULL REFERENCES hybrid_rule_unit_manifest(root_sha256),
  attestation_sha256 text NOT NULL REFERENCES hybrid_projection_attestation(attestation_sha256),
  publication_json jsonb NOT NULL,
  published_at timestamptz NOT NULL,
  published_by text NOT NULL,
  UNIQUE (source_id, source_publication_seq),
  UNIQUE (source_id, publication_id),
  FOREIGN KEY (source_id, generation_id, manifest_root_sha256)
    REFERENCES hybrid_rule_unit_manifest(source_id, generation_id, root_sha256),
  FOREIGN KEY (source_id, generation_id, attestation_sha256)
    REFERENCES hybrid_projection_attestation(source_id, generation_id, attestation_sha256),
  FOREIGN KEY (source_id, generation_id, attempt_id)
    REFERENCES hybrid_knowledge_publication_attempt(source_id, generation_id, attempt_id),
  FOREIGN KEY (source_id, generation_id, attempt_id, attestation_sha256)
    REFERENCES hybrid_projection_attestation(
      source_id, generation_id, publication_attempt_id, attestation_sha256
    )
);

CREATE TABLE IF NOT EXISTS hybrid_generation_projection (
  source_id text NOT NULL,
  generation_id text NOT NULL,
  index_uuid text NOT NULL,
  projection_locator text,
  attestation_sha256 text NOT NULL,
  fencing_token bigint NOT NULL CHECK (fencing_token > 0),
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (source_id, generation_id),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id),
  FOREIGN KEY (source_id, generation_id, attestation_sha256)
    REFERENCES hybrid_projection_attestation(source_id, generation_id, attestation_sha256)
);

ALTER TABLE hybrid_knowledge_source_authority
  DROP CONSTRAINT IF EXISTS hybrid_source_active_publication_fk;
ALTER TABLE hybrid_knowledge_source_authority
  ADD CONSTRAINT hybrid_source_active_publication_fk FOREIGN KEY (source_id, active_publication_id)
  REFERENCES hybrid_knowledge_publication(source_id, publication_id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS hybrid_projection_orphan_cleanup (
  attempt_id text PRIMARY KEY REFERENCES hybrid_projection_operation(operation_id),
  source_id text NOT NULL REFERENCES hybrid_knowledge_source_authority(source_id),
  generation_id text NOT NULL,
  index_uuid text NOT NULL,
  projection_locator text,
  state text NOT NULL CHECK (state IN ('PENDING','DELETED','RETRY')),
  retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  last_failure_code text,
  updated_at timestamptz NOT NULL,
  CHECK ((state = 'RETRY') = (last_failure_code IS NOT NULL)),
  FOREIGN KEY (source_id, generation_id)
    REFERENCES hybrid_knowledge_generation(source_id, generation_id),
  FOREIGN KEY (source_id, generation_id, attempt_id)
    REFERENCES hybrid_projection_operation(source_id, generation_id, operation_id)
);

CREATE OR REPLACE FUNCTION reject_hybrid_immutable_update() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'hybrid authority row is immutable';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'hybrid_knowledge_generation', 'hybrid_knowledge_retrieval_profile',
    'hybrid_knowledge_artifact_reference', 'hybrid_knowledge_document_revision',
    'hybrid_approved_rule_metadata', 'hybrid_approved_visibility_scope',
    'hybrid_knowledge_rule_unit_revision',
    'hybrid_knowledge_publication_validation',
    'hybrid_knowledge_publication_validation_claim', 'hybrid_rule_unit_manifest',
    'hybrid_projection_materialization',
    'hybrid_rule_unit_manifest_shard', 'hybrid_rule_unit_manifest_member',
    'hybrid_projection_attestation', 'hybrid_knowledge_publication'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS reject_update ON %I', table_name);
    EXECUTE format(
      'CREATE TRIGGER reject_update BEFORE UPDATE OR DELETE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION reject_hybrid_immutable_update()', table_name
    );
  END LOOP;
END $$;

COMMIT;
