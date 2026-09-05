"""Fixed synthetic capability boundaries driving the existing Control Plane.

No network, environment files, production runs, or alternate execution loop.
The observations report behavior; they never assert that a known bug must persist.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Self

from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.capabilities.react.intent import LLMIntentResolver
from proof_agent.capabilities.react.planner import LLMReActPlanner
from proof_agent.contracts import (
    ContextAdmission,
    ConversationRecord,
    ConversationTurn,
    EvidenceChunk,
    EvidenceStatus,
    IntentResolution,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    ReActActionProposal,
    ReActActionType,
    ReActPlannerConfig,
    ReasoningSummary,
    ReceiptOutcome,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    RetrievalQueryItem,
    ValidationStatus,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateExecutionBudget,
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.control.conversation import admit_conversation_context
from proof_agent.control.knowledge.candidate_request import BoundKnowledgeCandidateQueryFactory
from proof_agent.control.workflow.controlled_react import (
    ControlledReActStartRequest,
    build_controlled_react_orchestrator_for_invocation,
)
from proof_agent.control.workflow.harness_helpers import validate_model_output
from proof_agent.evaluation.kernel_baseline import Probe


FIXTURES = Path(__file__).parent / "fixtures"
QUERY_A = "Alpha policy reimbursement limit"
QUERY_B = "Beta policy waiting period"
FACT_A = "Alpha policy reimbursement limit is 100 yuan."
FACT_B = "Beta policy waiting period is 7 days."
REWRITTEN_QUERY = "inpatient reimbursement required documents"


class ScriptedModelProvider:
    provider_name = "deterministic"
    model_name = "kernel-baseline-scripted"

    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = responses
        self.requests: list[ModelRequest] = []

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self:
        raise ValueError("baseline providers require explicit synthetic responses")

    def estimate_tokens(self, request: ModelRequest) -> int:
        return sum(len(message.content) for message in request.messages) // 4 + 1

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return ModelResponse(
            content=self.responses[index],
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


class SyntheticCandidateService:
    def __init__(self, *, structured: bool = False) -> None:
        self.structured = structured
        self.requests: list[KnowledgeCandidateQuery] = []

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult:
        self.requests.append(request)
        payload = json.loads((FIXTURES / "kernel_baseline/knowledge_result.json").read_text())
        text_candidate = payload["evidence_groups"][0]["candidate_evidence"][0]
        text = FACT_B if request.question == QUERY_B else FACT_A
        text_candidate["content"]["text"] = text
        text_candidate["content_hash"] = "sha256:" + sha256(text.encode()).hexdigest()
        # Keep candidates from distinct queries distinct at the admission boundary.
        suffix = "b" if request.question == QUERY_B else "a"
        for field in ("candidate_evidence_id", "evidence_unit_id", "knowledge_source_version_id"):
            text_candidate[field] += "-" + suffix
        if not self.structured:
            payload["evidence_groups"] = payload["evidence_groups"][:1]
            payload["query_plan_summary"]["planned_lanes"] = ["lexical"]
            payload["query_plan_summary"]["structured_query_count"] = 0
            payload["execution_summary"]["budget_usage"]["candidates"] = 1
        return KnowledgeCandidateResult.model_validate(payload)


class SyntheticAdmissionScorer:
    scorer_id = "baseline-admission"
    scorer_revision = "baseline-admission.v1"

    def score_candidates(
        self, *, query: KnowledgeCandidateQuery, result: KnowledgeCandidateResult
    ) -> dict[str, float]:
        return {
            candidate.candidate_evidence_id: 1.0
            for group in result.evidence_groups
            for candidate in group.candidate_evidence
        }


@dataclass(frozen=True)
class RetrievalObservation:
    queries: tuple[str, ...]
    answer_inputs: tuple[str, ...]
    admitted_evidence: tuple[EvidenceChunk, ...] = ()
    final_answer_sources: tuple[str, ...] = ()

    def contains_answer_fact(self, fact: str) -> bool:
        return bool(self.answer_inputs) and _contains_complete_fact(self.answer_inputs[-1], fact)

    def contains_admitted_fact(self, fact: str, *, source_id: str | None = None) -> bool:
        return self.contains_answer_fact(fact) and any(
            chunk.status is EvidenceStatus.ACCEPTED
            and chunk.source in self.final_answer_sources
            and (source_id is None or chunk.source_id == source_id)
            and _contains_complete_fact(chunk.content, fact)
            for chunk in self.admitted_evidence
        )


def _contains_complete_fact(text: str, fact: str) -> bool:
    # Fixed lexical regression, not a general semantic or numeric judge.
    return re.search(r"(?<![\w.+-])" + re.escape(fact) + r"(?!\w|\.\d)", text) is not None


def exercise_retrieval(
    *,
    question: str,
    queries: tuple[str, ...],
    intent_queries: tuple[str, ...] = (),
    structured: bool = False,
) -> RetrievalObservation:
    service = SyntheticCandidateService(structured=structured)
    invocation = compose_harness_invocation(
        FIXTURES / "react_enterprise_qa_v3/agent.yaml",
        require_runtime_credentials=False,
        resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedKnowledgeSourceServiceBinding(
                    binding_id="baseline-kss",
                    knowledge_base_release_id="release-1",
                    client_credential_ref=ProductionSecretHandle(
                        protocol_id="vault-kv-v2",
                        handle_id="synthetic/baseline-unused",
                        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                        version_id="synthetic-v1",
                    ),
                    admission_scorer_id="baseline-admission",
                    admission_scorer_revision="baseline-admission.v1",
                ),
            )
        ),
        knowledge_candidate_service=service,
        knowledge_candidate_query_factory=BoundKnowledgeCandidateQueryFactory(
            knowledge_base_release_id="release-1",
            execution_budget=KnowledgeCandidateExecutionBudget(
                max_rounds=1,
                max_model_calls=1,
                max_candidates=10,
                max_model_tokens=1000,
                max_duration_ms=5000,
            ),
            deadline_after=timedelta(seconds=30),
            clock=lambda: datetime(2026, 9, 5, tzinfo=UTC),
        ),
        knowledge_candidate_admission_scorer=SyntheticAdmissionScorer(),
    )
    intent = IntentResolution(
        resolution_id="intent-baseline",
        user_goal=question,
        domain_intent="policy_question",
        known_facts=(),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=1.0,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        retrieval_query_set=tuple(
            RetrievalQueryItem(
                query=query,
                intent_angle=f"required_{index}",
                required=True,
                reason="Required to complete the user's question.",
            )
            for index, query in enumerate(intent_queries or queries)
        ),
    )
    actions = tuple(_action(query, index) for index, query in enumerate(queries))
    actions += (_action(None, len(queries)),)
    planner_provider = ScriptedModelProvider(
        tuple(
            json.dumps(action.model_dump(mode="python", warnings=False), default=dict)
            for action in actions
        )
    )
    # Its reply is immaterial to input-coverage probes; never claim answer correctness here.
    answer_provider = ScriptedModelProvider(
        (
            json.dumps(
                {
                    "message": "The requested policy information requires complete evidence.",
                    "citations": [],
                }
            ),
        )
    )
    config = ReActPlannerConfig(provider="deterministic", name="kernel-baseline-scripted")
    invocation = replace(
        invocation,
        intent_resolver=LLMIntentResolver(
            config=config,
            model_provider=ScriptedModelProvider(
                (json.dumps(intent.model_dump(mode="python"), default=dict),)
            ),
        ),
        react_planner=LLMReActPlanner(config=config, model_provider=planner_provider),
        model_provider=answer_provider,
    )
    orchestrator = build_controlled_react_orchestrator_for_invocation(invocation)
    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run-kernel-baseline",
            template_name=invocation.template.name,
            template_descriptor_version=invocation.template.descriptor_version,
            question=question,
            max_plan_rounds=4,
        )
    )
    return RetrievalObservation(
        queries=tuple(request.question for request in service.requests),
        answer_inputs=tuple(
            "\n".join(message.content for message in request.messages)
            for request in answer_provider.requests
        ),
        admitted_evidence=result.evidence,
        final_answer_sources=(
            answer_provider.requests[-1].evidence_sources if answer_provider.requests else ()
        ),
    )


def _action(query: str | None, index: int) -> ReActActionProposal:
    action_type = (
        ReActActionType.PLAN_RETRIEVAL
        if query is not None
        else ReActActionType.GENERATE_FINAL_ANSWER
    )
    return ReActActionProposal(
        action_id=f"action-baseline-{index}",
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="Complete required policy queries.",
            observations=(),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Fixed synthetic proposal.",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters={"query": query} if query is not None else {},
        risk_level="low",
    )


def numeric_validation_probe() -> dict[str, bool]:
    citation = "knowledge://baseline/policy#text-lines=1-1"
    evidence = (
        EvidenceChunk(
            source="knowledge://baseline/policy",
            content="The reimbursement limit is 100 yuan.",
            citation=citation,
            admission_score=1.0,
            status=EvidenceStatus.ACCEPTED,
        ),
    )

    def accepted(amount: int) -> bool:
        checks = validate_model_output(
            response=ModelResponse(
                content=json.dumps(
                    {
                        "message": f"The reimbursement limit is {amount} yuan.",
                        "citations": [citation],
                    }
                ),
                provider_name="deterministic",
                model_name="kernel-baseline-scripted",
                finish_reason="stop",
            ),
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            evidence=evidence,
            question="What is the reimbursement limit?",
        )
        return bool(checks) and all(check.status is ValidationStatus.PASSED for check in checks)

    return {"correct_answer_accepted": accepted(100), "wrong_amount_rejected": not accepted(500)}


def compound_retrieval_probe() -> dict[str, bool]:
    observation = exercise_retrieval(
        question="Retrieve Alpha reimbursement and Beta waiting period, then compare both policies.",
        queries=(QUERY_A, QUERY_B),
    )
    return {
        "both_sources_queried": {QUERY_A, QUERY_B}.issubset(observation.queries),
        "both_facts_reach_answer": (
            observation.contains_admitted_fact(FACT_A)
            and observation.contains_admitted_fact(FACT_B)
        ),
    }


def intent_rewrite_probe() -> dict[str, bool]:
    original = "What papers do I need for this hospital claim?"
    observation = exercise_retrieval(
        question=original,
        queries=(original,),
        intent_queries=(REWRITTEN_QUERY,),
    )
    return {"required_rewrite_reaches_kss": REWRITTEN_QUERY in observation.queries}


def structured_fact_probe() -> dict[str, bool]:
    question = "What is the claim total for the requested year?"
    observation = exercise_retrieval(question=question, queries=(question,), structured=True)
    return {
        "structured_amount_reaches_answer": observation.contains_admitted_fact(
            "12345.67",
            source_id="source-table-1",
        )
    }


def conversation_constraints_probe(*, turn_count: int = 30) -> dict[str, bool]:
    timestamp = "2026-09-05T00:00:00Z"
    turns = tuple(
        ConversationTurn(
            turn_id=f"turn-{index}",
            run_id=f"run-{index}",
            agent_id="baseline-agent",
            question=(
                "Budget is 500 yuan. Do not submit anything."
                if index == 0
                else f"Unrelated policy clarification {index}."
            ),
            final_output="Acknowledged.",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at=timestamp,
            context_admission=ContextAdmission(admitted=False),
        )
        for index in range(turn_count)
    )
    context = admit_conversation_context(
        ConversationRecord(
            conversation_id="conversation-baseline",
            agent_id="baseline-agent",
            created_at=timestamp,
            updated_at=timestamp,
            turns=turns,
        )
    )
    return measure_conversation_constraints(context)


def measure_conversation_constraints(context: ContextAdmission) -> dict[str, bool]:
    return {
        "budget_retained": context.admitted
        and _contains_complete_fact(context.summary, "500 yuan"),
        "submission_prohibition_retained": context.admitted
        and _contains_complete_fact(
            context.summary,
            "Do not submit anything.",
        ),
    }


def build_kernel_probes() -> dict[str, Probe]:
    return {
        "numeric_answer_validation": numeric_validation_probe,
        "compound_retrieval_completion": compound_retrieval_probe,
        "intent_rewrite_reaches_kss": intent_rewrite_probe,
        "structured_fact_reaches_answer": structured_fact_probe,
        "long_conversation_constraints": conversation_constraints_probe,
    }
