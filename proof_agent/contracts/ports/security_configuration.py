from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from proof_agent.contracts.persistence import AuditMetadataRecord
from proof_agent.contracts.egress import EgressPolicyVersion
from proof_agent.contracts.security import PermissionMappingVersion


class SecurityConfigurationRepository(Protocol):
    """Version and atomically activate tenant-global security configuration."""

    def append_permission_mapping(
        self,
        version: PermissionMappingVersion,
        *,
        expected_revision: int,
    ) -> PermissionMappingVersion: ...

    def get_permission_mapping(self, version_id: str) -> PermissionMappingVersion | None: ...

    def list_permission_mappings(self) -> Sequence[PermissionMappingVersion]: ...

    def get_active_permission_mapping(self) -> PermissionMappingVersion | None: ...

    def activate_permission_mapping(
        self,
        version_id: str,
        *,
        audit_event: AuditMetadataRecord,
    ) -> PermissionMappingVersion: ...

    def permission_epoch(self) -> int: ...

    def append_egress_policy(
        self,
        version: EgressPolicyVersion,
        *,
        expected_revision: int,
    ) -> EgressPolicyVersion: ...

    def get_egress_policy(self, version_id: str) -> EgressPolicyVersion | None: ...

    def list_egress_policies(self) -> Sequence[EgressPolicyVersion]: ...

    def get_active_egress_policy(self) -> EgressPolicyVersion | None: ...

    def activate_egress_policy(
        self,
        version_id: str,
        *,
        audit_event: AuditMetadataRecord,
    ) -> EgressPolicyVersion: ...
