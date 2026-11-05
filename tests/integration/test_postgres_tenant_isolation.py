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
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.api import auth
from app.storage.database import build_session_factory, set_tenant_context, set_user_context
from app.storage.file_store import LocalFileStore, StorageIntegrityError
from app.storage.models import (
    AuditEvent,
    DocumentVersion,
    Evidence,
    ExternalIdentity,
    Finding,
    Membership,
    Project,
    Review,
    SystemAdminGrant,
    SystemAuditEvent,
    Tenant,
    User,
)
from app.storage.upload_service import DocumentUploadService, UploadAccessDenied, UploadConflict

OWNER_DATABASE_URL = os.getenv("DATABASE_URL")
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL")
DATABASE_URL = APP_DATABASE_URL or OWNER_DATABASE_URL
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


def test_chat_conversations_and_messages_enforce_tenant_and_project_scope(connection):
    tenant_a, tenant_b = uuid4(), uuid4()
    user_id, project_a, project_b, conversation_id = uuid4(), uuid4(), uuid4(), uuid4()
    with connection.begin():
        _tenant(connection, tenant_a)
        connection.execute(
            text("INSERT INTO users (id, login, status) VALUES (:id, :login, 'active')"),
            {"id": user_id, "login": f"{user_id}@example.test"},
        )
        connection.execute(
            text("""INSERT INTO memberships (id, tenant_id, user_id, role, status)
                    VALUES (:id, :tenant, :user, 'member', 'active')"""),
            {"id": uuid4(), "tenant": tenant_a, "user": user_id},
        )
        connection.execute(
            text("""INSERT INTO projects (id, tenant_id, name, status, metadata)
                    VALUES (:a, :tenant, 'Chat A', 'active', '{}'::jsonb),
                           (:b, :tenant, 'Chat B', 'active', '{}'::jsonb)"""),
            {"a": project_a, "b": project_b, "tenant": tenant_a},
        )
        connection.execute(
            text("""INSERT INTO chat_conversations
                    (id, tenant_id, project_id, created_by, title, status)
                    VALUES (:id, :tenant, :project, :user, 'Chat', 'active')"""),
            {"id": conversation_id, "tenant": tenant_a, "project": project_a, "user": user_id},
        )
        connection.execute(
            text("""INSERT INTO chat_messages
                    (id, tenant_id, project_id, conversation_id, role, content, created_by)
                    VALUES (:id, :tenant, :project, :conversation, 'user', 'Question', :user)"""),
            {
                "id": uuid4(), "tenant": tenant_a, "project": project_a,
                "conversation": conversation_id, "user": user_id,
            },
        )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text("""INSERT INTO chat_messages
                            (id, tenant_id, project_id, conversation_id, role, content, created_by)
                            VALUES (:id, :tenant, :project, :conversation, 'user', 'Cross project', :user)"""),
                    {
                        "id": uuid4(), "tenant": tenant_a, "project": project_b,
                        "conversation": conversation_id, "user": user_id,
                    },
                )
    with connection.begin():
        _tenant(connection, tenant_b)
        assert connection.execute(text("SELECT count(*) FROM chat_conversations")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM chat_messages")).scalar_one() == 0


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



def test_keycloak_principal_switches_between_active_tenants_without_jwt_tenant_claim(monkeypatch):
    """One verified identity can select only its own active tenants under RLS."""
    tenant_a, tenant_b, tenant_forbidden, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    issuer = "https://sso.integration.test/realms/pea"
    subject = f"subject-{uuid4()}"
    factory = build_session_factory(OWNER_DATABASE_URL or DATABASE_URL)

    with factory() as session, session.begin():
        session.add(User(id=user_id, login=f"oidc-{user_id}@test.local", status="active"))
        session.flush()
        for tenant_id, tenant_name, role in (
            (tenant_a, "OIDC tenant A", "member"),
            (tenant_b, "OIDC tenant B", "tenant_admin"),
            (tenant_forbidden, "OIDC tenant forbidden", None),
        ):
            set_tenant_context(session, tenant_id)
            session.add(Tenant(id=tenant_id, name=tenant_name, status="active"))
            if role is not None:
                session.add(
                    Membership(
                        id=uuid4(), tenant_id=tenant_id, user_id=user_id,
                        role=role, status="active",
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
    rls_factory = build_session_factory(APP_DATABASE_URL or DATABASE_URL)
    try:
        with rls_factory() as session, session.begin():
            principal_a = auth.get_current_principal(
                credentials, session, x_tenant_id=str(tenant_a)
            )
            principal_b = auth.get_current_principal(
                credentials, session, x_tenant_id=str(tenant_b)
            )
            assert principal_a.user_id == principal_b.user_id == user_id
            assert principal_a.tenant_id == tenant_a
            assert principal_a.membership_role == "member"
            assert principal_b.tenant_id == tenant_b
            assert principal_b.membership_role == "tenant_admin"
            with pytest.raises(Exception):
                auth.get_current_principal(
                    credentials, session, x_tenant_id=str(tenant_forbidden)
                )
    finally:
        factory.kw["bind"].dispose()
        rls_factory.kw["bind"].dispose()


def test_review_finding_evidence_tables_enforce_tenant_rls():
    if not APP_DATABASE_URL:
        pytest.skip("APP_DATABASE_URL restricted role is required for RLS verification")

    tenant_id, user_id, project_id = uuid4(), uuid4(), uuid4()
    review_id, finding_id, evidence_id = uuid4(), uuid4(), uuid4()
    owner_factory = build_session_factory(OWNER_DATABASE_URL or DATABASE_URL)
    app_factory = build_session_factory(APP_DATABASE_URL or DATABASE_URL)
    try:
        with owner_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            session.add(Tenant(id=tenant_id, name="Review RLS tenant", status="active"))
            session.add(User(id=user_id, login=f"review-rls-{user_id}@test.local", status="active"))
            session.flush()
            session.add(Membership(
                id=uuid4(), tenant_id=tenant_id, user_id=user_id,
                role="member", status="active",
            ))
            session.add(Project(
                id=project_id, tenant_id=tenant_id, name="RLS project",
                status="active", project_metadata={},
            ))
            session.flush()
            session.add(Review(
                id=review_id, tenant_id=tenant_id, project_id=project_id,
                title="RLS review", scope="project", status="draft",
                created_by=user_id, review_metadata={},
            ))
            session.flush()
            session.add(Finding(
                id=finding_id, tenant_id=tenant_id, project_id=project_id,
                review_id=review_id, classification="evidence_gap", severity="minor",
                status="open", title="Missing source", description="Fixture finding",
                created_by=user_id,
            ))
            session.flush()
            session.add(Evidence(
                id=evidence_id, tenant_id=tenant_id, project_id=project_id,
                finding_id=finding_id, evidence_type="note", relation="context",
                locator={}, excerpt="Fixture note", created_by=user_id,
            ))

        with app_factory() as session, session.begin():
            for table in ("reviews", "findings", "evidence"):
                assert session.execute(text("SELECT count(*) FROM " + table)).scalar_one() == 0
            set_tenant_context(session, uuid4())
            for table in ("reviews", "findings", "evidence"):
                assert session.execute(text("SELECT count(*) FROM " + table)).scalar_one() == 0
            set_tenant_context(session, tenant_id)
            assert session.execute(text("SELECT count(*) FROM reviews")).scalar_one() == 1
            assert session.execute(text("SELECT count(*) FROM findings")).scalar_one() == 1
            assert session.execute(text("SELECT count(*) FROM evidence")).scalar_one() == 1
    finally:
        owner_factory.kw["bind"].dispose()
        app_factory.kw["bind"].dispose()



def test_identity_context_discovers_only_own_tenants_without_active_tenant(connection):
    user_id, other_user_id = uuid4(), uuid4()
    tenant_a, tenant_b = uuid4(), uuid4()

    with connection.begin():
        connection.execute(
            text("INSERT INTO users (id, login, status) VALUES (:id, :login, 'active'), (:other, :other_login, 'active')"),
            {
                "id": user_id, "login": f"identity-{user_id}@test.local",
                "other": other_user_id, "other_login": f"identity-{other_user_id}@test.local",
            },
        )

    with connection.begin():
        _tenant(connection, tenant_a)
        connection.execute(
            text("""INSERT INTO memberships (id, tenant_id, user_id, role, status)
                    VALUES (:id, :tenant, :user, 'member', 'active')"""),
            {"id": uuid4(), "tenant": tenant_a, "user": user_id},
        )

    with connection.begin():
        _tenant(connection, tenant_b)
        connection.execute(
            text("""INSERT INTO memberships (id, tenant_id, user_id, role, status)
                    VALUES (:id, :tenant, :user, 'tenant_admin', 'active'),
                           (:other_id, :tenant, :other_user, 'member', 'active')"""),
            {
                "id": uuid4(), "tenant": tenant_b, "user": user_id,
                "other_id": uuid4(), "other_user": other_user_id,
            },
        )

    with connection.begin():
        # No app.tenant_id is set: identity context grants only self-membership
        # discovery and the corresponding tenant names.
        connection.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )
        memberships = connection.execute(
            text("SELECT tenant_id FROM memberships ORDER BY tenant_id")
        ).scalars().all()
        visible_tenants = connection.execute(
            text("SELECT id FROM tenants ORDER BY id")
        ).scalars().all()
        assert set(memberships) == {tenant_a, tenant_b}
        assert set(visible_tenants) == {tenant_a, tenant_b}

        # Identity context alone must not grant writes to tenant-owned rows.
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("""INSERT INTO memberships (id, tenant_id, user_id, role, status)
                            VALUES (:id, :tenant, :user, 'member', 'active')"""),
                    {"id": uuid4(), "tenant": tenant_a, "user": user_id},
                )



def test_system_admin_grants_gate_global_tenant_and_audit_reads(connection):
    if not APP_DATABASE_URL:
        pytest.skip("APP_DATABASE_URL restricted role is required for system-admin RLS verification")

    admin_id, ordinary_id = uuid4(), uuid4()
    tenant_a, tenant_b = uuid4(), uuid4()
    owner_factory = build_session_factory(OWNER_DATABASE_URL or DATABASE_URL)
    app_factory = build_session_factory(APP_DATABASE_URL)
    event_id = uuid4()
    try:
        with owner_factory() as session, session.begin():
            session.add_all([
                User(id=admin_id, login=f"system-admin-{admin_id}@test.local", status="active"),
                User(id=ordinary_id, login=f"ordinary-{ordinary_id}@test.local", status="active"),
                Tenant(id=tenant_a, name="Admin-visible A", status="active"),
                Tenant(id=tenant_b, name="Admin-visible B", status="active"),
            ])
            session.flush()
            session.add_all([
                SystemAdminGrant(
                    id=uuid4(), user_id=admin_id, permission="system.audit.read",
                    status="active", reason="integration test",
                ),
                SystemAdminGrant(
                    id=uuid4(), user_id=admin_id, permission="system.tenants.read",
                    status="active", reason="integration test",
                ),
            ])

        with app_factory() as session, session.begin():
            set_user_context(session, admin_id)
            permissions = set(session.scalars(
                select(SystemAdminGrant.permission)
            ).all())
            assert permissions == {"system.audit.read", "system.tenants.read"}

            visible_tenants = set(session.scalars(select(Tenant.id)).all())
            assert {tenant_a, tenant_b} <= visible_tenants

            session.add(SystemAuditEvent(
                id=event_id,
                actor_user_id=admin_id,
                action="system.test",
                target_type="tenant",
                target_id=tenant_a,
                tenant_id=tenant_a,
                outcome="success",
                details={"test": True},
            ))
            session.flush()
            assert session.scalar(
                select(SystemAuditEvent.id).where(SystemAuditEvent.id == event_id)
            ) == event_id

            update_result = session.execute(
                text("UPDATE system_audit_events SET action = 'tampered' WHERE id = :id"),
                {"id": event_id},
            )
            delete_result = session.execute(
                text("DELETE FROM system_audit_events WHERE id = :id"),
                {"id": event_id},
            )
            assert update_result.rowcount == 0
            assert delete_result.rowcount == 0

        with app_factory() as session, session.begin():
            set_user_context(session, ordinary_id)
            assert session.scalars(select(SystemAdminGrant.id)).all() == []
            assert session.scalars(select(SystemAuditEvent.id)).all() == []
            assert session.scalars(select(Tenant.id)).all() == []
    finally:
        owner_factory.kw["bind"].dispose()
        app_factory.kw["bind"].dispose()
