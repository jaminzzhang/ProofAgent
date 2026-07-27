"""Prepared Hybrid publication commit on the caller's PostgreSQL transaction."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from proof_agent.capabilities.knowledge.hybrid.publication import (
    PublicationCommit,
    PublicationConflict,
)
from proof_agent.capabilities.persistence.postgres.publication_preparation_repository import (
    PostgresPublicationPreparationRepository,
)
from proof_agent.contracts import PreparedHybridKnowledgePublication
from proof_agent.contracts.knowledge_index import (
    HybridKnowledgePublicationRecord,
)


class PostgresHybridPublicationCommitAuthority:
    """Bridge staged legacy authority into the unified short transaction."""

    def __init__(
        self,
        connection: Connection,
        *,
        preparations: PostgresPublicationPreparationRepository,
        hybrid_repository: Any,
    ) -> None:
        self._connection = connection
        self._preparations = preparations
        self._hybrid_repository = hybrid_repository

    def commit_prepared(
        self,
        prepared: PreparedHybridKnowledgePublication,
        *,
        publication_id: str,
        published_by: str,
        change_note: str,
        published_at: str,
    ) -> str:
        del change_note, published_at
        job = self._preparations.get_for_validation(prepared.validation_id)
        if (
            job is None
            or job.state != "PREPARED"
            or job.prepared_commit is None
        ):
            raise PublicationConflict("PREPARED_PUBLICATION_NOT_FOUND")
        commit: PublicationCommit = job.prepared_commit
        attempt = commit.attempt
        if (
            job.operation_id != prepared.operation_id
            or attempt.attempt_id != prepared.attempt_id
            or attempt.fencing_token != prepared.fencing_token
            or attempt.source_id != prepared.source_id
            or attempt.source_draft_version_id
            != prepared.source_draft_version_id
            or attempt.candidate_digest != prepared.candidate_digest
            or attempt.generation_id != prepared.generation_id
            or commit.manifest.root.root_sha256 != prepared.manifest_sha256
            or commit.attestation.attestation_sha256
            != prepared.attestation_sha256
            or commit.smoke_result_sha256 != prepared.smoke_result_sha256
        ):
            raise PublicationConflict("PREPARED_IDENTITY_MISMATCH")
        raw_connection = self._connection.connection.driver_connection
        if raw_connection is None:
            raise RuntimeError("PostgreSQL driver connection is unavailable")
        publication: HybridKnowledgePublicationRecord = (
            self._hybrid_repository.commit_if_current(
            commit.model_copy(update={"published_by": published_by}),
            connection=raw_connection,
            publication_id=publication_id,
        )
        )
        if publication.publication_id != publication_id:
            raise PublicationConflict("PUBLICATION_IDENTITY_MISMATCH")
        return publication.publication_id


__all__ = ["PostgresHybridPublicationCommitAuthority"]
