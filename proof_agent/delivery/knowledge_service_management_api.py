"""OIDC-protected BFF adapter for Knowledge Source Service management."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol, TypeVar, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from proof_agent.contracts import Permission
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceBaseProjection,
    KnowledgeServiceIdentifier,
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceSourceProjection,
    KnowledgeServiceSpaceProjection,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    require_operator_permission,
)


class KnowledgeServiceManagementClient(Protocol):
    def workspace(self) -> KnowledgeServiceManagementWorkspace: ...

    def create_space(self, knowledge_space_id: str) -> None: ...

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


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CreateKnowledgeServiceSpaceRequest(_StrictRequest):
    knowledge_space_id: KnowledgeServiceIdentifier


class CreateKnowledgeServiceSourceRequest(_StrictRequest):
    knowledge_source_id: KnowledgeServiceIdentifier


class CreateKnowledgeServiceBaseRequest(_StrictRequest):
    knowledge_base_id: KnowledgeServiceIdentifier


router = APIRouter(prefix="/config/knowledge-service", tags=["knowledge-service"])
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


__all__ = ["KnowledgeServiceManagementClient", "router"]
