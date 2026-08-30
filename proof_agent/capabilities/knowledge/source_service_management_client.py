"""Fail-closed management adapter for the independent Knowledge Source Service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceBaseDraftMember,
    KnowledgeServiceBaseDraftProjection,
    KnowledgeServiceBaseProjection,
    KnowledgeServiceConnectionProfileDraft,
    KnowledgeServiceConnectionProfileProjection,
    KnowledgeServiceIdentifier,
    KnowledgeServiceManagementWorkspace,
    KnowledgeServicePreparationAuditPage,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseDeletionEligibilityProjection,
    KnowledgeServiceReleasePreparationProjection,
    KnowledgeServiceReleaseProjection,
    KnowledgeServiceReviseConnectionProfileRequest,
    KnowledgeServiceSaveBaseDraftRequest,
    KnowledgeServiceSourceProjection,
    KnowledgeServiceSourceVersionProjection,
    KnowledgeServiceSpaceProjection,
    KnowledgeServiceSynchronizationOutcome,
    KnowledgeServiceSynchronizationProblemProjection,
    KnowledgeServiceSynchronizationProjection,
    KnowledgeServiceSynchronizationRequest,
    KnowledgeServiceStartReleasePreparationRequest,
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


class _BaseDraftResource(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    members: tuple[KnowledgeServiceBaseDraftMember, ...] = Field(min_length=1)
    revision: int = Field(strict=True, ge=1)
    draft_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    updated_at: AwareDatetime


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
    state: Literal["queryable", "deprecated", "retired", "revoked"]


class _ReleaseCollection(StrictFrozenModel):
    schema_version: Literal["knowledge-base-release-collection.v1"]
    data: tuple[_ReleaseResource, ...] = Field(max_length=10_000)
    summary: _CollectionSummary


class _ExactReleaseIdentity(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier


class _ReleaseDeletionEligibilityResource(_ExactReleaseIdentity):
    schema_version: Literal["knowledge-base-release-deletion-eligibility.v1"]
    release_state: Literal["queryable", "deprecated", "retired", "revoked"]
    eligible: bool
    blockers: tuple[
        Literal[
            "release_not_retired",
            "emergency_revocation_incident_retention",
            "release_retirement_history_unavailable",
            "active_release_references_present",
            "artifact_retention_unverified",
            "artifact_retention_blocked",
        ],
        ...,
    ] = Field(max_length=6)
    active_reference_count: int = Field(ge=0)
    deregistered_reference_count: int = Field(ge=0)
    retired_at: AwareDatetime | None
    revoked_at: AwareDatetime | None
    assessed_at: AwareDatetime
    artifact_retention_state: Literal["not_assessed", "unverified", "blocked", "clear"]
    artifact_retention_authority_id: KnowledgeServiceIdentifier | None = None
    artifact_retention_assessment_id: KnowledgeServiceIdentifier | None = None


class _ConnectionProfileResource(StrictFrozenModel):
    connection_profile_id: KnowledgeServiceIdentifier
    revision: int = Field(strict=True, ge=1)
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    connector_kind: Literal["http_json"]
    configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state: Literal["draft", "validated", "published"]
    updated_at: AwareDatetime


class _ConnectionProfileIdentity(StrictFrozenModel):
    connection_profile_id: KnowledgeServiceIdentifier


class _SynchronizationIdentity(StrictFrozenModel):
    value: KnowledgeServiceIdentifier


class _PreparationIdentity(StrictFrozenModel):
    value: KnowledgeServiceIdentifier


class _SynchronizationProblemBlockerResource(StrictFrozenModel):
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class _SynchronizationProblemResource(StrictFrozenModel):
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: int = Field(ge=400, le=599)
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    retryable: bool
    blockers: tuple[_SynchronizationProblemBlockerResource, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )


class _SynchronizationLinksResource(StrictFrozenModel):
    self: str = Field(min_length=1, max_length=512)


class _PinnedConnectionProfileResource(StrictFrozenModel):
    connection_profile_id: KnowledgeServiceIdentifier
    revision: int = Field(strict=True, ge=1)
    configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _ProfileSynchronizationResource(StrictFrozenModel):
    schema_version: Literal["knowledge-source-synchronization.v2"]
    knowledge_source_synchronization_id: KnowledgeServiceIdentifier
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    state: Literal["queued", "running", "succeeded", "failed"]
    submitted_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    materialized_knowledge_source_version_id: KnowledgeServiceIdentifier | None = None
    problem: _SynchronizationProblemResource | None = None
    links: _SynchronizationLinksResource
    connection_profile: _PinnedConnectionProfileResource


class _ResolvedBaseMemberResource(StrictFrozenModel):
    knowledge_source_id: KnowledgeServiceIdentifier
    knowledge_source_version_id: KnowledgeServiceIdentifier


class _BaseVersionResource(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_version_id: KnowledgeServiceIdentifier
    members: tuple[_ResolvedBaseMemberResource, ...] = Field(min_length=1)
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _ReleasePreparationResource(StrictFrozenModel):
    schema_version: Literal["knowledge-release-preparation.v1"]
    release_preparation_id: KnowledgeServiceIdentifier
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    draft_revision: int = Field(strict=True, ge=1)
    draft_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    base_version: _BaseVersionResource
    submitted_at: AwareDatetime
    state: Literal["queued", "running", "cancelled", "ready", "expired", "consumed", "failed"]
    knowledge_base_release_id: KnowledgeServiceIdentifier | None = None
    release_manifest_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    completed_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    expired_at: AwareDatetime | None = None
    consumed_at: AwareDatetime | None = None
    failure_code: KnowledgeServiceIdentifier | None = None
    failed_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_state_specific_fields(self) -> Self:
        prepared = (
            self.knowledge_base_release_id,
            self.release_manifest_digest,
            self.completed_at,
            self.expires_at,
        )
        failure = (self.failure_code, self.failed_at)
        if self.state in {"queued", "running"} and any(
            value is not None
            for value in (*prepared, *failure, self.cancelled_at, self.expired_at, self.consumed_at)
        ):
            raise ValueError("non-terminal Preparation exposes terminal fields")
        if self.state == "cancelled" and (
            self.cancelled_at is None
            or any(
                value is not None
                for value in (*prepared, *failure, self.expired_at, self.consumed_at)
            )
        ):
            raise ValueError("cancelled Preparation fields are inconsistent")
        if self.state == "failed" and (
            any(value is None for value in failure)
            or any(
                value is not None
                for value in (*prepared, self.cancelled_at, self.expired_at, self.consumed_at)
            )
        ):
            raise ValueError("failed Preparation fields are inconsistent")
        if self.state in {"ready", "expired", "consumed"} and (
            any(value is None for value in prepared)
            or any(value is not None for value in (*failure, self.cancelled_at))
        ):
            raise ValueError("prepared Preparation fields are inconsistent")
        if self.state == "ready" and any(
            value is not None for value in (self.expired_at, self.consumed_at)
        ):
            raise ValueError("ready Preparation exposes a terminal timestamp")
        if self.state == "expired" and (self.expired_at is None or self.consumed_at is not None):
            raise ValueError("expired Preparation fields are inconsistent")
        if self.state == "consumed" and (self.consumed_at is None or self.expired_at is not None):
            raise ValueError("consumed Preparation fields are inconsistent")
        return self


class _PreparationAuditSuccessResource(StrictFrozenModel):
    action: Literal["save_draft", "start", "cancel"]
    operator_id: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$",
    )
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    draft_revision: int = Field(strict=True, ge=1)
    draft_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    release_preparation_id: KnowledgeServiceIdentifier | None = None
    knowledge_base_version_id: KnowledgeServiceIdentifier | None = None
    recorded_at: AwareDatetime


class _PreparationAuditRejectionResource(StrictFrozenModel):
    operator_id: str | None = Field(
        default=None,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$",
    )
    knowledge_space_id: KnowledgeServiceIdentifier | None = None
    knowledge_base_id: KnowledgeServiceIdentifier | None = None
    release_preparation_id: KnowledgeServiceIdentifier | None = None
    operation: Literal[
        "save_draft",
        "get_draft",
        "start",
        "get_preparation",
        "cancel",
        "expire",
        "publish",
        "audit",
    ]
    code: KnowledgeServiceIdentifier
    recorded_at: AwareDatetime


class _PreparationAuditCollectionResource(StrictFrozenModel):
    events: tuple[_PreparationAuditSuccessResource, ...] = Field(max_length=10_000)
    rejections: tuple[_PreparationAuditRejectionResource, ...] = Field(max_length=10_000)


_RELEASE_PREPARATION_PROJECTION: TypeAdapter[KnowledgeServiceReleasePreparationProjection] = (
    TypeAdapter(KnowledgeServiceReleasePreparationProjection)
)


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

    def create_connection_profile(
        self,
        draft: KnowledgeServiceConnectionProfileDraft,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        resource = self._parse(
            self._request(
                "POST",
                "/v1/connection-profiles",
                body=draft.model_dump(mode="json"),
                idempotency_key=idempotency_key,
                accepted=(201,),
            ),
            _ConnectionProfileResource,
        )
        if (
            resource.revision != 1
            or resource.state != "draft"
            or resource.knowledge_space_id != draft.knowledge_space_id
            or resource.knowledge_source_id != draft.knowledge_source_id
            or resource.connector_kind != draft.configuration.kind
        ):
            raise _contract_error("Connection Profile create response changed exact identity")
        return KnowledgeServiceConnectionProfileProjection.model_validate(
            resource.model_dump(mode="python")
        )

    def connection_profile(
        self,
        connection_profile_id: str,
        *,
        revision: int | None = None,
    ) -> KnowledgeServiceConnectionProfileProjection:
        identity = _ConnectionProfileIdentity(
            connection_profile_id=connection_profile_id,
        )
        if revision is not None and (type(revision) is not int or revision < 1):
            raise _contract_error("Connection Profile revision is invalid")
        path = f"/v1/connection-profiles/{identity.connection_profile_id}"
        if revision is not None:
            path = f"{path}?revision={revision}"
        resource = self._parse(
            self._request("GET", path),
            _ConnectionProfileResource,
        )
        if resource.connection_profile_id != identity.connection_profile_id or (
            revision is not None and resource.revision != revision
        ):
            raise _contract_error("Connection Profile read changed exact identity")
        return self._profile_projection(resource)

    def revise_connection_profile(
        self,
        connection_profile_id: str,
        request: KnowledgeServiceReviseConnectionProfileRequest,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        identity = _ConnectionProfileIdentity(
            connection_profile_id=connection_profile_id,
        )
        resource = self._parse(
            self._request(
                "PUT",
                f"/v1/connection-profiles/{identity.connection_profile_id}",
                body=request.model_dump(mode="json"),
                idempotency_key=idempotency_key,
            ),
            _ConnectionProfileResource,
        )
        draft = request.draft
        if (
            resource.connection_profile_id != identity.connection_profile_id
            or resource.revision != request.expected_revision + 1
            or resource.state != "draft"
            or resource.knowledge_space_id != draft.knowledge_space_id
            or resource.knowledge_source_id != draft.knowledge_source_id
            or resource.connector_kind != draft.configuration.kind
        ):
            raise _contract_error("Connection Profile revise response changed exact identity")
        return self._profile_projection(resource)

    def validate_connection_profile(
        self,
        connection_profile_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        return self._transition_connection_profile(
            connection_profile_id,
            operation="validate",
            expected_revision=expected_revision,
            expected_state="validated",
            idempotency_key=idempotency_key,
        )

    def publish_connection_profile(
        self,
        connection_profile_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        return self._transition_connection_profile(
            connection_profile_id,
            operation="publish",
            expected_revision=expected_revision,
            expected_state="published",
            idempotency_key=idempotency_key,
        )

    def submit_synchronization(
        self,
        request: KnowledgeServiceSynchronizationRequest,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceSynchronizationOutcome:
        response = self._request(
            "POST",
            "/v1/knowledge-source-synchronizations",
            body=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            accepted=(200, 202),
        )
        resource = self._parse(response, _ProfileSynchronizationResource)
        profile = request.connection_profile
        if (
            resource.knowledge_space_id != request.knowledge_space_id
            or resource.knowledge_source_id != request.knowledge_source_id
            or resource.connection_profile.connection_profile_id != profile.connection_profile_id
            or resource.connection_profile.revision != profile.revision
        ):
            raise _contract_error("Synchronization admission changed exact identity")
        return KnowledgeServiceSynchronizationOutcome(
            synchronization=self._synchronization_projection(resource),
            created=response.status_code == 202,
        )

    def synchronization(
        self,
        synchronization_id: str,
    ) -> KnowledgeServiceSynchronizationProjection:
        identity = _SynchronizationIdentity(
            value=synchronization_id,
        )
        resource = self._parse(
            self._request(
                "GET",
                (f"/v1/knowledge-source-synchronizations/{identity.value}"),
            ),
            _ProfileSynchronizationResource,
        )
        if resource.knowledge_source_synchronization_id != identity.value:
            raise _contract_error("Synchronization read changed exact identity")
        return self._synchronization_projection(resource)

    @staticmethod
    def _synchronization_projection(
        resource: _ProfileSynchronizationResource,
    ) -> KnowledgeServiceSynchronizationProjection:
        expected_link = (
            f"/v1/knowledge-source-synchronizations/{resource.knowledge_source_synchronization_id}"
        )
        if resource.links.self != expected_link:
            raise _contract_error("Synchronization response changed its exact self link")
        problem = None
        if resource.problem is not None:
            problem = KnowledgeServiceSynchronizationProblemProjection(
                code=resource.problem.code,
                retryable=resource.problem.retryable,
                blocker_codes=tuple(blocker.code for blocker in resource.problem.blockers),
            )
        return KnowledgeServiceSynchronizationProjection.model_validate(
            {
                "knowledge_source_synchronization_id": (
                    resource.knowledge_source_synchronization_id
                ),
                "knowledge_space_id": resource.knowledge_space_id,
                "knowledge_source_id": resource.knowledge_source_id,
                "state": resource.state,
                "submitted_at": resource.submitted_at,
                "started_at": resource.started_at,
                "completed_at": resource.completed_at,
                "materialized_knowledge_source_version_id": (
                    resource.materialized_knowledge_source_version_id
                ),
                "problem": problem,
                "connection_profile": resource.connection_profile.model_dump(mode="python"),
                "links": {
                    "self": (
                        "/api/config/knowledge-service/synchronizations/"
                        f"{resource.knowledge_source_synchronization_id}"
                    )
                },
            }
        )

    def _transition_connection_profile(
        self,
        connection_profile_id: str,
        *,
        operation: Literal["validate", "publish"],
        expected_revision: int,
        expected_state: Literal["validated", "published"],
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        identity = _ConnectionProfileIdentity(
            connection_profile_id=connection_profile_id,
        )
        if type(expected_revision) is not int or expected_revision < 1:
            raise _contract_error("Connection Profile revision is invalid")
        resource = self._parse(
            self._request(
                "POST",
                f"/v1/connection-profiles/{identity.connection_profile_id}:{operation}",
                body={"expected_revision": expected_revision},
                idempotency_key=idempotency_key,
            ),
            _ConnectionProfileResource,
        )
        if (
            resource.connection_profile_id != identity.connection_profile_id
            or resource.revision != expected_revision
            or resource.state != expected_state
        ):
            raise _contract_error(f"Connection Profile {operation} response changed exact identity")
        return self._profile_projection(resource)

    @staticmethod
    def _profile_projection(
        resource: _ConnectionProfileResource,
    ) -> KnowledgeServiceConnectionProfileProjection:
        return KnowledgeServiceConnectionProfileProjection.model_validate(
            resource.model_dump(mode="python")
        )

    def release_deletion_eligibility(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        knowledge_base_release_id: str,
    ) -> KnowledgeServiceReleaseDeletionEligibilityProjection:
        identity = _ExactReleaseIdentity(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            knowledge_base_release_id=knowledge_base_release_id,
        )
        resource = self._parse(
            self._request(
                "GET",
                (
                    f"/v1/knowledge-spaces/{identity.knowledge_space_id}/"
                    f"knowledge-bases/{identity.knowledge_base_id}/releases/"
                    f"{identity.knowledge_base_release_id}/deletion-eligibility"
                ),
            ),
            _ReleaseDeletionEligibilityResource,
        )
        if (
            resource.knowledge_space_id,
            resource.knowledge_base_id,
            resource.knowledge_base_release_id,
        ) != (
            identity.knowledge_space_id,
            identity.knowledge_base_id,
            identity.knowledge_base_release_id,
        ):
            raise _contract_error("Release deletion assessment changed exact identity")
        return KnowledgeServiceReleaseDeletionEligibilityProjection.model_validate(
            resource.model_dump(
                mode="python",
                exclude={
                    "schema_version",
                    "artifact_retention_authority_id",
                    "artifact_retention_assessment_id",
                },
            )
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

    def save_base_draft(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        request: KnowledgeServiceSaveBaseDraftRequest,
        idempotency_key: str,
    ) -> KnowledgeServiceBaseDraftProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        resource = self._parse(
            self._request(
                "PUT",
                self._base_draft_path(identity),
                body={
                    "knowledge_space_id": identity.knowledge_space_id,
                    "knowledge_base_id": identity.knowledge_base_id,
                    **request.model_dump(mode="json"),
                },
                idempotency_key=idempotency_key,
            ),
            _BaseDraftResource,
        )
        if (
            resource.knowledge_space_id != identity.knowledge_space_id
            or resource.knowledge_base_id != identity.knowledge_base_id
            or resource.revision != request.expected_revision + 1
            or resource.members != request.members
        ):
            raise _contract_error("Base Draft save response changed exact identity")
        return self._base_draft_projection(resource)

    def base_draft(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        revision: int,
    ) -> KnowledgeServiceBaseDraftProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        if type(revision) is not int or revision < 1:
            raise _contract_error("Base Draft revision is invalid")
        resource = self._parse(
            self._request(
                "GET",
                f"{self._base_draft_path(identity)}?revision={revision}",
            ),
            _BaseDraftResource,
        )
        if (
            resource.knowledge_space_id != identity.knowledge_space_id
            or resource.knowledge_base_id != identity.knowledge_base_id
            or resource.revision != revision
        ):
            raise _contract_error("Base Draft read changed exact identity")
        return self._base_draft_projection(resource)

    @staticmethod
    def _base_draft_path(identity: KnowledgeServiceBaseProjection) -> str:
        return (
            f"/v1/knowledge-spaces/{identity.knowledge_space_id}/"
            f"knowledge-bases/{identity.knowledge_base_id}/draft"
        )

    @staticmethod
    def _base_draft_projection(
        resource: _BaseDraftResource,
    ) -> KnowledgeServiceBaseDraftProjection:
        try:
            return KnowledgeServiceBaseDraftProjection.model_validate(
                resource.model_dump(mode="python")
            )
        except ValidationError as error:
            raise _contract_error("Knowledge service Base Draft projection is invalid") from error

    def start_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        request: KnowledgeServiceStartReleasePreparationRequest,
        idempotency_key: str,
    ) -> KnowledgeServiceReleasePreparationProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        collection_path = self._release_preparations_path(identity)
        response = self._request(
            "POST",
            collection_path,
            body={
                "knowledge_space_id": identity.knowledge_space_id,
                "knowledge_base_id": identity.knowledge_base_id,
                "draft_revision": request.draft_revision,
            },
            idempotency_key=idempotency_key,
            accepted=(202,),
        )
        resource = self._parse(response, _ReleasePreparationResource)
        self._require_preparation_identity(resource, identity)
        if resource.state != "queued" or resource.draft_revision != request.draft_revision:
            raise _contract_error("Release Preparation admission changed exact identity")
        expected_location = f"{collection_path}/{resource.release_preparation_id}"
        if _header(response.headers, "location") != expected_location:
            raise _contract_error("Release Preparation admission changed its exact Location")
        return self._release_preparation_projection(resource)

    def release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> KnowledgeServiceReleasePreparationProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        preparation = _PreparationIdentity(value=release_preparation_id)
        resource = self._parse(
            self._request(
                "GET",
                f"{self._release_preparations_path(identity)}/{preparation.value}",
            ),
            _ReleasePreparationResource,
        )
        self._require_preparation_identity(
            resource,
            identity,
            release_preparation_id=preparation.value,
        )
        return self._release_preparation_projection(resource)

    def preparation_audit(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        offset: int,
        limit: int,
    ) -> KnowledgeServicePreparationAuditPage:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        if type(offset) is not int or not 0 <= offset <= 20_000:
            raise _contract_error("Preparation audit offset is invalid")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise _contract_error("Preparation audit limit is invalid")
        resource = self._parse(
            self._request(
                "GET",
                (
                    f"/v1/knowledge-spaces/{identity.knowledge_space_id}/"
                    f"knowledge-bases/{identity.knowledge_base_id}/preparation-audit"
                ),
            ),
            _PreparationAuditCollectionResource,
        )
        entries: list[dict[str, object]] = []
        for event in resource.events:
            if (
                event.knowledge_space_id != identity.knowledge_space_id
                or event.knowledge_base_id != identity.knowledge_base_id
            ):
                raise _contract_error("Preparation audit event changed exact scope")
            entries.append(
                {
                    "kind": "success",
                    "action": event.action,
                    "actor": {
                        "identity_kind": "kss_service_operator",
                        "operator_id": event.operator_id,
                    },
                    "draft_revision": event.draft_revision,
                    "draft_digest": event.draft_digest,
                    "release_preparation_id": event.release_preparation_id,
                    "knowledge_base_version_id": event.knowledge_base_version_id,
                    "recorded_at": event.recorded_at,
                }
            )
        for rejection in resource.rejections:
            if rejection.knowledge_space_id not in {
                None,
                identity.knowledge_space_id,
            } or rejection.knowledge_base_id not in {None, identity.knowledge_base_id}:
                raise _contract_error("Preparation audit rejection changed exact scope")
            entries.append(
                {
                    "kind": "rejection",
                    "operation": rejection.operation,
                    "code": rejection.code,
                    "actor": None
                    if rejection.operator_id is None
                    else {
                        "identity_kind": "kss_service_operator",
                        "operator_id": rejection.operator_id,
                    },
                    "release_preparation_id": rejection.release_preparation_id,
                    "recorded_at": rejection.recorded_at,
                }
            )
        entries.sort(
            key=lambda entry: (
                entry["recorded_at"],
                entry["kind"],
                entry.get("action", entry.get("operation", "")),
                entry.get("release_preparation_id") or "",
            )
        )
        page_entries = entries[offset : offset + limit]
        total = len(entries)
        try:
            return KnowledgeServicePreparationAuditPage.model_validate(
                {
                    "knowledge_space_id": identity.knowledge_space_id,
                    "knowledge_base_id": identity.knowledge_base_id,
                    "entries": page_entries,
                    "page": {
                        "offset": offset,
                        "limit": limit,
                        "total": total,
                        "returned": len(page_entries),
                        "has_more": offset + len(page_entries) < total,
                    },
                }
            )
        except ValidationError as error:
            raise _contract_error(
                "Knowledge service Preparation audit projection is invalid"
            ) from error

    def publish_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> KnowledgeServiceReleasePreparationProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        preparation = _PreparationIdentity(value=release_preparation_id)
        resource_path = f"{self._release_preparations_path(identity)}/{preparation.value}"
        response = self._request("POST", f"{resource_path}:publish")
        resource = self._parse(response, _ReleasePreparationResource)
        self._require_preparation_identity(
            resource,
            identity,
            release_preparation_id=preparation.value,
        )
        if resource.state != "consumed":
            raise _contract_error("Release Preparation publication did not consume the resource")
        if _header(response.headers, "location") != resource_path:
            raise _contract_error("Release Preparation publication changed its exact Location")
        return self._release_preparation_projection(resource)

    def cancel_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
        idempotency_key: str,
    ) -> KnowledgeServiceReleasePreparationProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        preparation = _PreparationIdentity(value=release_preparation_id)
        resource_path = f"{self._release_preparations_path(identity)}/{preparation.value}"
        response = self._request(
            "POST",
            f"{resource_path}:cancel",
            idempotency_key=idempotency_key,
        )
        resource = self._parse(response, _ReleasePreparationResource)
        self._require_preparation_identity(
            resource,
            identity,
            release_preparation_id=preparation.value,
        )
        if resource.state != "cancelled":
            raise _contract_error("Release Preparation cancellation did not cancel the resource")
        if _header(response.headers, "location") != resource_path:
            raise _contract_error("Release Preparation cancellation changed its exact Location")
        return self._release_preparation_projection(resource)

    def expire_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> KnowledgeServiceReleasePreparationProjection:
        identity = KnowledgeServiceBaseProjection(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )
        preparation = _PreparationIdentity(value=release_preparation_id)
        resource_path = f"{self._release_preparations_path(identity)}/{preparation.value}"
        response = self._request("POST", f"{resource_path}:expire")
        resource = self._parse(response, _ReleasePreparationResource)
        self._require_preparation_identity(
            resource,
            identity,
            release_preparation_id=preparation.value,
        )
        if resource.state != "expired":
            raise _contract_error("Release Preparation expiry did not expire the resource")
        if _header(response.headers, "location") != resource_path:
            raise _contract_error("Release Preparation expiry changed its exact Location")
        return self._release_preparation_projection(resource)

    @staticmethod
    def _release_preparations_path(identity: KnowledgeServiceBaseProjection) -> str:
        return (
            f"/v1/knowledge-spaces/{identity.knowledge_space_id}/"
            f"knowledge-bases/{identity.knowledge_base_id}/release-preparations"
        )

    @staticmethod
    def _require_preparation_identity(
        resource: _ReleasePreparationResource,
        identity: KnowledgeServiceBaseProjection,
        *,
        release_preparation_id: str | None = None,
    ) -> None:
        if (
            resource.knowledge_space_id != identity.knowledge_space_id
            or resource.knowledge_base_id != identity.knowledge_base_id
            or resource.base_version.knowledge_space_id != identity.knowledge_space_id
            or resource.base_version.knowledge_base_id != identity.knowledge_base_id
            or (
                release_preparation_id is not None
                and resource.release_preparation_id != release_preparation_id
            )
        ):
            raise _contract_error("Release Preparation response changed exact identity")

    @staticmethod
    def _release_preparation_projection(
        resource: _ReleasePreparationResource,
    ) -> KnowledgeServiceReleasePreparationProjection:
        path = (
            f"/api/config/knowledge-service/spaces/{resource.knowledge_space_id}/"
            f"bases/{resource.knowledge_base_id}/release-preparations/"
            f"{resource.release_preparation_id}"
        )
        payload = resource.model_dump(
            mode="python",
            exclude={"schema_version"},
            exclude_none=True,
        )
        payload["schema_version"] = "knowledge-service-release-preparation.v1"
        payload["links"] = {"self": path}
        try:
            return _RELEASE_PREPARATION_PROJECTION.validate_python(payload)
        except ValidationError as error:
            raise _contract_error(
                "Knowledge service Release Preparation projection is invalid"
            ) from error

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        body: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
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
        if idempotency_key is not None:
            if not 1 <= len(idempotency_key) <= 256 or not idempotency_key.strip():
                raise _contract_error("Knowledge service idempotency key is invalid")
            headers["Idempotency-Key"] = idempotency_key
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


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == expected), None)


def _contract_error(detail: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        detail,
        "Verify the Knowledge Source Service release and strict management contract.",
    )


__all__ = ["KnowledgeSourceServiceManagementClient"]
