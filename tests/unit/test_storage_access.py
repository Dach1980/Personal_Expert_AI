from uuid import uuid4
from unittest.mock import Mock

import pytest

from app.storage.repositories import DocumentRepository, ProjectRepository, TenantRepository
from app.storage.services import (
    AccessDeniedError,
    DocumentService,
    ProjectService,
    ResourceNotFoundError,
)


def _where_sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_document_repository_scopes_by_tenant_project_and_document() -> None:
    session = Mock()
    tenant_id, project_id, document_id = uuid4(), uuid4(), uuid4()
    DocumentRepository(session).get(tenant_id, project_id, document_id)
    sql = _where_sql(session.scalar.call_args.args[0])
    assert f"documents.tenant_id = '{tenant_id}'" in sql
    assert f"documents.project_id = '{project_id}'" in sql
    assert f"documents.id = '{document_id}'" in sql


def test_project_repository_scopes_by_tenant_and_project() -> None:
    session = Mock()
    tenant_id, project_id = uuid4(), uuid4()
    ProjectRepository(session).get(tenant_id, project_id)
    sql = _where_sql(session.scalar.call_args.args[0])
    assert f"projects.tenant_id = '{tenant_id}'" in sql
    assert f"projects.id = '{project_id}'" in sql


def test_tenant_repository_membership_query_scopes_both_ids() -> None:
    session = Mock()
    tenant_id, user_id = uuid4(), uuid4()
    TenantRepository(session).active_membership(tenant_id, user_id)
    sql = _where_sql(session.scalar.call_args.args[0])
    assert f"memberships.tenant_id = '{tenant_id}'" in sql
    assert f"memberships.user_id = '{user_id}'" in sql
    assert "memberships.status = 'active'" in sql


def test_document_service_hides_project_without_membership() -> None:
    session = Mock()
    session.scalar.return_value = None
    service = DocumentService(session)
    with pytest.raises(ResourceNotFoundError, match="Project not found"):
        service.list(uuid4(), uuid4(), uuid4())


def test_project_service_rejects_non_admin_project_creation() -> None:
    session = Mock()
    membership = Mock(role="member")
    session.scalar.return_value = membership
    service = ProjectService(session)
    with pytest.raises(AccessDeniedError):
        service.create(uuid4(), uuid4(), name="Restricted project")
