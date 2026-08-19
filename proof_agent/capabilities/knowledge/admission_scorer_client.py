"""Strict private HTTP adapter for ProofAgent-owned Evidence Admission scoring."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
    KnowledgeRelevanceCandidateGroup,
    NonBlankText,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.errors import ProofAgentError


class _AdmissionScore(StrictFrozenModel):
    candidate_evidence_id: NonBlankText
    admission_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class _AdmissionScoreResponse(StrictFrozenModel):
    schema_version: Literal["knowledge-admission-score-response.v1"]
    scorer_id: NonBlankText
    scorer_revision: NonBlankText
    scores: tuple[_AdmissionScore, ...]

    @model_validator(mode="after")
    def reject_duplicate_candidates(self) -> Self:
        identities = tuple(item.candidate_evidence_id for item in self.scores)
        if len(set(identities)) != len(identities):
            raise ValueError("admission scorer returned duplicate candidate identities")
        return self


class HttpKnowledgeCandidateAdmissionScorer:
    """Call one approved scorer revision without exposing retrieval ranks as scores."""

    def __init__(
        self,
        *,
        endpoint: str,
        http_client: GuardedHttpClient,
        authorization_header_factory: Callable[[], str],
        scorer_id: str,
        scorer_revision: str,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        self._endpoint = _validated_endpoint(endpoint)
        self.scorer_id = _nonblank(scorer_id, "scorer_id")
        self.scorer_revision = _nonblank(scorer_revision, "scorer_revision")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("admission scorer timeout is invalid")
        if not 1 <= max_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("admission scorer response bound is invalid")
        self._http_client = http_client
        self._authorization_header_factory = authorization_header_factory
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def score_candidates(
        self,
        *,
        query: KnowledgeCandidateQuery,
        result: KnowledgeCandidateResult,
    ) -> Mapping[str, float]:
        candidates = tuple(
            candidate
            for group in result.evidence_groups
            if isinstance(group, KnowledgeRelevanceCandidateGroup)
            for candidate in group.candidate_evidence
        )
        if not candidates:
            return {}
        try:
            authorization = self._authorization_header_factory()
        except ProofAgentError:
            raise
        except Exception as exc:
            raise _scorer_error("admission scorer authorization is unavailable") from exc
        if (
            not authorization.strip()
            or "\r" in authorization
            or "\n" in authorization
        ):
            raise _scorer_error("admission scorer authorization is unavailable")
        body = json.dumps(
            {
                "schema_version": "knowledge-admission-score-request.v1",
                "scorer_id": self.scorer_id,
                "scorer_revision": self.scorer_revision,
                "knowledge_query_id": result.knowledge_query_id,
                "knowledge_base_release_id": query.knowledge_base_release_id,
                "question": query.question,
                "candidates": [
                    {
                        "candidate_evidence_id": candidate.candidate_evidence_id,
                        "knowledge_source_id": candidate.knowledge_source_id,
                        "knowledge_source_version_id": (
                            candidate.knowledge_source_version_id
                        ),
                        "evidence_unit_id": candidate.evidence_unit_id,
                        "content": candidate.content.model_dump(mode="json"),
                        "content_hash": candidate.content_hash,
                        "citation_locator": candidate.citation_locator.model_dump(
                            mode="json"
                        ),
                        "retrieval_lineage": candidate.retrieval_lineage.model_dump(
                            mode="json"
                        ),
                    }
                    for candidate in candidates
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self._http_client.request(
                "POST",
                f"{self._endpoint}/v1/evidence-admission-scores",
                headers={
                    "Accept": "application/json",
                    "Authorization": authorization,
                    "Content-Type": "application/json",
                },
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
        except ProofAgentError:
            raise
        except Exception as exc:
            raise _scorer_error("admission scorer request failed") from exc
        if response.status_code != 200:
            raise _scorer_error("admission scorer rejected the request")
        if len(response.body) > self._max_response_bytes:
            raise _scorer_error("admission scorer response exceeds its byte limit")
        try:
            payload = _AdmissionScoreResponse.model_validate_json(response.body)
        except Exception as exc:
            raise _scorer_error("admission scorer returned an invalid contract") from exc
        if (
            payload.scorer_id != self.scorer_id
            or payload.scorer_revision != self.scorer_revision
        ):
            raise _scorer_error("admission scorer identity changed")
        expected_ids = {candidate.candidate_evidence_id for candidate in candidates}
        actual_ids = {item.candidate_evidence_id for item in payload.scores}
        if actual_ids != expected_ids:
            raise _scorer_error("admission scorer did not score the exact candidate set")
        return {
            item.candidate_evidence_id: item.admission_score
            for item in payload.scores
        }


def _validated_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("admission scorer endpoint must be an HTTPS origin")
    return endpoint.strip().rstrip("/")


def _nonblank(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError(f"{field} is invalid")
    return normalized


def _scorer_error(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_001",
        message,
        "Restore the approved Evidence Admission scorer revision; no KSS rank was used as a fallback.",
    )


__all__ = ["HttpKnowledgeCandidateAdmissionScorer"]
