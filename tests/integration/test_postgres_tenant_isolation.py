"""PostgreSQL integration tests. Run after `alembic upgrade head`."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

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
                         media_type, size_bytes, checksum_sha256, storage_key, status)
                        VALUES (:id, :tenant, :project, :document, 'a.pdf',
                                'application/pdf', 10, 'abc', :storage, 'uploaded')"""),
                    {
                        "id": uuid4(), "tenant": tenant_id, "project": project_b,
                        "document": document_a, "storage": f"test/{uuid4()}",
                    },
                )
