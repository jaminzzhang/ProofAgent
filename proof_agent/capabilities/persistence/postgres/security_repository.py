from __future__ import annotations

from datetime import UTC, datetime

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
from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    active_egress_policy,
    active_permission_mapping,
    egress_policy_versions,
    permission_mapping_versions,
    security_configuration_state,
)
from proof_agent.contracts.egress import EgressPolicyVersion
from proof_agent.contracts.persistence import (
    AuditMetadataRecord,
    PersistenceConflictError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.security import PermissionMappingVersion


class PostgresSecurityConfigurationRepository:
    """Versioned security authority with locked activation and audit transaction."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def append_permission_mapping(
        self,
        version: PermissionMappingVersion,
        *,
        expected_revision: int,
    ) -> PermissionMappingVersion:
        if version.revision != expected_revision + 1:
            raise ValueError("permission mapping revision must increment exactly once")
        with write_connection(self._connection_source) as connection:
            state = connection.execute(
                sa.select(security_configuration_state.c.permission_mapping_revision)
                .where(security_configuration_state.c.singleton.is_(True))
                .with_for_update()
            ).scalar_one()
            if int(state) != expected_revision:
                raise PersistenceConflictError(
                    resource_type="permission_mapping",
                    resource_id=version.version_id,
                    expected_revision=expected_revision,
                    actual_revision=int(state),
                )
            connection.execute(
                sa.insert(permission_mapping_versions).values(
                    version_id=uuid_value(version.version_id, field="version_id"),
                    revision=version.revision,
                    mapping_json=model_json(version),
                    created_at=timestamp_value(version.created_at, field="created_at"),
                    created_by=version.created_by,
                )
            )
            connection.execute(
                sa.update(security_configuration_state)
                .where(security_configuration_state.c.singleton.is_(True))
                .values(
                    permission_mapping_revision=version.revision,
                    updated_at=timestamp_value(version.created_at, field="created_at"),
                )
            )
        return version

    def get_permission_mapping(self, version_id: str) -> PermissionMappingVersion | None:
        statement = sa.select(permission_mapping_versions.c.mapping_json).where(
            permission_mapping_versions.c.version_id
            == uuid_value(version_id, field="version_id")
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else PermissionMappingVersion.model_validate(payload)

    def list_permission_mappings(self) -> tuple[PermissionMappingVersion, ...]:
        statement = sa.select(permission_mapping_versions.c.mapping_json).order_by(
            permission_mapping_versions.c.revision.desc()
        )
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(statement).scalars().all()
        return tuple(PermissionMappingVersion.model_validate(item) for item in payloads)

    def get_active_permission_mapping(self) -> PermissionMappingVersion | None:
        statement = sa.select(permission_mapping_versions.c.mapping_json).join(
            active_permission_mapping,
            active_permission_mapping.c.version_id == permission_mapping_versions.c.version_id,
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else PermissionMappingVersion.model_validate(payload)

    def activate_permission_mapping(
        self,
        version_id: str,
        *,
        audit_event: AuditMetadataRecord,
    ) -> PermissionMappingVersion:
        version_uuid = uuid_value(version_id, field="version_id")
        with write_connection(self._connection_source) as connection:
            state = connection.execute(
                sa.select(security_configuration_state.c.permission_epoch)
                .where(security_configuration_state.c.singleton.is_(True))
                .with_for_update()
            ).scalar_one()
            payload = connection.execute(
                sa.select(permission_mapping_versions.c.mapping_json).where(
                    permission_mapping_versions.c.version_id == version_uuid
                )
            ).scalar_one_or_none()
            if payload is None:
                raise PersistenceNotFoundError(
                    resource_type="permission_mapping_version", resource_id=version_id
                )
            version = PermissionMappingVersion.model_validate(payload)
            activation = postgres_insert(active_permission_mapping).values(
                singleton=True,
                version_id=version_uuid,
                activated_at=datetime.now(UTC),
            )
            connection.execute(
                activation.on_conflict_do_update(
                    index_elements=[active_permission_mapping.c.singleton],
                    set_={
                        "version_id": activation.excluded.version_id,
                        "activated_at": activation.excluded.activated_at,
                    },
                )
            )
            connection.execute(
                sa.update(security_configuration_state)
                .where(security_configuration_state.c.singleton.is_(True))
                .values(permission_epoch=int(state) + 1, updated_at=datetime.now(UTC))
            )
            PostgresAuditRepository(connection).append(audit_event)
        return version

    def permission_epoch(self) -> int:
        statement = sa.select(security_configuration_state.c.permission_epoch).where(
            security_configuration_state.c.singleton.is_(True)
        )
        with read_connection(self._connection_source) as connection:
            return int(connection.execute(statement).scalar_one())

    def append_egress_policy(
        self,
        version: EgressPolicyVersion,
        *,
        expected_revision: int,
    ) -> EgressPolicyVersion:
        if version.revision != expected_revision + 1:
            raise ValueError("egress policy revision must increment exactly once")
        with write_connection(self._connection_source) as connection:
            state = connection.execute(
                sa.select(security_configuration_state.c.egress_policy_revision)
                .where(security_configuration_state.c.singleton.is_(True))
                .with_for_update()
            ).scalar_one()
            if int(state) != expected_revision:
                raise PersistenceConflictError(
                    resource_type="egress_policy",
                    resource_id=version.version_id,
                    expected_revision=expected_revision,
                    actual_revision=int(state),
                )
            connection.execute(
                sa.insert(egress_policy_versions).values(
                    version_id=uuid_value(version.version_id, field="version_id"),
                    revision=version.revision,
                    policy_json=model_json(version),
                    created_at=timestamp_value(version.created_at, field="created_at"),
                    created_by=version.created_by,
                )
            )
            connection.execute(
                sa.update(security_configuration_state)
                .where(security_configuration_state.c.singleton.is_(True))
                .values(
                    egress_policy_revision=version.revision,
                    updated_at=timestamp_value(version.created_at, field="created_at"),
                )
            )
        return version

    def get_egress_policy(self, version_id: str) -> EgressPolicyVersion | None:
        statement = sa.select(egress_policy_versions.c.policy_json).where(
            egress_policy_versions.c.version_id
            == uuid_value(version_id, field="version_id")
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else EgressPolicyVersion.model_validate(payload)

    def list_egress_policies(self) -> tuple[EgressPolicyVersion, ...]:
        statement = sa.select(egress_policy_versions.c.policy_json).order_by(
            egress_policy_versions.c.revision.desc()
        )
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(statement).scalars().all()
        return tuple(EgressPolicyVersion.model_validate(item) for item in payloads)

    def get_active_egress_policy(self) -> EgressPolicyVersion | None:
        statement = sa.select(egress_policy_versions.c.policy_json).join(
            active_egress_policy,
            active_egress_policy.c.version_id == egress_policy_versions.c.version_id,
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else EgressPolicyVersion.model_validate(payload)

    def activate_egress_policy(
        self,
        version_id: str,
        *,
        audit_event: AuditMetadataRecord,
    ) -> EgressPolicyVersion:
        version_uuid = uuid_value(version_id, field="version_id")
        with write_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(egress_policy_versions.c.policy_json).where(
                    egress_policy_versions.c.version_id == version_uuid
                )
            ).scalar_one_or_none()
            if payload is None:
                raise PersistenceNotFoundError(
                    resource_type="egress_policy_version",
                    resource_id=version_id,
                )
            version = EgressPolicyVersion.model_validate(payload)
            activation = postgres_insert(active_egress_policy).values(
                singleton=True,
                version_id=version_uuid,
                activated_at=datetime.now(UTC),
            )
            connection.execute(
                activation.on_conflict_do_update(
                    index_elements=[active_egress_policy.c.singleton],
                    set_={
                        "version_id": activation.excluded.version_id,
                        "activated_at": activation.excluded.activated_at,
                    },
                )
            )
            PostgresAuditRepository(connection).append(audit_event)
        return version
