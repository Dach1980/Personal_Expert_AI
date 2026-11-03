"""Add explicit external OIDC identity mappings.

Revision ID: 0008_external_identities
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_external_identities"
down_revision = "0007_fragment_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_external_identities_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_external_identities_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_external_identities"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identities_issuer_subject"),
    )
    op.create_index(
        "ix_external_identities_user_status",
        "external_identities",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_identities_user_status", table_name="external_identities")
    op.drop_table("external_identities")
