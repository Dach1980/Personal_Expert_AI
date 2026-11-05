from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.storage.models  # noqa: F401
from app.storage.models import Base


def test_initial_domain_tables_are_registered() -> None:
    expected = {
        "tenants", "users", "memberships", "workspaces", "projects",
        "project_memberships", "documents", "document_versions",
        "processing_runs", "processing_artifacts", "source_fragments",
        "knowledge_items", "knowledge_assertions", "conversations",
        "messages", "memory_entries", "audit_events", "upload_operations", "external_identities", "reviews", "findings", "evidence",
        "chat_conversations", "chat_messages", "system_admin_grants", "system_audit_events", "bionic_project_bindings", "delegation_grants",
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



def test_document_version_metadata_has_integrity_constraints() -> None:
    table = Base.metadata.tables["document_versions"]
    checks = {
        item.name: str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_document_versions_size_positive" in checks
    assert "ck_document_versions_checksum_sha256" in checks
    assert "ck_document_versions_filename_nonempty" in checks
    assert "ck_document_versions_media_type_nonempty" in checks
    assert "ck_document_versions_storage_key_nonempty" in checks



def test_upload_operations_constrain_idempotency_and_state_metadata() -> None:
    table = Base.metadata.tables["upload_operations"]
    checks = {
        item.name: str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_upload_operations_idempotency_key" in checks
    assert "ck_upload_operations_checksum" in checks
    assert "ck_upload_operations_validated_metadata" in checks
    assert "ck_upload_operations_completed_version" in checks



def test_review_finding_evidence_are_tenant_and_project_scoped() -> None:
    reviews = Base.metadata.tables["reviews"]
    findings = Base.metadata.tables["findings"]
    evidence = Base.metadata.tables["evidence"]

    review_fks = {item.name for item in reviews.constraints if isinstance(item, ForeignKeyConstraint)}
    finding_fks = {item.name for item in findings.constraints if isinstance(item, ForeignKeyConstraint)}
    evidence_fks = {item.name for item in evidence.constraints if isinstance(item, ForeignKeyConstraint)}

    assert "fk_reviews_project_tenant" in review_fks
    assert "fk_findings_review_parent" in finding_fks
    assert "fk_evidence_finding_parent" in evidence_fks
    assert "fk_evidence_source_fragment_parent" in evidence_fks


def test_finding_and_evidence_lifecycle_constraints_are_registered() -> None:
    findings = Base.metadata.tables["findings"]
    evidence = Base.metadata.tables["evidence"]
    finding_checks = {item.name for item in findings.constraints if isinstance(item, CheckConstraint)}
    evidence_checks = {item.name for item in evidence.constraints if isinstance(item, CheckConstraint)}

    assert {"ck_findings_classification", "ck_findings_severity", "ck_findings_status"} <= finding_checks
    assert {"ck_evidence_type", "ck_evidence_relation", "ck_evidence_source_fragment_required"} <= evidence_checks



def test_chat_conversations_and_messages_are_tenant_project_scoped() -> None:
    conversations = Base.metadata.tables["chat_conversations"]
    messages = Base.metadata.tables["chat_messages"]
    conversation_fks = {
        item.name for item in conversations.constraints if isinstance(item, ForeignKeyConstraint)
    }
    message_fks = {
        item.name for item in messages.constraints if isinstance(item, ForeignKeyConstraint)
    }
    assert "fk_chat_conversations_project_tenant" in conversation_fks
    assert "fk_chat_conversations_creator_membership" in conversation_fks
    assert "fk_chat_messages_conversation_parent" in message_fks
    assert "fk_chat_messages_sender_membership" in message_fks



def test_system_admin_grants_are_separate_from_tenant_membership_roles() -> None:
    table = Base.metadata.tables["system_admin_grants"]
    checks = {item.name for item in table.constraints if isinstance(item, CheckConstraint)}
    uniques = {item.name for item in table.constraints if isinstance(item, UniqueConstraint)}
    assert "ck_system_admin_grants_permission" in checks
    assert "ck_system_admin_grants_status" in checks
    assert "uq_system_admin_grants_user_permission" in uniques
    assert "tenant_id" not in table.columns


def test_system_audit_events_are_global_and_have_append_only_contract() -> None:
    table = Base.metadata.tables["system_audit_events"]
    checks = {item.name for item in table.constraints if isinstance(item, CheckConstraint)}
    indexes = {item.name for item in table.indexes}
    fks = {item.name: item for item in table.constraints if isinstance(item, ForeignKeyConstraint)}
    assert "ck_system_audit_events_outcome" in checks
    assert {"ix_system_audit_events_created", "ix_system_audit_events_tenant_created",
            "ix_system_audit_events_target"} <= indexes
    assert "fk_system_audit_events_actor" in fks
    assert "fk_system_audit_events_tenant" in fks
    assert table.columns["tenant_id"].nullable is True
    assert table.columns["actor_user_id"].nullable is False
    assert fks["fk_system_audit_events_actor"].ondelete == "RESTRICT"
    assert fks["fk_system_audit_events_tenant"].ondelete == "SET NULL"
