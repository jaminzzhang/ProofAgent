from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    model_connection_credentials,
)
from proof_agent.contracts.ports.model_credentials import (
    ModelCredentialResolutionError,
    ModelCredentialValidation,
    ResolvedModelCredential,
)
from proof_agent.control.security.envelope_cipher import (
    EnvelopeCipher,
    EnvelopeUnavailableError,
)


_MAX_CREDENTIAL_BYTES = 16 * 1024


class PostgresModelCredentialRepository:
    """Store and resolve authenticated model credential envelopes in PostgreSQL."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        cipher: EnvelopeCipher,
    ) -> None:
        self._connection_source = connection_source
        self._cipher = cipher

    def store(
        self,
        connection_id: str,
        value: bytes,
        *,
        updated_at: datetime,
    ) -> None:
        material = bytes(value)
        if not connection_id.strip():
            raise ValueError("model connection id cannot be empty")
        if not 1 <= len(material) <= _MAX_CREDENTIAL_BYTES:
            raise ValueError("model credential is outside its byte limit")
        if b"\r" in material or b"\n" in material:
            raise ValueError("model credential cannot contain line breaks")
        envelope = self._cipher.encrypt(
            material,
            context=_context(connection_id),
        )
        statement = (
            postgres_insert(model_connection_credentials)
            .values(
                connection_id=connection_id,
                key_version=envelope.key_version,
                ciphertext=envelope.ciphertext,
                created_at=updated_at,
                updated_at=updated_at,
            )
            .on_conflict_do_update(
                index_elements=[model_connection_credentials.c.connection_id],
                set_={
                    "key_version": envelope.key_version,
                    "ciphertext": envelope.ciphertext,
                    "updated_at": updated_at,
                },
            )
        )
        with write_connection(self._connection_source) as connection:
            connection.execute(statement)

    def validate(self, connection_id: str) -> ModelCredentialValidation:
        try:
            self.resolve(connection_id)
        except ModelCredentialResolutionError as exc:
            return ModelCredentialValidation(
                connection_id=connection_id,
                resolvable=False,
                reason_code=exc.reason_code,
            )
        return ModelCredentialValidation(
            connection_id=connection_id,
            resolvable=True,
        )

    def resolve(self, connection_id: str) -> ResolvedModelCredential:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(
                    model_connection_credentials.c.key_version,
                    model_connection_credentials.c.ciphertext,
                ).where(model_connection_credentials.c.connection_id == connection_id)
            ).mappings().one_or_none()
        if row is None:
            raise ModelCredentialResolutionError("credential_not_found")
        try:
            material = self._cipher.decrypt(
                bytes(row["ciphertext"]),
                key_version=str(row["key_version"]),
                context=_context(connection_id),
            )
        except EnvelopeUnavailableError as exc:
            raise ModelCredentialResolutionError("credential_envelope_unavailable") from exc
        if (
            not 1 <= len(material) <= _MAX_CREDENTIAL_BYTES
            or b"\r" in material
            or b"\n" in material
        ):
            raise ModelCredentialResolutionError("credential_material_invalid")
        return ResolvedModelCredential(value=material)


def _context(connection_id: str) -> str:
    return f"model-credential:{connection_id}"


__all__ = ["PostgresModelCredentialRepository"]
