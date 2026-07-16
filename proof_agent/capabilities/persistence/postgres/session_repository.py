from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_text,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    oidc_login_attempts,
    operator_sessions,
)
from proof_agent.contracts.identity import (
    OidcLoginAttemptRecord,
    OidcPrincipal,
    OperatorSessionRecord,
)
from proof_agent.contracts.persistence import PersistenceConflictError


class PostgresOperatorSessionRepository:
    """OIDC state replay guard and conditional backend session persistence."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def create_login_attempt(self, attempt: OidcLoginAttemptRecord) -> None:
        statement = (
            postgres_insert(oidc_login_attempts)
            .values(
                state_sha256=attempt.state_sha256,
                nonce_envelope=attempt.nonce_envelope,
                pkce_verifier_envelope=attempt.pkce_verifier_envelope,
                envelope_key_version=attempt.envelope_key_version,
                redirect_uri=attempt.redirect_uri,
                created_at=timestamp_value(attempt.created_at, field="created_at"),
                expires_at=timestamp_value(attempt.expires_at, field="expires_at"),
            )
            .on_conflict_do_nothing(index_elements=[oidc_login_attempts.c.state_sha256])
            .returning(oidc_login_attempts.c.state_sha256)
        )
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(statement).scalar_one_or_none()
        if inserted is None:
            raise PersistenceConflictError(
                resource_type="oidc_login_attempt",
                resource_id=attempt.state_sha256,
                expected_revision=0,
                actual_revision=1,
            )

    def consume_login_attempt(
        self,
        state_sha256: str,
        *,
        consumed_at: str,
    ) -> OidcLoginAttemptRecord | None:
        consumed = timestamp_value(consumed_at, field="consumed_at")
        statement = (
            sa.update(oidc_login_attempts)
            .where(
                oidc_login_attempts.c.state_sha256 == state_sha256,
                oidc_login_attempts.c.consumed_at.is_(None),
                oidc_login_attempts.c.expires_at > consumed,
            )
            .values(consumed_at=consumed)
            .returning(*oidc_login_attempts.c)
        )
        with write_connection(self._connection_source) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else _login_attempt_record(row)

    def create_session(self, session: OperatorSessionRecord) -> None:
        if session.session_version != 1:
            raise ValueError("new operator session version must be 1")
        statement = (
            postgres_insert(operator_sessions)
            .values(**_session_values(session))
            .on_conflict_do_nothing(index_elements=[operator_sessions.c.session_id])
            .returning(operator_sessions.c.session_id)
        )
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(statement).scalar_one_or_none()
        if inserted is None:
            raise PersistenceConflictError(
                resource_type="operator_session",
                resource_id=session.session_id,
                expected_revision=0,
                actual_revision=1,
            )

    def get_by_token_hash(self, token_sha256: str) -> OperatorSessionRecord | None:
        statement = sa.select(operator_sessions).where(
            operator_sessions.c.session_token_sha256 == token_sha256
        )
        with read_connection(self._connection_source) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else _session_record(row)

    def update_session(
        self,
        session: OperatorSessionRecord,
        *,
        expected_session_version: int,
    ) -> OperatorSessionRecord:
        if session.session_version != expected_session_version + 1:
            raise ValueError("session update must increment version exactly once")
        statement = (
            sa.update(operator_sessions)
            .where(
                operator_sessions.c.session_id
                == uuid_value(session.session_id, field="session_id"),
                operator_sessions.c.session_version == expected_session_version,
            )
            .values(**_session_values(session, include_identity=False))
            .returning(operator_sessions.c.session_version)
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(statement).scalar_one_or_none()
            if updated is None:
                actual = connection.execute(
                    sa.select(operator_sessions.c.session_version).where(
                        operator_sessions.c.session_id
                        == uuid_value(session.session_id, field="session_id")
                    )
                ).scalar_one_or_none()
                raise PersistenceConflictError(
                    resource_type="operator_session",
                    resource_id=session.session_id,
                    expected_revision=expected_session_version,
                    actual_revision=actual,
                )
        return session

    def revoke_by_token_hash(self, token_sha256: str, *, revoked_at: str) -> bool:
        statement = (
            sa.update(operator_sessions)
            .where(
                operator_sessions.c.session_token_sha256 == token_sha256,
                operator_sessions.c.revoked_at.is_(None),
            )
            .values(
                revoked_at=timestamp_value(revoked_at, field="revoked_at"),
                session_version=operator_sessions.c.session_version + 1,
            )
            .returning(operator_sessions.c.session_id)
        )
        with write_connection(self._connection_source) as connection:
            return connection.execute(statement).scalar_one_or_none() is not None


def _login_attempt_record(row: RowMapping) -> OidcLoginAttemptRecord:
    return OidcLoginAttemptRecord(
        state_sha256=str(row["state_sha256"]),
        nonce_envelope=bytes(row["nonce_envelope"]),
        pkce_verifier_envelope=bytes(row["pkce_verifier_envelope"]),
        envelope_key_version=str(row["envelope_key_version"]),
        redirect_uri=str(row["redirect_uri"]),
        created_at=timestamp_text(row["created_at"]),
        expires_at=timestamp_text(row["expires_at"]),
        consumed_at=(
            None if row["consumed_at"] is None else timestamp_text(row["consumed_at"])
        ),
    )


def _session_record(row: RowMapping) -> OperatorSessionRecord:
    return OperatorSessionRecord(
        session_id=str(row["session_id"]),
        session_version=int(row["session_version"]),
        session_token_sha256=str(row["session_token_sha256"]),
        principal=OidcPrincipal.model_validate(row["principal_json"]),
        provider_token_envelope=bytes(row["provider_token_envelope"]),
        envelope_key_version=str(row["envelope_key_version"]),
        permission_mapping_version_id=(
            None
            if row["permission_mapping_version_id"] is None
            else str(row["permission_mapping_version_id"])
        ),
        permission_epoch=int(row["permission_epoch"]),
        created_at=timestamp_text(row["created_at"]),
        absolute_expires_at=timestamp_text(row["absolute_expires_at"]),
        idle_expires_at=timestamp_text(row["idle_expires_at"]),
        claims_verified_at=timestamp_text(row["claims_verified_at"]),
        revoked_at=(None if row["revoked_at"] is None else timestamp_text(row["revoked_at"])),
    )


def _session_values(
    session: OperatorSessionRecord,
    *,
    include_identity: bool = True,
) -> dict[str, object]:
    values: dict[str, object] = {
        "session_version": session.session_version,
        "session_token_sha256": session.session_token_sha256,
        "principal_json": model_json(session.principal),
        "provider_token_envelope": session.provider_token_envelope,
        "envelope_key_version": session.envelope_key_version,
        "permission_mapping_version_id": (
            None
            if session.permission_mapping_version_id is None
            else uuid_value(
                session.permission_mapping_version_id,
                field="permission_mapping_version_id",
            )
        ),
        "permission_epoch": session.permission_epoch,
        "created_at": timestamp_value(session.created_at, field="created_at"),
        "absolute_expires_at": timestamp_value(
            session.absolute_expires_at, field="absolute_expires_at"
        ),
        "idle_expires_at": timestamp_value(session.idle_expires_at, field="idle_expires_at"),
        "claims_verified_at": timestamp_value(
            session.claims_verified_at, field="claims_verified_at"
        ),
        "revoked_at": (
            None
            if session.revoked_at is None
            else timestamp_value(session.revoked_at, field="revoked_at")
        ),
    }
    if include_identity:
        values["session_id"] = uuid_value(session.session_id, field="session_id")
    return values
