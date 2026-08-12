ALTER TABLE knowledge_base_releases
    ADD COLUMN index_identity text,
    ADD COLUMN index_mapping_digest text,
    ADD COLUMN index_corpus_digest text,
    ADD COLUMN index_document_count integer,
    ADD COLUMN dense_encoder_revision text,
    ADD COLUMN sparse_encoder_revision text,
    ADD COLUMN dense_dimension integer;

ALTER TABLE knowledge_base_releases
    ADD CONSTRAINT knowledge_base_releases_projection_shape_check CHECK (
        (
            index_identity IS NULL
            AND index_mapping_digest IS NULL
            AND index_corpus_digest IS NULL
            AND index_document_count IS NULL
            AND dense_encoder_revision IS NULL
            AND sparse_encoder_revision IS NULL
            AND dense_dimension IS NULL
        )
        OR (
            index_identity IS NOT NULL
            AND index_mapping_digest ~ '^sha256:[0-9a-f]{64}$'
            AND index_corpus_digest ~ '^sha256:[0-9a-f]{64}$'
            AND index_document_count IS NOT NULL
            AND index_document_count > 0
            AND dense_encoder_revision IS NOT NULL
            AND sparse_encoder_revision IS NOT NULL
            AND dense_dimension IS NOT NULL
            AND dense_dimension > 0
        )
    );

CREATE UNIQUE INDEX knowledge_base_releases_index_identity_unique
    ON knowledge_base_releases (index_identity)
    WHERE index_identity IS NOT NULL;
