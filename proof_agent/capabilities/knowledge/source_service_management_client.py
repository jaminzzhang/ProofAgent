"""Fail-closed management adapter for the independent Knowledge Source Service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationError

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceBaseProjection,
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
    KnowledgeServiceSourceProjection,
    KnowledgeServiceSourceVersionProjection,
    KnowledgeServiceSpaceProjection,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient, GuardedHttpResponse
from proof_agent.errors import ProofAgentError


class _DependencyReadiness(StrictFrozenModel):
    name: Literal["postgresql", "object_storage", "search"]
    status: Literal["ready", "unavailable"]


class _ReadinessResource(StrictFrozenModel):
    schema_version: Literal["knowledge-service-readiness.v1"]
    status: Literal["ready", "unavailable"]
    service: Literal["knowledge-source-service"]
    release_identity: str = Field(min_length=1, max_length=255)
    dependencies: tuple[_DependencyReadiness, ...] = Field(min_length=3, max_length=3)


class _CollectionSummary(StrictFrozenModel):
    total: int = Field(ge=0, le=10_000)


class _SpaceResource(StrictFrozenModel):
    schema_version: Literal["knowledge-space.v1"]
    knowledge_space_id: str


class _SpaceCollection(StrictFrozenModel):
    schema_version: Literal["knowledge-space-collection.v1"]
    data: tuple[_SpaceResource, ...] = Field(max_length=1_000)
    summary: _CollectionSummary


class _SourceResource(StrictFrozenModel):
    schema_version: Literal["knowledge-source.v1"]
    knowledge_space_id: str
    knowledge_source_id: str


class _SourceCollection(StrictFrozenModel):
    schema_version: Literal["knowledge-source-collection.v1"]
    data: tuple[_SourceResource, ...] = Field(max_length=10_000)
    summary: _CollectionSummary


class _BaseResource(StrictFrozenModel):
    schema_version: Literal["knowledge-base.v1"]
    knowledge_space_id: str
    knowledge_base_id: str


class _BaseCollection(StrictFrozenModel):
    schema_version: Literal["knowledge-base-collection.v1"]
    data: tuple[_BaseResource, ...] = Field(max_length=10_000)
    summary: _CollectionSummary


class _SourceVersionResource(StrictFrozenModel):
    schema_version: Literal["knowledge-source-version-summary.v1"]
    knowledge_space_id: str
    knowledge_source_id: str
    knowledge_source_version_id: str
    source_kind: Literal["document", "dataset"]
    media_type: str


class _SourceVersionCollection(StrictFrozenModel):
    schema_version: Literal["knowledge-source-version-collection.v1"]
    data: tuple[_SourceVersionResource, ...] = Field(max_length=10_000)
    summary: _CollectionSummary


class _ReleaseResource(StrictFrozenModel):
    schema_version: Literal["knowledge-base-release-summary.v1"]
    knowledge_space_id: str
    knowledge_base_id: str
    knowledge_base_version_id: str
    knowledge_base_release_id: str
    source_version_count: int = Field(ge=1, le=10_000)
    state: Literal["queryable", "retired"]


class _ReleaseCollection(StrictFrozenModel):
    schema_version: Literal["knowledge-base-release-collection.v1"]
    data: tuple[_ReleaseResource, ...] = Field(max_length=10_000)
    summary: _CollectionSummary


class KnowledgeSourceServiceManagementClient:
    """Read and mutate KSS catalog resources through guarded HTTPS."""

    def __init__(
        self,
        *,
        endpoint: str,
        http_client: GuardedHttpClient,
        authorization_header_factory: Callable[[], str],
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._endpoint = _validated_endpoint(endpoint)
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Knowledge service management timeout is invalid")
        if not 1 <= max_response_bytes <= 16 * 1024 * 1024:
            raise ValueError("Knowledge service management response bound is invalid")
        self._http_client = http_client
        self._authorization_header_factory = authorization_header_factory
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        readiness = self._parse(
            self._request("GET", "/readyz", authenticated=False, accepted=(200, 503)),
            _ReadinessResource,
        )
        blockers = tuple(
            dependency.name for dependency in readiness.dependencies if dependency.status != "ready"
        )
        readiness_projection = KnowledgeServiceReadinessProjection(
            state=readiness.status,
            revision=readiness.release_identity,
            blockers=blockers,
        )
        if readiness.status != "ready":
            return KnowledgeServiceManagementWorkspace(
                readiness=readiness_projection,
                spaces=(),
                sources=(),
                bases=(),
                source_versions=(),
                releases=(),
            )

        spaces_response = self._parse(
            self._request("GET", "/v1/knowledge-spaces"),
            _SpaceCollection,
        )
        spaces = tuple(
            KnowledgeServiceSpaceProjection(knowledge_space_id=item.knowledge_space_id)
            for item in spaces_response.data
        )
        sources: list[KnowledgeServiceSourceProjection] = []
        bases: list[KnowledgeServiceBaseProjection] = []
        source_versions: list[KnowledgeServiceSourceVersionProjection] = []
        releases: list[KnowledgeServiceReleaseProjection] = []
        for space in spaces:
            source_response = self._parse(
                self._request(
                    "GET",
                    f"/v1/knowledge-spaces/{space.knowledge_space_id}/knowledge-sources",
                ),
                _SourceCollection,
            )
            base_response = self._parse(
                self._request(
                    "GET",
                    f"/v1/knowledge-spaces/{space.knowledge_space_id}/knowledge-bases",
                ),
                _BaseCollection,
            )
            for item in source_response.data:
                source = KnowledgeServiceSourceProjection(
                    knowledge_space_id=item.knowledge_space_id,
                    knowledge_source_id=item.knowledge_source_id,
                )
                if source.knowledge_space_id != space.knowledge_space_id:
                    raise _contract_error("Knowledge Source collection changed Space identity")
                sources.append(source)
                version_response = self._parse(
                    self._request(
                        "GET",
                        (
                            f"/v1/knowledge-spaces/{space.knowledge_space_id}/"
                            f"knowledge-sources/{source.knowledge_source_id}/versions"
                        ),
                    ),
                    _SourceVersionCollection,
                )
                for version in version_response.data:
                    source_version_projection = (
                        KnowledgeServiceSourceVersionProjection.model_validate(
                            version.model_dump(mode="python", exclude={"schema_version"})
                        )
                    )
                    if (
                        source_version_projection.knowledge_space_id != space.knowledge_space_id
                        or source_version_projection.knowledge_source_id
                        != source.knowledge_source_id
                    ):
                        raise _contract_error("Source Version collection changed parent identity")
                    source_versions.append(source_version_projection)
            for item in base_response.data:
                base = KnowledgeServiceBaseProjection(
                    knowledge_space_id=item.knowledge_space_id,
                    knowledge_base_id=item.knowledge_base_id,
                )
                if base.knowledge_space_id != space.knowledge_space_id:
                    raise _contract_error("Knowledge Base collection changed Space identity")
                bases.append(base)
                release_response = self._parse(
                    self._request(
                        "GET",
                        (
                            f"/v1/knowledge-spaces/{space.knowledge_space_id}/"
                            f"knowledge-bases/{base.knowledge_base_id}/releases"
                        ),
                    ),
                    _ReleaseCollection,
                )
                for release in release_response.data:
                    release_projection = KnowledgeServiceReleaseProjection.model_validate(
                        release.model_dump(mode="python", exclude={"schema_version"})
                    )
                    if (
                        release_projection.knowledge_space_id != space.knowledge_space_id
                        or release_projection.knowledge_base_id != base.knowledge_base_id
                    ):
                        raise _contract_error("Release collection changed parent identity")
                    releases.append(release_projection)
        return KnowledgeServiceManagementWorkspace(
            readiness=readiness_projection,
            spaces=spaces,
            sources=tuple(sources),
            bases=tuple(bases),
            source_versions=tuple(source_versions),
            releases=tuple(releases),
        )

    def create_space(self, knowledge_space_id: str) -> None:
        resource = KnowledgeServiceSpaceProjection(knowledge_space_id=knowledge_space_id)
        self._request(
            "POST",
            "/v1/knowledge-spaces",
            body={"knowledge_space_id": resource.knowledge_space_id},
            accepted=(201,),
        )

    def create_source(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> None:
        resource = KnowledgeServiceSourceProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=knowledge_source_id,
        )
        self._request(
            "POST",
            f"/v1/knowledge-spaces/{resource.knowledge_space_id}/knowledge-sources",
            body={"knowledge_source_id": resource.knowledge_source_id},
            accepted=(201,),
        )

    def create_base(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> None:
        resource = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        self._request(
            "POST",
            f"/v1/knowledge-spaces/{resource.knowledge_space_id}/knowledge-bases",
            body={"knowledge_base_id": resource.knowledge_base_id},
            accepted=(201,),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        body: Mapping[str, object] | None = None,
        accepted: tuple[int, ...] = (200,),
    ) -> GuardedHttpResponse:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = self._authorization_header()
        encoded_body = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded_body = json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        try:
            response = self._http_client.request(
                method,
                f"{self._endpoint}{path}",
                headers=headers,
                body=encoded_body,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service management request failed.",
                "Check the guarded service origin, deployment readiness, and operator credential.",
            ) from error
        if 300 <= response.status_code < 400:
            raise _contract_error("Knowledge service management redirects are forbidden")
        if response.status_code not in accepted:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                f"Knowledge Source Service management rejected the request with HTTP {response.status_code}.",
                "Inspect the trace-safe service problem and management deployment configuration.",
            )
        if len(response.body) > self._max_response_bytes:
            raise _contract_error("Knowledge service management response exceeds its byte limit")
        return response

    def _authorization_header(self) -> str:
        try:
            value = self._authorization_header_factory()
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service operator authorization is unavailable.",
                "Restore the configured Knowledge credential Secret Handle.",
            ) from error
        if not value.startswith("Bearer ") or len(value) > 16_384:
            raise _contract_error("Knowledge service operator authorization is invalid")
        return value

    @staticmethod
    def _parse(response: GuardedHttpResponse, model: type[StrictFrozenModel]) -> Any:
        try:
            payload = json.loads(response.body)
            return model.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise _contract_error(
                "Knowledge service management returned an invalid contract"
            ) from error


def _validated_endpoint(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Knowledge service management endpoint must be an HTTPS origin")
    return value


def _contract_error(detail: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        detail,
        "Verify the Knowledge Source Service release and strict management contract.",
    )


__all__ = ["KnowledgeSourceServiceManagementClient"]
