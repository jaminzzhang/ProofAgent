from __future__ import annotations

import json

import httpx

from knowledge_source_service.adapters.http.agentic_controller import (
    HttpAgenticRetrievalController,
)
from knowledge_source_service.ports.agentic import AgenticRetrievalObservation


def test_http_agentic_controller_exposes_only_bounded_content_free_observation() -> None:
    observed: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer controller-secret-token"
        assert request.extensions["timeout"]["read"] <= 0.75
        payload = json.loads(request.content)
        observed.append(payload)
        return httpx.Response(
            200,
            json={
                "schema_version": "agentic-retrieval-decision.v1",
                "action": "continue",
                "revised_question": "flight delay compensation waiting period",
                "model_tokens_used": 23,
            },
        )

    controller = HttpAgenticRetrievalController(
        endpoint="https://controller.invalid/v1/retrieval-decisions",
        bearer_token="controller-secret-token",
        transport=httpx.MockTransport(respond),
    )
    decision = controller.decide(
        AgenticRetrievalObservation(
            retrieval_round=1,
            question="flight delay",
            knowledge_base_release_id="release-exact",
            access_scope_digest=f"sha256:{'a' * 64}",
            candidate_count=1,
            candidate_evidence_ids=("candidate-opaque",),
            remaining_rounds=2,
            remaining_model_calls=2,
            remaining_model_tokens=100,
            remaining_duration_ms=750,
        )
    )
    controller.close()

    assert decision.action == "continue"
    assert decision.model_tokens_used == 23
    assert observed == [
        {
            "schema_version": "agentic-retrieval-observation.v1",
            "retrieval_round": 1,
            "question": "flight delay",
            "knowledge_base_release_id": "release-exact",
            "access_scope_digest": f"sha256:{'a' * 64}",
            "candidate_count": 1,
            "candidate_evidence_ids": ["candidate-opaque"],
            "remaining_rounds": 2,
            "remaining_model_calls": 2,
            "remaining_model_tokens": 100,
            "remaining_duration_ms": 750,
        }
    ]
