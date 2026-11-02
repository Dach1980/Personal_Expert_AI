"""Authenticated Tenant, Project and Document endpoints."""
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_current_principal
from app.api.dependencies import get_document_upload_service
from app.api.schemas import (
    DocumentCreate,
    DocumentRead,
    DocumentVersionRead,
    ProjectCreate,
    ProjectRead,
    TenantRead,
)
from app.storage.database import get_session
from app.storage.file_store import StorageIntegrityError
from app.storage.services import (
    AccessDeniedError,
    DocumentService,
    ProjectService,
    ResourceNotFoundError,
    TenantService,
)
from app.storage.upload_service import (
    DocumentUploadService,
    UploadAccessDenied,
    UploadConflict,
    UploadNotFound,
    UploadValidationError,
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



@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions",
    response_model=DocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["documents"],
)
def upload_document_version(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    response: Response,
    file: UploadFile = File(...),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
    upload_service: DocumentUploadService = Depends(get_document_upload_service),
):
    """Upload one immutable source version using multipart/form-data."""
    _check_tenant(tenant_id, principal)
    try:
        result = upload_service.upload(
            tenant_id,
            project_id,
            document_id,
            principal.user_id,
            idempotency_key,
            file.filename or "",
            file.file,
        )
        response.status_code = status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
        return result.version
    except UploadAccessDenied:
        raise HTTPException(status_code=403, detail="Project access does not permit upload") from None
    except UploadNotFound:
        raise HTTPException(status_code=404, detail="Document not found") from None
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (UploadValidationError, ValueError) as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    except StorageIntegrityError:
        raise HTTPException(status_code=503, detail="Stored document integrity verification failed") from None
    finally:
        file.file.close()


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/content",
    response_class=StreamingResponse,
    tags=["documents"],
)
def download_document_version(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    upload_service: DocumentUploadService = Depends(get_document_upload_service),
):
    """Return an original only after verifying bytes against its registered SHA-256."""
    _check_tenant(tenant_id, principal)
    try:
        version, source = upload_service.open_verified(
            tenant_id, project_id, document_id, version_id, principal.user_id
        )
    except UploadAccessDenied:
        raise HTTPException(status_code=403, detail="Project access does not permit download") from None
    except UploadNotFound:
        raise HTTPException(status_code=404, detail="Document version not found") from None
    except (StorageIntegrityError, FileNotFoundError):
        raise HTTPException(status_code=503, detail="Original document is missing or failed integrity verification") from None

    def stream():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    filename = quote(version.original_filename, safe="")
    return StreamingResponse(
        stream(),
        media_type=version.media_type,
        headers={
            "Content-Length": str(version.size_bytes),
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{version.checksum_sha256}"',
            "Cache-Control": "private, no-store",
        },
    )
