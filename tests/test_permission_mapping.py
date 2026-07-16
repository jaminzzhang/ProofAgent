from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.security_repository import (
    PostgresSecurityConfigurationRepository,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    OidcPrincipal,
    Permission,
    PermissionClaimRule,
    PermissionMappingVersion,
    RecoveryOidcGroupMapping,
    PersistenceConflictError,
)
from proof_agent.contracts import InstitutionAuthorizationContext
from proof_agent.control.security.permissions import PermissionMappingService


pytest_plugins = ("postgres_fixtures",)


@dataclass
class FakeSecurityRepository:
    versions: list[PermissionMappingVersion] = field(default_factory=list)
    active: PermissionMappingVersion | None = None
    epoch: int = 0

    def append_permission_mapping(
        self,
        version: PermissionMappingVersion,
        *,
        expected_revision: int,
    ) -> PermissionMappingVersion:
        assert len(self.versions) == expected_revision
        self.versions.append(version)
        return version

    def get_permission_mapping(self, version_id: str) -> PermissionMappingVersion | None:
        return next((item for item in self.versions if item.version_id == version_id), None)

    def list_permission_mappings(self) -> tuple[PermissionMappingVersion, ...]:
        return tuple(reversed(self.versions))

    def get_active_permission_mapping(self) -> PermissionMappingVersion | None:
        return self.active

    def activate_permission_mapping(
        self,
        version_id: str,
        *,
        audit_event: AuditMetadataRecord,
    ) -> PermissionMappingVersion:
        del audit_event
        selected = self.get_permission_mapping(version_id)
        assert selected is not None
        self.active = selected
        self.epoch += 1
        return selected

    def permission_epoch(self) -> int:
        return self.epoch


def recovery_mapping() -> RecoveryOidcGroupMapping:
    return RecoveryOidcGroupMapping(
        claim_path="groups",
        group_name="proof-agent-recovery",
        permissions=(
            Permission.PERMISSION_MAPPING_VIEW,
            Permission.PERMISSION_MAPPING_EDIT,
            Permission.AUDIT_VIEW,
        ),
    )


def principal(
    *,
    groups: tuple[str, ...] = (),
    roles: tuple[str, ...] = (),
) -> OidcPrincipal:
    return OidcPrincipal(
        subject="oidc-subject-1",
        issuer="https://identity.example.com",
        audience="proof-agent",
        display_name="Operator One",
        trusted_groups=groups,
        trusted_roles=roles,
        authenticated_at="2026-07-15T00:00:00Z",
        claims_verified_at="2026-07-15T00:00:00Z",
    )


def mapping(
    *,
    version_id: str,
    revision: int,
    rules: tuple[PermissionClaimRule, ...],
) -> PermissionMappingVersion:
    return PermissionMappingVersion(
        version_id=version_id,
        revision=revision,
        rules=rules,
        created_at=f"2026-07-15T00:0{revision}:00Z",
        created_by="security-admin",
    )


def audit_event(*, audit_id: str, target_id: str) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=audit_id,
        category=AuditCategory.SECURITY,
        event_type="permission_mapping.activated",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="security-admin",
            identity_provider="enterprise-oidc",
            session_id="session-1",
            permissions=(Permission.PERMISSION_MAPPING_EDIT.value,),
        ),
        occurred_at="2026-07-15T00:10:00Z",
        target_type="permission_mapping_version",
        target_id=target_id,
    )


def test_permission_mapping_defaults_to_deny_and_unions_all_trusted_matches() -> None:
    repository = FakeSecurityRepository()
    service = PermissionMappingService(repository, recovery_mapping=recovery_mapping())
    selected = mapping(
        version_id="019ba001-1111-7000-8000-000000000201",
        revision=1,
        rules=(
            PermissionClaimRule(
                claim_path="groups",
                claim_value="insurance-ops",
                permissions=(Permission.RUN_SUBMIT, Permission.RUN_VIEW),
            ),
            PermissionClaimRule(
                claim_path="roles",
                claim_value="knowledge-editor",
                permissions=(Permission.KNOWLEDGE_SOURCE_EDIT,),
            ),
        ),
    )
    repository.versions.append(selected)
    repository.active = selected

    assert service.effective_permissions(principal()) == frozenset()
    assert service.effective_permissions(
        principal(groups=("insurance-ops",), roles=("knowledge-editor",))
    ) == frozenset(
        {Permission.RUN_SUBMIT, Permission.RUN_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}
    )


def test_permission_mapping_derives_server_side_institution_authorization_union() -> None:
    repository = FakeSecurityRepository()
    service = PermissionMappingService(repository, recovery_mapping=recovery_mapping())
    selected = mapping(
        version_id="019ba001-1111-7000-8000-000000000203",
        revision=1,
        rules=(
            PermissionClaimRule(
                claim_path="groups",
                claim_value="shanghai-specialists",
                institution_authorization=InstitutionAuthorizationContext(
                    institutions=("branch-shanghai",),
                    regions=("CN-SH",),
                    roles=("institution-specialist",),
                ),
            ),
            PermissionClaimRule(
                claim_path="roles",
                claim_value="health-insurance",
                institution_authorization=InstitutionAuthorizationContext(
                    business_lines=("health",),
                    channels=("agency",),
                ),
            ),
        ),
    )
    repository.versions.append(selected)
    repository.active = selected

    authorization = service.institution_authorization(
        principal(
            groups=("shanghai-specialists",),
            roles=("health-insurance",),
        )
    )

    assert authorization == InstitutionAuthorizationContext(
        institutions=("branch-shanghai",),
        regions=("CN-SH",),
        channels=("agency",),
        roles=("institution-specialist",),
        business_lines=("health",),
    )
    assert service.institution_authorization(principal()).public_only is True


def test_recovery_group_is_always_union_granted_and_cannot_be_replaced() -> None:
    repository = FakeSecurityRepository()
    service = PermissionMappingService(repository, recovery_mapping=recovery_mapping())
    assert service.effective_permissions(
        principal(groups=("proof-agent-recovery",))
    ) >= frozenset(recovery_mapping().permissions)

    reserved = mapping(
        version_id="019ba001-1111-7000-8000-000000000202",
        revision=1,
        rules=(
            PermissionClaimRule(
                claim_path="groups",
                claim_value="proof-agent-recovery",
                permissions=(Permission.RUN_VIEW,),
            ),
        ),
    )
    with pytest.raises(ValueError, match="deployment-owned"):
        service.append_mapping(reserved, expected_revision=0)
    assert repository.versions == []


@pytest.mark.postgres_integration
def test_postgres_permission_mapping_activation_audit_and_rollback_are_atomic(
    postgres_engine: Engine,
) -> None:
    repository = PostgresSecurityConfigurationRepository(postgres_engine)
    service = PermissionMappingService(repository, recovery_mapping=recovery_mapping())
    first = mapping(
        version_id="019ba001-1111-7000-8000-000000000211",
        revision=1,
        rules=(
            PermissionClaimRule(
                claim_path="groups",
                claim_value="operators",
                permissions=(Permission.RUN_VIEW,),
            ),
        ),
    )
    second = mapping(
        version_id="019ba001-1111-7000-8000-000000000212",
        revision=2,
        rules=(
            PermissionClaimRule(
                claim_path="groups",
                claim_value="operators",
                permissions=(Permission.RUN_VIEW, Permission.RUN_SUBMIT),
            ),
        ),
    )
    service.append_mapping(first, expected_revision=0)
    service.append_mapping(second, expected_revision=1)
    first_audit = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000213",
        target_id=first.version_id,
    )
    second_audit = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000214",
        target_id=second.version_id,
    )
    rollback_audit = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000215",
        target_id=first.version_id,
    )

    service.activate_mapping(first.version_id, audit_event=first_audit)
    service.activate_mapping(second.version_id, audit_event=second_audit)
    service.activate_mapping(first.version_id, audit_event=rollback_audit)

    assert repository.get_active_permission_mapping() == first
    assert repository.permission_epoch() == 3
    assert PostgresAuditRepository(postgres_engine).get(rollback_audit.audit_id) == (
        rollback_audit
    )


@pytest.mark.postgres_integration
def test_postgres_permission_activation_rolls_back_pointer_when_audit_conflicts(
    postgres_engine: Engine,
) -> None:
    repository = PostgresSecurityConfigurationRepository(postgres_engine)
    service = PermissionMappingService(repository, recovery_mapping=recovery_mapping())
    first = mapping(
        version_id="019ba001-1111-7000-8000-000000000221",
        revision=1,
        rules=(),
    )
    second = mapping(
        version_id="019ba001-1111-7000-8000-000000000222",
        revision=2,
        rules=(),
    )
    service.append_mapping(first, expected_revision=0)
    service.append_mapping(second, expected_revision=1)
    event = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000223",
        target_id=first.version_id,
    )
    service.activate_mapping(first.version_id, audit_event=event)

    with pytest.raises(PersistenceConflictError):
        service.activate_mapping(second.version_id, audit_event=event)

    assert repository.get_active_permission_mapping() == first
    assert repository.permission_epoch() == 1
