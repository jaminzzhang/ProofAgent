"""Current offline probe for captured run evidence, not a remote-model replay.

Read the original sensitive capture in place; regenerate source IDs under the
current projection. Never reuse historical IDs with a new catalogue. Run from
repository root. Outputs contain only counts and validation status.
"""

import json
import sys
import re
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd()))
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ModelResponse,
    ControlledReActRunState,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    AnswerEvidenceContext,
    ReceiptOutcome,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
    FinalAnswerAttemptRunner,
)

capture = json.load(
    open("runs/dify-verification/config/validation_captures/vcap_e78f9d12a17a/capture.json")
)["payload"]["llm_interactions"]
p = json.loads(capture[5]["request_json"]["messages"][-1]["content"])
evidence = tuple(
    EvidenceChunk(**e, status=EvidenceStatus.ACCEPTED, admission_score=1.0)
    for e in p["accepted_evidence"]
)


class Offline:
    provider_name = "offline"
    model_name = "selection-probe"

    def __init__(self):
        self.requests = []

    def estimate_tokens(self, r):
        return sum(len(m.content) for m in r.messages) // 4

    def generate(self, r):
        self.requests.append(r)
        assert r.function_schema.name == "select_answer_statements"
        payload = json.loads(r.messages[-1].content)
        patterns = [
            "集团实现归属于母公司股东的营运利润",
            "寿险及健康险业务营运利润",
            "新业务价值155.74",
            "新业务价值率（按首年保费",
            "平安产险原保险保费收入",
            "整体综合成本率",
            "平安银行实现营业收入",
            "净息差1.79",
        ]
        chosen = []
        for pattern in patterns:
            for o in payload["source_statement_options"]:
                if pattern in re.sub(r"\s+", "", o["statement"]):
                    chosen.append(o["statement_id"])
                    break
        chosen = list(dict.fromkeys(chosen))
        print(
            "SELECTED",
            len(chosen),
            "OPTIONS",
            len(payload["source_statement_options"]),
            "REQUEST_CHARS",
            sum(len(m.content) for m in r.messages),
        )
        return ModelResponse(
            content=json.dumps({"statement_ids": chosen}),
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


provider = Offline()
events = []
trace = SimpleNamespace(emit=lambda event_type, **kwargs: events.append((event_type, kwargs)))
state = ControlledReActRunState(
    run_id="offline-optimized-1fbcbc32",
    template_name="react_enterprise_qa_v3",
    template_descriptor_version="react_enterprise_qa.v3",
    question=p["question"],
)
action = ReActActionProposal(
    action_id="answer",
    action_type=ReActActionType.GENERATE_FINAL_ANSWER,
    parameters={},
    risk_level="low",
    reasoning_summary=ReasoningSummary(
        goal=p["question"],
        observations=(),
        candidate_actions=(ReActActionType.GENERATE_FINAL_ANSWER,),
        selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
        rationale_summary="Offline captured evidence probe.",
        risk_flags=(),
        required_evidence=(),
    ),
)
result = FinalAnswerAttemptRunner(
    SimpleNamespace(model_provider=provider, policy=PolicyEngine(())), trace=trace
).run(state, action, AnswerEvidenceContext(run_id=state.run_id), evidence=evidence)
print(
    "OUTCOME",
    result.outcome,
    "CALLS",
    len(provider.requests),
    "UNIQUE_EVIDENCE",
    len(result.evidence),
)
print("DIAGNOSTICS", [d.error_code for d in result.stage_failure_diagnostics])
print("HISTORICAL_REPAIR_SELECTED", len(capture[5]["response_json"]["statement_ids"]), "LIMIT", 16)
print("HAS_WEAK_TABLE_FACTS", all(t in result.message for t in ["23.5", "28.3", "4.8"]))
assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
assert len(provider.requests) == 1
assert len(result.evidence) == 4
assert all(t in result.message for t in ["23.5", "28.3", "4.8", "未确认最新性"])
