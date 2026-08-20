"""FastAPI delivery adapter for the public Knowledge Query interface."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.responses import JSONResponse

from knowledge_source_service.application.knowledge_queries import (
    IdempotencyKeyMismatch,
    KnowledgeQueryAccessDenied,
    KnowledgeQueryDeadlineElapsed,
    KnowledgeQueryApplication,
    KnowledgeQueryTerminalStateConflict,
    KnowledgeServiceClient,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
    KnowledgeQuery,
    KnowledgeServiceProblem,
)
from knowledge_source_service.contracts.health import (
    KnowledgeServiceDependencyName,
    KnowledgeServiceDependencyReadiness,
    KnowledgeServiceLiveness,
    KnowledgeServiceReadiness,
)


AuthenticateKnowledgeClient = Callable[[Request], KnowledgeServiceClient]


class InvalidIdempotencyKey(ValueError):
    """The required HTTP idempotency key is missing or blank."""


class InvalidKnowledgeClientCredential(PermissionError):
    """The request has no valid Bearer service identity."""


def bearer_client_authenticator(
    authenticate_token: Callable[[str], str | None],
) -> AuthenticateKnowledgeClient:
    """Adapt an exact Bearer token verifier to the HTTP authentication seam."""

    def authenticate(request: Request) -> KnowledgeServiceClient:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not token
            or token != token.strip()
            or " " in token
        ):
            raise InvalidKnowledgeClientCredential
        client_id = authenticate_token(token)
        if client_id is None:
            raise InvalidKnowledgeClientCredential
        return KnowledgeServiceClient(client_id=client_id)

    return authenticate


def require_idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """Normalize one non-blank key before it reaches the application module."""

    if value is None or not value.strip():
        raise InvalidIdempotencyKey
    return value.strip()


def _problem_response(problem: KnowledgeServiceProblem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def _knowledge_query_not_found_problem(trace_id: str) -> KnowledgeServiceProblem:
    return KnowledgeServiceProblem(
        type="urn:knowledge-source-service:problem:knowledge-query-not-found",
        title="Knowledge Query not found",
        status=status.HTTP_404_NOT_FOUND,
        code="knowledge_query_not_found",
        detail="The Knowledge Query does not exist or is not visible to this client.",
        trace_id=trace_id,
        retryable=False,
    )


def create_application(
    *,
    query_application: KnowledgeQueryApplication,
    authenticate_client: AuthenticateKnowledgeClient,
    trace_id_factory: Callable[[], str],
    release_identity: str,
    readiness_probe: Callable[[], Mapping[str, bool]],
) -> FastAPI:
    """Build an HTTP application from explicit authority-bearing dependencies."""

    application = FastAPI(title="Knowledge Source Service", version="1")

    @application.get("/livez", response_model=KnowledgeServiceLiveness)
    def get_liveness() -> KnowledgeServiceLiveness:
        return KnowledgeServiceLiveness(release_identity=release_identity)

    @application.get("/readyz", response_model=KnowledgeServiceReadiness)
    def get_readiness(response: Response) -> KnowledgeServiceReadiness:
        observed = readiness_probe()
        dependency_names: tuple[KnowledgeServiceDependencyName, ...] = (
            "postgresql",
            "object_storage",
            "search",
        )
        dependencies = tuple(
            KnowledgeServiceDependencyReadiness(
                name=name,
                status="ready" if observed.get(name, False) else "unavailable",
            )
            for name in dependency_names
        )
        readiness = KnowledgeServiceReadiness(
            status=(
                "ready"
                if all(dependency.status == "ready" for dependency in dependencies)
                else "unavailable"
            ),
            release_identity=release_identity,
            dependencies=dependencies,
        )
        if readiness.status == "unavailable":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return readiness

    @application.exception_handler(IdempotencyKeyMismatch)
    def handle_idempotency_key_mismatch(
        _request: Request,
        _error: IdempotencyKeyMismatch,
    ) -> JSONResponse:
        problem = KnowledgeServiceProblem(
            type="urn:knowledge-source-service:problem:idempotency-key-mismatch",
            title="Idempotency key conflict",
            status=status.HTTP_409_CONFLICT,
            code="idempotency_key_mismatch",
            detail="The Idempotency-Key is already bound to a different request.",
            trace_id=trace_id_factory(),
            retryable=False,
        )
        return _problem_response(problem)

    @application.exception_handler(InvalidKnowledgeClientCredential)
    def handle_invalid_knowledge_client_credential(
        _request: Request,
        _error: InvalidKnowledgeClientCredential,
    ) -> JSONResponse:
        problem = KnowledgeServiceProblem(
            type="urn:knowledge-source-service:problem:invalid-client-credential",
            title="Knowledge service client authentication failed",
            status=status.HTTP_401_UNAUTHORIZED,
            code="invalid_client_credential",
            detail="A valid Bearer service credential is required.",
            trace_id=trace_id_factory(),
            retryable=False,
        )
        response = _problem_response(problem)
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @application.exception_handler(KnowledgeQueryAccessDenied)
    def handle_knowledge_query_access_denied(
        _request: Request,
        _error: KnowledgeQueryAccessDenied,
    ) -> JSONResponse:
        problem = KnowledgeServiceProblem(
            type="urn:knowledge-source-service:problem:knowledge-query-access-denied",
            title="Knowledge Query access denied",
            status=status.HTTP_403_FORBIDDEN,
            code="knowledge_query_access_denied",
            detail=(
                "The client is not permitted to query the selected Knowledge Base Release."
            ),
            trace_id=trace_id_factory(),
            retryable=False,
        )
        return _problem_response(problem)

    @application.exception_handler(InvalidIdempotencyKey)
    def handle_invalid_idempotency_key(
        _request: Request,
        _error: InvalidIdempotencyKey,
    ) -> JSONResponse:
        problem = KnowledgeServiceProblem(
            type="urn:knowledge-source-service:problem:invalid-idempotency-key",
            title="Invalid Idempotency-Key",
            status=status.HTTP_400_BAD_REQUEST,
            code="invalid_idempotency_key",
            detail="A non-blank Idempotency-Key header is required.",
            trace_id=trace_id_factory(),
            retryable=False,
        )
        return _problem_response(problem)

    @application.exception_handler(KnowledgeQueryDeadlineElapsed)
    def handle_knowledge_query_deadline_elapsed(
        _request: Request,
        _error: KnowledgeQueryDeadlineElapsed,
    ) -> JSONResponse:
        problem = KnowledgeServiceProblem(
            type="urn:knowledge-source-service:problem:knowledge-query-deadline-elapsed",
            title="Knowledge Query deadline elapsed",
            status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="knowledge_query_deadline_elapsed",
            detail="deadline_at must be later than the Query submission time.",
            trace_id=trace_id_factory(),
            retryable=False,
        )
        return _problem_response(problem)

    @application.exception_handler(KnowledgeQueryTerminalStateConflict)
    def handle_knowledge_query_terminal_state_conflict(
        _request: Request,
        _error: KnowledgeQueryTerminalStateConflict,
    ) -> JSONResponse:
        problem = KnowledgeServiceProblem(
            type=(
                "urn:knowledge-source-service:problem:"
                "knowledge-query-terminal-state-conflict"
            ),
            title="Knowledge Query terminal state conflict",
            status=status.HTTP_409_CONFLICT,
            code="knowledge_query_terminal_state_conflict",
            detail="A terminal Knowledge Query cannot be cancelled.",
            trace_id=trace_id_factory(),
            retryable=False,
        )
        return _problem_response(problem)

    @application.post(
        "/v1/knowledge-queries",
        response_model=KnowledgeQuery,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_knowledge_query(
        request: CreateKnowledgeQueryRequest,
        response: Response,
        idempotency_key: str = Depends(require_idempotency_key),
        client: KnowledgeServiceClient = Depends(authenticate_client),
    ) -> KnowledgeQuery:
        outcome = query_application.create(
            request,
            client=client,
            idempotency_key=idempotency_key,
        )
        query = outcome.query
        if outcome.replayed:
            response.status_code = status.HTTP_200_OK
        response.headers["Location"] = query.links.self
        response.headers["Retry-After"] = "1"
        return query

    @application.get(
        "/v1/knowledge-queries/{knowledge_query_id}",
        response_model=KnowledgeQuery,
    )
    def get_knowledge_query(
        knowledge_query_id: str,
        client: KnowledgeServiceClient = Depends(authenticate_client),
    ) -> KnowledgeQuery | JSONResponse:
        query = query_application.get(knowledge_query_id, client=client)
        if query is None:
            return _problem_response(_knowledge_query_not_found_problem(trace_id_factory()))
        return query

    @application.post(
        "/v1/knowledge-queries/{knowledge_query_id}:cancel",
        response_model=KnowledgeQuery,
    )
    def cancel_knowledge_query(
        knowledge_query_id: str,
        client: KnowledgeServiceClient = Depends(authenticate_client),
    ) -> KnowledgeQuery | JSONResponse:
        query = query_application.cancel(knowledge_query_id, client=client)
        if query is None:
            return _problem_response(_knowledge_query_not_found_problem(trace_id_factory()))
        return query

    return application
