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
