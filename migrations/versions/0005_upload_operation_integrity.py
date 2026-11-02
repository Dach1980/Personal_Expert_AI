"""Constrain upload operation metadata and state transitions.

Revision ID: 0005_upload_operation_integrity
"""
from alembic import op

revision = "0005_upload_operation_integrity"
down_revision = "0004_upload_operations"
branch_labels = None
depends_on = None


CONSTRAINTS = [
    (
        "ck_upload_operations_idempotency_key",
        "length(idempotency_key) BETWEEN 8 AND 128 AND idempotency_key !~ '[^A-Za-z0-9._:-]' ",
    ),
    ("ck_upload_operations_filename", "length(trim(original_filename)) > 0"),
    ("ck_upload_operations_quarantine_key", "length(trim(quarantine_key)) > 0"),
    ("ck_upload_operations_storage_key", "length(trim(storage_key)) > 0"),
    (
        "ck_upload_operations_checksum",
        "checksum_sha256 IS NULL OR (length(checksum_sha256) = 64 AND "
        "translate(checksum_sha256, '0123456789abcdef', '') = '')",
    ),
    (
        "ck_upload_operations_media_type",
        "media_type IS NULL OR length(trim(media_type)) > 0",
    ),
    (
        "ck_upload_operations_validated_metadata",
        "status NOT IN ('quarantined','publishing','completed') OR "
        "(media_type IS NOT NULL AND size_bytes IS NOT NULL AND checksum_sha256 IS NOT NULL)",
    ),
    (
        "ck_upload_operations_completed_version",
        "status <> 'completed' OR document_version_id IS NOT NULL",
    ),
]


def upgrade() -> None:
    for name, expression in CONSTRAINTS:
        op.create_check_constraint(name, "upload_operations", expression)


def downgrade() -> None:
    for name, _ in reversed(CONSTRAINTS):
        op.drop_constraint(name, "upload_operations", type_="check")
