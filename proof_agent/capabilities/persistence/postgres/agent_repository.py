from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    active_agent_versions,
    agent_drafts,
    agent_version_shared_asset_refs,
    agent_versions,
    knowledge_source_versions,
    model_connection_versions,
    tool_source_versions,
)
from proof_agent.contracts.agent_configuration import (
    ActiveAgentVersion,
    DraftAgent,
    PublishedAgentVersion,
)
from proof_agent.contracts.persistence import (
    AgentDraftRecord,
    AgentPublicationRecord,
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
    PersistencePointerConflictError,
)
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


_SHARED_VERSION_TABLES = {
    SharedAssetKind.KNOWLEDGE_SOURCE: (knowledge_source_versions, "source_id"),
    SharedAssetKind.MODEL_CONNECTION: (model_connection_versions, "connection_id"),
    SharedAssetKind.TOOL_SOURCE: (tool_source_versions, "source_id"),
}


class PostgresAgentLifecycleRepository:
    """PostgreSQL Agent lifecycle adapter with conditional writes and atomic publication."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        draft_uuid = uuid_value(draft_id, field="draft_id")
        statement = sa.select(
            agent_drafts.c.draft_json,
            agent_drafts.c.revision,
        ).where(
            agent_drafts.c.agent_id == agent_id,
            agent_drafts.c.draft_id == draft_uuid,
        )
        with read_connection(self._connection_source) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        return AgentDraftRecord(
            draft=DraftAgent.model_validate(row["draft_json"]),
            revision=row["revision"],
        )

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        if expected_revision < 0:
            raise ValueError("expected_revision cannot be negative")
        draft_uuid = uuid_value(draft.draft_id, field="draft_id")
        created_at = timestamp_value(draft.created_at, field="created_at")
        updated_at = timestamp_value(draft.updated_at, field="updated_at")
        with write_connection(self._connection_source) as connection:
            if expected_revision == 0:
                insert_statement = (
                    postgres_insert(agent_drafts)
                    .values(
                        draft_id=draft_uuid,
                        agent_id=draft.agent_id,
                        revision=1,
                        draft_json=model_json(draft),
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                    .on_conflict_do_nothing(index_elements=[agent_drafts.c.draft_id])
                    .returning(agent_drafts.c.revision)
                )
                result = connection.execute(insert_statement)
            else:
                update_statement = (
                    sa.update(agent_drafts)
                    .where(
                        agent_drafts.c.draft_id == draft_uuid,
                        agent_drafts.c.agent_id == draft.agent_id,
                        agent_drafts.c.revision == expected_revision,
                    )
                    .values(
                        revision=agent_drafts.c.revision + 1,
                        draft_json=model_json(draft),
                        updated_at=updated_at,
                    )
                    .returning(agent_drafts.c.revision)
                )
                result = connection.execute(update_statement)
            next_revision = result.scalar_one_or_none()
            if next_revision is None:
                actual = connection.execute(
                    sa.select(agent_drafts.c.revision).where(
                        agent_drafts.c.draft_id == draft_uuid,
                        agent_drafts.c.agent_id == draft.agent_id,
                    )
                ).scalar_one_or_none()
                raise PersistenceConflictError(
                    resource_type="agent_draft",
                    resource_id=draft.draft_id,
                    expected_revision=expected_revision,
                    actual_revision=actual,
                )
        return AgentDraftRecord(draft=draft, revision=next_revision)

    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        if publication.draft_revision != expected_draft_revision:
            raise PersistenceInvariantError(
                "publication draft_revision must match expected_draft_revision"
            )
        version = publication.version
        version_uuid = uuid_value(version.version_id, field="version_id")
        draft_uuid = uuid_value(version.source_draft_id, field="source_draft_id")
        with write_connection(self._connection_source) as connection:
            # A transaction-scoped lock is required for the no-active-row case: a
            # SELECT FOR UPDATE cannot lock a row that does not exist yet.
            connection.execute(
                sa.select(
                    sa.func.pg_advisory_xact_lock(
                        sa.func.hashtextextended(version.agent_id, 0)
                    )
                )
            ).scalar_one()
            expectation = publication.active_pointer_expectation
            if expectation is not None:
                actual_active = connection.execute(
                    sa.select(active_agent_versions.c.version_id)
                    .where(active_agent_versions.c.agent_id == version.agent_id)
                    .with_for_update()
                ).scalar_one_or_none()
                expected_active = (
                    None
                    if expectation.version_id is None
                    else uuid_value(
                        expectation.version_id,
                        field="expected_active_version_id",
                    )
                )
                if actual_active != expected_active:
                    raise PersistencePointerConflictError(
                        resource_type="active_agent_version",
                        resource_id=version.agent_id,
                        expected_pointer=(
                            None if expected_active is None else str(expected_active)
                        ),
                        actual_pointer=(
                            None if actual_active is None else str(actual_active)
                        ),
                    )
            draft_row = connection.execute(
                sa.select(agent_drafts.c.revision, agent_drafts.c.draft_json)
                .where(
                    agent_drafts.c.draft_id == draft_uuid,
                    agent_drafts.c.agent_id == version.agent_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            actual_revision = None if draft_row is None else draft_row["revision"]
            if actual_revision != expected_draft_revision:
                raise PersistenceConflictError(
                    resource_type="agent_draft",
                    resource_id=version.source_draft_id,
                    expected_revision=expected_draft_revision,
                    actual_revision=actual_revision,
                )
            assert draft_row is not None
            persisted_draft = DraftAgent.model_validate(draft_row["draft_json"])
            if version.contract_bundle != persisted_draft.contract_bundle:
                raise PersistenceInvariantError(
                    "published Agent contract must match the revisioned Draft Agent"
                )
            existing = connection.execute(
                sa.select(agent_versions.c.version_id).where(
                    agent_versions.c.version_id == version_uuid
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise PersistenceConflictError(
                    resource_type="agent_version",
                    resource_id=version.version_id,
                    expected_revision=0,
                    actual_revision=1,
                )
            self._require_shared_asset_versions(
                connection,
                version.resolved_shared_asset_versions.versions,
            )
            connection.execute(
                sa.insert(agent_versions).values(
                    version_id=version_uuid,
                    agent_id=version.agent_id,
                    source_draft_id=draft_uuid,
                    source_draft_revision=expected_draft_revision,
                    version_json=model_json(version),
                    published_at=timestamp_value(
                        version.published_at, field="published_at"
                    ),
                    published_by=version.published_by,
                )
            )
            if version.resolved_shared_asset_versions.versions:
                connection.execute(
                    sa.insert(agent_version_shared_asset_refs),
                    [
                        {
                            "agent_version_id": version_uuid,
                            "asset_kind": item.kind.value,
                            "asset_id": item.asset_id,
                            "asset_version_id": uuid_value(
                                item.version_id, field="shared_asset_version_id"
                            ),
                            "asset_revision": item.revision,
                            "content_sha256": item.content_digest,
                        }
                        for item in version.resolved_shared_asset_versions.versions
                    ],
                )
            activation = publication.activation
            activation_insert = postgres_insert(active_agent_versions).values(
                agent_id=activation.agent_id,
                version_id=version_uuid,
                activation_json=model_json(activation),
                activated_at=timestamp_value(
                    activation.activated_at, field="activated_at"
                ),
            )
            connection.execute(
                activation_insert.on_conflict_do_update(
                    index_elements=[active_agent_versions.c.agent_id],
                    set_={
                        "version_id": activation_insert.excluded.version_id,
                        "activation_json": activation_insert.excluded.activation_json,
                        "activated_at": activation_insert.excluded.activated_at,
                    },
                )
            )
        return publication

    def get_published(
        self,
        agent_id: str,
        version_id: str,
    ) -> PublishedAgentVersion | None:
        version_uuid = uuid_value(version_id, field="version_id")
        statement = sa.select(agent_versions.c.version_json).where(
            agent_versions.c.agent_id == agent_id,
            agent_versions.c.version_id == version_uuid,
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else PublishedAgentVersion.model_validate(payload)

    def list_published(self, agent_id: str) -> tuple[PublishedAgentVersion, ...]:
        statement = (
            sa.select(agent_versions.c.version_json)
            .where(agent_versions.c.agent_id == agent_id)
            .order_by(agent_versions.c.published_at.desc(), agent_versions.c.version_id)
        )
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(statement).scalars().all()
        return tuple(PublishedAgentVersion.model_validate(payload) for payload in payloads)

    def get_active(self, agent_id: str) -> ActiveAgentVersion | None:
        statement = sa.select(active_agent_versions.c.activation_json).where(
            active_agent_versions.c.agent_id == agent_id
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else ActiveAgentVersion.model_validate(payload)

    def list_active(self) -> tuple[ActiveAgentVersion, ...]:
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(
                sa.select(active_agent_versions.c.activation_json).order_by(
                    active_agent_versions.c.agent_id
                )
            ).scalars().all()
        return tuple(ActiveAgentVersion.model_validate(payload) for payload in payloads)

    @staticmethod
    def _require_shared_asset_versions(
        connection: sa.Connection,
        references: tuple[SharedAssetVersionRef, ...],
    ) -> None:
        for reference in references:
            table, id_column_name = _SHARED_VERSION_TABLES[reference.kind]
            found = connection.execute(
                sa.select(table.c.version_id).where(
                    table.c.version_id
                    == uuid_value(reference.version_id, field="shared_asset_version_id"),
                    table.c[id_column_name] == reference.asset_id,
                    table.c.revision == reference.revision,
                    table.c.content_sha256 == reference.content_digest,
                )
            ).scalar_one_or_none()
            if found is None:
                raise PersistenceNotFoundError(
                    resource_type=f"{reference.kind.value}_version",
                    resource_id=f"{reference.asset_id}:{reference.version_id}",
                )
