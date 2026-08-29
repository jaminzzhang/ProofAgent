"""OIDC-protected BFF adapter for Knowledge Source Service management."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, Protocol, TypeVar, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from proof_agent.contracts import Permission
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceBaseDraftProjection,
    KnowledgeServiceBaseProjection,
    KnowledgeServiceConnectionProfileDraft,
    KnowledgeServiceConnectionProfileProjection,
    KnowledgeServiceConnectionProfileRevisionCommand,
    KnowledgeServiceIdentifier,
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReleaseDeletionEligibilityProjection,
    KnowledgeServiceReleasePreparationProjection,
    KnowledgeServiceReviseConnectionProfileRequest,
    KnowledgeServiceSaveBaseDraftRequest,
    KnowledgeServiceSourceProjection,
    KnowledgeServiceSpaceProjection,
    KnowledgeServiceSynchronizationOutcome,
    KnowledgeServiceSynchronizationProjection,
    KnowledgeServiceSynchronizationRequest,
    KnowledgeServiceStartReleasePreparationRequest,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


class KnowledgeServiceManagementClient(Protocol):
    def workspace(self) -> KnowledgeServiceManagementWorkspace: ...

    def release_deletion_eligibility(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        knowledge_base_release_id: str,
    ) -> KnowledgeServiceReleaseDeletionEligibilityProjection: ...

    def create_space(self, knowledge_space_id: str) -> None: ...

    def create_connection_profile(
        self,
        draft: KnowledgeServiceConnectionProfileDraft,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection: ...

    def connection_profile(
        self,
        connection_profile_id: str,
        *,
        revision: int | None = None,
    ) -> KnowledgeServiceConnectionProfileProjection: ...

    def revise_connection_profile(
        self,
        connection_profile_id: str,
        request: KnowledgeServiceReviseConnectionProfileRequest,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection: ...

    def validate_connection_profile(
        self,
        connection_profile_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection: ...

    def publish_connection_profile(
        self,
        connection_profile_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection: ...

    def submit_synchronization(
        self,
        request: KnowledgeServiceSynchronizationRequest,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceSynchronizationOutcome: ...

    def synchronization(
        self,
        synchronization_id: str,
    ) -> KnowledgeServiceSynchronizationProjection: ...

    def create_source(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> None: ...

    def create_base(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> None: ...

    def save_base_draft(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        request: KnowledgeServiceSaveBaseDraftRequest,
        idempotency_key: str,
    ) -> KnowledgeServiceBaseDraftProjection: ...

    def base_draft(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        revision: int,
    ) -> KnowledgeServiceBaseDraftProjection: ...

    def start_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        request: KnowledgeServiceStartReleasePreparationRequest,
        idempotency_key: str,
    ) -> KnowledgeServiceReleasePreparationProjection: ...

    def release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> KnowledgeServiceReleasePreparationProjection: ...

    def publish_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> KnowledgeServiceReleasePreparationProjection: ...

    def cancel_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
        idempotency_key: str,
    ) -> KnowledgeServiceReleasePreparationProjection: ...


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CreateKnowledgeServiceSpaceRequest(_StrictRequest):
    knowledge_space_id: KnowledgeServiceIdentifier


class CreateKnowledgeServiceSourceRequest(_StrictRequest):
    knowledge_source_id: KnowledgeServiceIdentifier


class CreateKnowledgeServiceBaseRequest(_StrictRequest):
    knowledge_base_id: KnowledgeServiceIdentifier


class _SecretSafeValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def secret_safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"detail": "invalid_knowledge_service_management_request"},
                )

        return secret_safe_handler


router = APIRouter(
    prefix="/config/knowledge-service",
    tags=["knowledge-service"],
    route_class=_SecretSafeValidationRoute,
)
_T = TypeVar("_T")


def _management_client(request: Request) -> KnowledgeServiceManagementClient:
    client = getattr(request.app.state, "knowledge_service_management_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="knowledge_service_management_unavailable",
        )
    return cast(KnowledgeServiceManagementClient, client)


def _invoke(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc


@router.get("/workspace", response_model=KnowledgeServiceManagementWorkspace)
def get_workspace(
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceManagementWorkspace:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _invoke(_management_client(request).workspace)


@router.get(
    (
        "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/"
        "releases/{knowledge_base_release_id}/deletion-eligibility"
    ),
    response_model=KnowledgeServiceReleaseDeletionEligibilityProjection,
)
def get_release_deletion_eligibility(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    knowledge_base_release_id: KnowledgeServiceIdentifier,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceReleaseDeletionEligibilityProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _invoke(
        lambda: _management_client(request).release_deletion_eligibility(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            knowledge_base_release_id=knowledge_base_release_id,
        )
    )


@router.post(
    "/connection-profiles",
    response_model=KnowledgeServiceConnectionProfileProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_connection_profile(
    body: KnowledgeServiceConnectionProfileDraft,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceConnectionProfileProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    profile = _invoke(
        lambda: _management_client(request).create_connection_profile(
            body,
            idempotency_key=idempotency_key,
        )
    )
    response.headers["Location"] = (
        f"/api/config/knowledge-service/connection-profiles/{profile.connection_profile_id}"
    )
    return profile


@router.get(
    "/connection-profiles/{connection_profile_id}",
    response_model=KnowledgeServiceConnectionProfileProjection,
)
def get_connection_profile(
    connection_profile_id: KnowledgeServiceIdentifier,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    revision: Annotated[int | None, Query(ge=1)] = None,
) -> KnowledgeServiceConnectionProfileProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _invoke(
        lambda: _management_client(request).connection_profile(
            connection_profile_id,
            revision=revision,
        )
    )


@router.put(
    "/connection-profiles/{connection_profile_id}",
    response_model=KnowledgeServiceConnectionProfileProjection,
)
def revise_connection_profile(
    connection_profile_id: KnowledgeServiceIdentifier,
    body: KnowledgeServiceReviseConnectionProfileRequest,
    request: Request,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceConnectionProfileProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _invoke(
        lambda: _management_client(request).revise_connection_profile(
            connection_profile_id,
            body,
            idempotency_key=idempotency_key,
        )
    )


def _transition_connection_profile(
    *,
    operation: Literal["validate", "publish"],
    connection_profile_id: str,
    body: KnowledgeServiceConnectionProfileRevisionCommand,
    request: Request,
    idempotency_key: str,
) -> KnowledgeServiceConnectionProfileProjection:
    client = _management_client(request)
    if operation == "validate":
        return _invoke(
            lambda: client.validate_connection_profile(
                connection_profile_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
    return _invoke(
        lambda: client.publish_connection_profile(
            connection_profile_id,
            expected_revision=body.expected_revision,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/connection-profiles/{connection_profile_id}:validate",
    response_model=KnowledgeServiceConnectionProfileProjection,
)
def validate_connection_profile(
    connection_profile_id: KnowledgeServiceIdentifier,
    body: KnowledgeServiceConnectionProfileRevisionCommand,
    request: Request,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceConnectionProfileProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _transition_connection_profile(
        operation="validate",
        connection_profile_id=connection_profile_id,
        body=body,
        request=request,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/connection-profiles/{connection_profile_id}:publish",
    response_model=KnowledgeServiceConnectionProfileProjection,
)
def publish_connection_profile(
    connection_profile_id: KnowledgeServiceIdentifier,
    body: KnowledgeServiceConnectionProfileRevisionCommand,
    request: Request,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceConnectionProfileProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _transition_connection_profile(
        operation="publish",
        connection_profile_id=connection_profile_id,
        body=body,
        request=request,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/synchronizations",
    response_model=KnowledgeServiceSynchronizationProjection,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_synchronization(
    body: KnowledgeServiceSynchronizationRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceSynchronizationProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    outcome = _invoke(
        lambda: _management_client(request).submit_synchronization(
            body,
            idempotency_key=idempotency_key,
        )
    )
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = outcome.synchronization.links.self
    response.headers["Retry-After"] = "1"
    return outcome.synchronization


@router.get(
    "/synchronizations/{synchronization_id}",
    response_model=KnowledgeServiceSynchronizationProjection,
)
def get_synchronization(
    synchronization_id: KnowledgeServiceIdentifier,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceSynchronizationProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _invoke(lambda: _management_client(request).synchronization(synchronization_id))


@router.post(
    "/spaces",
    response_model=KnowledgeServiceSpaceProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_space(
    body: CreateKnowledgeServiceSpaceRequest,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceSpaceProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    _invoke(lambda: _management_client(request).create_space(body.knowledge_space_id))
    return KnowledgeServiceSpaceProjection(knowledge_space_id=body.knowledge_space_id)


@router.post(
    "/spaces/{knowledge_space_id}/sources",
    response_model=KnowledgeServiceSourceProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    knowledge_space_id: KnowledgeServiceIdentifier,
    body: CreateKnowledgeServiceSourceRequest,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceSourceProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    _invoke(
        lambda: _management_client(request).create_source(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=body.knowledge_source_id,
        )
    )
    return KnowledgeServiceSourceProjection(
        knowledge_space_id=knowledge_space_id,
        knowledge_source_id=body.knowledge_source_id,
    )


@router.post(
    "/spaces/{knowledge_space_id}/bases",
    response_model=KnowledgeServiceBaseProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_base(
    knowledge_space_id: KnowledgeServiceIdentifier,
    body: CreateKnowledgeServiceBaseRequest,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceBaseProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    _invoke(
        lambda: _management_client(request).create_base(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=body.knowledge_base_id,
        )
    )
    return KnowledgeServiceBaseProjection(
        knowledge_space_id=knowledge_space_id,
        knowledge_base_id=body.knowledge_base_id,
    )


@router.put(
    "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/draft",
    response_model=KnowledgeServiceBaseDraftProjection,
)
def save_base_draft(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    body: KnowledgeServiceSaveBaseDraftRequest,
    request: Request,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceBaseDraftProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    return _invoke(
        lambda: _management_client(request).save_base_draft(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            request=body,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/draft",
    response_model=KnowledgeServiceBaseDraftProjection,
)
def get_base_draft(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
    revision: Annotated[int, Query(ge=1)],
) -> KnowledgeServiceBaseDraftProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _invoke(
        lambda: _management_client(request).base_draft(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            revision=revision,
        )
    )


@router.post(
    "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/release-preparations",
    response_model=KnowledgeServiceReleasePreparationProjection,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_release_preparation(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    body: KnowledgeServiceStartReleasePreparationRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceReleasePreparationProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    preparation = _invoke(
        lambda: _management_client(request).start_release_preparation(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            request=body,
            idempotency_key=idempotency_key,
        )
    )
    response.headers["Location"] = preparation.links.self
    response.headers["Retry-After"] = "1"
    return preparation


@router.post(
    (
        "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/"
        "release-preparations/{release_preparation_id}:publish"
    ),
    response_model=KnowledgeServiceReleasePreparationProjection,
)
async def publish_release_preparation(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    release_preparation_id: KnowledgeServiceIdentifier,
    request: Request,
    response: Response,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceReleasePreparationProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    if await request.body():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_knowledge_service_management_request",
        )
    preparation = _invoke(
        lambda: _management_client(request).publish_release_preparation(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            release_preparation_id=release_preparation_id,
        )
    )
    response.headers["Location"] = preparation.links.self
    return preparation


@router.post(
    (
        "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/"
        "release-preparations/{release_preparation_id}:cancel"
    ),
    response_model=KnowledgeServiceReleasePreparationProjection,
)
async def cancel_release_preparation(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    release_preparation_id: KnowledgeServiceIdentifier,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceReleasePreparationProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_EDIT)
    if await request.body():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_knowledge_service_management_request",
        )
    preparation = _invoke(
        lambda: _management_client(request).cancel_release_preparation(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            release_preparation_id=release_preparation_id,
            idempotency_key=idempotency_key,
        )
    )
    response.headers["Location"] = preparation.links.self
    return preparation


@router.get(
    (
        "/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/"
        "release-preparations/{release_preparation_id}"
    ),
    response_model=KnowledgeServiceReleasePreparationProjection,
)
def get_release_preparation(
    knowledge_space_id: KnowledgeServiceIdentifier,
    knowledge_base_id: KnowledgeServiceIdentifier,
    release_preparation_id: KnowledgeServiceIdentifier,
    request: Request,
    identity: Annotated[OperatorIdentityContext, Depends(get_operator_identity)],
) -> KnowledgeServiceReleasePreparationProjection:
    require_operator_permission(identity, Permission.KNOWLEDGE_SOURCE_VIEW)
    return _invoke(
        lambda: _management_client(request).release_preparation(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            release_preparation_id=release_preparation_id,
        )
    )


__all__ = ["KnowledgeServiceManagementClient", "router"]
