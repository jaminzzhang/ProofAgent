from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from proof_agent.capabilities.persistence.bundle import (
    PersistenceBundle,
    PersistenceMode,
    create_persistence_bundle,
)
from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.capabilities.identity import GuardedOidcClient, OidcProviderConfiguration
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    Permission,
    ProductionSecretHandle,
    RecoveryOidcGroupMapping,
    SecretPurpose,
)
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.control.security.egress import CompiledEgressPolicy
from proof_agent.control.security.permissions import PermissionMappingService
from proof_agent.control.security.sessions import OperatorSessionService
from proof_agent.control.security.token_cipher import TokenEnvelopeCipher


@dataclass(frozen=True)
class ProductionSecurityComposition:
    stable_origin: str
    guarded_http_client: GuardedHttpsClient
    permission_service: PermissionMappingService
    operator_session_service: OperatorSessionService
    oidc_client: GuardedOidcClient
    recovery_mapping: RecoveryOidcGroupMapping
    secret_provider: SecretProvider


def compose_production_egress_client(
    persistence: PostgresPersistenceBundle,
) -> GuardedHttpsClient:
    """Build the sole outbound HTTPS boundary from the active PostgreSQL policy."""

    active_egress = persistence.security.get_active_egress_policy()
    if active_egress is None:
        raise ValueError("an active Egress Policy is required before production startup")
    return GuardedHttpsClient(
        policy=CompiledEgressPolicy(active_egress),
        max_response_bytes=64 * 1024 * 1024,
        denial_audit_sink=lambda reason, origin: _audit_egress_denial(
            persistence,
            reason_code=reason,
            origin=origin,
        ),
    )


def compose_production_vault_secret_provider(
    guarded_http_client: GuardedHttpsClient,
    *,
    environment: Mapping[str, str] | None = None,
) -> SecretProvider:
    """Compose the exact Vault KV v2 provider without caching resolved material."""

    from proof_agent.capabilities.secrets.configured_provider import (
        load_secret_provider_compatibility,
    )
    from proof_agent.capabilities.secrets.guarded_transport import GuardedVaultJsonTransport
    from proof_agent.capabilities.secrets.provider_adapter import (
        VaultKvV2Locator,
        VaultKvV2SecretProvider,
    )

    values = os.environ if environment is None else environment
    compatibility = load_secret_provider_compatibility(
        Path(_required(values, "PROOF_AGENT_SECRET_PROVIDER_COMPATIBILITY_INPUT"))
    )
    raw_handles = _json_object(
        _required(values, "PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON"),
        label="Secret Handle locator mapping",
    )
    handles: dict[str, VaultKvV2Locator] = {}
    for handle_id, payload in raw_handles.items():
        if not isinstance(handle_id, str) or not handle_id or not isinstance(payload, dict):
            raise ValueError("Secret Handle locator mapping is invalid")
        if set(payload) != {"mount", "path", "field"}:
            raise ValueError("Secret Handle locator mapping is invalid")
        try:
            handles[handle_id] = VaultKvV2Locator(
                mount=str(payload["mount"]),
                path=str(payload["path"]),
                field=str(payload["field"]),
            )
        except (KeyError, ValueError) as exc:
            raise ValueError("Secret Handle locator mapping is invalid") from exc
    if not handles or len(handles) > 256:
        raise ValueError("Secret Handle locator mapping is invalid")
    token_path = Path(_required(values, "PROOF_AGENT_VAULT_AGENT_TOKEN_FILE"))
    return VaultKvV2SecretProvider(
        GuardedVaultJsonTransport(
            guarded_http_client,
            endpoint_origin=str(compatibility.endpoint_origin).rstrip("/"),
        ),
        token_supplier=lambda: _read_vault_agent_token(token_path),
        handles=handles,
    )


def compose_application_persistence(
    *,
    environment: Mapping[str, str] | None = None,
    development_root: Path | None = None,
) -> PersistenceBundle:
    """Build application persistence from an explicit deployment mode."""

    values = os.environ if environment is None else environment
    raw_mode = values.get("PROOF_AGENT_MODE", "").strip()
    if not raw_mode:
        raise ValueError("PROOF_AGENT_MODE=development|production is required")
    try:
        mode = PersistenceMode(raw_mode)
    except ValueError as exc:
        raise ValueError("PROOF_AGENT_MODE must be development or production") from exc
    root = development_root
    if root is None and mode is PersistenceMode.DEVELOPMENT:
        raw_root = values.get("PROOF_AGENT_DEVELOPMENT_STATE_DIR", "").strip()
        if not raw_root:
            raise ValueError(
                "PROOF_AGENT_DEVELOPMENT_STATE_DIR is required in development mode"
            )
        root = Path(raw_root)
    return create_persistence_bundle(
        mode=mode,
        development_root=root,
        postgres_dsn=values.get("PROOF_AGENT_POSTGRES_DSN"),
    )


def compose_production_security(
    persistence: PostgresPersistenceBundle,
    secret_provider: SecretProvider,
    *,
    environment: Mapping[str, str] | None = None,
    guarded_http_client: GuardedHttpsClient | None = None,
) -> ProductionSecurityComposition:
    """Compose the production security graph with no local or network fallback."""

    values = os.environ if environment is None else environment
    if values.get("PROOF_AGENT_MODE", "").strip() != "production":
        raise ValueError("production security composition requires PROOF_AGENT_MODE=production")
    guarded_client = guarded_http_client or compose_production_egress_client(persistence)
    recovery = RecoveryOidcGroupMapping(
        claim_path=_required(values, "PROOF_AGENT_RECOVERY_GROUP_CLAIM"),
        group_name=_required(values, "PROOF_AGENT_RECOVERY_GROUP_NAME"),
        permissions=(
            Permission.PERMISSION_MAPPING_VIEW,
            Permission.PERMISSION_MAPPING_EDIT,
            Permission.AUDIT_VIEW,
        ),
    )
    permission_service = PermissionMappingService(
        persistence.security,
        recovery_mapping=recovery,
    )
    envelope_handle_ids = _string_mapping(
        _required(values, "PROOF_AGENT_SESSION_ENVELOPE_KEY_HANDLES_JSON")
    )
    active_key_version = _required(values, "PROOF_AGENT_SESSION_ACTIVE_KEY_VERSION")
    envelope_keys = {
        key_version: _resolve_secret(
            secret_provider,
            handle_id=handle_id,
            purpose=SecretPurpose.SESSION_ENVELOPE_KEY,
        )
        for key_version, handle_id in envelope_handle_ids.items()
    }
    csrf_key = _resolve_secret(
        secret_provider,
        handle_id=_required(values, "PROOF_AGENT_CSRF_KEY_HANDLE"),
        purpose=SecretPurpose.SESSION_ENVELOPE_KEY,
    )
    oidc_secret = _resolve_secret(
        secret_provider,
        handle_id=_required(values, "PROOF_AGENT_OIDC_CLIENT_SECRET_HANDLE"),
        purpose=SecretPurpose.OIDC_CLIENT_SECRET,
    )
    oidc_client = GuardedOidcClient(
        guarded_client,
        configuration=OidcProviderConfiguration(
            issuer=_required(values, "PROOF_AGENT_OIDC_ISSUER"),
            authorization_endpoint=_required(
                values, "PROOF_AGENT_OIDC_AUTHORIZATION_ENDPOINT"
            ),
            token_endpoint=_required(values, "PROOF_AGENT_OIDC_TOKEN_ENDPOINT"),
            jwks_uri=_required(values, "PROOF_AGENT_OIDC_JWKS_URI"),
            client_id=_required(values, "PROOF_AGENT_OIDC_CLIENT_ID"),
            groups_claim=values.get("PROOF_AGENT_OIDC_GROUPS_CLAIM", "groups").strip(),
            roles_claim=values.get("PROOF_AGENT_OIDC_ROLES_CLAIM", "roles").strip(),
        ),
        client_secret=oidc_secret,
    )
    session_service = OperatorSessionService(
        persistence.sessions,
        oidc_client,
        TokenEnvelopeCipher(
            active_key_version=active_key_version,
            keys=envelope_keys,
        ),
        permission_service,
        csrf_key=csrf_key,
    )
    return ProductionSecurityComposition(
        stable_origin=_required(values, "PROOF_AGENT_STABLE_ORIGIN"),
        guarded_http_client=guarded_client,
        permission_service=permission_service,
        operator_session_service=session_service,
        oidc_client=oidc_client,
        recovery_mapping=recovery,
        secret_provider=secret_provider,
    )


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required in production")
    return value


def _string_mapping(value: str) -> dict[str, str]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("session envelope key handle mapping must be valid JSON") from exc
    if (
        not isinstance(payload, dict)
        or not payload
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(item, str)
            or not item
            for key, item in payload.items()
        )
    ):
        raise ValueError("session envelope key handle mapping is invalid")
    return payload


def _json_object(value: str, *, label: str) -> dict[str, object]:
    if len(value.encode("utf-8")) > 256 * 1024:
        raise ValueError(f"{label} exceeds its byte limit")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _read_vault_agent_token(path: Path) -> str:
    if path.is_symlink():
        raise ValueError("Vault Agent token file cannot be a symlink")
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise ValueError("Vault Agent token file is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_mode & 0o077:
        raise ValueError("Vault Agent token file permissions are unsafe")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("Vault Agent token file is unavailable") from exc
    if not 1 <= len(payload) <= 16 * 1024 or b"\x00" in payload:
        raise ValueError("Vault Agent token file is invalid")
    try:
        token = payload.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Vault Agent token file is invalid") from exc
    if not token or any(char.isspace() for char in token):
        raise ValueError("Vault Agent token file is invalid")
    return token


def _resolve_secret(
    provider: SecretProvider,
    *,
    handle_id: str,
    purpose: SecretPurpose,
) -> bytes:
    return provider.resolve(
        ProductionSecretHandle(
            protocol_id=provider.protocol_id,
            handle_id=handle_id,
            purpose=purpose,
        )
    ).reveal_for_use()


def _audit_egress_denial(
    persistence: PostgresPersistenceBundle,
    *,
    reason_code: str,
    origin: str | None,
) -> None:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    persistence.audit.append(
        AuditMetadataRecord(
            audit_id=str(uuid4()),
            category=AuditCategory.SECURITY,
            event_type="egress.denied",
            outcome=AuditOutcome.DENIED,
            actor=AuditActorFacts(
                subject="proof-agent-runtime",
                identity_provider="workload-identity",
                session_id="system",
            ),
            occurred_at=now,
            target_type="https_origin",
            target_id=origin or "unparsed",
            metadata={"reason_code": reason_code},
        )
    )
