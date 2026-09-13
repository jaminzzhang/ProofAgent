from types import SimpleNamespace

from proof_agent.contracts import ReActActionType
from proof_agent.control.workflow.controlled_react.composition import _context_summary


def test_pending_retrieval_preserves_progress_without_authorizing_answer():
    state = SimpleNamespace(
        effective_react_action_set=(ReActActionType.PLAN_RETRIEVAL, ReActActionType.REFUSE),
        observation_records=(SimpleNamespace(accepted_evidence_count=3, citation_refs=("source#1",)),),
        question="What is covered?",
    )
    summary = _context_summary(state)
    assert "accepted_evidence_count=3" in summary
    assert "next_action=plan_retrieval" in summary
    assert "required_retrieval_pending=true" in summary
    assert "generate_final_answer" not in summary
