from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.storage.models  # noqa: F401
from app.storage.models import Base


def test_initial_domain_tables_are_registered() -> None:
    expected = {
        "tenants", "users", "memberships", "workspaces", "projects",
        "project_memberships", "documents", "document_versions",
        "processing_runs", "processing_artifacts", "source_fragments",
        "knowledge_items", "knowledge_assertions", "conversations",
        "messages", "memory_entries", "audit_events",
    }
    assert expected == set(Base.metadata.tables)


def test_document_versions_have_immutable_storage_identity() -> None:
    table = Base.metadata.tables["document_versions"]
    assert {"checksum_sha256", "storage_key", "document_id", "project_id"} <= set(table.columns.keys())
    assert any(
        isinstance(item, UniqueConstraint) and "storage_key" in [c.name for c in item.columns]
        for item in table.constraints
    )


def test_document_current_version_is_scoped_to_its_document() -> None:
    table = Base.metadata.tables["documents"]
    assert any(
        isinstance(item, ForeignKeyConstraint)
        and item.name == "fk_documents_current_version_parent"
        and [column.name for column in item.columns]
        == ["tenant_id", "project_id", "id", "current_version_id"]
        for item in table.constraints
    )


def test_project_membership_is_tenant_scoped() -> None:
    table = Base.metadata.tables["project_memberships"]
    names = {item.name for item in table.constraints if isinstance(item, ForeignKeyConstraint)}
    assert "fk_project_memberships_project_tenant" in names
    assert "fk_project_memberships_tenant_member" in names


def test_assertions_constrain_confidence() -> None:
    table = Base.metadata.tables["knowledge_assertions"]
    assert any(
        isinstance(item, CheckConstraint) and "confidence" in str(item.sqltext)
        for item in table.constraints
    )
