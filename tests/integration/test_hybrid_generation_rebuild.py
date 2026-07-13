from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from proof_agent.capabilities.knowledge.hybrid.recovery import (
    HybridRecoveryService,
    OpenSearchRecoveryIndex,
)
from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationValidationAuthority,
)
from proof_agent.capabilities.knowledge.hybrid.opensearch import rrf_pipeline_name
from proof_agent.capabilities.knowledge.hybrid.ports import HybridSearchRequest
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from test_hybrid_postgres_s3 import (
    INSTRUCTION,
    _Embedding,
    _cleanup,
    _environment,
    _request,
)


pytestmark = pytest.mark.hybrid_integration


def test_disposable_generation_rebuild_creates_fresh_uuid_with_same_root_and_coverage() -> None:
    env: dict[str, Any] = _environment()
    try:
        env["service"].publish(env["request"])
        second_request = _request(
            env["source_id"],
            env["generation"],
            env["identity"],
            rule_suffix="two",
            publication_seq_from=2,
        )
        env["repository"].advance_source_candidate(
            source_id=env["source_id"],
            expected_source_draft_version_id=env["request"].source_draft_version_id,
            expected_candidate_digest=env["request"].candidate_digest,
            source_draft_version_id=second_request.source_draft_version_id,
            candidate_digest=second_request.candidate_digest,
        )
        env["repository"].register_validation(
            HybridPublicationValidationAuthority(
                validation_id=second_request.validation_id,
                source_id=second_request.source_id,
                source_draft_version_id=second_request.source_draft_version_id,
                candidate_digest=second_request.candidate_digest,
                generation_id=second_request.generation.generation_id,
                validated_at=datetime.now(UTC),
                validated_by="integration-validator",
            )
        )
        publication = env["service"].publish(second_request)
        pre_rebuild_search = HybridSearchRequest(
            identity=env["identity"],
            manifest_root_sha256=publication.manifest_ref.sha256,
            query_text="Exact integration insurance rule",
            query_embedding=(1.0, 0.0),
            source_publication_seq=1,
            authorization=InstitutionAuthorizationContext(),
            as_of_date=date(2026, 7, 14),
            lexical_budget=10,
            dense_budget=10,
            rrf_window=10,
            rrf_pipeline=rrf_pipeline_name(rank_constant=60),
            rrf_rank_constant=60,
            limit=10,
        )
        pre_sequence_one = env["index"].search(pre_rebuild_search)
        assert any(hit.rule_unit_revision_id.endswith("-one") for hit in pre_sequence_one)
        assert all(not hit.rule_unit_revision_id.endswith("-two") for hit in pre_sequence_one)
        pre_sequence_two = env["index"].search(
            pre_rebuild_search.model_copy(update={"source_publication_seq": 2})
        )
        assert all(not hit.rule_unit_revision_id.endswith("-one") for hit in pre_sequence_two)
        assert any(hit.rule_unit_revision_id.endswith("-two") for hit in pre_sequence_two)
        recovery = HybridRecoveryService(
            repository=env["repository"],
            artifact_store=env["store"],
            index=OpenSearchRecoveryIndex(
                index=env["index"],
                embedding=cast(Any, _Embedding()),
                embedding_instruction=INSTRUCTION,
            ),
        )
        rebuilt = recovery.rebuild_generation(
            source_id=env["source_id"],
            generation_id=env["generation"].generation_id,
        )
        assert rebuilt.index_uuid != publication.attestation.index_uuid
        assert rebuilt.manifest_root_sha256 == publication.manifest_ref.sha256
        assert rebuilt.covered_publication_sequences == (
            publication.attestation.covered_publication_sequences
        )
        authority = env["repository"].load_generation_rebuild(
            env["source_id"], env["generation"].generation_id
        )
        assert authority.current_attestation == rebuilt
        assert authority.current_identity.projection_locator is not None
        assert env["index"].verify_identity(authority.current_identity) == (
            authority.current_identity
        )
        base_search = HybridSearchRequest(
            identity=authority.current_identity,
            manifest_root_sha256=publication.manifest_ref.sha256,
            query_text="Exact integration insurance rule",
            query_embedding=(1.0, 0.0),
            source_publication_seq=1,
            authorization=InstitutionAuthorizationContext(),
            as_of_date=date(2026, 7, 14),
            lexical_budget=10,
            dense_budget=10,
            rrf_window=10,
            rrf_pipeline=rrf_pipeline_name(rank_constant=60),
            rrf_rank_constant=60,
            limit=10,
        )
        sequence_one = env["index"].search(base_search)
        assert any(hit.rule_unit_revision_id.endswith("-one") for hit in sequence_one)
        assert all(not hit.rule_unit_revision_id.endswith("-two") for hit in sequence_one)
        sequence_two = env["index"].search(
            base_search.model_copy(update={"source_publication_seq": 2})
        )
        assert all(not hit.rule_unit_revision_id.endswith("-one") for hit in sequence_two)
        assert any(hit.rule_unit_revision_id.endswith("-two") for hit in sequence_two)
        third_request = _request(
            env["source_id"],
            env["generation"],
            authority.current_identity,
            rule_suffix="three",
            publication_seq_from=3,
        )
        env["repository"].advance_source_candidate(
            source_id=env["source_id"],
            expected_source_draft_version_id=second_request.source_draft_version_id,
            expected_candidate_digest=second_request.candidate_digest,
            source_draft_version_id=third_request.source_draft_version_id,
            candidate_digest=third_request.candidate_digest,
        )
        env["repository"].register_validation(
            HybridPublicationValidationAuthority(
                validation_id=third_request.validation_id,
                source_id=third_request.source_id,
                source_draft_version_id=third_request.source_draft_version_id,
                candidate_digest=third_request.candidate_digest,
                generation_id=third_request.generation.generation_id,
                validated_at=datetime.now(UTC),
                validated_by="integration-validator",
            )
        )
        third_publication = env["service"].publish(third_request)
        assert third_publication.attestation.parent_attestation_sha256 == (
            rebuilt.attestation_sha256
        )
        post_recovery_authority = env["repository"].load_generation_rebuild(
            env["source_id"], env["generation"].generation_id
        )
        assert post_recovery_authority.current_attestation == third_publication.attestation
        env["cleanup_identities"] = [env["identity"], authority.current_identity]
    finally:
        _cleanup(env)
