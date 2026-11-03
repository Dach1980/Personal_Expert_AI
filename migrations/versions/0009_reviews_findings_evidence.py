"""Add structured Review, Finding and Evidence domain entities.

Revision ID: 0009_reviews_findings_evidence
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_reviews_findings_evidence"
down_revision = "0008_external_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("scope", sa.String(length=40), server_default="project", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="draft", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','in_progress','completed','approved','rejected','cancelled')",
            name="ck_reviews_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"],
            name="fk_reviews_project_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.project_id", "document_versions.id"],
            name="fk_reviews_document_version_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"], ["memberships.tenant_id", "memberships.user_id"],
            name="fk_reviews_creator_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assigned_to"], ["memberships.tenant_id", "memberships.user_id"],
            name="fk_reviews_assignee_membership",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.UniqueConstraint("tenant_id", "project_id", "id", name="uq_reviews_parent"),
    )
    op.create_index(
        "ix_reviews_project_status_created", "reviews",
        ["tenant_id", "project_id", "status", "created_at"],
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("normative_reference", sa.String(length=500), nullable=True),
        sa.Column("requirement_reference", sa.String(length=500), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "classification IN ('violation','evidence_gap','inconsistency','observation')",
            name="ck_findings_classification",
        ),
        sa.CheckConstraint("severity IN ('info','minor','major','critical')", name="ck_findings_severity"),
        sa.CheckConstraint(
            "status IN ('open','accepted','rejected','resolved','waived')",
            name="ck_findings_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "review_id"],
            ["reviews.tenant_id", "reviews.project_id", "reviews.id"],
            name="fk_findings_review_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"], ["memberships.tenant_id", "memberships.user_id"],
            name="fk_findings_creator_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resolved_by"], ["memberships.tenant_id", "memberships.user_id"],
            name="fk_findings_resolver_membership",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_findings"),
        sa.UniqueConstraint("tenant_id", "project_id", "id", name="uq_findings_parent"),
    )
    op.create_index("ix_findings_review_status", "findings", ["tenant_id", "review_id", "status"])
    op.create_index("ix_findings_project_severity", "findings", ["tenant_id", "project_id", "severity"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=30), nullable=False),
        sa.Column("relation", sa.String(length=20), server_default="supports", nullable=False),
        sa.Column("source_fragment_id", sa.Uuid(), nullable=True),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("reference_label", sa.String(length=500), nullable=True),
        sa.Column("reference_uri", sa.String(length=2000), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN ('source_fragment','note','external_reference')",
            name="ck_evidence_type",
        ),
        sa.CheckConstraint("relation IN ('supports','contradicts','context')", name="ck_evidence_relation"),
        sa.CheckConstraint(
            "(evidence_type = 'source_fragment' AND source_fragment_id IS NOT NULL) OR "
            "(evidence_type <> 'source_fragment' AND source_fragment_id IS NULL)",
            name="ck_evidence_source_fragment_required",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"]),
        sa.ForeignKeyConstraint(["source_fragment_id"], ["source_fragments.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "finding_id"],
            ["findings.tenant_id", "findings.project_id", "findings.id"],
            name="fk_evidence_finding_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_fragment_id"],
            ["source_fragments.tenant_id", "source_fragments.project_id", "source_fragments.id"],
            name="fk_evidence_source_fragment_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"], ["memberships.tenant_id", "memberships.user_id"],
            name="fk_evidence_creator_membership",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
    )
    op.create_index("ix_evidence_finding_created", "evidence", ["tenant_id", "finding_id", "created_at"])
    op.create_index("ix_evidence_source_fragment", "evidence", ["source_fragment_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_source_fragment", table_name="evidence")
    op.drop_index("ix_evidence_finding_created", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_findings_project_severity", table_name="findings")
    op.drop_index("ix_findings_review_status", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_reviews_project_status_created", table_name="reviews")
    op.drop_table("reviews")
