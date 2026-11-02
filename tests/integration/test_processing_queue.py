"""PostgreSQL integration coverage for durable processing runs."""
import os
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select

from app.processing.service import ProcessingConflict, ProcessingService
from app.storage.database import build_session_factory, set_tenant_context
from app.storage.file_store import LocalFileStore
from app.storage.models import DocumentVersion, ProcessingArtifact, ProcessingRun
from app.storage.upload_service import DocumentUploadService
from tests.integration.test_postgres_tenant_isolation import _create_upload_fixture

DATABASE_URL = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")


def _fixture():
    engine = create_engine(os.getenv("DATABASE_URL") or DATABASE_URL)
    try:
        with engine.connect() as connection:
            return _create_upload_fixture(connection)
    finally:
        engine.dispose()


def test_processing_queue_requires_completed_upload_and_is_idempotent(tmp_path):
    tenant_id, project_id, user_id, document_id = _fixture()
    factory = build_session_factory(DATABASE_URL)
    uploads = DocumentUploadService(factory, LocalFileStore(tmp_path / "source"), max_bytes=1024 * 1024)
    processing = ProcessingService(factory)
    try:
        uploaded = uploads.upload(
            tenant_id, project_id, document_id, user_id,
            "processing-upload-001", "source.pdf", BytesIO(b"%PDF-1.7\nprocessing source"),
        )
        run, replayed = processing.enqueue(
            tenant_id, project_id, document_id, uploaded.version.id, user_id,
            "processing-run-001", parser_manifest={"pdf": "pymupdf@1.24"},
        )
        assert run.status == "queued"
        assert run.manifest["source"]["checksum_sha256"] == uploaded.version.checksum_sha256
        assert run.manifest["parsers"]["pdf"] == "pymupdf@1.24"
        assert replayed is False
        replay, replayed = processing.enqueue(
            tenant_id, project_id, document_id, uploaded.version.id, user_id,
            "processing-run-001", parser_manifest={"pdf": "pymupdf@1.24"},
        )
        assert replay.id == run.id and replayed is True
        with pytest.raises(ProcessingConflict, match="different processing request"):
            processing.enqueue(
                tenant_id, project_id, document_id, uploaded.version.id, user_id,
                "processing-run-001", pipeline_version="2",
                parser_manifest={"pdf": "pymupdf@1.24"},
            )
    finally:
        factory.kw["bind"].dispose()


def test_worker_lease_retry_artifact_registration_and_completion(tmp_path):
    tenant_id, project_id, user_id, document_id = _fixture()
    factory = build_session_factory(DATABASE_URL)
    uploads = DocumentUploadService(factory, LocalFileStore(tmp_path / "worker"), max_bytes=1024 * 1024)
    processing = ProcessingService(factory)
    try:
        uploaded = uploads.upload(
            tenant_id, project_id, document_id, user_id,
            "processing-upload-002", "worker.pdf", BytesIO(b"%PDF-1.7\nworker source"),
        )
        queued, _ = processing.enqueue(
            tenant_id, project_id, document_id, uploaded.version.id, user_id,
            "processing-run-002", max_attempts=2,
        )
        claimed = processing.claim_next(tenant_id, "worker-A", lease_seconds=60)
        assert claimed is not None and claimed.id == queued.id and claimed.attempt_count == 1
        assert processing.claim_next(tenant_id, "worker-B") is None
        with pytest.raises(ProcessingConflict):
            processing.heartbeat(tenant_id, queued.id, "worker-B")
        artifact_bytes = b'{"pages":1}'
        artifact = processing.register_artifact(
            tenant_id, queued.id, "worker-A", artifact_type="extraction_manifest",
            storage_key=f"{tenant_id}/{project_id}/{queued.id}/manifest.json",
            checksum_sha256=sha256(artifact_bytes).hexdigest(), size_bytes=len(artifact_bytes),
            media_type="application/json", metadata={"source_version_id": str(uploaded.version.id)},
        )
        assert artifact.processing_run_id == queued.id
        retried = processing.fail(
            tenant_id, queued.id, "worker-A", error_code="temporary_parser_error",
            error_message="temporary", retry_delay_seconds=0,
        )
        assert retried.status == "queued"
        claimed_again = processing.claim_next(tenant_id, "worker-A", lease_seconds=60)
        assert claimed_again is not None and claimed_again.attempt_count == 2
        completed = processing.complete(tenant_id, queued.id, "worker-A")
        assert completed.status == "succeeded"
        with factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            stored = session.get(ProcessingRun, queued.id)
            artifacts = list(session.scalars(select(ProcessingArtifact).where(
                ProcessingArtifact.processing_run_id == queued.id
            )))
            assert stored.status == "succeeded" and len(artifacts) == 1
    finally:
        factory.kw["bind"].dispose()


def test_queue_rejects_version_without_completed_upload_operation(tmp_path):
    tenant_id, project_id, user_id, document_id = _fixture()
    factory = build_session_factory(DATABASE_URL)
    processing = ProcessingService(factory)
    try:
        with factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            version = DocumentVersion(
                id=uuid4(), tenant_id=tenant_id, project_id=project_id,
                document_id=document_id, original_filename="manual.pdf",
                media_type="application/pdf", size_bytes=10, checksum_sha256="a" * 64,
                storage_key=f"{tenant_id}/{project_id}/manual", status="uploaded",
            )
            session.add(version)
            session.flush()
            version_id = version.id
        with pytest.raises(ProcessingConflict, match="completed upload operation"):
            processing.enqueue(
                tenant_id, project_id, document_id, version_id, user_id, "processing-run-003",
            )
    finally:
        factory.kw["bind"].dispose()
