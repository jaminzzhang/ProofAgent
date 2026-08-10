from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from proof_agent.capabilities.persistence.postgres.hybrid_ingestion_repository import (
    PostgresHybridIngestionRepository,
)
from proof_agent.contracts import (
    InstitutionAuthorizationContext,
    Permission,
    PermissionClaimRule,
    PermissionMappingVersion,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _local_module(filename: str) -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / filename
    spec = importlib.util.spec_from_file_location(
        f"proof_agent_test_{path.stem}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SecurityAuthority:
    def __init__(self, legacy: PermissionMappingVersion) -> None:
        self.legacy = legacy
        self.appended: PermissionMappingVersion | None = None
        self.appended_expected_revision: int | None = None
        self.activated: str | None = None

    def get_permission_mapping(self, version_id: str) -> PermissionMappingVersion | None:
        if self.appended is not None and self.appended.version_id == version_id:
            return self.appended
        if self.legacy.version_id == version_id:
            return self.legacy
        return None

    def list_permission_mappings(self) -> tuple[PermissionMappingVersion, ...]:
        return (self.legacy,) if self.appended is None else (self.appended, self.legacy)

    def append_permission_mapping(
        self,
        version: PermissionMappingVersion,
        *,
        expected_revision: int,
    ) -> None:
        self.appended = version
        self.appended_expected_revision = expected_revision

    def get_active_permission_mapping(self) -> PermissionMappingVersion:
        return self.legacy

    def activate_permission_mapping(self, version_id: str, **_: Any) -> None:
        self.activated = version_id


def test_security_bootstrap_upgrades_legacy_admin_permissions_immutably() -> None:
    bootstrap = _local_module("bootstrap_security.py")
    legacy_permissions = tuple(
        permission
        for permission in Permission
        if permission is not Permission.KNOWLEDGE_SOURCE_REVIEW
    )
    legacy = PermissionMappingVersion(
        version_id="019ba100-0000-7000-8000-000000000001",
        revision=1,
        rules=(
            PermissionClaimRule(
                claim_path="roles",
                claim_value="proof-agent-admin",
                permissions=legacy_permissions,
                institution_authorization=InstitutionAuthorizationContext(
                    institutions=("local-branch",),
                    regions=("LOCAL",),
                    channels=("LOCAL",),
                    roles=("ADMIN",),
                    business_lines=("INSURANCE",),
                    public_only=False,
                ),
            ),
        ),
        created_at="2026-07-01T00:00:00Z",
        created_by="legacy-local-bootstrap",
    )
    security = _SecurityAuthority(legacy)

    bootstrap._bootstrap_permissions(SimpleNamespace(security=security))

    assert security.appended is not None
    assert security.appended.version_id != legacy.version_id
    assert security.appended.revision == 2
    assert security.appended_expected_revision == 1
    assert security.appended.rules[0].permissions == tuple(Permission)
    assert security.activated == security.appended.version_id


class _ReferenceMetadataAuthority:
    def __init__(self) -> None:
        self.published: tuple[object, str, str] | None = None
        self.bound: dict[str, object] | None = None

    def publish_profile(
        self,
        profile: object,
        *,
        display_name: str,
        actor: str,
    ) -> object:
        self.published = (profile, display_name, actor)
        return profile

    def bind_source_profile(self, **kwargs: object) -> object:
        self.bound = kwargs
        return self.published[0] if self.published is not None else object()


def test_reference_metadata_bootstrap_binds_only_the_designated_local_fixture() -> None:
    bootstrap = _local_module("bootstrap_reference_metadata.py")
    metadata = _ReferenceMetadataAuthority()
    bundle = SimpleNamespace(
        knowledge=SimpleNamespace(
            get_source_record=lambda source_id: (
                object() if source_id == "ks_insurance" else None
            )
        ),
        metadata_reviews=metadata,
    )

    bootstrap.bootstrap_reference_metadata(bundle)

    assert metadata.published is not None
    profile, display_name, actor = metadata.published
    assert profile.profile_revision_id == "proofagent-insurance-reference.v1"
    assert profile.reference_only is True
    assert display_name == "Proof Agent insurance reference"
    assert actor == "local-production-bootstrap"
    assert metadata.bound == {
        "source_id": "ks_insurance",
        "profile_revision_id": "proofagent-insurance-reference.v1",
        "actor": "local-production-bootstrap",
        "production": False,
    }


def test_reference_profile_allowlist_is_exact_and_fail_closed() -> None:
    repository = PostgresHybridIngestionRepository(object())

    assert repository._metadata_profile_requires_production("ks_insurance") is True

    repository.configure_reference_profile_source_ids(("ks_insurance",))

    assert repository._metadata_profile_requires_production("ks_insurance") is False
    assert repository._metadata_profile_requires_production("ks_other") is True

    with pytest.raises(ValueError, match="already configured"):
        repository.configure_reference_profile_source_ids(("ks_other",))
