"""Durable tenant-scoped document processing queue and run lifecycle."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.storage.database import set_tenant_context
from app.storage.models import (
    AuditEvent, Document, DocumentVersion, Membership, ProcessingArtifact,
    ProcessingRun, ProjectMembership, UploadOperation,
)


class ProcessingAccessDenied(PermissionError):
    """The caller is not allowed to manage processing for this project."""


class ProcessingNotFound(LookupError):
    """The requested processing resource is not visible in the supplied scope."""


class ProcessingConflict(RuntimeError):
    """The requested operation conflicts with an existing processing run."""


class ProcessingService:
    WRITE_ROLES = {"owner", "tenant_admin", "project_manager", "engineer"}

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _authorize(
        session: Session, tenant_id: UUID, project_id: UUID, user_id: UUID, *, write: bool
    ) -> None:
        set_tenant_context(session, tenant_id)
        tenant_member = session.scalar(select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.user_id == user_id,
            Membership.status == "active",
        ))
        project_member = session.scalar(select(ProjectMembership).where(
            ProjectMembership.tenant_id == tenant_id, ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id, ProjectMembership.status == "active",
        ))
        if tenant_member is None:
            raise ProcessingNotFound("Project not found")
        role = tenant_member.role if tenant_member.role in {"owner", "tenant_admin"} else (
            project_member.role if project_member else None
        )
        if role is None:
            raise ProcessingNotFound("Project not found")
        if write and role not in ProcessingService.WRITE_ROLES:
            raise ProcessingAccessDenied("Project role does not permit processing changes")

    def enqueue(
        self, tenant_id: UUID, project_id: UUID, document_id: UUID,
        version_id: UUID, user_id: UUID, idempotency_key: str, *,
        pipeline_name: str = "document-ingestion",
        pipeline_version: str = "1",
        parser_manifest: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> tuple[ProcessingRun, bool]:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
            raise ValueError("Idempotency-Key must be 8-128 safe ASCII characters")
        if not pipeline_name.strip() or len(pipeline_name) > 150:
            raise ValueError("Invalid pipeline_name")
        if not pipeline_version.strip() or len(pipeline_version) > 100:
            raise ValueError("Invalid pipeline_version")
        if not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        parsers = parser_manifest or {}
        if not isinstance(parsers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            or not key.strip() or not value.strip()
            for key, value in parsers.items()
        ):
            raise ValueError("parser_manifest must map format names to non-empty version strings")
        if len(json.dumps(parsers, sort_keys=True, separators=(",", ":"))) > 32768:
            raise ValueError("parser_manifest exceeds 32 KiB")

        with self.session_factory() as session, session.begin():
            self._authorize(session, tenant_id, project_id, user_id, write=True)
            # Serialize concurrent requests that reuse the same tenant/project key.
            lock_key = f"{tenant_id}:{project_id}:{idempotency_key}"
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )
            existing = session.scalar(select(ProcessingRun).where(
                ProcessingRun.tenant_id == tenant_id,
                ProcessingRun.project_id == project_id,
                ProcessingRun.idempotency_key == idempotency_key,
            ))
            if existing is not None:
                same_request = (
                    existing.document_version_id == version_id
                    and existing.pipeline_name == pipeline_name
                    and existing.pipeline_version == pipeline_version
                    and existing.max_attempts == max_attempts
                    and existing.manifest.get("parsers", {}) == parsers
                )
                if not same_request:
                    raise ProcessingConflict("Idempotency key was already used for another processing request")
                return existing, True

            document = session.scalar(select(Document).where(
                Document.tenant_id == tenant_id, Document.project_id == project_id,
                Document.id == document_id, Document.status == "active",
            ))
            version = session.scalar(select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.project_id == project_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.id == version_id,
            ))
            if document is None or version is None:
                raise ProcessingNotFound("Document version not found")
            if version.status != "uploaded":
                raise ProcessingConflict("Only an uploaded, integrity-verified DocumentVersion can be queued")
            upload = session.scalar(select(UploadOperation).where(
                UploadOperation.tenant_id == tenant_id,
                UploadOperation.project_id == project_id,
                UploadOperation.document_id == document_id,
                UploadOperation.document_version_id == version_id,
                UploadOperation.status == "completed",
            ))
            if upload is None:
                raise ProcessingConflict("DocumentVersion has no completed upload operation")

            run = ProcessingRun(
                id=uuid4(), tenant_id=tenant_id, project_id=project_id,
                document_version_id=version_id, pipeline_name=pipeline_name,
                pipeline_version=pipeline_version, status="queued",
                idempotency_key=idempotency_key, max_attempts=max_attempts,
                manifest={
                    "source": {
                        "document_id": str(document_id), "document_version_id": str(version_id),
                        "checksum_sha256": version.checksum_sha256,
                        "size_bytes": version.size_bytes, "media_type": version.media_type,
                    },
                    "parsers": parsers,
                },
            )
            session.add(run)
            session.flush()
            session.add(AuditEvent(
                id=uuid4(), tenant_id=tenant_id, actor_user_id=user_id,
                action="document.processing_queued", target_type="processing_run",
                target_id=run.id, outcome="success",
                details={
                    "document_version_id": str(version_id),
                    "pipeline_name": pipeline_name, "pipeline_version": pipeline_version,
                    "parser_manifest": parsers,
                },
            ))
            return run, False

    def list_for_version(
        self, tenant_id: UUID, project_id: UUID, document_id: UUID,
        version_id: UUID, user_id: UUID,
    ) -> list[ProcessingRun]:
        with self.session_factory() as session, session.begin():
            self._authorize(session, tenant_id, project_id, user_id, write=False)
            version = session.scalar(select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id, DocumentVersion.project_id == project_id,
                DocumentVersion.document_id == document_id, DocumentVersion.id == version_id,
            ))
            if version is None:
                raise ProcessingNotFound("Document version not found")
            return list(session.scalars(select(ProcessingRun).where(
                ProcessingRun.tenant_id == tenant_id, ProcessingRun.project_id == project_id,
                ProcessingRun.document_version_id == version_id,
            ).order_by(ProcessingRun.created_at.desc())))

    def claim_next(
        self, tenant_id: UUID, worker_id: str, *, lease_seconds: int = 300
    ) -> ProcessingRun | None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", worker_id):
            raise ValueError("Invalid worker_id")
        if not 15 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 15 and 3600")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            candidates = list(session.scalars(
                select(ProcessingRun).where(
                    ProcessingRun.tenant_id == tenant_id,
                    or_(
                        (ProcessingRun.status == "queued") & (ProcessingRun.available_at <= now),
                        (ProcessingRun.status == "running") & (ProcessingRun.lease_expires_at <= now),
                    ),
                ).order_by(ProcessingRun.available_at, ProcessingRun.created_at)
                .with_for_update(skip_locked=True).limit(20)
            ))
            for run in candidates:
                if run.attempt_count >= run.max_attempts:
                    run.status = "failed"
                    run.finished_at = now
                    run.lease_owner = None
                    run.lease_expires_at = None
                    run.error_code = "lease_attempts_exhausted"
                    run.error_message = "Worker lease expired and retry limit was reached"
                    session.add(AuditEvent(
                        id=uuid4(), tenant_id=tenant_id, action="document.processing_failed",
                        target_type="processing_run", target_id=run.id, outcome="failure",
                        details={"error_code": run.error_code, "attempt_count": run.attempt_count},
                    ))
                    continue
                run.status = "running"
                run.attempt_count += 1
                run.lease_owner = worker_id
                run.lease_expires_at = now + timedelta(seconds=lease_seconds)
                run.heartbeat_at = now
                run.started_at = run.started_at or now
                run.finished_at = None
                session.flush()
                return run
            return None

    def heartbeat(
        self, tenant_id: UUID, run_id: UUID, worker_id: str, *, lease_seconds: int = 300
    ) -> ProcessingRun:
        if not 15 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 15 and 3600")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            run = session.scalar(select(ProcessingRun).where(
                ProcessingRun.tenant_id == tenant_id, ProcessingRun.id == run_id,
                ProcessingRun.status == "running", ProcessingRun.lease_owner == worker_id,
                ProcessingRun.lease_expires_at > now,
            ).with_for_update())
            if run is None:
                raise ProcessingConflict("Worker lease is missing, expired, or owned by another worker")
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return run

    def register_artifact(
        self, tenant_id: UUID, run_id: UUID, worker_id: str, *,
        artifact_type: str, storage_key: str, checksum_sha256: str,
        size_bytes: int, media_type: str, metadata: dict[str, Any] | None = None,
    ) -> ProcessingArtifact:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,99}", artifact_type):
            raise ValueError("Invalid artifact_type")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum_sha256):
            raise ValueError("Invalid artifact SHA-256")
        if size_bytes <= 0 or not storage_key.strip() or len(storage_key) > 500:
            raise ValueError("Invalid artifact storage metadata")
        normalized_key = storage_key.replace("\\", "/")
        if (
            normalized_key.startswith("/") or re.match(r"^[A-Za-z]:", normalized_key)
            or any(part in {"", ".", ".."} for part in normalized_key.split("/"))
        ):
            raise ValueError("Unsafe artifact storage key")
        if not media_type.strip() or len(media_type) > 150:
            raise ValueError("Invalid artifact media type")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("Artifact metadata must be an object")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            run = session.scalar(select(ProcessingRun).where(
                ProcessingRun.tenant_id == tenant_id, ProcessingRun.id == run_id,
                ProcessingRun.status == "running", ProcessingRun.lease_owner == worker_id,
                ProcessingRun.lease_expires_at > now,
            ).with_for_update())
            if run is None:
                raise ProcessingConflict("A valid worker lease is required to register an artifact")
            artifact = ProcessingArtifact(
                id=uuid4(), tenant_id=tenant_id, project_id=run.project_id,
                processing_run_id=run.id, artifact_type=artifact_type,
                storage_key=storage_key, checksum_sha256=checksum_sha256,
                size_bytes=size_bytes, media_type=media_type,
                artifact_metadata=metadata or {},
            )
            session.add(artifact)
            session.flush()
            return artifact

    def complete(self, tenant_id: UUID, run_id: UUID, worker_id: str) -> ProcessingRun:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            run = session.scalar(select(ProcessingRun).where(
                ProcessingRun.tenant_id == tenant_id, ProcessingRun.id == run_id,
                ProcessingRun.status == "running", ProcessingRun.lease_owner == worker_id,
                ProcessingRun.lease_expires_at > now,
            ).with_for_update())
            if run is None:
                raise ProcessingConflict("A valid worker lease is required to complete the run")
            run.status = "succeeded"
            run.finished_at = now
            run.lease_owner = None
            run.lease_expires_at = None
            session.add(AuditEvent(
                id=uuid4(), tenant_id=tenant_id, action="document.processing_succeeded",
                target_type="processing_run", target_id=run.id, outcome="success",
                details={"attempt_count": run.attempt_count},
            ))
            return run

    def fail(
        self, tenant_id: UUID, run_id: UUID, worker_id: str, *,
        error_code: str, error_message: str, retry_delay_seconds: int = 30,
    ) -> ProcessingRun:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            run = session.scalar(select(ProcessingRun).where(
                ProcessingRun.tenant_id == tenant_id, ProcessingRun.id == run_id,
                ProcessingRun.status == "running", ProcessingRun.lease_owner == worker_id,
                ProcessingRun.lease_expires_at > now,
            ).with_for_update())
            if run is None:
                raise ProcessingConflict("A valid worker lease is required to fail the run")
            run.error_code = error_code[:100]
            run.error_message = error_message[:2000]
            run.lease_owner = None
            run.lease_expires_at = None
            if run.attempt_count < run.max_attempts:
                run.status = "queued"
                run.available_at = now + timedelta(seconds=max(0, min(retry_delay_seconds, 86400)))
            else:
                run.status = "failed"
                run.finished_at = now
            session.add(AuditEvent(
                id=uuid4(), tenant_id=tenant_id, action="document.processing_failed",
                target_type="processing_run", target_id=run.id,
                outcome="failure", details={
                    "error_code": run.error_code, "attempt_count": run.attempt_count,
                    "will_retry": run.status == "queued",
                },
            ))
            return run
