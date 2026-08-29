"""Safe metadata used by the atomic Base preparation admission transaction."""

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Literal

from pydantic import AwareDatetime, Field

from knowledge_source_service.contracts.base_preparations import (
    BaseIdentifier,
    BasePreparationContract,
    CancelledReleasePreparation,
    ConsumedReleasePreparation,
    ExpiredReleasePreparation,
    KnowledgeBaseDraft,
    ReleasePreparationIdentity,
    QueuedReleasePreparation,
    ReadyReleasePreparation,
    ReleasePreparationResource,
    RunningReleasePreparation,
)
from knowledge_source_service.domain.identities import content_identifier, sha256_json
from knowledge_source_service.domain.publications import PreparedKnowledgeBaseRelease


class PreparationClaim(BasePreparationContract):
    """Worker-only claim; never a browser-supplied capability or public resource."""

    admission: QueuedReleasePreparation
    worker_id: BaseIdentifier
    fencing_token: int = Field(strict=True, ge=1)
    lease_expires_at: AwareDatetime


def preparation_admission(resource: ReleasePreparationResource) -> QueuedReleasePreparation:
    """Restore the immutable admission view, never a mutable state as a receipt."""
    return QueuedReleasePreparation.model_validate(
        {
            **{
                field: getattr(resource, field) for field in ReleasePreparationIdentity.model_fields
            },
            "state": "queued",
        }
    )


def cancel_preparation(
    preparation: ReleasePreparationResource, *, cancelled_at: datetime
) -> CancelledReleasePreparation:
    if not isinstance(preparation, (QueuedReleasePreparation, RunningReleasePreparation)):
        raise BasePreparationError("base_preparation_not_cancellable")
    return CancelledReleasePreparation.model_validate(
        {
            **preparation_admission(preparation).model_dump(mode="python", exclude={"state"}),
            "state": "cancelled",
            "cancelled_at": cancelled_at,
        }
    )


def validate_prepared_candidate(
    admission: QueuedReleasePreparation, candidate: PreparedKnowledgeBaseRelease
) -> None:
    release = candidate.release
    if (
        release.knowledge_space_id != admission.knowledge_space_id
        or release.knowledge_base_id != admission.knowledge_base_id
        or release.knowledge_base_version_id != admission.base_version.knowledge_base_version_id
        or release.knowledge_source_version_ids
        != tuple(member.knowledge_source_version_id for member in admission.base_version.members)
        or release.release_manifest_digest != candidate.release_manifest_artifact.sha256
        or release.knowledge_base_release_id
        != content_identifier("release", release.release_manifest_digest)
    ):
        raise BasePreparationError("base_preparation_invalid_candidate")


def validate_publishable_candidate(
    admission: QueuedReleasePreparation, candidate: PreparedKnowledgeBaseRelease
) -> None:
    """Pure final-CAS validation; artifact/network verification belongs to build time."""

    validate_prepared_candidate(admission, candidate)
    release = candidate.release
    projection = release.retrieval_projection
    manifest: dict[str, object] = {
        "schema": "knowledge-release-manifest.v1",
        "base_version": release.knowledge_base_version_id,
        "source_versions": release.knowledge_source_version_ids,
    }
    if projection is not None:
        manifest["retrieval_projection"] = {
            "index_identity": projection.index_identity,
            "mapping_digest": projection.mapping_digest,
            "corpus_digest": projection.corpus_digest,
            "document_count": projection.document_count,
            "dense_revision": projection.dense_revision,
            "sparse_revision": projection.sparse_revision,
            "dense_dimension": projection.dense_dimension,
        }
    manifest_content = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected_digest = sha256_json(manifest)
    expected_release_id = content_identifier("release", expected_digest)
    expected_object_key = (
        f"spaces/{release.knowledge_space_id}/bases/{release.knowledge_base_id}/"
        f"releases/{expected_release_id}/release-manifest.json"
    )
    artifact = candidate.release_manifest_artifact
    if (
        release.release_manifest_digest != expected_digest
        or release.knowledge_base_release_id != expected_release_id
        or artifact.sha256 != expected_digest
        or artifact.object_key != expected_object_key
        or artifact.size_bytes != len(manifest_content)
        or artifact.media_type != "application/vnd.knowledge.release-manifest+json"
    ):
        raise BasePreparationError("base_preparation_invalid_candidate")


def expire_ready_preparation(
    preparation: ReadyReleasePreparation, *, expired_at: datetime
) -> ExpiredReleasePreparation:
    if expired_at < preparation.expires_at:
        raise BasePreparationError("base_preparation_not_expired")
    return ExpiredReleasePreparation.model_validate(
        {
            **preparation.model_dump(mode="python", exclude={"state"}),
            "state": "expired",
            "expired_at": expired_at,
        }
    )


def consume_ready_preparation(
    preparation: ReadyReleasePreparation, *, consumed_at: datetime
) -> ConsumedReleasePreparation:
    if consumed_at >= preparation.expires_at:
        raise BasePreparationError("base_preparation_expired")
    return ConsumedReleasePreparation.model_validate(
        {
            **preparation.model_dump(mode="python", exclude={"state"}),
            "state": "consumed",
            "consumed_at": consumed_at,
        }
    )


class BasePreparationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReadySourceVersion:
    """Catalog-visible metadata; ready_at is the first publication timestamp, not replay time."""

    knowledge_space_id: str
    knowledge_source_id: str
    knowledge_source_version_id: str
    ready_at: datetime


BasePreparationAction = Literal["save_draft", "start", "cancel"]
BasePreparationResult = KnowledgeBaseDraft | QueuedReleasePreparation | CancelledReleasePreparation


@dataclass(frozen=True)
class BasePreparationCommand:
    operator_id: str
    key_digest: str
    fingerprint: str
    action: BasePreparationAction


@dataclass(frozen=True)
class BasePreparationReceipt:
    command: BasePreparationCommand
    result: BasePreparationResult
