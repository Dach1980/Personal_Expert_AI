"""PostgreSQL integration tests. Run after `alembic upgrade head`."""
import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.api import auth
from app.storage.database import build_session_factory, set_tenant_context
from app.storage.file_store import LocalFileStore, StorageIntegrityError
from app.storage.models import (
    AuditEvent, DocumentVersion, ExternalIdentity, Membership, Tenant, User,
)
from app.storage.upload_service import DocumentUploadService, UploadAccessDenied, UploadConflict

DATABASE_URL = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")


@pytest.fixture()
def connection():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def _tenant(conn, tenant_id):
    conn.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
    conn.execute(
        text("INSERT INTO tenants (id, name, status) VALUES (:id, 'Tenant', 'active')"),
        {"id": tenant_id},
    )


def test_rls_hides_rows_from_other_tenants(connection):
    tenant_a, tenant_b = uuid4(), uuid4()
    project_a, project_b = uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_a)
        connection.execute(
            text("INSERT INTO projects (id, tenant_id, name, status, metadata) VALUES (:id, :tenant, 'A', 'active', '{}'::jsonb)"),
            {"id": project_a, "tenant": tenant_a},
        )
    with connection.begin():
        _tenant(connection, tenant_b)
        connection.execute(
            text("INSERT INTO projects (id, tenant_id, name, status, metadata) VALUES (:id, :tenant, 'B', 'active', '{}'::jsonb)"),
            {"id": project_b, "tenant": tenant_b},
        )
    with connection.begin():
        # Transaction-local tenant context must not leak from the previous transaction.
        assert connection.execute(text("SELECT count(*) FROM projects")).scalar_one() == 0
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
        visible = connection.execute(text("SELECT id FROM projects")).scalars().all()
        assert visible == [project_a]


def test_composite_fk_rejects_cross_tenant_document(connection):
    tenant_a, tenant_b, project_a = uuid4(), uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_a)
        connection.execute(
            text("INSERT INTO projects (id, tenant_id, name, status, metadata) VALUES (:id, :tenant, 'A', 'active', '{}'::jsonb)"),
            {"id": project_a, "tenant": tenant_a},
        )
    with connection.begin():
        _tenant(connection, tenant_b)
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text("INSERT INTO documents (id, tenant_id, project_id, title, status) VALUES (:id, :tenant, :project, 'cross-tenant', 'active')"),
                    {"id": uuid4(), "tenant": tenant_b, "project": project_a},
                )


def test_document_version_cannot_belong_to_another_project_document(connection):
    tenant_id, project_a, project_b, document_a = uuid4(), uuid4(), uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_id)
        connection.execute(
            text("INSERT INTO projects (id, tenant_id, name, status, metadata) VALUES (:id, :tenant, 'A', 'active', '{}'::jsonb), (:other, :tenant, 'B', 'active', '{}'::jsonb)"),
            {"id": project_a, "other": project_b, "tenant": tenant_id},
        )
        connection.execute(
            text("INSERT INTO documents (id, tenant_id, project_id, title, status) VALUES (:id, :tenant, :project, 'Document A', 'active')"),
            {"id": document_a, "tenant": tenant_id, "project": project_a},
        )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text("""INSERT INTO document_versions
                        (id, tenant_id, project_id, document_id, original_filename,
                         media_type, size_bytes, checksum_sha256, storage_key, status, metadata)
                        VALUES (:id, :tenant, :project, :document, 'a.pdf',
                                'application/pdf', 10, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', :storage, 'uploaded', '{}'::jsonb)"""),
                    {
                        "id": uuid4(), "tenant": tenant_id, "project": project_b,
                        "document": document_a, "storage": f"test/{uuid4()}",
                    },
                )



def test_document_version_source_identity_cannot_be_mutated(connection):
    tenant_id, project_id, document_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    checksum = "b" * 64
    with connection.begin():
        _tenant(connection, tenant_id)
        connection.execute(
            text("INSERT INTO projects (id, tenant_id, name, status, metadata) VALUES (:id, :tenant, 'Integrity', 'active', '{}'::jsonb)"),
            {"id": project_id, "tenant": tenant_id},
        )
        connection.execute(
            text("INSERT INTO documents (id, tenant_id, project_id, title, status) VALUES (:id, :tenant, :project, 'Source', 'active')"),
            {"id": document_id, "tenant": tenant_id, "project": project_id},
        )
        connection.execute(
            text("""INSERT INTO document_versions
                (id, tenant_id, project_id, document_id, original_filename,
                 media_type, size_bytes, checksum_sha256, storage_key, status, metadata)
                VALUES (:id, :tenant, :project, :document, 'source.pdf',
                        'application/pdf', 10, :checksum, :storage, 'uploaded', '{}'::jsonb)"""),
            {
                "id": version_id, "tenant": tenant_id, "project": project_id,
                "document": document_id, "checksum": checksum,
                "storage": f"{tenant_id}/{project_id}/{version_id}/source",
            },
        )
        with pytest.raises(IntegrityError, match="source identity is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE document_versions SET checksum_sha256 = :checksum WHERE id = :id"),
                    {"checksum": "c" * 64, "id": version_id},
                )
        # Workflow state may change; source identity must not.
        connection.execute(
            text("UPDATE document_versions SET status = 'validating' WHERE id = :id"),
            {"id": version_id},
        )


def test_document_version_rejects_invalid_checksum_and_zero_size(connection):
    tenant_id, project_id, document_id = uuid4(), uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_id)
        connection.execute(
            text("INSERT INTO projects (id, tenant_id, name, status, metadata) VALUES (:id, :tenant, 'Integrity', 'active', '{}'::jsonb)"),
            {"id": project_id, "tenant": tenant_id},
        )
        connection.execute(
            text("INSERT INTO documents (id, tenant_id, project_id, title, status) VALUES (:id, :tenant, :project, 'Source', 'active')"),
            {"id": document_id, "tenant": tenant_id, "project": project_id},
        )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text("""INSERT INTO document_versions
                        (id, tenant_id, project_id, document_id, original_filename,
                         media_type, size_bytes, checksum_sha256, storage_key, status, metadata)
                        VALUES (:id, :tenant, :project, :document, 'bad.pdf',
                                'application/pdf', 0, 'not-a-sha256', :storage, 'uploaded', '{}'::jsonb)"""),
                    {
                        "id": uuid4(), "tenant": tenant_id, "project": project_id,
                        "document": document_id, "storage": f"{tenant_id}/{uuid4()}/bad",
                    },
                )



def _create_upload_fixture(connection):
    tenant_id, project_id, user_id, document_id = uuid4(), uuid4(), uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_id)
        connection.execute(
            text("INSERT INTO users (id, login, status) VALUES (:id, :login, 'active')"),
            {"id": user_id, "login": f"upload-{user_id}@test.local"},
        )
        connection.execute(
            text("""INSERT INTO memberships (id, tenant_id, user_id, role, status)
                    VALUES (:id, :tenant, :user, 'member', 'active')"""),
            {"id": uuid4(), "tenant": tenant_id, "user": user_id},
        )
        connection.execute(
            text("""INSERT INTO projects (id, tenant_id, name, status, metadata)
                    VALUES (:id, :tenant, 'Upload project', 'active', '{}'::jsonb)"""),
            {"id": project_id, "tenant": tenant_id},
        )
        connection.execute(
            text("""INSERT INTO project_memberships
                    (id, tenant_id, project_id, user_id, role, status)
                    VALUES (:id, :tenant, :project, :user, 'engineer', 'active')"""),
            {"id": uuid4(), "tenant": tenant_id, "project": project_id, "user": user_id},
        )
        connection.execute(
            text("""INSERT INTO documents
                    (id, tenant_id, project_id, title, status)
                    VALUES (:id, :tenant, :project, 'Upload source', 'active')"""),
            {"id": document_id, "tenant": tenant_id, "project": project_id},
        )
    return tenant_id, project_id, user_id, document_id


def test_upload_is_idempotent_and_download_rechecks_sha256(connection, tmp_path):
    tenant_id, project_id, user_id, document_id = _create_upload_fixture(connection)
    factory = build_session_factory(DATABASE_URL)
    store = LocalFileStore(tmp_path / "private-documents")
    service = DocumentUploadService(factory, store, max_bytes=1024 * 1024)
    source_bytes = b"%PDF-1.7\n% immutable test source"
    try:
        result = service.upload(
            tenant_id, project_id, document_id, user_id,
            "upload-key-0001", "source.pdf", BytesIO(source_bytes),
        )
        assert result.version.checksum_sha256
        assert result.version.size_bytes == len(source_bytes)
        assert result.version.media_type == "application/pdf"
        with factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            upload_audit = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.target_id == result.version.id,
                    AuditEvent.action == "document.version_uploaded",
                )
            )
            assert upload_audit is not None

        # The new upload-operation table must be protected by the same tenant RLS boundary.
        with connection.begin():
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(uuid4())},
            )
            assert connection.execute(
                text("""SELECT count(*) FROM upload_operations
                        WHERE tenant_id = :tenant AND idempotency_key = 'upload-key-0001'"""),
                {"tenant": tenant_id},
            ).scalar_one() == 0

        with connection.begin():
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant_id)},
            )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE upload_operations SET media_type = NULL
                                WHERE tenant_id = :tenant AND idempotency_key = 'upload-key-0001'"""),
                        {"tenant": tenant_id},
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("""UPDATE upload_operations SET document_version_id = NULL
                                WHERE tenant_id = :tenant AND idempotency_key = 'upload-key-0001'"""),
                        {"tenant": tenant_id},
                    )

        replay = service.upload(
            tenant_id, project_id, document_id, user_id,
            "upload-key-0001", "source.pdf", BytesIO(source_bytes),
        )
        assert replay.replayed is True
        assert replay.version.id == result.version.id

        with pytest.raises(UploadConflict):
            service.upload(
                tenant_id, project_id, document_id, user_id,
                "upload-key-0001", "source.pdf", BytesIO(b"%PDF-1.7\nother source"),
            )

        version, stream = service.open_verified(
            tenant_id, project_id, document_id, result.version.id, user_id
        )
        with stream:
            assert stream.read() == source_bytes
        target = store.root / version.storage_key
        target.chmod(0o600)
        target.write_bytes(b"tampered")
        with pytest.raises(StorageIntegrityError):
            service.open_verified(
                tenant_id, project_id, document_id, result.version.id, user_id
            )
        with factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            stored_version = session.get(DocumentVersion, result.version.id)
            assert stored_version.status == "integrity_failed"
            audit = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.target_id == result.version.id,
                    AuditEvent.action == "document.source_integrity_failed",
                )
            )
            assert audit is not None
    finally:
        factory.kw["bind"].dispose()


def test_upload_reconciliation_recovers_publishing_crash(connection, tmp_path):
    tenant_id, project_id, user_id, document_id = _create_upload_fixture(connection)
    factory = build_session_factory(DATABASE_URL)
    store = LocalFileStore(tmp_path / "recovery-documents")
    service = DocumentUploadService(factory, store, max_bytes=1024 * 1024)
    original_put = store.put_stream
    source_bytes = b"%PDF-1.7\n% recover after file/database boundary"
    tenant_prefix = f"{tenant_id}/{project_id}/"
    def fail_published_object(storage_key, chunks, *, max_bytes):
        if storage_key.startswith(tenant_prefix):
            raise OSError("simulated process failure before final object publication")
        return original_put(storage_key, chunks, max_bytes=max_bytes)
    store.put_stream = fail_published_object
    try:
        with pytest.raises(OSError, match="simulated process failure"):
            service.upload(
                tenant_id, project_id, document_id, user_id,
                "recovery-key-0001", "recover.pdf", BytesIO(source_bytes),
            )
        store.put_stream = original_put
        report = service.reconcile(tenant_id, stale_after_seconds=0)
        assert report.inspected == 1
        assert report.recovered == 1
        assert report.failed == 0
        assert report.orphan_keys == ()
    finally:
        factory.kw["bind"].dispose()


def test_viewer_cannot_upload_documents(connection, tmp_path):
    tenant_id, project_id, user_id, document_id = _create_upload_fixture(connection)
    with connection.begin():
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(tenant_id)},
        )
        connection.execute(
            text("""UPDATE project_memberships SET role = 'viewer'
                    WHERE tenant_id = :tenant AND project_id = :project AND user_id = :user"""),
            {"tenant": tenant_id, "project": project_id, "user": user_id},
        )
    factory = build_session_factory(DATABASE_URL)
    service = DocumentUploadService(
        factory, LocalFileStore(tmp_path / "viewer-documents"), max_bytes=1024 * 1024
    )
    try:
        with pytest.raises(UploadAccessDenied):
            service.upload(
                tenant_id, project_id, document_id, user_id,
                "viewer-key-0001", "source.pdf", BytesIO(b"%PDF-1.7\nnot allowed"),
            )
    finally:
        factory.kw["bind"].dispose()


def test_document_read_service_isolates_projects_within_one_tenant(connection):
    from app.storage.services import DocumentService, ResourceNotFoundError

    tenant_id, user_id = uuid4(), uuid4()
    project_a, project_b = uuid4(), uuid4()
    document_a, document_b = uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_id)
        connection.execute(
            text("INSERT INTO users (id, login, status) VALUES (:id, :login, 'active')"),
            {"id": user_id, "login": f"reader-{user_id}@test.local"},
        )
        connection.execute(
            text("""INSERT INTO memberships (id, tenant_id, user_id, role, status)
                    VALUES (:id, :tenant, :user, 'member', 'active')"""),
            {"id": uuid4(), "tenant": tenant_id, "user": user_id},
        )
        connection.execute(
            text("""INSERT INTO projects (id, tenant_id, name, status, metadata)
                    VALUES (:a, :tenant, 'Readable project', 'active', '{}'::jsonb),
                           (:b, :tenant, 'Private project', 'active', '{}'::jsonb)"""),
            {"a": project_a, "b": project_b, "tenant": tenant_id},
        )
        connection.execute(
            text("""INSERT INTO project_memberships
                    (id, tenant_id, project_id, user_id, role, status)
                    VALUES (:id, :tenant, :project, :user, 'engineer', 'active')"""),
            {"id": uuid4(), "tenant": tenant_id, "project": project_a, "user": user_id},
        )
        connection.execute(
            text("""INSERT INTO documents
                    (id, tenant_id, project_id, title, status)
                    VALUES (:a, :tenant, :project_a, 'Visible source', 'active'),
                           (:b, :tenant, :project_b, 'Hidden source', 'active')"""),
            {
                "a": document_a, "b": document_b, "tenant": tenant_id,
                "project_a": project_a, "project_b": project_b,
            },
        )

    factory = build_session_factory(DATABASE_URL)
    try:
        with factory() as session, session.begin():
            service = DocumentService(session)
            assert service.get(
                tenant_id, project_a, document_a, user_id
            ).id == document_a
            assert service.list(tenant_id, project_a, user_id)[0].id == document_a
            with pytest.raises(ResourceNotFoundError):
                service.get(tenant_id, project_b, document_b, user_id)
            with pytest.raises(ResourceNotFoundError):
                service.list(tenant_id, project_b, user_id)
    finally:
        factory.kw["bind"].dispose()



def test_keycloak_principal_sets_rls_context_before_membership_lookup(monkeypatch):
    """A valid identity must resolve through the restricted app role with RLS enabled."""
    tenant_id, user_id = uuid4(), uuid4()
    issuer = "https://sso.integration.test/realms/pea"
    subject = f"subject-{uuid4()}"
    factory = build_session_factory(DATABASE_URL)

    with factory() as session, session.begin():
        set_tenant_context(session, tenant_id)
        session.add(Tenant(id=tenant_id, name="OIDC integration tenant", status="active"))
        session.add(User(id=user_id, login=f"oidc-{user_id}@test.local", status="active"))
        session.flush()
        session.add(
            Membership(
                id=uuid4(), tenant_id=tenant_id, user_id=user_id,
                role="member", status="active",
            )
        )
        session.add(
            ExternalIdentity(
                id=uuid4(), issuer=issuer, subject=subject,
                user_id=user_id, status="active",
            )
        )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": "pea-api",
            "sub": subject,
            "tenant_id": str(tenant_id),
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    class SigningKey:
        key = private_key.public_key()

    class JwksClient:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setenv("OIDC_ISSUER", issuer)
    monkeypatch.setenv("OIDC_AUDIENCE", "pea-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://sso.integration.test/realms/pea/certs")
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: JwksClient())

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    try:
        with factory() as session, session.begin():
            principal = auth.get_current_principal(credentials, session)
            assert principal.user_id == user_id
            assert principal.tenant_id == tenant_id
    finally:
        factory.kw["bind"].dispose()
