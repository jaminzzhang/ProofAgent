"""PostgreSQL service-client authentication and exact-Release Query grants."""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any, Literal

import psycopg
from psycopg import errors
from psycopg.rows import dict_row

from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
AllowedStrategy = Literal["single_pass", "agentic"]


class KnowledgeAccessConflict(RuntimeError):
    """A client or Grant identity is already bound to different authority facts."""


class PostgresKnowledgeAccessControl:
    """Own hashed service credentials and immutable exact-Release Query grants."""

    def __init__(self, dsn: str) -> None:
        self._dsn = _psycopg_dsn(dsn)

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresKnowledgeAccessControl:
        return cls(dsn)

    def register_client(self, *, client_id: str, bearer_token: str) -> None:
        _validate_authority_id(client_id, "client_id")
        token_digest = _token_digest(bearer_token)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            connection.execute(
                """
                INSERT INTO knowledge_service_clients (client_id, bearer_token_digest)
                VALUES (%s, %s)
                ON CONFLICT (client_id) DO NOTHING
                """,
                (client_id, token_digest),
            )
            row = connection.execute(
                """
                SELECT bearer_token_digest, active
                FROM knowledge_service_clients
                WHERE client_id = %s
                """,
                (client_id,),
            ).fetchone()
            if (
                row is None
                or row["bearer_token_digest"] != token_digest
                or row["active"] is not True
            ):
                raise KnowledgeAccessConflict(
                    "service client identity is already bound to different credentials"
                )

    def grant_release_query(
        self,
        *,
        client_grant_id: str,
        client_id: str,
        knowledge_base_release_id: str,
        allowed_strategies: tuple[AllowedStrategy, ...],
        max_rounds: int,
        max_model_calls: int,
        max_candidates: int,
        max_model_tokens: int,
        max_duration_ms: int,
        effective_access_scope_digest: str,
    ) -> None:
        _validate_authority_id(client_grant_id, "client_grant_id")
        _validate_authority_id(client_id, "client_id")
        if (
            not allowed_strategies
            or len(set(allowed_strategies)) != len(allowed_strategies)
            or any(strategy not in {"single_pass", "agentic"} for strategy in allowed_strategies)
        ):
            raise ValueError("allowed_strategies are invalid")
        limits = (
            max_rounds,
            max_model_calls,
            max_candidates,
            max_model_tokens,
            max_duration_ms,
        )
        if any(limit < 1 for limit in limits):
            raise ValueError("Grant Query limits must be positive")
        if _DIGEST.fullmatch(effective_access_scope_digest) is None:
            raise ValueError("effective_access_scope_digest is invalid")
        parameters: tuple[object, ...] = (
            client_grant_id,
            client_id,
            knowledge_base_release_id,
            list(allowed_strategies),
            *limits,
            effective_access_scope_digest,
            knowledge_base_release_id,
        )
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute(
                    """
                    INSERT INTO knowledge_client_grants (
                        client_grant_id,
                        client_id,
                        knowledge_space_id,
                        knowledge_base_release_id,
                        allowed_strategies,
                        max_rounds,
                        max_model_calls,
                        max_candidates,
                        max_model_tokens,
                        max_duration_ms,
                        effective_access_scope_digest
                    )
                    SELECT
                        %s,
                        %s,
                        release.knowledge_space_id,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    FROM knowledge_base_releases AS release
                    WHERE release.knowledge_base_release_id = %s
                      AND release.state = 'queryable'
                    ON CONFLICT (client_grant_id) DO NOTHING
                    """,
                    parameters,
                )
                row = connection.execute(
                    """
                    SELECT * FROM knowledge_client_grants
                    WHERE client_grant_id = %s
                    """,
                    (client_grant_id,),
                ).fetchone()
                if row is None or not _grant_matches(
                    row,
                    client_id=client_id,
                    release_id=knowledge_base_release_id,
                    allowed_strategies=allowed_strategies,
                    limits=limits,
                    scope_digest=effective_access_scope_digest,
                ):
                    raise KnowledgeAccessConflict(
                        "Client Grant identity is unavailable or immutable facts differ"
                    )
        except (errors.ForeignKeyViolation, errors.UniqueViolation) as error:
            raise KnowledgeAccessConflict(
                "Client Grant conflicts with existing client or Release authority"
            ) from error

    def authenticate_bearer_token(self, bearer_token: str) -> str | None:
        try:
            token_digest = _token_digest(bearer_token)
        except ValueError:
            return None
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT client_id
                FROM knowledge_service_clients
                WHERE bearer_token_digest = %s AND active
                """,
                (token_digest,),
            ).fetchone()
        return None if row is None else str(row["client_id"])

    def authorize(
        self,
        *,
        client_id: str,
        request: CreateKnowledgeQueryRequest,
    ) -> KnowledgeQueryAdmission | None:
        if request.access_narrowing_context is not None:
            return None
        budget = request.execution_budget
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT
                    client_grant.client_grant_id,
                    client_grant.knowledge_space_id,
                    client_grant.effective_access_scope_digest
                FROM knowledge_client_grants AS client_grant
                JOIN knowledge_service_clients AS client
                  ON client.client_id = client_grant.client_id
                JOIN knowledge_base_releases AS release
                  ON release.knowledge_base_release_id =
                     client_grant.knowledge_base_release_id
                 AND release.knowledge_space_id = client_grant.knowledge_space_id
                WHERE client_grant.client_id = %s
                  AND client_grant.knowledge_base_release_id = %s
                  AND client_grant.active
                  AND client.active
                  AND release.state = 'queryable'
                  AND %s = ANY(client_grant.allowed_strategies)
                  AND client_grant.max_rounds >= %s
                  AND client_grant.max_model_calls >= %s
                  AND client_grant.max_candidates >= %s
                  AND client_grant.max_model_tokens >= %s
                  AND client_grant.max_duration_ms >= %s
                """,
                (
                    client_id,
                    request.knowledge_base_release_id,
                    request.strategy,
                    budget.max_rounds,
                    budget.max_model_calls,
                    budget.max_candidates,
                    budget.max_model_tokens,
                    budget.max_duration_ms,
                ),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeQueryAdmission(
            knowledge_space_id=str(row["knowledge_space_id"]),
            client_grant_id=str(row["client_grant_id"]),
            effective_access_scope_digest=str(row["effective_access_scope_digest"]),
        )


def _grant_matches(
    row: dict[str, Any],
    *,
    client_id: str,
    release_id: str,
    allowed_strategies: tuple[AllowedStrategy, ...],
    limits: tuple[int, int, int, int, int],
    scope_digest: str,
) -> bool:
    return bool(
        row["client_id"] == client_id
        and row["knowledge_base_release_id"] == release_id
        and tuple(row["allowed_strategies"]) == allowed_strategies
        and row["max_rounds"] == limits[0]
        and row["max_model_calls"] == limits[1]
        and row["max_candidates"] == limits[2]
        and row["max_model_tokens"] == limits[3]
        and row["max_duration_ms"] == limits[4]
        and row["effective_access_scope_digest"] == scope_digest
        and row["active"] is True
    )


def _token_digest(bearer_token: str) -> str:
    if (
        type(bearer_token) is not str
        or len(bearer_token) < 16
        or len(bearer_token) > 4096
        or any(ord(character) < 33 for character in bearer_token)
    ):
        raise ValueError("Bearer token is invalid")
    digest = sha256(f"knowledge-service-bearer.v1\0{bearer_token}".encode()).hexdigest()
    return f"sha256:{digest}"


def _validate_authority_id(value: str, field: str) -> None:
    if _AUTHORITY_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is not a valid opaque authority identifier")


def _psycopg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)
