"""Durable, tenant-scoped document upload and recovery workflow."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.storage.document_validation import detect_document_type
from app.storage.file_store import (
    LocalFileStore,
    StorageConflictError,
    StorageIntegrityError,
)
from app.storage.models import (
    Document,
    DocumentVersion,
    Membership,
    ProjectMembership,
    UploadOperation,
)


class UploadAccessDenied(PermissionError):
    """Caller cannot upload or download within the requested project."""


class UploadNotFound(LookupError):
    """The scoped document or version does not exist."""


class UploadConflict(RuntimeError):
    """The idempotency key is already in use by another or unfinished request."""


class UploadValidationError(ValueError):
    """Upload metadata or file contents are invalid."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    version: DocumentVersion
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    inspected: int
    recovered: int
    failed: int
    missing: int
    orphan_keys: tuple[str, ...]


def _safe_filename(value: str) -> str:
    filename = Path(unquote(value.replace("\\", "/"))).name.strip()
    if not filename or filename in {".", ".."} or len(filename) > 500:
        raise UploadValidationError("Invalid original filename")
    if any(ord(char) < 32 for char in filename):
        raise UploadValidationError("Filename contains control characters")
    return filename


def _chunks(stream: BinaryIO, chunk_size: int = 1024 * 1024):
    while chunk := stream.read(chunk_size):
        yield chunk


def _hash_stream(stream: BinaryIO, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    stream.seek(0)
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise UploadValidationError("File exceeds the configured size limit")
        digest.update(chunk)
    stream.seek(0)
    if size == 0:
        raise UploadValidationError("Empty files are not accepted")
    return digest.hexdigest(), size


def _hash_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class DocumentUploadService:
    """Coordinates independent durable DB transactions and immutable file writes."""

    UPLOAD_ROLES = {"owner", "tenant_admin", "project_manager", "engineer"}

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        store: LocalFileStore,
        *,
        max_bytes: int,
    ) -> None:
        self.session_factory = session_factory
        self.store = store
        self.max_bytes = max_bytes

    def _authorize(
        self, session: Session, tenant_id: UUID, project_id: UUID,
        document_id: UUID, user_id: UUID, *, write: bool,
    ) -> Document:
        from app.storage.database import set_tenant_context

        set_tenant_context(session, tenant_id)
        tenant_member = session.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == user_id,
                Membership.status == "active",
            )
        )
        project_member = session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.tenant_id == tenant_id,
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.status == "active",
            )
        )
        tenant_admin = tenant_member is not None and tenant_member.role in {"owner", "tenant_admin"}
        role = tenant_member.role if tenant_admin else (project_member.role if project_member else None)
        if role is None or (write and role not in self.UPLOAD_ROLES):
            raise UploadAccessDenied("Project access does not permit this operation")
        document = session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.project_id == project_id,
                Document.id == document_id,
            )
        )
        if document is None:
            raise UploadNotFound("Document not found")
        return document

    def upload(
        self,
        tenant_id: UUID,
        project_id: UUID,
        document_id: UUID,
        user_id: UUID,
        idempotency_key: str,
        original_filename: str,
        source: BinaryIO,
    ) -> UploadResult:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
            raise UploadValidationError("Idempotency-Key must be 8-128 safe ASCII characters")
        filename = _safe_filename(original_filename)

        with self.session_factory() as session, session.begin():
            self._authorize(session, tenant_id, project_id, document_id, user_id, write=True)
            operation = session.scalar(
                select(UploadOperation).where(
                    UploadOperation.tenant_id == tenant_id,
                    UploadOperation.project_id == project_id,
                    UploadOperation.idempotency_key == idempotency_key,
                )
            )
            if operation is not None:
                existing_id = operation.id
                existing_status = operation.status
                existing_hash = operation.checksum_sha256
                existing_size = operation.size_bytes
                existing_version_id = operation.document_version_id
                existing_document_id = operation.document_id
                existing_filename = operation.original_filename
            else:
                existing_id = None
                existing_status = None
                existing_hash = None
                existing_size = None
                existing_version_id = None
                existing_document_id = None
                existing_filename = None

        if existing_id is not None:
            if existing_document_id != document_id or existing_filename != filename:
                raise UploadConflict("Idempotency key was already used for a different document or filename")
            if existing_status != "completed" or not existing_version_id:
                raise UploadConflict("An upload with this idempotency key is already in progress or failed")
            digest, size = _hash_stream(source, self.max_bytes)
            if digest != existing_hash or size != existing_size:
                raise UploadConflict("Idempotency key was already used for different file contents")
            with self.session_factory() as session, session.begin():
                self._authorize(session, tenant_id, project_id, document_id, user_id, write=False)
                version = session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.tenant_id == tenant_id,
                        DocumentVersion.project_id == project_id,
                        DocumentVersion.id == existing_version_id,
                    )
                )
                if version is None:
                    raise StorageIntegrityError("Completed upload has no registered document version")
                self.store.verify(
                    version.storage_key,
                    expected_checksum=version.checksum_sha256,
                    expected_size=version.size_bytes,
                )
                return UploadResult(version=version, replayed=True)

        operation_id = uuid4()
        suffix = Path(filename).suffix.lower()
        quarantine_key = f"quarantine/{tenant_id}/{operation_id}.part"
        storage_key = (
            f"{tenant_id}/{project_id}/{document_id}/{operation_id}/source{suffix}"
        )
        with self.session_factory() as session, session.begin():
            from app.storage.database import set_tenant_context

            set_tenant_context(session, tenant_id)
            self._authorize(session, tenant_id, project_id, document_id, user_id, write=True)
            session.add(
                UploadOperation(
                    id=operation_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    idempotency_key=idempotency_key,
                    created_by=user_id,
                    status="receiving",
                    original_filename=filename,
                    quarantine_key=quarantine_key,
                    storage_key=storage_key,
                )
            )
            try:
                session.flush()
            except IntegrityError:
                raise UploadConflict("Idempotency key was concurrently registered") from None

        try:
            quarantined = self.store.put_stream(
                quarantine_key, _chunks(source), max_bytes=self.max_bytes
            )
            quarantine_path = self.store.root / quarantine_key
            media_type = detect_document_type(quarantine_path, filename)
            with self.session_factory() as session, session.begin():
                from app.storage.database import set_tenant_context

                set_tenant_context(session, tenant_id)
                operation = session.get(UploadOperation, operation_id)
                if operation is None:
                    raise RuntimeError("Upload operation disappeared during ingestion")
                operation.media_type = media_type
                operation.size_bytes = quarantined.size_bytes
                operation.checksum_sha256 = quarantined.checksum_sha256
                operation.status = "quarantined"
            self._publish_and_finalize(operation_id, tenant_id)
        except (UploadValidationError, ValueError) as exc:
            self._mark_failed(operation_id, tenant_id, "validation_failed", str(exc))
            self.store.delete(quarantine_key)
            raise
        except Exception:
            # Leave a durable non-terminal operation and its files for reconciliation.
            raise

        with self.session_factory() as session, session.begin():
            from app.storage.database import set_tenant_context

            set_tenant_context(session, tenant_id)
            operation = session.get(UploadOperation, operation_id)
            if operation is None or operation.document_version_id is None:
                raise RuntimeError("Upload completed without a registered version")
            version = session.get(DocumentVersion, operation.document_version_id)
            if version is None:
                raise RuntimeError("Upload completed without a registered version")
            result = UploadResult(version=version)
        self.store.delete(quarantine_key)
        return result

    def _publish_and_finalize(self, operation_id: UUID, tenant_id: UUID) -> None:
        from app.storage.database import set_tenant_context

        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            operation = session.get(UploadOperation, operation_id)
            if operation is None:
                raise UploadNotFound("Upload operation not found")
            if operation.status == "completed":
                return
            if operation.status not in {"quarantined", "publishing"}:
                raise UploadConflict("Upload operation is not ready for publication")
            operation.status = "publishing"
            quarantine_key = operation.quarantine_key
            storage_key = operation.storage_key
            checksum = operation.checksum_sha256
            size = operation.size_bytes

        if not self.store.exists(storage_key):
            if not self.store.exists(quarantine_key):
                raise StorageIntegrityError("Neither quarantine nor published source exists")
            with self.store.open(quarantine_key) as source:
                try:
                    self.store.put_stream(storage_key, _chunks(source), max_bytes=self.max_bytes)
                except StorageConflictError:
                    pass
        self.store.verify(storage_key, expected_checksum=checksum, expected_size=size)

        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            operation = session.scalar(
                select(UploadOperation)
                .where(UploadOperation.id == operation_id)
                .with_for_update()
            )
            if operation is None:
                raise UploadNotFound("Upload operation not found")
            if operation.status == "completed":
                return
            document = session.scalar(
                select(Document).where(
                    Document.tenant_id == tenant_id,
                    Document.project_id == operation.project_id,
                    Document.id == operation.document_id,
                )
            )
            if document is None:
                raise UploadNotFound("Document disappeared before upload finalization")
            version = session.get(DocumentVersion, operation.document_version_id) if operation.document_version_id else None
            if version is None:
                version = DocumentVersion(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    project_id=operation.project_id,
                    document_id=operation.document_id,
                    original_filename=operation.original_filename,
                    media_type=operation.media_type,
                    size_bytes=operation.size_bytes,
                    checksum_sha256=operation.checksum_sha256,
                    storage_key=operation.storage_key,
                    status="uploaded",
                    uploaded_by=operation.created_by,
                    version_metadata={"upload_operation_id": str(operation.id)},
                )
                session.add(version)
                session.flush()
            document.current_version_id = version.id
            operation.document_version_id = version.id
            operation.status = "completed"
            operation.completed_at = datetime.now(timezone.utc)

    def _mark_failed(self, operation_id: UUID, tenant_id: UUID, code: str, message: str) -> None:
        from app.storage.database import set_tenant_context

        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            operation = session.get(UploadOperation, operation_id)
            if operation is not None and operation.status != "completed":
                operation.status = "failed"
                operation.error_code = code
                operation.error_message = message[:2000]

    def get_version(
        self, tenant_id: UUID, project_id: UUID, document_id: UUID,
        version_id: UUID, user_id: UUID,
    ) -> DocumentVersion:
        from app.storage.database import set_tenant_context

        with self.session_factory() as session, session.begin():
            self._authorize(session, tenant_id, project_id, document_id, user_id, write=False)
            version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.tenant_id == tenant_id,
                    DocumentVersion.project_id == project_id,
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.id == version_id,
                )
            )
            if version is None:
                raise UploadNotFound("Document version not found")
            return version

    def open_verified(
        self, tenant_id: UUID, project_id: UUID, document_id: UUID,
        version_id: UUID, user_id: UUID,
    ) -> tuple[DocumentVersion, BinaryIO]:
        version = self.get_version(
            tenant_id, project_id, document_id, version_id, user_id
        )
        stream = self.store.open_verified(
            version.storage_key,
            expected_checksum=version.checksum_sha256,
            expected_size=version.size_bytes,
        )
        return version, stream

    def reconcile(
        self, tenant_id: UUID, *, stale_after_seconds: int = 900
    ) -> ReconciliationReport:
        from app.storage.database import set_tenant_context

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            operations = list(
                session.scalars(
                    select(UploadOperation).where(
                        UploadOperation.tenant_id == tenant_id,
                        UploadOperation.status != "completed",
                    )
                )
            )
            operation_ids = [item.id for item in operations]
            known_keys = {
                item.storage_key for item in session.scalars(
                    select(DocumentVersion).where(DocumentVersion.tenant_id == tenant_id)
                )
            }
            known_keys.update(item.quarantine_key for item in operations)
            known_keys.update(item.storage_key for item in operations)

        recovered = failed = missing = 0
        for operation_id in operation_ids:
            try:
                with self.session_factory() as session, session.begin():
                    set_tenant_context(session, tenant_id)
                    operation = session.get(UploadOperation, operation_id)
                    if operation is None:
                        continue
                    if operation.status == "receiving":
                        if not self.store.exists(operation.quarantine_key):
                            if operation.created_at < cutoff:
                                operation.status = "failed"
                                operation.error_code = "stale_upload_without_quarantine"
                                operation.error_message = "No quarantined bytes were found"
                                failed += 1
                            else:
                                missing += 1
                            continue
                        path = self.store.root / operation.quarantine_key
                        digest, size = _hash_path(path)
                        media_type = detect_document_type(path, operation.original_filename)
                        operation.checksum_sha256 = digest
                        operation.size_bytes = size
                        operation.media_type = media_type
                        operation.status = "quarantined"
                self._publish_and_finalize(operation_id, tenant_id)
                recovered += 1
            except Exception as exc:
                with self.session_factory() as session, session.begin():
                    set_tenant_context(session, tenant_id)
                    operation = session.get(UploadOperation, operation_id)
                    if operation is not None and operation.status != "completed":
                        operation.error_code = "reconciliation_error"
                        operation.error_message = str(exc)[:2000]
                failed += 1

        with self.session_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            versions = list(session.scalars(
                select(DocumentVersion).where(DocumentVersion.tenant_id == tenant_id)
            ))
            completed_operations = list(session.scalars(
                select(UploadOperation).where(
                    UploadOperation.tenant_id == tenant_id,
                    UploadOperation.status == "completed",
                )
            ))
            known_keys.update(item.storage_key for item in versions)
            for version in versions:
                try:
                    self.store.verify(
                        version.storage_key,
                        expected_checksum=version.checksum_sha256,
                        expected_size=version.size_bytes,
                    )
                except (StorageIntegrityError, FileNotFoundError):
                    missing += 1
            for operation in completed_operations:
                self.store.delete(operation.quarantine_key)
            known_keys.update(
                item.storage_key for item in session.scalars(
                    select(UploadOperation).where(UploadOperation.tenant_id == tenant_id)
                )
            )
            known_keys.update(
                item.quarantine_key for item in session.scalars(
                    select(UploadOperation).where(
                        UploadOperation.tenant_id == tenant_id,
                        UploadOperation.status != "completed",
                    )
                )
            )
            known_keys.update(
                item.storage_key for item in session.scalars(
                    select(UploadOperation).where(UploadOperation.tenant_id == tenant_id)
                )
            )
        tenant_prefix = f"{tenant_id}/"
        orphan_keys = tuple(
            key for key in self.store.iter_objects()
            if (key.startswith(tenant_prefix) or key.startswith(f"quarantine/{tenant_id}/"))
            and key not in known_keys
        )
        return ReconciliationReport(
            inspected=len(operation_ids),
            recovered=recovered,
            failed=failed,
            missing=missing,
            orphan_keys=orphan_keys,
        )
