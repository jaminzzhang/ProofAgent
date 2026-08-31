"""Verify the production-local Admission Scorer with fixed synthetic data.

The verifier binds the deployment-owned scorer through the normal production
runtime. It does not query KSS, call a configured answer model, persist artifacts,
or enter publication authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import math
import os
import sys
from typing import Any
import warnings

from proof_agent.contracts import (
    ProductionSecretHandle,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.contracts.ports.secret_provider import SecretProvider


_SYNTHETIC_BINDING_ID = "synthetic-admission-binding-v1"
_SYNTHETIC_RELEASE_ID = "synthetic-admission-release-v1"
_SYNTHETIC_QUERY_ID = "synthetic-admission-query-v1"
_SYNTHETIC_CANDIDATE_ID = "synthetic-admission-candidate-1"
_SYNTHETIC_QUESTION = "What synthetic evidence should this verifier score?"
_SYNTHETIC_CONTENT = "Candidate Evidence contains only synthetic validation data."


def verify_production_local_admission_scorer(
    *,
    runtime: Any,
    binding: ResolvedKnowledgeSourceServiceBinding,
) -> dict[str, object]:
    """Score one fixed synthetic Candidate through the public runtime binding."""

    dependencies = runtime.bind_for_run(ResolvedKnowledgeBindingSet(bindings=(binding,)))
    scorer = dependencies.admission_scorer
    if (
        scorer.scorer_id != binding.admission_scorer_id
        or scorer.scorer_revision != binding.admission_scorer_revision
    ):
        raise RuntimeError("production-local scorer identity changed")

    query = _synthetic_query()
    result = _synthetic_result()
    scores = scorer.score_candidates(query=query, result=result)
    expected_ids = {
        candidate.candidate_evidence_id
        for group in result.evidence_groups
        for candidate in group.candidate_evidence
    }
    if set(scores) != expected_ids:
        raise RuntimeError("Admission Scorer did not score the exact synthetic candidate set")
    if any(not _valid_score(score) for score in scores.values()):
        raise RuntimeError("Admission Scorer returned an invalid synthetic score")

    ordered_candidate_ids = "\n".join(sorted(expected_ids))
    return {
        "schema_version": "production-local-admission-scorer-verification.v1",
        "evidence_class": "local_synthetic_dependency_validation_only",
        "status": "passed",
        "scorer_id": scorer.scorer_id,
        "scorer_revision": scorer.scorer_revision,
        "question_sha256": _sha256(_SYNTHETIC_QUESTION),
        "candidate_set_sha256": _sha256(ordered_candidate_ids),
        "candidate_count": len(expected_ids),
        "score_count": len(scores),
        "kss_query_created": False,
        "external_model_called": False,
        "phase_f_authorized": False,
        "publication_authorized": False,
    }


def main() -> None:
    from authlib.deprecate import (  # type: ignore[import-untyped]
        AuthlibDeprecationWarning,
    )

    warnings.simplefilter("ignore", AuthlibDeprecationWarning)
    from proof_agent.bootstrap.application_services import (
        compose_application_persistence,
        compose_production_egress_client,
        compose_production_vault_secret_provider,
    )
    from proof_agent.bootstrap.knowledge_candidate_runtime import (
        compose_production_knowledge_candidate_runtime,
    )
    from proof_agent.capabilities.persistence.postgres.bundle import (
        PostgresPersistenceBundle,
    )

    values = os.environ
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise RuntimeError("production-local scorer verification requires PostgreSQL")
    try:
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        runtime = compose_production_knowledge_candidate_runtime(
            values,
            http_client=guarded,
            secret_provider=secret_provider,
        )
        result = verify_production_local_admission_scorer(
            runtime=runtime,
            binding=_synthetic_binding(values, secret_provider=secret_provider),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        persistence.close()


def cli() -> int:
    """Run without projecting exceptions, credentials, or scorer response details."""

    try:
        main()
    except Exception:
        print(
            json.dumps(
                {
                    "schema_version": ("production-local-admission-scorer-verification-failure.v1"),
                    "status": "failed",
                    "error_code": "admission_scorer_verification_failed",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


def _synthetic_binding(
    values: Mapping[str, str],
    *,
    secret_provider: SecretProvider,
) -> ResolvedKnowledgeSourceServiceBinding:
    return ResolvedKnowledgeSourceServiceBinding(
        binding_id=_SYNTHETIC_BINDING_ID,
        knowledge_base_release_id=_SYNTHETIC_RELEASE_ID,
        client_credential_ref=ProductionSecretHandle(
            protocol_id=secret_provider.protocol_id,
            handle_id=_required(values, "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE"),
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id=_required(
                values,
                "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID",
            ),
        ),
        admission_scorer_id=_required(
            values,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID",
        ),
        admission_scorer_revision=_required(
            values,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION",
        ),
    )


def _synthetic_query() -> KnowledgeCandidateQuery:
    return KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "production-local-admission-scorer-verification-v1",
            "knowledge_base_release_id": _SYNTHETIC_RELEASE_ID,
            "question": _SYNTHETIC_QUESTION,
            "strategy": "single_pass",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 1,
                "max_model_tokens": 1,
                "max_duration_ms": 1_000,
            },
            "deadline_at": datetime(2099, 1, 1, tzinfo=UTC),
        }
    )


def _synthetic_result() -> KnowledgeCandidateResult:
    access_scope_digest = _sha256_digest("synthetic-access-scope-v1")
    query_digest = _sha256_digest("synthetic-query-v1")
    plan_digest = _sha256_digest("synthetic-plan-v1")
    return KnowledgeCandidateResult.model_validate(
        {
            "schema_version": "knowledge-query-result.v1",
            "knowledge_query_id": _SYNTHETIC_QUERY_ID,
            "evidence_groups": [
                {
                    "evidence_group_id": "synthetic-relevance-group-v1",
                    "group_type": "relevance_ranked",
                    "ordering": {
                        "kind": "relevance",
                        "final_rank_field": "fused_rank",
                    },
                    "candidate_evidence": [
                        {
                            "candidate_evidence_id": _SYNTHETIC_CANDIDATE_ID,
                            "knowledge_space_id": "synthetic-space-v1",
                            "knowledge_base_id": "synthetic-base-v1",
                            "knowledge_base_version_id": "synthetic-base-version-v1",
                            "knowledge_base_release_id": _SYNTHETIC_RELEASE_ID,
                            "knowledge_source_id": "synthetic-source-v1",
                            "knowledge_source_version_id": ("synthetic-source-version-v1"),
                            "evidence_unit_id": "synthetic-evidence-unit-v1",
                            "content": {
                                "media_type": "text/plain",
                                "text": _SYNTHETIC_CONTENT,
                            },
                            "content_hash": _sha256_digest(_SYNTHETIC_CONTENT),
                            "citation_locator": {
                                "kind": "text_lines",
                                "start_line": 1,
                                "end_line": 1,
                            },
                            "context_evidence_units": [],
                            "ranking": {
                                "kind": "relevance",
                                "lane_contributions": [
                                    {
                                        "lane": "lexical",
                                        "native_score": 1.0,
                                        "lane_rank": 1,
                                        "weight": 1.0,
                                        "rrf_contribution": 1.0,
                                    }
                                ],
                                "fused_rank": 1,
                                "reranked_rank": None,
                            },
                            "retrieval_lineage": {
                                "retrieval_round": 1,
                                "plan_revision": 1,
                                "index_identity": "synthetic-index-v1",
                                "query_digest": query_digest,
                                "access_scope_digest": access_scope_digest,
                            },
                        }
                    ],
                }
            ],
            "query_plan_summary": {
                "plan_revision": 1,
                "planned_lanes": ["lexical"],
                "structured_query_count": 0,
                "plan_digest": plan_digest,
            },
            "execution_summary": {
                "strategy": "single_pass",
                "rounds": 1,
                "stop_reason": "single_pass_complete",
                "degraded": False,
                "budget_usage": {
                    "rounds": 1,
                    "model_calls": 0,
                    "candidates": 1,
                    "model_tokens": 0,
                    "duration_ms": 1,
                },
            },
            "retrieval_lineage": {
                "knowledge_base_release_id": _SYNTHETIC_RELEASE_ID,
                "release_manifest_digest": _sha256_digest("synthetic-release-manifest-v1"),
                "access_scope_digest": access_scope_digest,
                "plan_revision_digests": [plan_digest],
            },
        }
    )


def _valid_score(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return False
    score = float(value)
    return math.isfinite(score) and 0.0 <= score <= 1.0


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_digest(value: str) -> str:
    return f"sha256:{_sha256(value)}"


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required for Admission Scorer verification")
    return value


if __name__ == "__main__":
    raise SystemExit(cli())
