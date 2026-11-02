"""Add durable upload operations with tenant/project isolation.

Revision ID: 0004_upload_operations
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_upload_operations"
down_revision = "0003_document_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(150)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("checksum_sha256", sa.String(64)),
        sa.Column("quarantine_key", sa.String(500), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_upload_operations_idempotency"),
        sa.CheckConstraint(
            "status IN ('receiving','quarantined','publishing','completed','failed')",
            name="ck_upload_operations_status",
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes > 0", name="ck_upload_operations_size"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_upload_operations_tenant"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="upload_operations_document_id_fkey"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="upload_operations_created_by_fkey"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_id"],
            ["documents.tenant_id", "documents.project_id", "documents.id"],
            name="fk_upload_operations_document_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_upload_operations_creator_tenant_member",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.project_id", "document_versions.id"],
            name="fk_upload_operations_version_parent",
        ),
    )
    op.create_index("ix_upload_operations_status_created", "upload_operations", ["status", "created_at"])
    op.execute("""
        CREATE POLICY tenant_isolation ON upload_operations
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("ALTER TABLE upload_operations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE upload_operations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON upload_operations")
    op.execute("ALTER TABLE upload_operations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE upload_operations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_upload_operations_status_created", table_name="upload_operations")
    op.drop_table("upload_operations")
