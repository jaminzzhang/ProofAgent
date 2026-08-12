"""Fail-closed HTTP adapter for a content-free Agentic retrieval controller."""

from __future__ import annotations

import ipaddress
import json
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.ports.agentic import (
    AgenticRetrievalDecision,
    AgenticRetrievalObservation,
)


_MAX_RESPONSE_BYTES = 16 * 1024


class AgenticControllerError(RuntimeError):
    """The isolated Agentic controller failed or violated its strict contract."""


class _ControllerDecision(StrictContract):
    schema_version: Literal["agentic-retrieval-decision.v1"]
    action: Literal["continue", "complete", "abort"]
    revised_question: NonBlankText | None
    model_tokens_used: int


class HttpAgenticRetrievalController:
    """Call one no-tools controller endpoint with content-free observations only."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        _validate_endpoint(endpoint)
        if (
            len(bearer_token) < 16
            or bearer_token != bearer_token.strip()
            or any(character.isspace() for character in bearer_token)
        ):
            raise ValueError("Agentic controller Bearer credential is invalid")
        self._endpoint = endpoint
        self._client = httpx.Client(
            timeout=httpx.Timeout(10, connect=3),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer_token}",
            },
        )

    def close(self) -> None:
        self._client.close()

    def decide(
        self,
        observation: AgenticRetrievalObservation,
    ) -> AgenticRetrievalDecision:
        payload = {
            "schema_version": "agentic-retrieval-observation.v1",
            "retrieval_round": observation.retrieval_round,
            "question": observation.question,
            "knowledge_base_release_id": observation.knowledge_base_release_id,
            "access_scope_digest": observation.access_scope_digest,
            "candidate_count": observation.candidate_count,
            "candidate_evidence_ids": observation.candidate_evidence_ids,
            "remaining_rounds": observation.remaining_rounds,
            "remaining_model_calls": observation.remaining_model_calls,
            "remaining_model_tokens": observation.remaining_model_tokens,
            "remaining_duration_ms": observation.remaining_duration_ms,
        }
        timeout_seconds = observation.remaining_duration_ms / 1000
        try:
            with self._client.stream(
                "POST",
                self._endpoint,
                json=payload,
                timeout=httpx.Timeout(
                    timeout_seconds,
                    connect=min(3.0, timeout_seconds),
                ),
            ) as response:
                if response.status_code != 200:
                    raise AgenticControllerError(
                        "Agentic controller returned a non-success status"
                    )
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.casefold() != "application/json":
                    raise AgenticControllerError(
                        "Agentic controller returned an invalid media type"
                    )
                declared_length = response.headers.get("Content-Length")
                if declared_length is not None and (
                    not declared_length.isdecimal()
                    or int(declared_length) > _MAX_RESPONSE_BYTES
                ):
                    raise AgenticControllerError(
                        "Agentic controller response exceeded its bound"
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise AgenticControllerError(
                            "Agentic controller response exceeded its bound"
                        )
        except AgenticControllerError:
            raise
        except httpx.HTTPError as error:
            raise AgenticControllerError(
                "Agentic controller request failed"
            ) from error
        try:
            raw = json.loads(content)
            decision = _ControllerDecision.model_validate(raw)
            return AgenticRetrievalDecision(
                action=decision.action,
                revised_question=decision.revised_question,
                model_tokens_used=decision.model_tokens_used,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as error:
            raise AgenticControllerError(
                "Agentic controller returned an invalid decision"
            ) from error


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Agentic controller endpoint is invalid")
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback:
        raise ValueError("non-loopback Agentic controller endpoint must use HTTPS")
