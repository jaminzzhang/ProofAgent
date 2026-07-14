from proof_agent.evaluation.knowledge_shadow import (
    ActiveKnowledgePointers,
    KnowledgeShadowSuite,
    ShadowObservation,
    ShadowQuestion,
    run_shadow_comparison,
    run_shadow_suite,
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


def test_shadow_suite_executes_pinned_bindings_through_live_driver() -> None:
    pointers = ActiveKnowledgePointers(
        source_publication_id="publication-7",
        agent_version_id="agent-version-4",
    )

    class Driver:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def snapshot_active_pointers(self) -> ActiveKnowledgePointers:
            return pointers

        def run_binding(
            self,
            *,
            binding_kind: str,
            binding_ref: str,
            question: ShadowQuestion,
        ) -> ShadowObservation:
            self.calls.append((binding_kind, binding_ref, question.question_ref))
            return ShadowObservation(
                case_id=question.case_id,
                binding_kind=binding_kind,
                outcome="answered",
                evidence_identity_hashes=("a" * 64,),
                citation_identity_hashes=("b" * 64,),
                latency_ms=10,
            )

    suite = KnowledgeShadowSuite(
        schema_version="insurance-knowledge-shadow.v2",
        questions=(ShadowQuestion(case_id="case-1", question_ref="sha256:question"),),
        legacy_binding_ref="legacy-publication-3",
        hybrid_binding_ref="hybrid-generation-8/profile-2",
    )
    driver = Driver()

    result = run_shadow_suite(suite, driver)

    assert result.active_pointers == pointers
    assert driver.calls == [
        ("legacy", "legacy-publication-3", "sha256:question"),
        ("hybrid", "hybrid-generation-8/profile-2", "sha256:question"),
    ]
