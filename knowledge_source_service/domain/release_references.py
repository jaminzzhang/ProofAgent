"""Command and receipt facts for exact Release references and lifecycle."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from knowledge_source_service.contracts.release_references import (
    DeregisteredKnowledgeBaseReleaseReference,
    DeprecatedKnowledgeBaseRelease,
    KnowledgeBaseReleaseReference,
    RetiredKnowledgeBaseRelease,
    RevokedKnowledgeBaseRelease,
)


class ReleaseReferenceError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReleaseLifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReleaseReferenceTarget:
    knowledge_space_id: str
    knowledge_base_id: str
    knowledge_base_release_id: str


@dataclass(frozen=True)
class ReleaseReferenceCommand:
    action: Literal["register", "deregister"]
    authenticated_client_id: str
    key_digest: str
    fingerprint: str


@dataclass(frozen=True)
class ReleaseReferenceReceipt:
    command: ReleaseReferenceCommand
    result: KnowledgeBaseReleaseReference | DeregisteredKnowledgeBaseReleaseReference


@dataclass(frozen=True)
class PermanentExternalResourceRetirementVerification:
    verifier_id: str
    verification_id: str
    release_reference_id: str


@dataclass(frozen=True)
class ReleaseLifecycleTarget:
    knowledge_space_id: str
    knowledge_base_id: str
    knowledge_base_release_id: str
    state: Literal["queryable", "deprecated", "retired", "revoked"]
    deprecated_at: datetime | None


@dataclass(frozen=True)
class ReleaseLifecycleCommand:
    action: Literal["deprecate", "retire", "revoke"]
    operator_id: str
    key_digest: str
    fingerprint: str


@dataclass(frozen=True)
class ReleaseLifecycleReceipt:
    command: ReleaseLifecycleCommand
    result: (
        DeprecatedKnowledgeBaseRelease | RetiredKnowledgeBaseRelease | RevokedKnowledgeBaseRelease
    )


@dataclass(frozen=True)
class ReleaseRetentionPolicy:
    policy_id: str
    minimum_age: timedelta
