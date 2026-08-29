"""Versioned HTTP snapshot configuration and its safe management projection."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, field_validator

from knowledge_source_service.contracts.base import StrictContract
from knowledge_source_service.contracts.results import Sha256Digest


ProfileIdentifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


class ProfileContract(StrictContract):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)


class VersionedConnectionSecretHandle(ProfileContract):
    handle_id: ProfileIdentifier
    version: int = Field(strict=True, ge=1)


class HttpSnapshotProfile(ProfileContract):
    """Server-side input; never serialize this as a browser response."""

    kind: Literal["http_json"]
    endpoint: str = Field(min_length=1, max_length=2048, repr=False)
    credential: VersionedConnectionSecretHandle | None = Field(default=None, repr=False)
    egress_policy_id: ProfileIdentifier = Field(repr=False)
    trust_root_id: ProfileIdentifier = Field(repr=False)
    max_response_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)

    @field_validator("endpoint")
    @classmethod
    def require_credential_free_https_endpoint(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
            valid = (
                parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.path.startswith("/")
                and parsed.path != "/"
                and not parsed.query
                and not parsed.fragment
                and (port is None or port > 0)
                and "\\" not in value
                and not any(character.isspace() or ord(character) < 32 for character in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("HTTP snapshot endpoint is invalid")
        return value


class ConnectionProfileDraft(ProfileContract):
    knowledge_space_id: ProfileIdentifier
    knowledge_source_id: ProfileIdentifier
    configuration: HttpSnapshotProfile = Field(repr=False)


class ConnectionProfileView(ProfileContract):
    """Allowlisted projection, excluding all downstream connection details."""

    connection_profile_id: ProfileIdentifier
    revision: int = Field(ge=1)
    knowledge_space_id: ProfileIdentifier
    knowledge_source_id: ProfileIdentifier
    connector_kind: Literal["http_json"]
    configuration_digest: Sha256Digest
    state: Literal["draft", "validated", "published"]
    updated_at: AwareDatetime


class ConnectionProfileReference(ProfileContract):
    connection_profile_id: ProfileIdentifier
    revision: int = Field(strict=True, ge=1)


class PinnedConnectionProfile(ConnectionProfileReference):
    configuration_digest: Sha256Digest


class ConnectionProfileRevisionCommand(ProfileContract):
    expected_revision: int = Field(strict=True, ge=1)


class ReviseConnectionProfileRequest(ConnectionProfileRevisionCommand):
    draft: ConnectionProfileDraft = Field(repr=False)


class ConnectionProfileAuditEntry(ProfileContract):
    action: Literal["create", "revise", "validate", "publish"]
    operator_id: str
    connection_profile_id: ProfileIdentifier
    revision: int = Field(ge=1)
    configuration_digest: str
    recorded_at: AwareDatetime


class ConnectionProfileRejectionEntry(ProfileContract):
    operator_id: str | None = Field(default=None, max_length=256)
    connection_profile_id: ProfileIdentifier | None = None
    operation: Literal["create", "get", "revise", "validate", "publish", "audit"]
    code: ProfileIdentifier
    recorded_at: AwareDatetime


class ConnectionProfileAuditCollection(ProfileContract):
    events: tuple[ConnectionProfileAuditEntry, ...]
    rejections: tuple[ConnectionProfileRejectionEntry, ...]
