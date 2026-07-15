from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from proof_agent.bootstrap.production_hybrid_publication import (
    ProductionHybridKnowledgePublicationFacade,
)
from proof_agent.capabilities.knowledge.hybrid.publication import PublicationConflict


@dataclass(frozen=True)
class _Candidate:
    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    generation: Any
    validation_id: str
    published_by: str


class _Assembler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str | None]] = []

    def build(
        self,
        *,
        source_id: str,
        validation_id: str,
        actor: str,
        smoke_query: str | None = None,
    ) -> _Candidate:
        self.calls.append((source_id, validation_id, actor, smoke_query))
        return _Candidate(
            source_id=source_id,
            source_draft_version_id="draft-1",
            candidate_digest="a" * 64,
            generation=SimpleNamespace(generation_id="generation-1"),
            validation_id=validation_id,
            published_by=actor,
        )


class _Repository:
    def __init__(self) -> None:
        self.staged: list[dict[str, Any]] = []
        self.validations: list[Any] = []
        self.profiles: list[dict[str, Any]] = []

    def stage_source_candidate(self, **kwargs: Any) -> None:
        self.staged.append(kwargs)

    def publish_retrieval_profile(self, **kwargs: Any) -> None:
        self.profiles.append(kwargs)

    def register_validation(self, validation: Any) -> None:
        self.validations.append(validation)

    def list_publication_validations(self, source_id: str) -> tuple[Any, ...]:
        return tuple(item for item in self.validations if item.source_id == source_id)

    def list_publications(self, source_id: str) -> tuple[Any, ...]:
        return ()


class _PublicationService:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def publish(self, request: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            source_id=request.source_id,
            validation_id=request.validation_id,
            model_dump=lambda **_: {
                "source_id": request.source_id,
                "validation_id": request.validation_id,
            },
        )


def _facade() -> tuple[
    ProductionHybridKnowledgePublicationFacade,
    _Assembler,
    _Repository,
    _PublicationService,
]:
    assembler = _Assembler()
    repository = _Repository()
    service = _PublicationService()
    facade = ProductionHybridKnowledgePublicationFacade(
        assembler=assembler,
        repository=repository,
        publication_service=service,
        retrieval_profile=SimpleNamespace(profile_revision_id="profile-1"),
        clock=lambda: datetime(2026, 7, 15, tzinfo=UTC),
        validation_id_factory=lambda: "validation-1",
    )
    return facade, assembler, repository, service


def test_validate_stages_exact_candidate_profile_and_validation_authority() -> None:
    facade, assembler, repository, _ = _facade()

    validation = facade.validate(
        source_id="source-1",
        smoke_query="保险责任是什么？",
        actor="operator-1",
    )

    assert assembler.calls == [
        ("source-1", "validation-1", "operator-1", "保险责任是什么？")
    ]
    assert repository.staged == [
        {
            "source_id": "source-1",
            "source_draft_version_id": "draft-1",
            "candidate_digest": "a" * 64,
            "generation": SimpleNamespace(generation_id="generation-1"),
        }
    ]
    assert repository.profiles == [
        {
            "source_id": "source-1",
            "profile": SimpleNamespace(profile_revision_id="profile-1"),
            "make_default": True,
        }
    ]
    assert validation == repository.validations[0]
    assert validation.candidate_digest == "a" * 64
    assert validation.smoke_query == "保险责任是什么？"


def test_publish_rebuilds_and_matches_the_exact_validated_candidate() -> None:
    facade, assembler, _, service = _facade()
    facade.validate(source_id="source-1", smoke_query="保险责任", actor="validator")

    publication = facade.publish(
        source_id="source-1",
        validation_id="validation-1",
        change_note="首次发布",
        actor="publisher",
    )

    assert assembler.calls[-1] == (
        "source-1",
        "validation-1",
        "publisher",
        "保险责任",
    )
    assert service.requests[0].candidate_digest == "a" * 64
    assert publication.validation_id == "validation-1"


def test_publish_rejects_candidate_drift_after_validation() -> None:
    facade, assembler, _, service = _facade()
    facade.validate(source_id="source-1", smoke_query="保险责任", actor="validator")
    original_build = assembler.build

    def drifted_build(
        *,
        source_id: str,
        validation_id: str,
        actor: str,
        smoke_query: str | None = None,
    ) -> _Candidate:
        candidate = original_build(
            source_id=source_id,
            validation_id=validation_id,
            actor=actor,
            smoke_query=smoke_query,
        )
        return _Candidate(
            **{
                **candidate.__dict__,
                "source_draft_version_id": "draft-2",
                "candidate_digest": "b" * 64,
            }
        )

    assembler.build = drifted_build  # type: ignore[method-assign]

    with pytest.raises(PublicationConflict, match="STALE_VALIDATION"):
        facade.publish(
            source_id="source-1",
            validation_id="validation-1",
            change_note="漂移",
            actor="publisher",
        )

    assert service.requests == []
