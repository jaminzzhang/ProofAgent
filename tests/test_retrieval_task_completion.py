import pytest

from proof_agent.contracts import (
    EnforcementPoint,
    EffectiveToolProposalScope,
    PolicyDecision,
    PolicyDecisionType,
    ReviewDecision,
    ToolObservationTruth,
    ToolProposalInterface,
    EvidenceChunk,
    EvidenceStatus,
    IntentResolution,
    IntentResolutionResult,
    ObservationRecord,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalObservationTruth,
    RetrievalQueryItem,
)
from proof_agent.control.workflow.controlled_react import (
    AnswerSynthesisResult,
    ControlledReActOrchestrator,
    ControlledReActPorts,
    ControlledReActStartRequest,
    ControlledReActResumeRequest,
    ObservationEffect,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
    FileObservationTruthStore,
)
from proof_agent.control.workflow.controlled_react.task_completion import (
    assess_retrieval_completion,
    completion_projection,
    required_retrievals,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import bind_observation_truth
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.demo.kernel_probes import (
    FACT_A,
    FACT_B,
    QUERY_A,
    QUERY_B,
    exercise_retrieval,
)


def test_compound_required_queries_reach_final_answer_through_real_composition() -> None:
    observation = exercise_retrieval(question="Compare both policies.", queries=(QUERY_A, QUERY_B))
    assert observation.queries == (QUERY_A, QUERY_B)
    assert observation.contains_admitted_fact(FACT_A)
    assert observation.contains_admitted_fact(FACT_B)


def test_real_model_proposing_only_final_still_executes_required_queries():
    observation = exercise_retrieval(
        question="Compare both policies.", queries=(), intent_queries=(QUERY_A, QUERY_B)
    )
    assert observation.queries == (QUERY_A, QUERY_B)
    assert observation.contains_admitted_fact(FACT_A) and observation.contains_admitted_fact(FACT_B)


def _action(query=None, *, action_type=None):
    kind = action_type or (
        ReActActionType.PLAN_RETRIEVAL
        if query is not None
        else ReActActionType.GENERATE_FINAL_ANSWER
    )
    return ReActActionProposal(
        action_id="synthetic_action",
        action_type=kind,
        reasoning_summary=ReasoningSummary(
            goal="Complete the request.",
            observations=(),
            candidate_actions=(kind,),
            selected_action=kind,
            rationale_summary="Synthetic proposal.",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters={"query": query} if query is not None else {},
        risk_level="medium",
    )


class _Planner:
    def __init__(self, proposals=(None,)):
        self.proposals = proposals
        self.states = []

    def plan(self, state):
        index = min(len(self.states), len(self.proposals) - 1)
        self.states.append(state)
        return _action(self.proposals[index])


class _Intent:
    def __init__(self, queries=((QUERY_A, True), (QUERY_B, True))):
        self.queries = queries
        self.calls = 0

    def resolve(self, state):
        self.calls += 1
        return IntentResolutionResult(
            intent_resolution=IntentResolution(
                resolution_id="synthetic_intent",
                user_goal=state.question,
                domain_intent="policy_question",
                known_facts=(),
                missing_fields=(),
                ambiguities=(),
                risk_flags=(),
                confidence=1,
                recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
                retrieval_query_set=tuple(
                    RetrievalQueryItem(
                        query=query,
                        required=required,
                        intent_angle="policy",
                        reason="Required by the synthetic task.",
                    )
                    for query, required in self.queries
                ),
            )
        )


class _Knowledge:
    def __init__(self, modes=None):
        self.modes = modes or {}
        self.queries = []
        self.evidence_by_query = {}

    def observe(self, state, action, identity):
        query = action.parameters["query"]
        self.queries.append(query)
        mode = self.modes.get(query, "accepted")
        source = "synthetic://policy/" + ("a" if query == QUERY_A else "b")
        citation = source + "#L1"
        if mode == "blank_source":
            source = " "
        if mode == "blank_citation":
            citation = " "
        chunks = (
            ()
            if mode in {"empty", "spoof_count"}
            else (
                EvidenceChunk(
                    source=source,
                    citation=None if mode == "no_citation" else citation,
                    content=FACT_A if query == QUERY_A else FACT_B,
                    status=EvidenceStatus(mode)
                    if mode in {"candidate", "rejected"}
                    else EvidenceStatus.ACCEPTED,
                ),
            )
        )
        if query in self.evidence_by_query:
            chunks = (self.evidence_by_query[query],)
            source, citation = chunks[0].source, chunks[0].citation
        truth = RetrievalObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=chunks,
            citation_refs=(citation,) if chunks and mode != "no_citation" else (),
            admission_metadata={
                "query": "Unrelated query" if mode == "mismatched_query" else query
            },
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            accepted_evidence_count=99 if mode == "spoof_count" else len(chunks),
            new_evidence_count=len(chunks),
            source_refs=(source,) if chunks and mode != "no_source" else (),
            citation_refs=truth.citation_refs,
            unresolved_subgoals=("variant_conflict",) if mode == "unresolved" else (),
        )
        return ObservationEffect(observation_record=record, truth_artifact=truth)


class _Answer:
    def __init__(self):
        self.contexts = []

    def synthesize(self, state, action, answer_context):
        self.contexts.append(answer_context)
        evidence = tuple(
            chunk
            for truth in answer_context.observation_truth
            if isinstance(truth, RetrievalObservationTruth)
            for chunk in truth.accepted_evidence
        )
        message = " ".join(chunk.content for chunk in evidence)
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output=message,
            message=message,
            evidence=evidence,
        )


class _Trace:
    def __init__(self):
        self.events = []

    def emit(self, event_type, *, status="ok", payload=None):
        self.events.append({"event_type": event_type, "status": status, "payload": payload or {}})


def _harness(*, proposals=(None,), queries=((QUERY_A, True), (QUERY_B, True)), modes=None, **ports):
    planner, knowledge, answer, trace = _Planner(proposals), _Knowledge(modes), _Answer(), _Trace()
    trace = ports.pop("trace", trace)
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=planner,
            knowledge_observation=knowledge,
            answer_synthesis=ports.pop("answer_synthesis", answer),
            trace=trace,
            intent_resolution=ports.pop("intent_resolution", _Intent(queries)),
            **ports,
        )
    )
    return orchestrator, knowledge, answer, trace, planner


def _start(orchestrator, *, budget=4):
    return orchestrator.start(
        ControlledReActStartRequest(
            run_id="task_run",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Compare both policies.",
            max_plan_rounds=budget,
        )
    )


def test_premature_final_is_redirected_to_required_queries():
    orchestrator, knowledge, answer, _, _ = _harness()
    result = _start(orchestrator)
    assert knowledge.queries == [QUERY_A, QUERY_B]
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(answer.contexts) == 1
    assert FACT_A in result.final_output and FACT_B in result.final_output


def test_two_sided_performance_search_continues_after_required_queries():
    question = "甲公司业绩有哪些亮点，哪些业务比较好，哪些业务比较差？"
    followup = "甲公司各业务下降指标"
    orchestrator, knowledge, answer, trace, _ = _harness(
        queries=((QUERY_A, True), (QUERY_B, True), (followup, False)),
    )
    for query in (QUERY_A, QUERY_B):
        knowledge.evidence_by_query[query] = EvidenceChunk(
            source="synthetic://same", citation="synthetic://same#L1", status=EvidenceStatus.ACCEPTED,
            content="2026 年第一季度，甲公司营业收入 120 亿元，同比增长 20%。",
        )
    knowledge.evidence_by_query[followup] = EvidenceChunk(
        source="synthetic://pressures", citation="synthetic://pressures#L1", status=EvidenceStatus.ACCEPTED,
        content="2026 年第一季度，甲公司寿险新业务价值率 23.5%，同比下降 4.8 个百分点。",
    )
    result = orchestrator.start(ControlledReActStartRequest(
        run_id="two_sided", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=question, max_plan_rounds=4,
    ))
    assert knowledge.queries == [QUERY_A, QUERY_B, followup]
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(answer.contexts) == 1
    projections = [e["payload"] for e in trace.events if e["event_type"] == "task_completion_evaluated"]
    assert any(p["completed_count"] == 2 and p["status"] == "incomplete" for p in projections)
    assert any("pressures" in p.get("missing_answer_requirements", []) for p in projections)


def test_two_sided_coverage_gap_cannot_bypass_retrieval_budget():
    orchestrator, knowledge, answer, _, _ = _harness(queries=((QUERY_A, True),))
    knowledge.evidence_by_query[QUERY_A] = EvidenceChunk(
        source="synthetic://same", citation="synthetic://same#L1", status=EvidenceStatus.ACCEPTED,
        content="2026 年第一季度，甲公司营业收入 120 亿元，同比增长 20%。",
    )
    result = orchestrator.start(ControlledReActStartRequest(
        run_id="bounded_two_sided", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="甲公司业绩有哪些亮点，哪些业务比较差？", max_plan_rounds=1,
    ))
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert knowledge.queries == [QUERY_A]
    assert not answer.contexts


@pytest.mark.parametrize(
    "budget,queries,outcome",
    [
        (0, [], ReceiptOutcome.REFUSED_NO_EVIDENCE),
        (1, [QUERY_A], ReceiptOutcome.REFUSED_NO_EVIDENCE),
        (2, [QUERY_A, QUERY_B], ReceiptOutcome.ANSWERED_WITH_CITATIONS),
    ],
)
def test_completion_and_budget_boundaries(budget, queries, outcome):
    orchestrator, knowledge, answer, trace, _ = _harness()
    result = _start(orchestrator, budget=budget)
    assert knowledge.queries == queries
    assert result.outcome is outcome
    assert len(answer.contexts) == int(outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    projection = next(
        s.summary["task_completion"] for s in reversed(result.stage_results) if s.stage_id == "plan"
    )
    assert projection["required_count"] == 2
    assert projection["completed_count"] == len(queries)
    assert projection["reason"] == (
        "requirements_satisfied" if len(queries) == 2 else "plan_budget_exhausted"
    )
    events = [e for e in trace.events if e["event_type"] == "task_completion_evaluated"]
    assert events and events[-1]["payload"]["completed_count"] == len(queries)
    assert QUERY_A not in str(projection) and QUERY_B not in str(projection)


def test_duplicate_planner_query_cannot_starve_other_required_query():
    orchestrator, knowledge, answer, _, _ = _harness(proposals=(QUERY_A,))
    result = _start(orchestrator)
    assert knowledge.queries == [QUERY_A, QUERY_B]
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(answer.contexts) == 1


def test_optional_and_duplicate_requirements_do_not_add_observations():
    orchestrator, knowledge, _, _, _ = _harness(
        queries=(
            (QUERY_A, True),
            (" " + QUERY_A + " ", True),
            (QUERY_B, False),
        )
    )
    result = _start(orchestrator)
    assert knowledge.queries == [QUERY_A]
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS


def test_empty_required_result_does_not_hide_other_work_or_produce_partial_answer():
    orchestrator, knowledge, answer, _, _ = _harness(modes={QUERY_A: "empty"})
    result = _start(orchestrator)
    assert knowledge.queries == [QUERY_A, QUERY_B]
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert not answer.contexts
    assert "1 required retrieval requirement" in result.message
    projection = next(
        s.summary["task_completion"] for s in reversed(result.stage_results) if s.stage_id == "plan"
    )
    assert projection["reason"] == "requirements_unsatisfied"
    assert projection["completed_count"] == 1


@pytest.mark.parametrize(
    "mode",
    [
        "candidate",
        "rejected",
        "no_citation",
        "no_source",
        "spoof_count",
        "mismatched_query",
        "blank_source",
        "blank_citation",
    ],
)
def test_unverified_observation_does_not_satisfy_requirement(mode):
    orchestrator, knowledge, answer, _, _ = _harness(
        queries=((QUERY_A, True),), modes={QUERY_A: mode}
    )
    result = _start(orchestrator)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert not answer.contexts
    assert knowledge.queries == [QUERY_A]
    projection = next(
        s.summary["task_completion"] for s in reversed(result.stage_results) if s.stage_id == "plan"
    )
    assert projection["completed_count"] == 0


def test_frozen_intent_cannot_be_mutated_by_planner():
    orchestrator, _, _, _, planner = _harness()
    _start(orchestrator)
    state = planner.states[0]
    with pytest.raises(TypeError):
        state.intent_resolution["retrieval_query_set"] = ()
    with pytest.raises(TypeError):
        state.intent_resolution["retrieval_query_set"][0]["required"] = False


def test_required_evidence_does_not_override_existing_unresolved_subgoal():
    orchestrator, _, answer, _, planner = _harness(
        queries=((QUERY_A, True),), modes={QUERY_A: "unresolved"}
    )

    def plan(state):
        planner.states.append(state)
        if state.observation_records:
            return _action(action_type=ReActActionType.ASK_CLARIFICATION).model_copy(
                update={"parameters": {"missing_fields": ("policy_variant",)}}
            )
        return _action(QUERY_A)

    planner.plan = plan
    result = _start(orchestrator)
    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert not answer.contexts


@pytest.mark.parametrize(
    "kind,outcome",
    [
        (ReActActionType.REFUSE, ReceiptOutcome.REFUSED_NO_EVIDENCE),
        (ReActActionType.ASK_CLARIFICATION, ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION),
    ],
)
@pytest.mark.parametrize("budget", [1, 4])
def test_completed_retrieval_preserves_explicit_terminal_decisions(kind, outcome, budget):
    orchestrator, _, answer, _, planner = _harness(queries=((QUERY_A, True),))

    def plan(state):
        if not state.observation_records:
            return _action(QUERY_A)
        return _action(action_type=kind).model_copy(
            update={
                "parameters": {
                    "refusal_reason": "business_flow_admission_failed",
                    "missing_fields": ("policy_variant",),
                }
            }
        )

    planner.plan = plan
    result = _start(orchestrator, budget=budget)
    assert result.outcome is outcome
    assert not answer.contexts
    projection = next(
        s.summary["task_completion"] for s in reversed(result.stage_results) if s.stage_id == "plan"
    )
    assert projection["status"] == "complete"
    if kind is ReActActionType.REFUSE:
        assert "Business Flow Skill Pack route was not admitted" in result.message
        assert projection["reason"] == "business_flow_admission_failed"


def test_incomplete_budget_preserves_explicit_admission_refusal():
    orchestrator, knowledge, answer, _, planner = _harness()
    planner.plan = lambda state: _action(action_type=ReActActionType.REFUSE).model_copy(
        update={"parameters": {"refusal_reason": "business_flow_admission_failed"}}
    )
    result = _start(orchestrator, budget=0)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert not knowledge.queries and not answer.contexts
    assert "Business Flow Skill Pack route was not admitted" in result.message


def test_three_equal_count_observations_do_not_trigger_saturation():
    queries = (QUERY_A, QUERY_B, "Gamma policy coverage")
    orchestrator, knowledge, answer, _, _ = _harness(queries=tuple((q, True) for q in queries))
    result = _start(orchestrator, budget=3)
    assert knowledge.queries == list(queries)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(answer.contexts[0].observation_truth) == 3


@pytest.mark.parametrize("queries", [(), ((QUERY_A, False),)])
def test_no_required_queries_remain_not_applicable(queries):
    orchestrator, knowledge, _, trace, _ = _harness(queries=queries)
    result = _start(orchestrator)
    assert not knowledge.queries
    assert _projection(result)["status"] == "not_applicable"
    assert not [e for e in trace.events if e["event_type"] == "task_completion_evaluated"]


@pytest.mark.parametrize("intent", [None, {}, {"retrieval_query_set": ()}])
def test_missing_required_set_is_not_implicit_completion(intent):
    assert required_retrievals(intent) == ()
    assert completion_projection(None)["status"] == "not_applicable"


@pytest.mark.parametrize(
    "items",
    [
        None,
        "bad",
        ({"query": QUERY_A, "required": "true"},),
        ({"query": " ", "required": True},),
        ({"query": QUERY_A},),
        tuple({"query": str(i), "required": True} for i in range(6)),
    ],
)
def test_invalid_required_set_fails_closed(items):
    with pytest.raises(ProofAgentError, match="Required retrieval specification is invalid"):
        required_retrievals({"retrieval_query_set": items})


def test_query_identity_does_not_merge_case_or_punctuation():
    requirements = required_retrievals(
        {
            "retrieval_query_set": [
                {"query": query, "required": True} for query in ("A", " A ", "a", "A.")
            ]
        }
    )
    assert tuple(r.query for r in requirements) == ("A", "a", "A.")
    assert len({r.requirement_id for r in requirements}) == 3


def _projection(result):
    return next(
        s.summary["task_completion"] for s in reversed(result.stage_results) if s.stage_id == "plan"
    )


class _DenyReview:
    def __init__(self):
        self.actions = []

    def review(self, state, action):
        self.actions.append(action)
        return ReviewDecision(
            review_id="synthetic_review",
            subject_action_id=action.action_id,
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            suggested_decision=PolicyDecisionType.DENY,
            reason="Synthetic denial.",
            confidence=1,
            risk_flags=(),
        )


def test_redirect_preserves_risk_and_passes_review_without_tool_parameters():
    review = _DenyReview()
    orchestrator, knowledge, answer, _, planner = _harness(review=review)
    original = _action().model_copy(
        update={
            "risk_level": "high",
            "target_tool_name": "synthetic_lookup",
            "parameters": {"private_argument": "synthetic-only"},
            "reasoning_summary": _action().reasoning_summary.model_copy(
                update={"risk_flags": ("sensitive_scope",)}
            ),
        }
    )
    planner.plan = lambda state: original
    result = _start(orchestrator)
    assert not knowledge.queries and not answer.contexts
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert _projection(result)["reason"] == "review_denied"
    redirected = review.actions[0]
    assert redirected.action_type is ReActActionType.PLAN_RETRIEVAL
    assert redirected.risk_level == "high" and redirected.reasoning_summary.risk_flags == (
        "sensitive_scope",
    )
    assert redirected.parameters == {"query": QUERY_A} and redirected.target_tool_name is None


class _Tool:
    def __init__(self):
        self.calls = 0

    def observe(self, state, action, identity):
        self.calls += 1
        truth = ToolObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            tool_name="synthetic_lookup",
            result_schema_id="synthetic.v1",
            authorized_result={
                "success": True,
                "all_requirements_complete": True,
                "query": QUERY_B,
            },
        )
        return ObservationEffect(
            truth_artifact=truth,
            observation_record=ObservationRecord(
                observation_id=identity.observation_id,
                action_id=action.action_id,
                action_type=action.action_type,
                round=state.plan_round,
                truth_ref=identity.truth_ref,
                accepted_evidence_count=99,
                source_refs=("tool://synthetic_lookup",),
                summary={"task_complete": True},
            ),
        )


class _ToolPolicy:
    def __init__(self, decision=PolicyDecisionType.REQUIRE_APPROVAL):
        self.decision = decision

    def evaluate(self, state, action):
        return PolicyDecision(
            decision=self.decision,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            reason="Synthetic tool policy.",
            policy_rule_id="synthetic.tool",
            trace_event_id="synthetic_trace",
        )


def _tool_after_first_query(state):
    if not state.observation_records:
        return _action(QUERY_A)
    if len(state.observation_records) == 1:
        return _action(action_type=ReActActionType.PROPOSE_TOOL_CALL).model_copy(
            update={
                "action_id": "synthetic_tool",
                "target_tool_name": "synthetic_lookup",
            }
        )
    return _action()


def test_successful_tool_result_cannot_complete_required_retrieval():
    tool = _Tool()
    orchestrator, knowledge, answer, trace, planner = _harness(
        tool_observation=tool, policy=_ToolPolicy(PolicyDecisionType.ALLOW)
    )
    planner.plan = _tool_after_first_query
    result = _start(orchestrator, budget=3)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert tool.calls == 1 and knowledge.queries == [QUERY_A, QUERY_B]
    assert len(answer.contexts[0].observation_truth) == 3
    progress = [
        e["payload"]["completed_count"]
        for e in trace.events
        if e["event_type"] == "task_completion_evaluated"
    ]
    assert progress == [0, 1, 1, 2]


def test_tool_policy_denial_still_prevents_execution():
    tool = _Tool()
    orchestrator, knowledge, answer, _, planner = _harness(
        tool_observation=tool, policy=_ToolPolicy(PolicyDecisionType.DENY)
    )
    planner.plan = _tool_after_first_query
    result = _start(orchestrator)
    assert result.outcome is ReceiptOutcome.TOOL_APPROVAL_DENIED
    assert tool.calls == 0 and not answer.contexts and knowledge.queries == [QUERY_A]
    assert _projection(result)["status"] == "incomplete"
    assert _projection(result)["reason"] == "policy_denied"


def _pause_with_partial_retrieval(tmp_path, *, typed=False):
    intent, tool = _Intent(), _Tool()
    snapshots = FileControlledReActSnapshotStore(tmp_path)
    truths = FileObservationTruthStore(tmp_path)
    orchestrator, knowledge, answer, _, planner = _harness(
        intent_resolution=intent,
        tool_observation=tool,
        policy=_ToolPolicy(),
        snapshot_store=snapshots,
        observation_truth_store=truths,
    )
    planner.plan = _tool_after_first_query
    if typed:
        import json
        from hashlib import sha256
        from proof_agent.contracts.structured_evidence import parse_structured_evidence
        content = json.dumps({
            "schema_version": "proofagent-structured-evidence.v1", "record_id": "alpha",
            "fields": [{"field": "summary", "value_type": "string", "value": FACT_A},
                       {"field": "limit", "value_type": "decimal", "value": "100.00", "unit": "CNY"}],
        })
        digest = sha256(content.encode()).hexdigest()
        source = "external://policies/datasets/policy-dataset/documents/alpha"
        knowledge.evidence_by_query[QUERY_A] = EvidenceChunk(
            source=source, citation=f"{source}#segment=s1&sha256={digest}",
            content=content, status=EvidenceStatus.ACCEPTED, admission_score=1.0,
            binding_id="policies", source_id="policy-dataset", document_id="alpha", chunk_id="s1",
            source_version_id=f"sha256:{digest}", structured_data=parse_structured_evidence(content),
        )
    result = _start(orchestrator, budget=3)
    assert result.outcome is ReceiptOutcome.WAITING_FOR_APPROVAL
    assert result.approval_pause and knowledge.queries == [QUERY_A]
    return result.approval_pause, intent, tool, answer, snapshots, truths


@pytest.mark.parametrize("typed", [False, True])
def test_file_snapshot_resume_preserves_original_requirements_and_truth(tmp_path, typed):
    pause, intent, tool, _, snapshots, _ = _pause_with_partial_retrieval(tmp_path, typed=typed)
    snapshot = snapshots.load(pause.checkpoint_ref)
    first_ref = snapshot.state.observation_records[0].truth_ref
    # A fresh orchestrator and file adapters model restart, not an in-memory resume.
    orchestrator, knowledge, answer, _, _ = _harness(
        intent_resolution=intent,
        tool_observation=tool,
        snapshot_store=FileControlledReActSnapshotStore(tmp_path),
        observation_truth_store=FileObservationTruthStore(tmp_path),
    )
    result = orchestrator.resume(
        ControlledReActResumeRequest(
            snapshot_ref=pause.checkpoint_ref,
            approval_id=pause.approval_id,
            approved=True,
            actor="synthetic_operator",
            max_plan_rounds=3,
        )
    )
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert intent.calls == 1 and tool.calls == 1 and knowledge.queries == [QUERY_B]
    assert FACT_A in result.final_output and FACT_B in result.final_output
    assert first_ref in _projection(result)["proofs"][0]["truth_refs"]
    assert answer.contexts[0].observation_truth[0].truth_ref == first_ref
    assert "task_completion" not in snapshot.state.model_dump(warnings=False)
    if typed:
        chunk = answer.contexts[0].observation_truth[0].accepted_evidence[0]
        assert chunk.structured_data.fields[1].value == "100.00"
        assert chunk.structured_data.fields[1].value_type == "decimal"
        assert chunk.structured_data.fields[1].unit == "CNY"


@pytest.mark.parametrize("corruption", ["missing", "replaced"])
def test_resume_rejects_missing_or_replaced_required_truth(tmp_path, corruption):
    import json

    pause, intent, tool, _, _, _ = _pause_with_partial_retrieval(tmp_path)
    truth_path = next(tmp_path.glob("task_run/controlled_react/observation_truth/*.json"))
    if corruption == "missing":
        truth_path.unlink()
    else:
        payload = json.loads(truth_path.read_text())
        payload["admission_metadata"]["query"] = QUERY_B
        truth_path.write_text(json.dumps(payload))
    orchestrator, knowledge, answer, _, _ = _harness(
        intent_resolution=intent,
        tool_observation=tool,
        snapshot_store=FileControlledReActSnapshotStore(tmp_path),
        observation_truth_store=FileObservationTruthStore(tmp_path),
    )
    with pytest.raises(ProofAgentError):
        orchestrator.resume(
            ControlledReActResumeRequest(
                snapshot_ref=pause.checkpoint_ref,
                approval_id=pause.approval_id,
                approved=True,
                actor="synthetic_operator",
                max_plan_rounds=3,
            )
        )
    assert not answer.contexts and not knowledge.queries and intent.calls == 1
    assert tool.calls == 0


@pytest.mark.parametrize(
    "corruption", ["cross_run", "unbound", "content", "action_id", "record_ref"]
)
def test_requirement_proof_rejects_invalid_binding_or_identity(corruption):
    truth = RetrievalObservationTruth(
        truth_ref="observation://task_run/obs_1/truth",
        observation_id="obs_1",
        action_id="action_1",
        accepted_evidence=(
            EvidenceChunk(
                source="synthetic://a",
                citation="a#L1",
                status=EvidenceStatus.ACCEPTED,
                content=FACT_A,
            ),
        ),
        citation_refs=("a#L1",),
        admission_metadata={"query": QUERY_A},
    )
    if corruption == "cross_run":
        truth = truth.model_copy(update={"truth_ref": "observation://other_run/obs_1/truth"})
    if corruption != "unbound":
        truth = bind_observation_truth(truth).truth
    record = ObservationRecord(
        observation_id="obs_1",
        action_id="action_1",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        round=1,
        truth_ref=truth.truth_ref,
        source_refs=("synthetic://a",),
        citation_refs=("a#L1",),
    )
    if corruption == "content":
        truth = truth.model_copy(update={"admission_metadata": {"query": QUERY_B}})
    if corruption == "action_id":
        record = record.model_copy(update={"action_id": "other_action"})
    if corruption == "record_ref":
        record = record.model_copy(update={"truth_ref": "observation://task_run/other_obs"})
    with pytest.raises(ProofAgentError):
        assess_retrieval_completion(
            run_id="task_run",
            requirements=required_retrievals(
                {
                    "retrieval_query_set": ({"query": QUERY_A, "required": True},),
                }
            ),
            records=(record,),
            truths=(truth,),
        )


def test_unknown_refusal_reason_is_not_copied_into_completion_audit():
    orchestrator, _, _, trace, planner = _harness()
    planner.plan = lambda state: _action(action_type=ReActActionType.REFUSE).model_copy(
        update={
            "parameters": {"refusal_reason": "private synthetic payload"},
        }
    )
    result = _start(orchestrator)
    assert _projection(result)["reason"] == "planner_refused"
    assert "private synthetic payload" not in str(_projection(result))
    assert "private synthetic payload" not in str(
        [e for e in trace.events if e["event_type"] == "task_completion_evaluated"]
    )


def test_earlier_unresolved_observation_is_not_cleared_by_another_query():
    orchestrator, knowledge, answer, _, _ = _harness(modes={QUERY_A: "unresolved"})
    result = _start(orchestrator)
    assert knowledge.queries == [QUERY_A, QUERY_B]
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE and not answer.contexts
    assert _projection(result)["reason"] == "unresolved_subgoals"


def test_completion_events_survive_real_trace_writer_without_raw_content(tmp_path):
    import json
    from proof_agent.observability.audit.trace import TraceWriter

    trace_path = tmp_path / "trace.jsonl"
    orchestrator, _, _, _, _ = _harness(trace=TraceWriter(trace_path, run_id="task_run"))
    result = _start(orchestrator)
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    completion_events = [e for e in events if e["event_type"] == "task_completion_evaluated"]
    assert [e["payload"]["completed_count"] for e in completion_events] == [0, 1, 2]
    assert completion_events[-1]["payload"]["proofs"][0]["truth_refs"] == list(
        _projection(result)["proofs"][0]["truth_refs"]
    )
    assert not any(value in str(completion_events) for value in (QUERY_A, QUERY_B, FACT_A, FACT_B))


def test_approval_denial_allows_governed_alternative_retrieval(tmp_path):
    pause, intent, tool, _, _, _ = _pause_with_partial_retrieval(tmp_path)
    orchestrator, knowledge, answer, _, _ = _harness(
        intent_resolution=intent,
        tool_observation=tool,
        snapshot_store=FileControlledReActSnapshotStore(tmp_path),
        observation_truth_store=FileObservationTruthStore(tmp_path),
    )
    result = orchestrator.resume(
        ControlledReActResumeRequest(
            snapshot_ref=pause.checkpoint_ref,
            approval_id=pause.approval_id,
            approved=False,
            actor="synthetic_operator",
            max_plan_rounds=3,
        )
    )
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert tool.calls == 0 and knowledge.queries == [QUERY_B] and len(answer.contexts) == 1
    assert _projection(result)["completed_count"] == 2
    denied_truth = answer.contexts[0].observation_truth[1]
    assert denied_truth.authorized_result["approval_state"] == "denied"


@pytest.mark.parametrize(
    "kind,parameters",
    [
        (ReActActionType.PLAN_RETRIEVAL, {"query": {"query": QUERY_B}}),
        (ReActActionType.REFUSE, {"refusal_reason": {"private": "synthetic"}}),
    ],
)
def test_untyped_proposal_parameters_do_not_break_gate(kind, parameters):
    orchestrator, knowledge, _, _, planner = _harness()
    planner.plan = lambda state: _action(action_type=kind).model_copy(
        update={"parameters": parameters}
    )
    result = _start(orchestrator)
    if kind is ReActActionType.REFUSE:
        assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
        assert _projection(result)["reason"] == "planner_refused" and not knowledge.queries
    else:
        assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
        assert knowledge.queries == [QUERY_A, QUERY_B]


def test_tool_scope_denial_has_completion_projection_without_execution():
    class Scope:
        def resolve(self, state):
            return EffectiveToolProposalScope(
                run_id=state.run_id,
                plan_round=state.plan_round,
                schema_digest="sha256:synthetic",
                tool_interfaces=(
                    ToolProposalInterface(
                        tool_contract_id="other_lookup",
                        purpose="Another synthetic lookup.",
                        risk_level="low",
                        read_only=True,
                        requires_approval=False,
                    ),
                ),
            )

    tool = _Tool()
    orchestrator, knowledge, answer, _, planner = _harness(
        tool_observation=tool,
        tool_proposal_scope=Scope(),
        policy=_ToolPolicy(PolicyDecisionType.ALLOW),
    )
    planner.plan = _tool_after_first_query
    result = _start(orchestrator)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert tool.calls == 0 and not answer.contexts and knowledge.queries == [QUERY_A]
    assert _projection(result)["reason"] == "tool_scope_denied"
    assert _projection(result)["completed_count"] == 1
