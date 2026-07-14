from proof_agent.evaluation.knowledge_shadow import (
    ActiveKnowledgePointers,
    ShadowObservation,
    ShadowQuestion,
    run_shadow_comparison,
)


def test_shadow_run_never_changes_active_agent_or_source() -> None:
    pointers = ActiveKnowledgePointers(
        source_publication_id="publication-7",
        agent_version_id="agent-version-4",
    )

    def runner(kind: str):
        return lambda question: ShadowObservation(
            case_id=question.case_id,
            binding_kind=kind,
            outcome="answered",
            evidence_identity_hashes=("a" * 64,),
            citation_identity_hashes=("b" * 64,),
            latency_ms=10,
        )

    result = run_shadow_comparison(
        questions=(ShadowQuestion(case_id="case-1", question_ref="question-sha256:1"),),
        legacy_runner=runner("legacy"),
        hybrid_runner=runner("hybrid"),
        active_pointers=lambda: pointers,
    )

    assert result.active_pointers == pointers
    assert len(result.observations) == 2
    assert not hasattr(result.observations[0], "raw_rule_content")
