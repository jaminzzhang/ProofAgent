"""Regression coverage for ISSUE-007 evidence projection identity."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from proof_agent.observability.storage import run_store as run_store_module
from proof_agent.observability.storage.run_store import RunStore


_MAX_JAVASCRIPT_SAFE_INTEGER = 9_007_199_254_740_991


def _events_for_summary(chunks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_type": "retrieval_result",
            "payload": {
                "sources": [str(chunk.get("source") or "") for chunk in chunks],
                "chunk_count": len(chunks),
            },
        },
        {
            "event_type": "evidence_evaluation",
            "payload": {"metadata": {"evidence": list(chunks)}},
        },
    ]


def _extract_summary(
    store: RunStore,
    chunks: Sequence[dict[str, Any]],
) -> list[Any]:
    return store._extract_evidence(_events_for_summary(chunks))  # noqa: SLF001


def test_evidence_summary_projects_typed_unique_javascript_safe_indexes(
    tmp_path: Any,
) -> None:
    store = RunStore(tmp_path / "history")
    projected = _extract_summary(
        store,
        [
            {
                "source": "policy://travel#meals",
                "citation": "travel-policy.md#meals:L10-L18",
                "score": 0.84,
                "status": "accepted",
            },
            {
                "source": "policy://travel#lodging",
                "citation": "travel-policy.md#lodging:L20-L28",
                "score": 0.79,
                "status": "rejected",
            },
        ],
    )

    assert all(type(chunk).__name__ == "DashboardEvidenceChunk" for chunk in projected)
    indexes = [chunk.index for chunk in projected]
    assert len(set(indexes)) == len(projected)
    assert all(0 <= index <= _MAX_JAVASCRIPT_SAFE_INTEGER for index in indexes)
    assert projected[0].citation == "travel-policy.md#meals:L10-L18"
    assert projected[0].admission_score == 0.84
    assert not hasattr(projected[0], "score")


def test_evidence_summary_indexes_are_stable_when_chunks_are_reordered(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "history")
    chunks = [
        {
            "source": "policy://travel#meals",
            "citation": "travel-policy.md#meals:L10-L18",
            "evidence_id": "evidence_meals",
            "source_id": "ks_travel",
            "binding_id": "binding_travel",
            "provider_native_score": 0.91,
            "fusion_rank": 1,
            "status": "accepted",
        },
        {
            "source": "policy://travel#lodging",
            "citation": "travel-policy.md#lodging:L20-L28",
            "evidence_id": "evidence_lodging",
            "source_id": "ks_travel",
            "binding_id": "binding_travel",
            "provider_native_score": 0.87,
            "fusion_rank": 2,
            "status": "accepted",
        },
    ]

    forward = _extract_summary(store, chunks)
    reversed_projection = _extract_summary(store, list(reversed(chunks)))

    assert {chunk.citation: chunk.index for chunk in forward} == {
        chunk.citation: chunk.index for chunk in reversed_projection
    }
    assert forward[0].evidence_id == "evidence_meals"
    assert forward[0].source_id == "ks_travel"
    assert forward[0].binding_id == "binding_travel"


def test_duplicate_evidence_gets_deterministic_unique_ordinals(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "history")
    duplicate = {
        "source": "policy://travel#meals",
        "citation": "travel-policy.md#meals:L10-L18",
        "status": "accepted",
    }
    unique = {
        "source": "policy://travel#lodging",
        "citation": "travel-policy.md#lodging:L20-L28",
        "status": "accepted",
    }

    forward = _extract_summary(store, [duplicate, unique, duplicate])
    reordered = _extract_summary(store, [duplicate, duplicate, unique])

    assert len({chunk.index for chunk in forward}) == 3
    assert sorted(chunk.index for chunk in forward) == sorted(chunk.index for chunk in reordered)


def test_digest_collision_resolution_is_unique_and_reorder_stable(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def colliding_digest(material: str) -> int:
        marker = "\x00collision:"
        if marker not in material:
            return 41
        return 41 + int(material.rsplit(marker, maxsplit=1)[1])

    monkeypatch.setattr(
        run_store_module,
        "_javascript_safe_evidence_index",
        colliding_digest,
    )
    store = RunStore(tmp_path / "history")
    chunks = [
        {"source": "alpha.md", "citation": "alpha.md#L1", "status": "accepted"},
        {"source": "beta.md", "citation": "beta.md#L2", "status": "accepted"},
        {"source": "gamma.md", "citation": "gamma.md#L3", "status": "rejected"},
    ]

    forward = _extract_summary(store, chunks)
    reordered = _extract_summary(store, list(reversed(chunks)))

    assert len({chunk.index for chunk in forward}) == len(chunks)
    assert {chunk.citation: chunk.index for chunk in forward} == {
        chunk.citation: chunk.index for chunk in reordered
    }


def test_retrieval_fallback_shape_uses_same_stable_typed_projection(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "history")
    events = [
        {
            "event_type": "retrieval_result",
            "payload": {
                "sources": ["policy://travel#meals", "policy://travel#lodging"],
                "chunk_count": 2,
            },
        },
        {
            "event_type": "evidence_evaluation",
            "payload": {
                "metadata": {
                    "admission_scores": [0.84, 0.73],
                    "accepted_count": 1,
                }
            },
        },
    ]

    projected = store._extract_evidence(events)  # noqa: SLF001

    assert all(type(chunk).__name__ == "DashboardEvidenceChunk" for chunk in projected)
    assert projected[0].source == "policy://travel#meals"
    assert projected[0].admission_score == 0.84
    assert projected[0].status == "accepted"
    assert projected[1].status == "rejected"
    assert projected[0].index != projected[1].index


def test_retrieval_fallback_indexes_are_stable_when_sources_are_reordered(
    tmp_path: Any,
) -> None:
    store = RunStore(tmp_path / "history")

    def fallback_events(sources: list[str], scores: list[float]) -> list[dict[str, Any]]:
        return [
            {
                "event_type": "retrieval_result",
                "payload": {"sources": sources, "chunk_count": len(sources)},
            },
            {
                "event_type": "evidence_evaluation",
                "payload": {
                    "metadata": {
                        "admission_scores": scores,
                        "accepted_count": len(sources),
                    }
                },
            },
        ]

    forward = store._extract_evidence(  # noqa: SLF001
        fallback_events(
            ["policy://travel#meals", "policy://travel#lodging"],
            [0.84, 0.73],
        )
    )
    reordered = store._extract_evidence(  # noqa: SLF001
        fallback_events(
            ["policy://travel#lodging", "policy://travel#meals"],
            [0.73, 0.84],
        )
    )

    assert {chunk.source: chunk.index for chunk in forward} == {
        chunk.source: chunk.index for chunk in reordered
    }
