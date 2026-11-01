from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint

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
    assert {"checksum_sha256", "storage_key", "document_id", "project_id"} <= set(table.columns)
    assert any(
        isinstance(item, UniqueConstraint) and "storage_key" in [c.name for c in item.columns]
        for item in table.constraints
    )


def test_document_current_version_references_a_version() -> None:
    table = Base.metadata.tables["documents"]
    column = table.columns["current_version_id"]
    assert any(
        isinstance(item, ForeignKey) and item.target_fullname == "document_versions.id"
        for item in column.foreign_keys
    )


def test_assertions_constrain_confidence() -> None:
    table = Base.metadata.tables["knowledge_assertions"]
    assert any(
        isinstance(item, CheckConstraint) and "confidence" in str(item.sqltext)
        for item in table.constraints
    )
