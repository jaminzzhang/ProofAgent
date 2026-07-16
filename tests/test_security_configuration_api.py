from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.contracts import (
    AuditMetadataRecord,
    EgressPolicyVersion,
    Permission,
    PermissionMappingVersion,
    ProductionSecretHandle,
    RecoveryOidcGroupMapping,
    SecretHandleValidation,
    SecretPurpose,
)
from proof_agent.delivery.security_configuration_api import router
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


@dataclass
class InMemorySecurityRepository:
    permission_versions: list[PermissionMappingVersion] = field(default_factory=list)
    egress_versions: list[EgressPolicyVersion] = field(default_factory=list)
    active_permission: PermissionMappingVersion | None = None
    active_egress: EgressPolicyVersion | None = None
    epoch: int = 0
    audits: list[AuditMetadataRecord] = field(default_factory=list)

    def append_permission_mapping(
        self, version: PermissionMappingVersion, *, expected_revision: int
    ) -> PermissionMappingVersion:
        assert expected_revision == len(self.permission_versions)
        self.permission_versions.append(version)
        return version

    def get_permission_mapping(self, version_id: str) -> PermissionMappingVersion | None:
        return next(
            (item for item in self.permission_versions if item.version_id == version_id),
            None,
        )

    def list_permission_mappings(self) -> tuple[PermissionMappingVersion, ...]:
        return tuple(reversed(self.permission_versions))

    def get_active_permission_mapping(self) -> PermissionMappingVersion | None:
        return self.active_permission

    def activate_permission_mapping(
        self, version_id: str, *, audit_event: AuditMetadataRecord
    ) -> PermissionMappingVersion:
        selected = self.get_permission_mapping(version_id)
        assert selected is not None
        self.active_permission = selected
        self.epoch += 1
        self.audits.append(audit_event)
        return selected

    def permission_epoch(self) -> int:
        return self.epoch

    def append_egress_policy(
        self, version: EgressPolicyVersion, *, expected_revision: int
    ) -> EgressPolicyVersion:
        assert expected_revision == len(self.egress_versions)
        self.egress_versions.append(version)
        return version

    def get_egress_policy(self, version_id: str) -> EgressPolicyVersion | None:
        return next(
            (item for item in self.egress_versions if item.version_id == version_id),
            None,
        )

    def list_egress_policies(self) -> tuple[EgressPolicyVersion, ...]:
        return tuple(reversed(self.egress_versions))

    def get_active_egress_policy(self) -> EgressPolicyVersion | None:
        return self.active_egress

    def activate_egress_policy(
        self, version_id: str, *, audit_event: AuditMetadataRecord
    ) -> EgressPolicyVersion:
        selected = self.get_egress_policy(version_id)
        assert selected is not None
        self.active_egress = selected
        self.audits.append(audit_event)
        return selected


class MetadataOnlySecretProvider:
    protocol_id = "hashicorp-vault-2.0-kv-v2"

    def validate(
        self, handle: ProductionSecretHandle, *, checked_at: str
    ) -> SecretHandleValidation:
        return SecretHandleValidation(
            handle=handle,
            resolvable=True,
            provider_version_id="7",
            checked_at=checked_at,
        )


class StaticIdentityProvider:
    def __init__(self, permissions: frozenset[Permission]) -> None:
        self._permissions = permissions

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="security-admin",
            display_name="Security Admin",
            permissions=self._permissions,
        )


def application(*, permissions: frozenset[Permission] | None = None):
    app = FastAPI()
    repository = InMemorySecurityRepository()
    app.state.security_configuration_repository = repository
    app.state.secret_provider = MetadataOnlySecretProvider()
    app.state.recovery_oidc_group_mapping = RecoveryOidcGroupMapping(
        claim_path="groups",
        group_name="proof-agent-recovery",
        permissions=(
            Permission.PERMISSION_MAPPING_VIEW,
            Permission.PERMISSION_MAPPING_EDIT,
            Permission.AUDIT_VIEW,
        ),
    )
    app.state.operator_identity_provider = StaticIdentityProvider(
        permissions if permissions is not None else frozenset(Permission)
    )
    app.include_router(router, prefix="/api")
    return app, repository


def test_permission_mapping_api_exposes_immutable_recovery_and_activates_with_audit() -> None:
    app, repository = application()
    client = TestClient(app)
    created = client.post(
        "/api/security/permission-mappings",
        json={
            "version_id": "019ba001-1111-7000-8000-000000000501",
            "expected_revision": 0,
            "rules": [
                {
                    "claim_path": "groups",
                    "claim_value": "operators",
                    "permissions": ["run.view"],
                }
            ],
        },
    )
    assert created.status_code == 201
    version_id = created.json()["version_id"]
    assert client.post(
        f"/api/security/permission-mappings/{version_id}/activate"
    ).status_code == 200

    listed = client.get("/api/security/permission-mappings").json()
    assert listed["active"]["version_id"] == version_id
    assert listed["recovery_mapping"]["group_name"] == "proof-agent-recovery"
    assert repository.audits[-1].event_type == "permission_mapping.activated"

    immutable = client.post(
        "/api/security/permission-mappings",
        json={
            "version_id": "019ba001-1111-7000-8000-000000000502",
            "expected_revision": 1,
            "rules": [
                {
                    "claim_path": "groups",
                    "claim_value": "proof-agent-recovery",
                    "permissions": ["run.view"],
                }
            ],
        },
    )
    assert immutable.status_code == 422


def test_egress_policy_api_versions_and_activates_exact_rules() -> None:
    app, repository = application()
    client = TestClient(app)
    created = client.post(
        "/api/security/egress-policies",
        json={
            "version_id": "019ba001-1111-7000-8000-000000000511",
            "expected_revision": 0,
            "rules": [
                {
                    "origin": {"host": "api.example.com", "port": 443},
                    "allowed_ip_networks": ["203.0.113.0/24"],
                }
            ],
        },
    )
    assert created.status_code == 201
    version_id = created.json()["version_id"]
    assert client.post(
        f"/api/security/egress-policies/{version_id}/activate"
    ).status_code == 200
    assert client.get("/api/security/egress-policies").json()["active"][
        "version_id"
    ] == version_id
    assert repository.audits[-1].event_type == "egress_policy.activated"


def test_secret_handle_validation_returns_metadata_never_resolved_material() -> None:
    app, _ = application()
    response = TestClient(app).post(
        "/api/security/secret-handles/validate",
        json={
            "handle": {
                "protocol_id": "hashicorp-vault-2.0-kv-v2",
                "handle_id": "model-answer-credential",
                "purpose": SecretPurpose.MODEL_CREDENTIAL.value,
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["provider_version_id"] == "7"
    assert "value" not in response.text
    assert "secret" not in response.text.lower().replace("secret_handle", "")


def test_security_configuration_api_enforces_backend_permissions() -> None:
    app, _ = application(permissions=frozenset({Permission.EGRESS_POLICY_VIEW}))
    client = TestClient(app)

    assert client.get("/api/security/egress-policies").status_code == 200
    assert client.get("/api/security/permission-mappings").status_code == 403
    assert client.post(
        "/api/security/secret-handles/validate",
        json={
            "handle": {
                "protocol_id": "hashicorp-vault-2.0-kv-v2",
                "handle_id": "credential",
                "purpose": "tool_credential",
            }
        },
    ).status_code == 403
