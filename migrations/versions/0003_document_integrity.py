"""Protect immutable document-version source identity.

Revision ID: 0003_document_integrity
"""
from alembic import op

revision = "0003_document_integrity"
down_revision = "0002_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document_versions
        ADD CONSTRAINT ck_document_versions_size_positive CHECK (size_bytes > 0)
    """)
    op.execute("""
        ALTER TABLE document_versions
        ADD CONSTRAINT ck_document_versions_checksum_sha256
        CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
    """)
    op.execute("""
        ALTER TABLE document_versions
        ADD CONSTRAINT ck_document_versions_filename_nonempty
        CHECK (length(trim(original_filename)) > 0)
    """)
    op.execute("""
        ALTER TABLE document_versions
        ADD CONSTRAINT ck_document_versions_media_type_nonempty
        CHECK (length(trim(media_type)) > 0)
    """)
    op.execute("""
        ALTER TABLE document_versions
        ADD CONSTRAINT ck_document_versions_storage_key_nonempty
        CHECK (length(trim(storage_key)) > 0)
    """)
    op.execute("""
        CREATE FUNCTION prevent_document_version_source_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.document_id, NEW.original_filename,
                NEW.media_type, NEW.size_bytes, NEW.checksum_sha256, NEW.storage_key,
                NEW.uploaded_by, NEW.uploaded_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.document_id, OLD.original_filename,
                OLD.media_type, OLD.size_bytes, OLD.checksum_sha256, OLD.storage_key,
                OLD.uploaded_by, OLD.uploaded_at
            ) THEN
                RAISE EXCEPTION 'document version source identity is immutable'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'tr_document_versions_source_immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_document_versions_source_immutable
        BEFORE UPDATE ON document_versions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_document_version_source_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_document_versions_source_immutable ON document_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_document_version_source_mutation()")
    for constraint in (
        "ck_document_versions_storage_key_nonempty",
        "ck_document_versions_media_type_nonempty",
        "ck_document_versions_filename_nonempty",
        "ck_document_versions_checksum_sha256",
        "ck_document_versions_size_positive",
    ):
        op.execute(f"ALTER TABLE document_versions DROP CONSTRAINT IF EXISTS {constraint}")
