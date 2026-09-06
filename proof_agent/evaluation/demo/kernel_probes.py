"""Fixed synthetic capability boundaries driving the existing Control Plane.

No network, environment files, production runs, or alternate execution loop.
The observations report behavior; they never assert that a known bug must persist.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Self

from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider
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
    RetrievalQueryItem,
    ValidationStatus,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.control.conversation import admit_conversation_context
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


class SyntheticDifyHttp:
    """Exercise the real Dify adapter with deterministic, secret-free wire responses."""

    def __init__(self, *, structured: bool = False) -> None:
        self.structured = structured
        self.queries: list[str] = []

    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None, body: bytes | None = None, timeout_seconds: float = 10.0) -> GuardedHttpResponse:
        assert body is not None
        query = json.loads(body)["query"]
        self.queries.append(query)
        content = FACT_B if query == QUERY_B else FACT_A
        if self.structured:
            content = (FIXTURES / "kernel_baseline/structured_record.json").read_text()
        payload = {"query": {"content": query}, "records": [{"score": 0.95, "segment": {
            "id": "segment_b" if query == QUERY_B else "segment_a", "document_id": "source-table-1" if self.structured else "policy",
            "enabled": True, "status": "completed", "content": content,
        }}]}
        return GuardedHttpResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode())


@dataclass(frozen=True)
class RetrievalObservation:
    queries: tuple[str, ...]
    answer_inputs: tuple[str, ...]
    admitted_evidence: tuple[EvidenceChunk, ...] = ()
    final_answer_sources: tuple[str, ...] = ()
    answer_requests: tuple[ModelRequest, ...] = ()

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
    service = SyntheticDifyHttp(structured=structured)
    manifest_path = FIXTURES / "react_enterprise_qa_v3/agent.yaml"
    binding = ExternalKnowledgeBinding(
        binding_id="baseline-dify", provider="dify", endpoint="https://dify.example/v1",
        dataset_id="c42e2a6e-40b3-4330-96f8-f1e4d768e8c9",
        content_format="structured_json" if structured else "text",
        credential_ref=ProductionSecretHandle(protocol_id="local-environment-v1",
            handle_id="BASELINE_DIFY_KEY", purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL, version_id="env"),
    )
    manifest = load_agent_manifest(manifest_path).model_copy(update={"knowledge_bindings": (binding,)})
    invocation = compose_harness_invocation(
        manifest_path, manifest=manifest, require_runtime_credentials=False,
        guarded_http_client=service,
        secret_provider=LocalEnvironmentSecretProvider({"BASELINE_DIFY_KEY": "synthetic-unused-key"}, mode="development"),
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
        queries=tuple(service.queries),
        answer_inputs=tuple(
            "\n".join(message.content for message in request.messages)
            for request in answer_provider.requests
        ),
        admitted_evidence=result.evidence,
        answer_requests=tuple(answer_provider.requests),
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
        "structured_amount_reaches_answer": observation.contains_admitted_fact("12345.67") and any(
            chunk.document_id == "source-table-1" and chunk.structured_data is not None
            and any(field.field == "claim_total" and field.value_type == "decimal" and field.value == "12345.67"
                    for field in chunk.structured_data.fields)
            for chunk in observation.admitted_evidence
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
