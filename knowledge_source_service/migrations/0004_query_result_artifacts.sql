ALTER TABLE knowledge_queries
    ADD COLUMN result_artifact_json jsonb,
    ADD COLUMN result_digest text,
    ADD COLUMN result_candidate_count integer;

ALTER TABLE knowledge_queries
    ADD CONSTRAINT knowledge_queries_result_artifact_shape_check CHECK (
        (
            query_json ->> 'result_availability' = 'available'
            AND result_artifact_json IS NOT NULL
            AND jsonb_typeof(result_artifact_json) = 'object'
            AND result_digest ~ '^sha256:[0-9a-f]{64}$'
            AND result_candidate_count IS NOT NULL
            AND result_candidate_count >= 0
        )
        OR (
            query_json ->> 'result_availability' <> 'available'
            AND result_artifact_json IS NULL
            AND result_digest IS NULL
            AND result_candidate_count IS NULL
        )
    );
