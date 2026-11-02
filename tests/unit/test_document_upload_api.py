from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import Principal, get_current_principal
from app.api.dependencies import get_document_upload_service
from app.main import app
from app.storage.upload_service import UploadResult


class FakeUploadService:
    def __init__(self):
        self.replayed = False
        self.version = SimpleNamespace(
            id=uuid4(),
            document_id=uuid4(),
            original_filename="source.pdf",
            media_type="application/pdf",
            size_bytes=12,
            checksum_sha256="a" * 64,
            status="uploaded",
            uploaded_at=datetime.now(UTC),
        )

    def upload(self, *args):
        return UploadResult(self.version, replayed=self.replayed)

    def open_verified(self, *args):
        return self.version, BytesIO(b"%PDF-1.7 test")


def _client_for(tenant_id, service):
    user_id = uuid4()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id, tenant_id)
    app.dependency_overrides[get_document_upload_service] = lambda: service
    return TestClient(app)


def test_multipart_upload_endpoint_and_idempotent_http_statuses():
    tenant_id, project_id, document_id = uuid4(), uuid4(), uuid4()
    service = FakeUploadService()
    client = _client_for(tenant_id, service)
    path = (
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}"
        f"/documents/{document_id}/versions"
    )
    try:
        first = client.post(
            path,
            headers={"Idempotency-Key": "api-upload-key-0001"},
            files={"file": ("source.pdf", b"%PDF-1.7 test", "application/pdf")},
        )
        assert first.status_code == 201
        assert first.json()["id"] == str(service.version.id)

        service.replayed = True
        replay = client.post(
            path,
            headers={"Idempotency-Key": "api-upload-key-0001"},
            files={"file": ("source.pdf", b"%PDF-1.7 test", "application/pdf")},
        )
        assert replay.status_code == 200
    finally:
        app.dependency_overrides.clear()
        client.close()


def test_download_endpoint_streams_only_verified_service_content():
    tenant_id, project_id, document_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    service = FakeUploadService()
    service.version.document_id = document_id
    service.version.id = version_id
    client = _client_for(tenant_id, service)
    path = (
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}"
        f"/documents/{document_id}/versions/{version_id}/content"
    )
    try:
        response = client.get(path)
        assert response.status_code == 200
        assert response.content == b"%PDF-1.7 test"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["etag"] == f'"{"a" * 64}"'
    finally:
        app.dependency_overrides.clear()
        client.close()


def test_upload_endpoint_hides_other_tenant():
    tenant_id, project_id, document_id = uuid4(), uuid4(), uuid4()
    other_tenant = uuid4()
    service = FakeUploadService()
    client = _client_for(tenant_id, service)
    path = (
        f"/api/v1/tenants/{other_tenant}/projects/{project_id}"
        f"/documents/{document_id}/versions"
    )
    try:
        response = client.post(
            path,
            headers={"Idempotency-Key": "api-upload-key-0002"},
            files={"file": ("source.pdf", b"%PDF-1.7 test", "application/pdf")},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        client.close()
