"""Authenticated Tenant, Project and Document endpoints."""
import json
import os
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.api.auth import (
    AuthenticatedIdentity,
    Principal,
    SystemAdminPrincipal,
    get_current_identity,
    get_current_principal,
    get_current_system_admin,
    require_system_permission,
)
from app.api.dependencies import get_document_upload_service
from app.api.schemas import (
    ChatMessageCreate,
    ChatMessageRead,
    ConversationCreate,
    ConversationRead,
    DocumentCreate,
    DocumentRead,
    DocumentVersionRead,
    EvidenceCreate,
    EvidenceRead,
    FindingCreate,
    FindingRead,
    FindingStatusUpdate,
    KnowledgeItemRead,
    ProcessingArtifactRead,
    ProjectCreate,
    ProjectRead,
    ReviewCreate,
    ReviewRead,
    ReviewStatusUpdate,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SessionRead,
    SystemAdminMeRead,
    SystemAuditEventRead,
    SourceFragmentRead,
    TenantMembershipRead,
    TenantRead,
)
from app.llm.lm_studio import LMStudioConfig, LMStudioProvider
from app.storage.config import storage_root
from app.storage.database import get_session, get_session_factory, set_tenant_context
from app.storage.file_store import LocalFileStore, StorageIntegrityError
from app.storage.models import (
    AuditEvent,
    ChatConversation,
    ChatMessage,
    Document,
    DocumentVersion,
    Evidence,
    Finding,
    KnowledgeItem,
    ProcessingArtifact,
    ProcessingRun,
    Review,
    Membership,
    SourceFragment,
    SystemAuditEvent,
    Tenant,
    User,
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


@router.get("/session", response_model=SessionRead)
def get_session_info(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Expose the already-verified principal to a trusted browser API gateway."""
    user = session.scalar(select(User).where(User.id == principal.user_id, User.status == "active"))
    if user is None:
        raise HTTPException(status_code=401, detail="User is inactive or unknown")
    return SessionRead(
        userId=principal.user_id,
        displayName=user.display_name or user.login,
        tenantId=principal.tenant_id,
    )


@router.get("/tenants", response_model=list[TenantMembershipRead])
def list_current_user_tenants(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
):
    """List only active tenants the verified identity may select."""
    rows = session.execute(
        select(Tenant.id, Tenant.name, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(
            Membership.user_id == identity.user_id,
            Membership.status == "active",
            Tenant.status == "active",
        )
        .order_by(Tenant.name, Tenant.id)
    ).all()
    return [
        TenantMembershipRead(id=tenant_id, name=name, role=role)
        for tenant_id, name, role in rows
    ]


@router.get("/admin/me", response_model=SystemAdminMeRead, tags=["admin"])
def get_system_admin_info(
    admin: SystemAdminPrincipal = Depends(get_current_system_admin),
):
    """Return the verified caller's effective PEA system permissions."""
    return SystemAdminMeRead(user_id=admin.user_id, permissions=list(admin.permissions))


@router.get(
    "/admin/audit-events",
    response_model=list[SystemAuditEventRead],
    tags=["admin"],
)
def list_system_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_id: UUID | None = None,
    action: str | None = Query(default=None, min_length=1, max_length=120),
    outcome: str | None = Query(default=None, pattern="^(success|denied|failure)$"),
    identity: AuthenticatedIdentity = Depends(require_system_permission("system.audit.read")),
    session: Session = Depends(get_session),
):
    """List global append-only audit events for explicitly authorized admins."""
    statement = select(SystemAuditEvent)
    if tenant_id is not None:
        statement = statement.where(SystemAuditEvent.tenant_id == tenant_id)
    if action is not None:
        statement = statement.where(SystemAuditEvent.action == action)
    if outcome is not None:
        statement = statement.where(SystemAuditEvent.outcome == outcome)
    return list(
        session.scalars(
            statement.order_by(
                SystemAuditEvent.created_at.desc(),
                SystemAuditEvent.id.desc(),
            ).limit(limit).offset(offset)
        )
    )


@router.get("/admin/tenants", response_model=list[TenantRead], tags=["admin"])
def list_all_tenants(
    identity: AuthenticatedIdentity = Depends(require_system_permission("system.tenants.read")),
    session: Session = Depends(get_session),
):
    """List platform tenants only for users with the dedicated system permission."""
    return list(session.scalars(select(Tenant).order_by(Tenant.name, Tenant.id)))


@router.get("/projects", response_model=list[ProjectRead])
def list_current_user_projects(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """List only projects visible to the authenticated principal in the active tenant."""
    try:
        return ProjectService(session).list(principal.tenant_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Tenant not found") from None


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/search",
    response_model=SearchResponse,
    tags=["search"],
)
def search_project_sources(
    tenant_id: UUID,
    project_id: UUID,
    payload: SearchRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Search only source fragments visible in the verified tenant/project context."""
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None

    set_tenant_context(session, tenant_id)
    escaped = payload.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    statement = (
        select(SourceFragment, DocumentVersion, Document)
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.tenant_id == SourceFragment.tenant_id,
                DocumentVersion.project_id == SourceFragment.project_id,
                DocumentVersion.id == SourceFragment.document_version_id,
            ),
        )
        .join(
            Document,
            and_(
                Document.tenant_id == SourceFragment.tenant_id,
                Document.project_id == SourceFragment.project_id,
                Document.id == DocumentVersion.document_id,
            ),
        )
        .where(
            SourceFragment.tenant_id == tenant_id,
            SourceFragment.project_id == project_id,
            SourceFragment.content.is_not(None),
            SourceFragment.content.ilike(pattern, escape="\\"),
        )
    )
    if payload.filters.document_types:
        statement = statement.where(Document.document_type.in_(payload.filters.document_types))
    if payload.filters.version_state == "current":
        statement = statement.where(Document.current_version_id == DocumentVersion.id)

    rows = session.execute(
        statement.order_by(SourceFragment.created_at.desc(), SourceFragment.id)
        .limit(payload.top_k + 1)
    ).all()
    truncated = len(rows) > payload.top_k
    results = []
    query_lower = payload.query.casefold()
    for fragment, version, document in rows[:payload.top_k]:
        text = fragment.content or ""
        match_at = text.casefold().find(query_lower)
        start = max(0, match_at - 400) if match_at >= 0 else 0
        excerpt = text[start : start + 1200]
        results.append(
            SearchResult(
                fragment_id=fragment.id,
                document_id=document.id,
                document_version_id=version.id,
                document_title=document.title,
                document_type=document.document_type,
                original_filename=version.original_filename,
                fragment_type=fragment.fragment_type,
                locator=fragment.locator,
                excerpt=excerpt,
                content_hash=fragment.content_hash,
            )
        )
    return SearchResponse(query=payload.query, results=results, truncated=truncated)


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
@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/source-fragments/{fragment_id}/preview",
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


def _require_review_write(
    tenant_id: UUID, project_id: UUID, user_id: UUID, session: Session
) -> None:
    try:
        role = DocumentService(session)._require_project_access(tenant_id, project_id, user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    if role not in {"owner", "tenant_admin", "project_manager", "engineer", "reviewer"}:
        raise HTTPException(status_code=403, detail="Project role does not permit review changes")


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/reviews",
    response_model=list[ReviewRead],
    tags=["reviews"],
)
def list_reviews(
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
    return list(session.scalars(
        select(Review)
        .where(Review.tenant_id == tenant_id, Review.project_id == project_id)
        .order_by(Review.created_at.desc(), Review.id)
    ))


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/reviews",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED,
    tags=["reviews"],
)
def create_review(
    tenant_id: UUID,
    project_id: UUID,
    payload: ReviewCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    _require_review_write(tenant_id, project_id, principal.user_id, session)
    if payload.scope == "document_version" and payload.document_version_id is None:
        raise HTTPException(status_code=422, detail="Document-version review requires document_version_id")
    if payload.scope == "project" and payload.document_version_id is not None:
        raise HTTPException(status_code=422, detail="Project review cannot be bound to a document version")
    if payload.document_version_id is not None:
        version = session.scalar(select(DocumentVersion).where(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.project_id == project_id,
            DocumentVersion.id == payload.document_version_id,
        ))
        if version is None:
            raise HTTPException(status_code=404, detail="Document version not found")
    if payload.assigned_to is not None:
        try:
            DocumentService(session)._require_project_access(
                tenant_id, project_id, payload.assigned_to
            )
        except ResourceNotFoundError:
            raise HTTPException(
                status_code=422, detail="Assignee is not an active project member"
            ) from None
    review = Review(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        document_version_id=payload.document_version_id,
        title=payload.title.strip(),
        scope=payload.scope,
        status="draft",
        created_by=principal.user_id,
        assigned_to=payload.assigned_to,
        summary=payload.summary,
        review_metadata={},
    )
    session.add(review)
    session.flush()
    return review


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/reviews/{review_id}/findings",
    response_model=list[FindingRead],
    tags=["reviews"],
)
def list_findings(
    tenant_id: UUID,
    project_id: UUID,
    review_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    set_tenant_context(session, tenant_id)
    review = session.scalar(select(Review).where(
        Review.tenant_id == tenant_id,
        Review.project_id == project_id,
        Review.id == review_id,
    ))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return list(session.scalars(
        select(Finding)
        .where(
            Finding.tenant_id == tenant_id,
            Finding.project_id == project_id,
            Finding.review_id == review_id,
        )
        .order_by(Finding.created_at, Finding.id)
    ))


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/reviews/{review_id}/findings",
    response_model=FindingRead,
    status_code=status.HTTP_201_CREATED,
    tags=["reviews"],
)
def create_finding(
    tenant_id: UUID,
    project_id: UUID,
    review_id: UUID,
    payload: FindingCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    _require_review_write(tenant_id, project_id, principal.user_id, session)
    set_tenant_context(session, tenant_id)
    review = session.scalar(select(Review).where(
        Review.tenant_id == tenant_id,
        Review.project_id == project_id,
        Review.id == review_id,
    ))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    finding = Finding(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        review_id=review_id,
        classification=payload.classification,
        severity=payload.severity,
        status="open",
        title=payload.title.strip(),
        description=payload.description,
        normative_reference=payload.normative_reference,
        requirement_reference=payload.requirement_reference,
        recommendation=payload.recommendation,
        created_by=principal.user_id,
    )
    session.add(finding)
    session.flush()
    return finding


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/findings/{finding_id}/evidence",
    response_model=list[EvidenceRead],
    tags=["evidence"],
)
def list_evidence(
    tenant_id: UUID,
    project_id: UUID,
    finding_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    set_tenant_context(session, tenant_id)
    finding = session.scalar(select(Finding).where(
        Finding.tenant_id == tenant_id,
        Finding.project_id == project_id,
        Finding.id == finding_id,
    ))
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    rows = session.scalars(
        select(Evidence)
        .where(
            Evidence.tenant_id == tenant_id,
            Evidence.project_id == project_id,
            Evidence.finding_id == finding_id,
        )
        .order_by(Evidence.created_at, Evidence.id)
    )
    return [
        EvidenceRead(
            id=item.id,
            tenant_id=item.tenant_id,
            project_id=item.project_id,
            finding_id=item.finding_id,
            evidence_type=item.evidence_type,
            relation=item.relation,
            source_fragment_id=item.source_fragment_id,
            locator=_public_locator(item.locator or {}),
            excerpt=(item.excerpt or "")[:4000] or None,
            reference_label=item.reference_label,
            reference_uri=item.reference_uri,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/findings/{finding_id}/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
    tags=["evidence"],
)
def create_evidence(
    tenant_id: UUID,
    project_id: UUID,
    finding_id: UUID,
    payload: EvidenceCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    _require_review_write(tenant_id, project_id, principal.user_id, session)
    set_tenant_context(session, tenant_id)
    finding = session.scalar(select(Finding).where(
        Finding.tenant_id == tenant_id,
        Finding.project_id == project_id,
        Finding.id == finding_id,
    ))
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if payload.evidence_type == "source_fragment":
        if payload.source_fragment_id is None:
            raise HTTPException(status_code=422, detail="Source-fragment evidence requires source_fragment_id")
        fragment = session.scalar(select(SourceFragment).where(
            SourceFragment.tenant_id == tenant_id,
            SourceFragment.project_id == project_id,
            SourceFragment.id == payload.source_fragment_id,
        ))
        if fragment is None:
            raise HTTPException(status_code=404, detail="Source fragment not found")
    elif payload.source_fragment_id is not None:
        raise HTTPException(status_code=422, detail="Only source-fragment evidence may reference a source fragment")
    if payload.evidence_type == "note" and not (payload.excerpt or "").strip():
        raise HTTPException(status_code=422, detail="Note evidence requires excerpt text")
    if payload.evidence_type == "external_reference" and not (payload.reference_uri or "").strip():
        raise HTTPException(status_code=422, detail="External-reference evidence requires reference_uri")

    evidence = Evidence(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        finding_id=finding_id,
        evidence_type=payload.evidence_type,
        relation=payload.relation,
        source_fragment_id=payload.source_fragment_id,
        locator=_public_locator(payload.locator),
        excerpt=(payload.excerpt or "")[:4000] or None,
        reference_label=payload.reference_label,
        reference_uri=payload.reference_uri,
        created_by=principal.user_id,
    )
    session.add(evidence)
    session.flush()
    return EvidenceRead(
        id=evidence.id,
        tenant_id=evidence.tenant_id,
        project_id=evidence.project_id,
        finding_id=evidence.finding_id,
        evidence_type=evidence.evidence_type,
        relation=evidence.relation,
        source_fragment_id=evidence.source_fragment_id,
        locator=evidence.locator,
        excerpt=evidence.excerpt,
        reference_label=evidence.reference_label,
        reference_uri=evidence.reference_uri,
        created_by=evidence.created_by,
        created_at=evidence.created_at,
    )


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/reviews/{review_id}",
    response_model=ReviewRead,
    tags=["reviews"],
)
def get_review(
    tenant_id: UUID,
    project_id: UUID,
    review_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    set_tenant_context(session, tenant_id)
    review = session.scalar(select(Review).where(
        Review.tenant_id == tenant_id,
        Review.project_id == project_id,
        Review.id == review_id,
    ))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.patch(
    "/tenants/{tenant_id}/projects/{project_id}/reviews/{review_id}",
    response_model=ReviewRead,
    tags=["reviews"],
)
def update_review_status(
    tenant_id: UUID,
    project_id: UUID,
    review_id: UUID,
    payload: ReviewStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    _require_review_write(tenant_id, project_id, principal.user_id, session)
    set_tenant_context(session, tenant_id)
    review = session.scalar(select(Review).where(
        Review.tenant_id == tenant_id,
        Review.project_id == project_id,
        Review.id == review_id,
    ))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    previous_status = review.status
    review.status = payload.status
    if "summary" in payload.model_fields_set:
        review.summary = payload.summary
    session.add(AuditEvent(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_user_id=principal.user_id,
        action="review.status_changed",
        target_type="review",
        target_id=review.id,
        outcome="success",
        details={"from": previous_status, "to": review.status},
    ))
    session.flush()
    return review


@router.patch(
    "/tenants/{tenant_id}/projects/{project_id}/findings/{finding_id}",
    response_model=FindingRead,
    tags=["reviews"],
)
def update_finding_status(
    tenant_id: UUID,
    project_id: UUID,
    finding_id: UUID,
    payload: FindingStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    _require_review_write(tenant_id, project_id, principal.user_id, session)
    set_tenant_context(session, tenant_id)
    finding = session.scalar(select(Finding).where(
        Finding.tenant_id == tenant_id,
        Finding.project_id == project_id,
        Finding.id == finding_id,
    ))
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    previous_status = finding.status
    finding.status = payload.status
    if payload.status == "resolved":
        finding.resolved_by = principal.user_id
        finding.resolved_at = func.now()
    elif previous_status == "resolved":
        finding.resolved_by = None
        finding.resolved_at = None
    session.add(AuditEvent(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_user_id=principal.user_id,
        action="finding.status_changed",
        target_type="finding",
        target_id=finding.id,
        outcome="success",
        details={"from": previous_status, "to": finding.status},
    ))
    session.flush()
    return finding


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/conversations",
    response_model=list[ConversationRead],
    tags=["conversations"],
)
def list_conversations(
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
    return list(session.scalars(
        select(ChatConversation)
        .where(
            ChatConversation.tenant_id == tenant_id,
            ChatConversation.project_id == project_id,
            ChatConversation.status == "active",
        )
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id)
    ))


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["conversations"],
)
def create_conversation(
    tenant_id: UUID,
    project_id: UUID,
    payload: ConversationCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    conversation = ChatConversation(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=principal.user_id,
        title=payload.title.strip(),
        status="active",
    )
    session.add(conversation)
    session.flush()
    return conversation


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageRead],
    tags=["conversations"],
)
def list_conversation_messages(
    tenant_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _check_tenant(tenant_id, principal)
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    set_tenant_context(session, tenant_id)
    conversation = session.scalar(select(ChatConversation).where(
        ChatConversation.tenant_id == tenant_id,
        ChatConversation.project_id == project_id,
        ChatConversation.id == conversation_id,
        ChatConversation.status == "active",
    ))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(session.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.project_id == project_id,
            ChatMessage.conversation_id == conversation_id,
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
    ))


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/conversations/{conversation_id}/messages",
    tags=["conversations"],
)
def send_conversation_message(
    tenant_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    payload: ChatMessageCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Persist the prompt and stream a response from the configured local LM Studio model."""
    _check_tenant(tenant_id, principal)
    model = (os.getenv("PEA_LLM_MODEL") or os.getenv("LM_STUDIO_MODEL", "")).strip()
    if not model:
        raise HTTPException(
            status_code=503,
            detail="Local model is not configured; set PEA_LLM_MODEL",
        )
    try:
        provider = LMStudioProvider(
            LMStudioConfig(
                base_url=os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                api_key=os.getenv("LM_STUDIO_API_KEY", "lm-studio"),
                timeout_seconds=float(os.getenv("LM_STUDIO_TIMEOUT_SECONDS", "180")),
            )
        )
    except (RuntimeError, ValueError):
        raise HTTPException(
            status_code=503,
            detail="Local LM Studio provider is unavailable or incorrectly configured",
        ) from None

    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message cannot be empty")
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None

    factory = get_session_factory()
    with factory.begin() as write_session:
        set_tenant_context(write_session, tenant_id)
        conversation = write_session.scalar(select(ChatConversation).where(
            ChatConversation.tenant_id == tenant_id,
            ChatConversation.project_id == project_id,
            ChatConversation.id == conversation_id,
            ChatConversation.status == "active",
        ))
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history = list(write_session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.project_id == project_id,
                ChatMessage.conversation_id == conversation_id,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(20)
        ))
        history.reverse()
        write_session.add(ChatMessage(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            role="user",
            content=content,
            created_by=principal.user_id,
        ))
        history_payload = [
            {"role": item.role, "content": item.content}
            for item in history
        ]
        history_payload.append({"role": "user", "content": content})

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — помощник Personal Expert AI. Отвечай по существу. "
                "Не выдумывай факты и нормативные ссылки. Если в контексте нет "
                "доказательств, прямо сообщи об этом. Пока не подключён retrieval, "
                "не утверждай, что проверил документы проекта."
            ),
        },
        *history_payload,
    ]

    def event_stream():
        yield "event: message_start\ndata: {}\n\n"
        answer_parts: list[str] = []
        try:
            for item in provider.stream_chat(model=model, messages=messages):
                if item.event == "delta" and item.content:
                    answer_parts.append(item.content)
                    yield "event: text_delta\ndata: " + json.dumps(
                        {"delta": item.content}, ensure_ascii=False
                    ) + "\n\n"
            answer = "".join(answer_parts).strip()
            if answer:
                with factory.begin() as write_session:
                    set_tenant_context(write_session, tenant_id)
                    write_session.add(ChatMessage(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        role="assistant",
                        content=answer,
                        model=model,
                        created_by=None,
                    ))
                    write_session.execute(
                        update(ChatConversation)
                        .where(
                            ChatConversation.tenant_id == tenant_id,
                            ChatConversation.project_id == project_id,
                            ChatConversation.id == conversation_id,
                        )
                        .values(updated_at=func.now())
                    )
            yield "event: message_end\ndata: {}\n\n"
        except Exception:
            # Do not expose provider internals, local paths, or upstream details.
            yield "event: error\ndata: " + json.dumps(
                {"message": "Локальная модель не смогла завершить ответ."},
                ensure_ascii=False,
            ) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
