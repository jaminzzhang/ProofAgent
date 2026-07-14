from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from proof_agent.contracts import (
    ExactArtifactRef,
    InstitutionAuthorizationContext,
    IntentResolution,
    IntentResolutionResult,
    KnowledgeRetrievalProfileRevision,
    ReActActionType,
    ResolvedHybridKnowledgeBinding,
    RetrievalQueryItem,
    ReceiptOutcome,
)
from proof_agent.control.knowledge.hybrid_request import (
    ApprovedInsuranceConditionTaxonomy,
    GovernedHybridRequestFactory,
    InsuranceConditionProposal,
    admit_insurance_conditions,
    build_governed_hybrid_request,
)
from proof_agent.control.workflow.controlled_react import (
    ControlledReActOrchestrator,
    ControlledReActPorts,
    ControlledReActStartRequest,
)
from proof_agent.control.workflow.controlled_react.composition import (
    _InvocationPlannerAdapter,
)


def _approved_taxonomy() -> ApprovedInsuranceConditionTaxonomy:
    return ApprovedInsuranceConditionTaxonomy(
        taxonomy_id="insurance-guidance",
        taxonomy_revision_id="taxonomy-2",
        allowed_values={
            "region": ("SHANGHAI", "BEIJING"),
            "channel": ("AGENCY", "BROKER"),
            "product": ("PRODUCT-A", "PRODUCT-B"),
        },
        authority_required_fields=("region", "channel"),
    )


def test_model_proposed_unknown_condition_is_rejected() -> None:
    proposal = InsuranceConditionProposal(values={"vip_override": "yes"})

    result = admit_insurance_conditions(proposal, taxonomy=_approved_taxonomy())

    assert result.admitted is False
    assert result.reason == "unknown_condition_key"
    assert result.normalized_values == {}


def _hybrid_binding() -> ResolvedHybridKnowledgeBinding:
    return ResolvedHybridKnowledgeBinding(
        binding_id="binding-1",
        source_id="source-1",
        source_publication_id="publication-7",
        source_snapshot_id="snapshot-7",
        index_generation_id="generation-7",
        source_publication_seq=7,
        retrieval_profile_revision_id="profile-2",
        manifest_ref=ExactArtifactRef(
            artifact_uri="s3://knowledge/manifests/root.json",
            version_id="manifest-version-7",
            sha256="1" * 64,
            size_bytes=42,
            media_type="application/json",
        ),
        publication_attestation_id="attestation-7",
    )


def _retrieval_profile() -> KnowledgeRetrievalProfileRevision:
    return KnowledgeRetrievalProfileRevision(
        profile_revision_id="profile-2",
        lexical_budget=100,
        dense_budget=100,
        rrf_window=50,
        reranker_revision="reranker-2",
        rerank_budget=50,
        final_budget=16,
    )


def test_missing_authority_condition_clarifies_before_search() -> None:
    intent = _conditional_intent()

    result = build_governed_hybrid_request(
        intent=intent,
        authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            channels=("AGENCY",),
        ),
        binding=_hybrid_binding(),
        retrieval_profile=_retrieval_profile(),
        taxonomy=_approved_taxonomy(),
        as_of_time=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert result.request is None
    assert result.clarification is not None
    assert result.clarification.missing_fields == ("region",)


def _conditional_intent() -> IntentResolution:
    return IntentResolution(
        resolution_id="intent-1",
        user_goal="Explain whether Product A applies.",
        domain_intent="insurance_conditional_guidance",
        known_facts=("The channel is agency.",),
        missing_fields=("region",),
        ambiguities=(),
        risk_flags=(),
        confidence=0.9,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        retrieval_query_set=(
            RetrievalQueryItem(
                query="Product A applicable conditions",
                intent_angle="applicability",
                required=True,
                reason="The user asks for conditional guidance.",
            ),
        ),
        insurance_condition_proposal=InsuranceConditionProposal(
            values={"channel": "agency", "product": "product-a"}
        ),
    )


class _FixedIntentResolution:
    def resolve(self, state: object) -> IntentResolutionResult:
        _ = state
        return IntentResolutionResult(intent_resolution=_conditional_intent())


class _FailIfSearched:
    calls = 0

    def observe(self, *args: object, **kwargs: object) -> Any:
        self.calls += 1
        raise AssertionError("Knowledge search must not run before authority clarification")


class _FailIfAnswered:
    def synthesize(self, *args: object, **kwargs: object) -> Any:
        raise AssertionError("Answer synthesis must not run before authority clarification")


def test_controlled_react_clarifies_missing_authority_before_knowledge_search() -> None:
    factory = GovernedHybridRequestFactory(
        binding=_hybrid_binding(),
        retrieval_profile=_retrieval_profile(),
        taxonomy=_approved_taxonomy(),
        clock=lambda: datetime(2026, 7, 14, tzinfo=UTC),
    )
    invocation = SimpleNamespace(
        governed_hybrid_request_factory=factory,
        react_planner=None,
    )
    search = _FailIfSearched()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            intent_resolution=_FixedIntentResolution(),
            planner=_InvocationPlannerAdapter(invocation),  # type: ignore[arg-type]
            knowledge_observation=search,
            answer_synthesis=_FailIfAnswered(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run-missing-region",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Does Product A apply?",
            institution_authorization=InstitutionAuthorizationContext(
                institutions=("INST-1",),
                channels=("AGENCY",),
            ),
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert result.clarification_need is not None
    assert result.clarification_need.missing_fields == ("region",)
    assert search.calls == 0


def test_governed_request_uses_trusted_scope_pinned_authority_and_profile_budgets() -> None:
    intent = IntentResolution(
        resolution_id="intent-2",
        user_goal="Explain whether Product A applies.",
        domain_intent="insurance_conditional_guidance",
        known_facts=("The product is Product A.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.92,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        retrieval_query_set=(
            RetrievalQueryItem(
                query="Product A applicable conditions",
                intent_angle="applicability",
                required=True,
                reason="The user asks for conditional guidance.",
            ),
        ),
        insurance_condition_proposal=InsuranceConditionProposal(values={"product": "product-a"}),
    )
    as_of_time = datetime(2026, 7, 14, tzinfo=UTC)

    result = build_governed_hybrid_request(
        intent=intent,
        authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            regions=("SHANGHAI",),
            channels=("AGENCY",),
        ),
        binding=_hybrid_binding(),
        retrieval_profile=_retrieval_profile(),
        taxonomy=_approved_taxonomy(),
        as_of_time=as_of_time,
    )

    assert result.clarification is None
    assert result.no_recommendation_reason is None
    request = result.request
    assert request is not None
    assert request.binding == _hybrid_binding()
    assert request.retrieval_profile == _retrieval_profile()
    assert request.normalized_conditions == {
        "channel": "AGENCY",
        "product": "PRODUCT-A",
        "region": "SHANGHAI",
    }
    assert tuple(item.key for item in request.applicability_filters) == (
        "channel",
        "product",
        "region",
    )
    assert request.query_type == "conditional_guidance"
    assert request.as_of_time == as_of_time
    assert request.candidate_budgets.model_dump() == {
        "lexical": 100,
        "dense": 100,
        "rrf_window": 50,
        "rerank": 50,
        "final": 16,
    }
    assert tuple(slot.requirement_kind for slot in request.required_evidence_slots) == (
        "governing_rule",
        "applicable_condition",
        "exclusion_or_exception",
        "precedence_source",
    )


@pytest.mark.parametrize(
    ("domain_intent", "proposal", "expected_type", "expected_slots"),
    (
        (
            "insurance_clause_lookup",
            {"product": "product-a"},
            "clause_lookup",
            ("requested-clause",),
        ),
        (
            "insurance_product_comparison",
            {"product_left": "product-a", "product_right": "product-b"},
            "comparison",
            ("comparison:PRODUCT-A", "comparison:PRODUCT-B"),
        ),
    ),
)
def test_clause_and_comparison_requests_pin_exact_evidence_slots(
    domain_intent: str,
    proposal: dict[str, str],
    expected_type: str,
    expected_slots: tuple[str, ...],
) -> None:
    taxonomy = ApprovedInsuranceConditionTaxonomy(
        taxonomy_id="insurance-guidance",
        taxonomy_revision_id="taxonomy-3",
        allowed_values={
            **dict(_approved_taxonomy().allowed_values),
            "product_left": ("PRODUCT-A", "PRODUCT-B"),
            "product_right": ("PRODUCT-A", "PRODUCT-B"),
        },
        authority_required_fields=("region", "channel"),
    )
    intent = _conditional_intent().model_copy(
        update={
            "domain_intent": domain_intent,
            "insurance_condition_proposal": InsuranceConditionProposal(values=proposal),
        }
    )

    result = build_governed_hybrid_request(
        intent=intent,
        authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            regions=("SHANGHAI",),
            channels=("AGENCY",),
        ),
        binding=_hybrid_binding(),
        retrieval_profile=_retrieval_profile(),
        taxonomy=taxonomy,
        as_of_time=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert result.request is not None
    assert result.request.query_type == expected_type
    assert tuple(slot.slot_id for slot in result.request.required_evidence_slots) == expected_slots
