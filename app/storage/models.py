"""Initial SQLAlchemy domain models for Personal Expert AI."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric,
    String, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Base for persistent domain entities."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("login", name="uq_users_login"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        CheckConstraint("role IN ('owner','tenant_admin','member')", name="ck_memberships_role"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_workspaces_tenant_id"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_tenant_status", "tenant_id", "status"),
        Index("ix_projects_tenant_code", "tenant_id", "code"),
        UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "workspace_id"], ["workspaces.tenant_id", "workspaces.id"], name="fk_projects_workspace_tenant"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("workspaces.id"))
    code: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    project_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)


class ProjectMembership(Base, TimestampMixin):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
        CheckConstraint("role IN ('project_manager','engineer','reviewer','viewer')", name="ck_project_memberships_role"),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_project_memberships_project_tenant"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_project_memberships_tenant_member"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="viewer")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_project_status", "project_id", "status"), UniqueConstraint("tenant_id", "project_id", "id", name="uq_documents_tenant_project_id"), ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_documents_project_tenant"), ForeignKeyConstraint(["tenant_id", "project_id", "id", "current_version_id"], ["document_versions.tenant_id", "document_versions.project_id", "document_versions.document_id", "document_versions.id"], name="fk_documents_current_version_parent", use_alter=True))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_document_versions_storage_key"),
        CheckConstraint("size_bytes > 0", name="ck_document_versions_size_positive"),
        CheckConstraint("length(checksum_sha256) = 64 AND translate(checksum_sha256, '0123456789abcdef', '') = ''", name="ck_document_versions_checksum_sha256"),
        CheckConstraint("length(trim(original_filename)) > 0", name="ck_document_versions_filename_nonempty"),
        CheckConstraint("length(trim(media_type)) > 0", name="ck_document_versions_media_type_nonempty"),
        CheckConstraint("length(trim(storage_key)) > 0", name="ck_document_versions_storage_key_nonempty"),
        Index("ix_document_versions_project_checksum", "project_id", "checksum_sha256"),
        Index("ix_document_versions_document_uploaded", "document_id", "uploaded_at"),
        UniqueConstraint("tenant_id", "project_id", "id", name="uq_document_versions_tenant_project_id"),
        UniqueConstraint("tenant_id", "project_id", "document_id", "id", name="uq_document_versions_parent"),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_document_versions_project_tenant"),
        ForeignKeyConstraint(["tenant_id", "project_id", "document_id"], ["documents.tenant_id", "documents.project_id", "documents.id"], name="fk_document_versions_document_parent"),
        ForeignKeyConstraint(["tenant_id", "uploaded_by"], ["memberships.tenant_id", "memberships.user_id"], name="fk_document_versions_uploader_tenant"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("documents.id"), nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(100))
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")
    uploaded_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)


class ProcessingRun(Base, TimestampMixin):
    __tablename__ = "processing_runs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','succeeded','partially_succeeded','failed','cancelled')", name="ck_processing_runs_status"),
        CheckConstraint("attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20", name="ck_processing_runs_attempts"),
        CheckConstraint("status <> 'running' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)", name="ck_processing_runs_running_lease"),
        CheckConstraint("status = 'running' OR (lease_owner IS NULL AND lease_expires_at IS NULL)", name="ck_processing_runs_nonrunning_without_lease"),
        CheckConstraint("idempotency_key IS NULL OR (length(idempotency_key) BETWEEN 8 AND 128 AND idempotency_key !~ '[^A-Za-z0-9._:-]')", name="ck_processing_runs_idempotency_key"),
        UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_processing_runs_idempotency"),
        Index("ix_processing_runs_queue", "tenant_id", "status", "available_at", "created_at"),
        Index("ix_processing_runs_version_created", "document_version_id", "created_at"),
        Index("ix_processing_runs_project_status", "project_id", "status"),
        UniqueConstraint("tenant_id", "project_id", "id", name="uq_processing_runs_parent"),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_processing_runs_project_tenant"),
        ForeignKeyConstraint(["tenant_id", "project_id", "document_version_id"], ["document_versions.tenant_id", "document_versions.project_id", "document_versions.id"], name="fk_processing_runs_version_parent"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("document_versions.id"), nullable=False)
    pipeline_name: Mapped[str] = mapped_column(String(150), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class ProcessingArtifact(Base):
    __tablename__ = "processing_artifacts"
    __table_args__ = (UniqueConstraint("storage_key", name="uq_processing_artifacts_storage_key"), ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_processing_artifacts_project_tenant"), ForeignKeyConstraint(["tenant_id", "project_id", "processing_run_id"], ["processing_runs.tenant_id", "processing_runs.project_id", "processing_runs.id"], name="fk_processing_artifacts_run_parent"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    processing_run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("processing_runs.id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceFragment(Base):
    __tablename__ = "source_fragments"
    __table_args__ = (
        Index("ix_source_fragments_version_run", "document_version_id", "processing_run_id"),
        Index("ix_source_fragments_project_type", "project_id", "fragment_type"),
        UniqueConstraint("tenant_id", "project_id", "id", name="uq_source_fragments_parent"),
        UniqueConstraint(
            "tenant_id", "project_id", "processing_run_id", "fragment_key",
            name="uq_source_fragments_run_key",
        ),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_source_fragments_project_tenant"),
        ForeignKeyConstraint(["tenant_id", "project_id", "document_version_id"], ["document_versions.tenant_id", "document_versions.project_id", "document_versions.id"], name="fk_source_fragments_version_parent"),
        ForeignKeyConstraint(["tenant_id", "project_id", "processing_run_id"], ["processing_runs.tenant_id", "processing_runs.project_id", "processing_runs.id"], name="fk_source_fragments_run_parent"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("document_versions.id"), nullable=False)
    processing_run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("processing_runs.id"), nullable=False)
    fragment_type: Mapped[str] = mapped_column(String(80), nullable=False, default="text")
    locator: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    content: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fragment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_method: Mapped[str | None] = mapped_column(String(100))
    extractor_version: Mapped[str | None] = mapped_column(String(100))
    quality: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeItem(Base, TimestampMixin):
    __tablename__ = "knowledge_items"
    __table_args__ = (Index("ix_knowledge_items_project_kind_status", "project_id", "kind", "status"), UniqueConstraint("tenant_id", "project_id", "id", name="uq_knowledge_items_parent"), ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_knowledge_items_project_tenant"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_key: Mapped[str | None] = mapped_column(String(300))
    canonical_value: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    item_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)


class KnowledgeAssertion(Base, TimestampMixin):
    __tablename__ = "knowledge_assertions"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_assertions_confidence"),
        Index("ix_assertions_item", "knowledge_item_id"),
        Index("ix_assertions_fragment", "source_fragment_id"),
        ForeignKeyConstraint(["tenant_id", "project_id", "knowledge_item_id"], ["knowledge_items.tenant_id", "knowledge_items.project_id", "knowledge_items.id"], name="fk_assertions_item_parent"),
        ForeignKeyConstraint(["tenant_id", "project_id", "source_fragment_id"], ["source_fragments.tenant_id", "source_fragments.project_id", "source_fragments.id"], name="fk_assertions_fragment_parent"),
        ForeignKeyConstraint(["tenant_id", "reviewed_by"], ["memberships.tenant_id", "memberships.user_id"], name="fk_assertions_reviewer_tenant"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    knowledge_item_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("knowledge_items.id"), nullable=False)
    source_fragment_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("source_fragments.id"), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80))
    extractor: Mapped[str | None] = mapped_column(String(100))
    extractor_version: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_project_owner_updated", "project_id", "owner_user_id", "updated_at"), UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id"), ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_conversations_project_tenant"), ForeignKeyConstraint(["tenant_id", "owner_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_conversations_owner_tenant"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('system','user','assistant','tool')", name="ck_messages_role"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], name="fk_messages_conversation_tenant"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"
    __table_args__ = (
        CheckConstraint("scope_type IN ('user','tenant','project','conversation')", name="ck_memory_scope"),
        CheckConstraint("status IN ('proposed','confirmed','rejected','expired','deleted')", name="ck_memory_status"),
        Index("ix_memory_scope_lookup", "tenant_id", "scope_type", "scope_id", "status"),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], name="fk_memory_entries_project_tenant"),
        ForeignKeyConstraint(["tenant_id", "owner_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_memory_entries_owner_tenant"),
        ForeignKeyConstraint(["tenant_id", "confirmed_by"], ["memberships.tenant_id", "memberships.user_id"], name="fk_memory_entries_confirmer_tenant"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    project_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"))
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_audit_events_actor_tenant"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, default="success")
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class UploadOperation(Base, TimestampMixin):
    """Durable state for an idempotent, recoverable multipart upload."""

    __tablename__ = "upload_operations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_upload_operations_idempotency"),
        CheckConstraint(
            "status IN ('receiving','quarantined','publishing','completed','failed')",
            name="ck_upload_operations_status",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes > 0", name="ck_upload_operations_size"),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128 AND "
            "idempotency_key !~ '[^A-Za-z0-9._:-]'",
            name="ck_upload_operations_idempotency_key",
        ),
        CheckConstraint("length(trim(original_filename)) > 0", name="ck_upload_operations_filename"),
        CheckConstraint("length(trim(quarantine_key)) > 0", name="ck_upload_operations_quarantine_key"),
        CheckConstraint("length(trim(storage_key)) > 0", name="ck_upload_operations_storage_key"),
        CheckConstraint(
            "checksum_sha256 IS NULL OR (length(checksum_sha256) = 64 AND "
            "translate(checksum_sha256, '0123456789abcdef', '') = '')",
            name="ck_upload_operations_checksum",
        ),
        CheckConstraint(
            "media_type IS NULL OR length(trim(media_type)) > 0",
            name="ck_upload_operations_media_type",
        ),
        CheckConstraint(
            "status NOT IN ('quarantined','publishing','completed') OR "
            "(media_type IS NOT NULL AND size_bytes IS NOT NULL AND checksum_sha256 IS NOT NULL)",
            name="ck_upload_operations_validated_metadata",
        ),
        CheckConstraint(
            "status <> 'completed' OR document_version_id IS NOT NULL",
            name="ck_upload_operations_completed_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_id"],
            ["documents.tenant_id", "documents.project_id", "documents.id"],
            name="fk_upload_operations_document_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_upload_operations_creator_tenant_member",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.project_id", "document_versions.id"],
            name="fk_upload_operations_version_parent",
        ),
        Index("ix_upload_operations_status_created", "status", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("documents.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="receiving")
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    quarantine_key: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    document_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
