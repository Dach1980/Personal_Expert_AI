"""Add stable source-fragment keys for retry-safe extraction persistence.

Revision ID: 0007_fragment_idempotency
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_fragment_idempotency"
down_revision = "0006_processing_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_fragments", sa.Column("fragment_key", sa.String(64), nullable=True))
    op.execute("UPDATE source_fragments SET fragment_key = md5(id::text) WHERE fragment_key IS NULL")
    op.alter_column("source_fragments", "fragment_key", nullable=False)
    op.create_unique_constraint(
        "uq_source_fragments_run_key", "source_fragments",
        ["tenant_id", "project_id", "processing_run_id", "fragment_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_source_fragments_run_key", "source_fragments", type_="unique")
    op.drop_column("source_fragments", "fragment_key")
