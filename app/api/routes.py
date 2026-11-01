"""Authenticated Tenant, Project and Document endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_current_principal
from app.api.schemas import DocumentCreate, DocumentRead, ProjectCreate, ProjectRead, TenantRead
from app.storage.database import get_session
from app.storage.services import (
    AccessDeniedError,
    DocumentService,
    ProjectService,
    ResourceNotFoundError,
    TenantService,
)

router = APIRouter(prefix="/api/v1", tags=["workspace"])


@router.get("/tenants/{tenant_id}", response_model=TenantRead)
def get_tenant(
    tenant_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        return TenantService(session).get(tenant_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Tenant not found") from None


def _check_tenant(tenant_id: UUID, principal: Principal) -> None:
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")


@router.get("/tenants/{tenant_id}/projects", response_model=list[ProjectRead])
def list_projects(
    tenant_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        return ProjectService(session).list(tenant_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Tenant not found") from None


@router.post("/tenants/{tenant_id}/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    tenant_id: UUID,
    payload: ProjectCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        return ProjectService(session).create(
            tenant_id, principal.user_id, name=payload.name, code=payload.code,
            workspace_id=payload.workspace_id, description=payload.description,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.get("/tenants/{tenant_id}/projects/{project_id}/documents", response_model=list[DocumentRead])
def list_documents(
    tenant_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        return DocumentService(session).list(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project or resource not found") from None


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    tenant_id: UUID,
    project_id: UUID,
    payload: DocumentCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        return DocumentService(session).create(
            tenant_id, project_id, principal.user_id,
            title=payload.title, document_type=payload.document_type,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
