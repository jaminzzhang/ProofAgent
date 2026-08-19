from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from proof_agent.contracts import (
    ReceiptOutcome,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateExecutionBudget,
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.control.knowledge.candidate_request import (
    BoundKnowledgeCandidateQueryFactory,
)
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)
from proof_agent.errors import ProofAgentError


AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _bindings() -> ResolvedKnowledgeBindingSet:
    return ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeSourceServiceBinding(
                binding_id="enterprise-knowledge",
                knowledge_base_release_id="release-enterprise-1",
                client_credential_ref=ProductionSecretHandle(
                    protocol_id="vault-kv-v2",
                    handle_id="knowledge/source-service/enterprise-client",
                    purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                    version_id="credential-v1",
                ),
                admission_scorer_id="enterprise-admission",
                admission_scorer_revision="enterprise-admission.v1",
            ),
        )
    )


def _query_factory() -> BoundKnowledgeCandidateQueryFactory:
    return BoundKnowledgeCandidateQueryFactory(
        knowledge_base_release_id="release-enterprise-1",
        execution_budget=KnowledgeCandidateExecutionBudget(
            max_rounds=1,
            max_model_calls=1,
            max_candidates=10,
            max_model_tokens=1000,
            max_duration_ms=5000,
        ),
        deadline_after=timedelta(seconds=30),
        clock=lambda: datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )


class CandidateService:
    def __init__(self, *, include_candidate: bool = True) -> None:
        self.include_candidate = include_candidate
        self.requests: list[KnowledgeCandidateQuery] = []

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult:
        self.requests.append(request)
        candidates = []
        if self.include_candidate:
            candidates.append(
                {
                    "candidate_evidence_id": "candidate-enterprise-1",
                    "knowledge_space_id": "space-enterprise-1",
                    "knowledge_base_id": "base-enterprise-1",
                    "knowledge_base_version_id": "base-version-enterprise-1",
                    "knowledge_base_release_id": request.knowledge_base_release_id,
                    "knowledge_source_id": "source-enterprise-1",
                    "knowledge_source_version_id": "source-version-enterprise-1",
                    "evidence_unit_id": "unit-enterprise-1",
                    "content": {
                        "media_type": "text/plain",
                        "text": "Travel meals are reimbursed up to 50 USD per day with receipts.",
                    },
                    "content_hash": _digest("a"),
                    "citation_locator": {
                        "kind": "text_lines",
                        "start_line": 3,
                        "end_line": 3,
                    },
                    "context_evidence_units": [],
                    "ranking": {
                        "kind": "relevance",
                        "lane_contributions": [
                            {
                                "lane": "lexical",
                                "native_score": 3.0,
                                "lane_rank": 1,
                                "weight": 1.0,
                                "rrf_contribution": 0.01639,
                            }
                        ],
                        "fused_rank": 1,
                        "reranked_rank": None,
                    },
                    "retrieval_lineage": {
                        "retrieval_round": 1,
                        "plan_revision": 1,
                        "index_identity": "index-enterprise-1",
                        "query_digest": _digest("b"),
                        "access_scope_digest": _digest("c"),
                    },
                }
            )
        return KnowledgeCandidateResult.model_validate(
            {
                "schema_version": "knowledge-query-result.v1",
                "knowledge_query_id": "query-enterprise-1",
                "evidence_groups": [
                    {
                        "evidence_group_id": "relevance-enterprise-1",
                        "group_type": "relevance_ranked",
                        "ordering": {
                            "kind": "relevance",
                            "final_rank_field": "fused_rank",
                        },
                        "candidate_evidence": candidates,
                    }
                ],
                "query_plan_summary": {
                    "plan_revision": 1,
                    "planned_lanes": ["lexical"],
                    "structured_query_count": 0,
                    "plan_digest": _digest("d"),
                },
                "execution_summary": {
                    "strategy": "single_pass",
                    "rounds": 1,
                    "stop_reason": "single_pass_complete",
                    "degraded": False,
                    "budget_usage": {
                        "rounds": 1,
                        "model_calls": 0,
                        "candidates": len(candidates),
                        "model_tokens": 0,
                        "duration_ms": 10,
                    },
                },
                "retrieval_lineage": {
                    "knowledge_base_release_id": request.knowledge_base_release_id,
                    "release_manifest_digest": _digest("e"),
                    "access_scope_digest": _digest("c"),
                    "plan_revision_digests": [_digest("d")],
                },
            }
        )


class AdmissionScorer:
    scorer_id = "enterprise-admission"
    scorer_revision = "enterprise-admission.v1"

    def score_candidates(
        self,
        *,
        query: KnowledgeCandidateQuery,
        result: KnowledgeCandidateResult,
    ) -> dict[str, float]:
        del query
        return {
            candidate.candidate_evidence_id: 1.0
            for group in result.evidence_groups
            for candidate in group.candidate_evidence
        }


def test_package_without_published_kss_binding_refuses_no_evidence(tmp_path: Path) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT,
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path,
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_template_execution_result is not None
    assert result.workflow_template_execution_result.evidence == ()


def test_candidate_runtime_without_published_kss_binding_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProofAgentError, match="requires one exact Published KSS binding"):
        execute_agent_package_run(
            AgentPackageRunRequest(
                agent_yaml=AGENT,
                question="What is the reimbursement rule for travel meals?",
                runs_dir=tmp_path,
                knowledge_candidate_service=CandidateService(),
                knowledge_candidate_query_factory=_query_factory(),
                knowledge_candidate_admission_scorer=AdmissionScorer(),
            )
        )


def test_exact_kss_binding_answers_from_proofagent_admitted_candidates(
    tmp_path: Path,
) -> None:
    service = CandidateService()

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT,
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path,
            run_id="run-kss-candidate-1",
            resolved_knowledge_bindings=_bindings(),
            knowledge_candidate_service=service,
            knowledge_candidate_query_factory=_query_factory(),
            knowledge_candidate_admission_scorer=AdmissionScorer(),
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert service.requests[0].knowledge_base_release_id == "release-enterprise-1"
    assert result.workflow_template_execution_result is not None
    evidence = result.workflow_template_execution_result.evidence[0]
    assert evidence.source.startswith(
        "knowledge://space-enterprise-1/release-enterprise-1/source-version-enterprise-1/"
    )
    assert evidence.admission_score == 1.0


def test_exact_kss_binding_refuses_when_service_returns_no_candidates(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT,
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path,
            resolved_knowledge_bindings=_bindings(),
            knowledge_candidate_service=CandidateService(include_candidate=False),
            knowledge_candidate_query_factory=_query_factory(),
            knowledge_candidate_admission_scorer=AdmissionScorer(),
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_template_execution_result is not None
    assert result.workflow_template_execution_result.evidence == ()
