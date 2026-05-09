from proof_agent.compare.harness_rag import run_harness_rag
from proof_agent.compare.plain_rag import run_plain_rag


def test_plain_and_harness_diverge_on_unsupported_question() -> None:
    question = "What discount should we give this customer next year?"
    plain = run_plain_rag(question)
    harness = run_harness_rag(question)
    assert plain.outcome == "ANSWERED_LOOSELY"
    assert harness.outcome == "REFUSED_NO_EVIDENCE"
