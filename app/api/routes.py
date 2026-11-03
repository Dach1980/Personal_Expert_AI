"""Authenticated Tenant, Project and Document endpoints."""
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_current_principal
from app.api.dependencies import get_document_upload_service
from app.api.schemas import (
    DocumentCreate,
    DocumentRead,
    DocumentVersionRead,
    KnowledgeItemRead,
    ProcessingArtifactRead,
    SourceFragmentRead,
    ProjectCreate,
    ProjectRead,
    TenantRead,
)
from app.storage.config import storage_root
from app.storage.database import get_session, set_tenant_context
from app.storage.file_store import LocalFileStore, StorageIntegrityError
from app.storage.models import (
    DocumentVersion, KnowledgeItem, ProcessingArtifact, ProcessingRun, SourceFragment,
)
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


def _public_locator(locator: dict) -> dict:
    """Remove storage internals recursively before returning a locator to the browser."""
    blocked = {"storage_key", "artifact_storage_key", "artifact_checksum_sha256", "path", "absolute_path"}
    if isinstance(locator, dict):
        return {
            str(key): _public_locator(value)
            for key, value in locator.items()
            if str(key).lower() not in blocked
        }
    if isinstance(locator, list):
        return [_public_locator(value) for value in locator]
    return locator


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions",
    response_model=list[DocumentVersionRead],
    tags=["documents"],
)
def list_document_versions(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """List immutable versions after checking the caller's project membership."""
    _check_tenant(tenant_id, principal)
    try:
        DocumentService(session).get(tenant_id, project_id, document_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    set_tenant_context(session, tenant_id)
    return list(session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.project_id == project_id,
            DocumentVersion.document_id == document_id,
        )
        .order_by(DocumentVersion.uploaded_at.desc(), DocumentVersion.id.desc())
    ))


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}",
    response_model=DocumentVersionRead,
    tags=["documents"],
)
def get_document_version(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        DocumentService(session).get(tenant_id, project_id, document_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    set_tenant_context(session, tenant_id)
    version = session.scalar(select(DocumentVersion).where(
        DocumentVersion.tenant_id == tenant_id,
        DocumentVersion.project_id == project_id,
        DocumentVersion.document_id == document_id,
        DocumentVersion.id == version_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    return version


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/source-fragments",
    response_model=list[SourceFragmentRead],
    tags=["evidence"],
)
def list_source_fragments(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        DocumentService(session).get(tenant_id, project_id, document_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    set_tenant_context(session, tenant_id)
    version = session.scalar(select(DocumentVersion).where(
        DocumentVersion.tenant_id == tenant_id,
        DocumentVersion.project_id == project_id,
        DocumentVersion.document_id == document_id,
        DocumentVersion.id == version_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    fragments = session.scalars(select(SourceFragment).where(
        SourceFragment.tenant_id == tenant_id,
        SourceFragment.project_id == project_id,
        SourceFragment.document_version_id == version_id,
    ).order_by(SourceFragment.created_at, SourceFragment.id))
    return [
        SourceFragmentRead(
            id=item.id,
            document_version_id=item.document_version_id,
            fragment_type=item.fragment_type,
            locator=_public_locator(item.locator or {}),
            excerpt=(item.content or "")[:4000] or None,
            content_hash=item.content_hash,
            extraction_method=item.extraction_method,
            extractor_version=item.extractor_version,
            quality=item.quality or {},
            created_at=item.created_at,
        )
        for item in fragments
    ]


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/source-fragments/{fragment_id}",
    response_model=SourceFragmentRead,
    tags=["evidence"],
)
def get_source_fragment(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    fragment_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        DocumentService(session).get(tenant_id, project_id, document_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    set_tenant_context(session, tenant_id)
    version = session.scalar(select(DocumentVersion).where(
        DocumentVersion.tenant_id == tenant_id,
        DocumentVersion.project_id == project_id,
        DocumentVersion.document_id == document_id,
        DocumentVersion.id == version_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    fragment = session.scalar(select(SourceFragment).where(
        SourceFragment.tenant_id == tenant_id,
        SourceFragment.project_id == project_id,
        SourceFragment.document_version_id == version_id,
        SourceFragment.id == fragment_id,
    ))
    if fragment is None:
        raise HTTPException(status_code=404, detail="Source fragment not found")
    return SourceFragmentRead(
        id=fragment.id,
        document_version_id=fragment.document_version_id,
        fragment_type=fragment.fragment_type,
        locator=_public_locator(fragment.locator or {}),
        excerpt=(fragment.content or "")[:4000] or None,
        content_hash=fragment.content_hash,
        extraction_method=fragment.extraction_method,
        extractor_version=fragment.extractor_version,
        quality=fragment.quality or {},
        created_at=fragment.created_at,
    )


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/artifacts",
    response_model=list[ProcessingArtifactRead],
    tags=["documents"],
)
def list_version_artifacts(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """List safe metadata for rendered pages and other extraction artifacts."""
    _check_tenant(tenant_id, principal)
    try:
        DocumentService(session).get(tenant_id, project_id, document_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    set_tenant_context(session, tenant_id)
    version = session.scalar(select(DocumentVersion).where(
        DocumentVersion.tenant_id == tenant_id,
        DocumentVersion.project_id == project_id,
        DocumentVersion.document_id == document_id,
        DocumentVersion.id == version_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    rows = session.execute(
        select(ProcessingArtifact, ProcessingRun)
        .join(ProcessingRun, ProcessingRun.id == ProcessingArtifact.processing_run_id)
        .where(
            ProcessingArtifact.tenant_id == tenant_id,
            ProcessingArtifact.project_id == project_id,
            ProcessingRun.document_version_id == version_id,
            ProcessingArtifact.artifact_type == "rendered_page",
        )
        .order_by(ProcessingArtifact.created_at, ProcessingArtifact.id)
    )
    return [
        ProcessingArtifactRead(
            id=artifact.id,
            document_version_id=version_id,
            artifact_type=artifact.artifact_type,
            media_type=artifact.media_type,
            size_bytes=artifact.size_bytes,
            locator=_public_locator((artifact.artifact_metadata or {}).get("locator", {})),
            checksum_sha256=artifact.checksum_sha256,
            created_at=artifact.created_at,
        )
        for artifact, _run in rows
    ]


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/artifacts/{artifact_id}/content",
    response_class=StreamingResponse,
    tags=["documents"],
)
def get_version_artifact_content(
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    artifact_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Stream one rendered-page image only after scoped authorization and checksum verification."""
    _check_tenant(tenant_id, principal)
    try:
        DocumentService(session).get(tenant_id, project_id, document_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    set_tenant_context(session, tenant_id)
    version = session.scalar(select(DocumentVersion).where(
        DocumentVersion.tenant_id == tenant_id,
        DocumentVersion.project_id == project_id,
        DocumentVersion.document_id == document_id,
        DocumentVersion.id == version_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    row = session.execute(
        select(ProcessingArtifact, ProcessingRun)
        .join(ProcessingRun, ProcessingRun.id == ProcessingArtifact.processing_run_id)
        .where(
            ProcessingArtifact.tenant_id == tenant_id,
            ProcessingArtifact.project_id == project_id,
            ProcessingArtifact.id == artifact_id,
            ProcessingArtifact.artifact_type == "rendered_page",
            ProcessingRun.document_version_id == version_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Rendered page not found")
    artifact, _run = row
    if artifact.media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=415, detail="Unsupported rendered-page media type")
    if not artifact.storage_key or not artifact.checksum_sha256 or not artifact.size_bytes:
        raise HTTPException(status_code=503, detail="Rendered page integrity metadata is incomplete")
    store = LocalFileStore(storage_root())
    try:
        source = store.open_verified(
            artifact.storage_key,
            expected_checksum=artifact.checksum_sha256,
            expected_size=artifact.size_bytes,
        )
    except (StorageIntegrityError, FileNotFoundError, ValueError):
        raise HTTPException(status_code=503, detail="Rendered page is unavailable or failed integrity verification") from None

    def stream():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        stream(),
        media_type=artifact.media_type,
        headers={
            "Content-Length": str(artifact.size_bytes),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/knowledge",
    response_model=list[KnowledgeItemRead],
    tags=["knowledge"],
)
def list_project_knowledge(
    tenant_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    set_tenant_context(session, tenant_id)
    items = session.scalars(select(KnowledgeItem).where(
        KnowledgeItem.tenant_id == tenant_id,
        KnowledgeItem.project_id == project_id,
    ).order_by(KnowledgeItem.updated_at.desc(), KnowledgeItem.id))
    return [
        KnowledgeItemRead(
            id=item.id,
            project_id=item.project_id,
            kind=item.kind,
            canonical_key=item.canonical_key,
            canonical_value=item.canonical_value or {},
            status=item.status,
            metadata=item.item_metadata or {},
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]
