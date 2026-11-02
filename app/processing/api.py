"""Authenticated API for queueing and inspecting document processing runs."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_current_principal
from app.storage.database import get_session, get_session_factory
from app.processing.service import (
    ProcessingAccessDenied, ProcessingConflict, ProcessingNotFound, ProcessingService,
)

router = APIRouter(prefix="/api/v1", tags=["document-processing"])


class ProcessingRunCreate(BaseModel):
    pipeline_name: str = Field(default="document-ingestion", min_length=1, max_length=150)
    pipeline_version: str = Field(default="1", min_length=1, max_length=100)
    parser_manifest: dict[str, object] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)


class ProcessingRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_version_id: UUID
    pipeline_name: str
    pipeline_version: str
    status: str
    manifest: dict[str, object]
    attempt_count: int
    max_attempts: int
    available_at: object
    started_at: object | None
    finished_at: object | None
    error_code: str | None
    error_message: str | None


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/processing-runs",
    response_model=ProcessingRunRead,
    status_code=status.HTTP_201_CREATED,
)
def enqueue_processing_run(
    tenant_id: UUID, project_id: UUID, document_id: UUID, version_id: UUID,
    payload: ProcessingRunCreate,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
):
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        run, replayed = ProcessingService(get_session_factory()).enqueue(
            tenant_id, project_id, document_id, version_id, principal.user_id,
            idempotency_key, pipeline_name=payload.pipeline_name,
            pipeline_version=payload.pipeline_version,
            parser_manifest=payload.parser_manifest, max_attempts=payload.max_attempts,
        )
        # The API response is stable for idempotent replay; callers can distinguish it by status.
        return run
    except ProcessingAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ProcessingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProcessingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/processing-runs",
    response_model=list[ProcessingRunRead],
)
def list_processing_runs(
    tenant_id: UUID, project_id: UUID, document_id: UUID, version_id: UUID,
    principal: Principal = Depends(get_current_principal),
):
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        return ProcessingService(get_session_factory()).list_for_version(
            tenant_id, project_id, document_id, version_id, principal.user_id
        )
    except ProcessingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
