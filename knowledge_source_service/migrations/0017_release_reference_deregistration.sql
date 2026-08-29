-- Permanently ineligible executable resources may release their KSS retention hold.
ALTER TABLE knowledge_base_release_references
    DROP CONSTRAINT knowledge_base_release_references_state_check,
    ADD COLUMN deregistration_verifier_id text,
    ADD COLUMN deregistration_verification_id text,
    ADD COLUMN deregistered_at timestamptz,
    ADD CONSTRAINT knowledge_base_release_references_verifier_id_check CHECK (
        deregistration_verifier_id IS NULL
        OR deregistration_verifier_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
    ),
    ADD CONSTRAINT knowledge_base_release_references_verification_id_check CHECK (
        deregistration_verification_id IS NULL
        OR deregistration_verification_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
    ),
    ADD CONSTRAINT knowledge_base_release_references_state_check CHECK (
        state IN ('active', 'deregistered')
    ),
    ADD CONSTRAINT knowledge_base_release_references_deregistration_check CHECK (
        (
            state = 'active'
            AND deregistration_verifier_id IS NULL
            AND deregistration_verification_id IS NULL
            AND deregistered_at IS NULL
        )
        OR (
            state = 'deregistered'
            AND deregistration_verifier_id IS NOT NULL
            AND deregistration_verification_id IS NOT NULL
            AND deregistered_at IS NOT NULL
            AND deregistered_at >= registered_at
            AND reference_json ->> 'deregistration_verifier_id'
                = deregistration_verifier_id
            AND reference_json ->> 'deregistration_verification_id'
                = deregistration_verification_id
            AND (reference_json ->> 'deregistered_at')::timestamptz
                = deregistered_at
        )
    );

-- Registration and deregistration share one client-scoped idempotency namespace and audit order.
ALTER TABLE knowledge_base_release_reference_commands
    DROP CONSTRAINT knowledge_base_release_reference_commands_action_check,
    ADD CONSTRAINT knowledge_base_release_reference_commands_action_check CHECK (
        action IN ('register', 'deregister')
    ),
    ADD CONSTRAINT knowledge_base_release_reference_commands_result_state_check CHECK (
        (action = 'register' AND result_json ->> 'state' = 'active')
        OR (
            action = 'deregister'
            AND result_json ->> 'state' = 'deregistered'
            AND result_json ? 'deregistration_verifier_id'
            AND result_json ? 'deregistration_verification_id'
            AND result_json ? 'deregistered_at'
            AND result_json ->> 'deregistration_verifier_id'
                ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            AND result_json ->> 'deregistration_verification_id'
                ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
        )
    ),
    ADD CONSTRAINT knowledge_base_release_reference_commands_client_check CHECK (
        result_json ->> 'authenticated_client_id' = authenticated_client_id
    );
