from __future__ import annotations

from proof_agent.capabilities.knowledge.hybrid.evaluation_driver import (
    PrivateKnowledgeEvaluationDriver,
)
from proof_agent.evaluation.knowledge_shadow import ShadowQuestion


def test_private_driver_executes_shadow_against_exact_binding_reference() -> None:
    requests: list[tuple[str, object]] = []

    def post(path: str, payload: object) -> object:
        requests.append((path, payload))
        if path.endswith("/pointers"):
            return {
                "source_publication_id": "publication-7",
                "agent_version_id": "agent-version-4",
            }
        return {
            "case_id": "case-1",
            "binding_kind": "hybrid",
            "outcome": "answered",
            "evidence_identity_hashes": ["a" * 64],
            "citation_identity_hashes": ["b" * 64],
            "latency_ms": 25,
        }

    driver = PrivateKnowledgeEvaluationDriver(post=post)

    pointers = driver.snapshot_active_pointers()
    observation = driver.run_binding(
        binding_kind="hybrid",
        binding_ref="generation-8/profile-2",
        question=ShadowQuestion(case_id="case-1", question_ref="sha256:question"),
    )

    assert pointers.source_publication_id == "publication-7"
    assert observation.binding_kind == "hybrid"
    assert requests[1] == (
        "/v1/knowledge-evaluation/shadow/run",
        {
            "binding_kind": "hybrid",
            "binding_ref": "generation-8/profile-2",
            "case_id": "case-1",
            "question_ref": "sha256:question",
        },
    )
