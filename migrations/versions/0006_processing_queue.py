"""Add durable processing queue, idempotency and worker leases.

Revision ID: 0006_processing_queue
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_processing_queue"
down_revision = "0005_upload_operation_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_runs", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("processing_runs", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("processing_runs", sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False))
    op.add_column("processing_runs", sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("processing_runs", sa.Column("lease_owner", sa.String(128), nullable=True))
    op.add_column("processing_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("processing_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(
        "uq_processing_runs_idempotency", "processing_runs",
        ["tenant_id", "project_id", "idempotency_key"],
    )
    op.create_index(
        "ix_processing_runs_queue", "processing_runs",
        ["tenant_id", "status", "available_at", "created_at"],
    )
    op.create_check_constraint(
        "ck_processing_runs_attempts", "processing_runs",
        "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20",
    )
    op.create_check_constraint(
        "ck_processing_runs_running_lease", "processing_runs",
        "status <> 'running' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_processing_runs_nonrunning_without_lease", "processing_runs",
        "status = 'running' OR (lease_owner IS NULL AND lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_processing_runs_idempotency_key", "processing_runs",
        "idempotency_key IS NULL OR (length(idempotency_key) BETWEEN 8 AND 128 "
        "AND idempotency_key !~ '[^A-Za-z0-9._:-]')",
    )


def downgrade() -> None:
    for name in (
        "ck_processing_runs_idempotency_key",
        "ck_processing_runs_nonrunning_without_lease",
        "ck_processing_runs_running_lease",
        "ck_processing_runs_attempts",
    ):
        op.drop_constraint(name, "processing_runs", type_="check")
    op.drop_index("ix_processing_runs_queue", table_name="processing_runs")
    op.drop_constraint("uq_processing_runs_idempotency", "processing_runs", type_="unique")
    for column in (
        "heartbeat_at", "lease_expires_at", "lease_owner", "available_at",
        "max_attempts", "attempt_count", "idempotency_key",
    ):
        op.drop_column("processing_runs", column)
