"""Initial relational schema.

Revision ID: 0001_initial_domain
This migration is a frozen DDL snapshot. Do not import live ORM metadata here.
"""

from alembic import op

revision = "0001_initial_domain"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    ddl = """
        CREATE TABLE tenants (
            id UUID PRIMARY KEY, name VARCHAR(200) NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE users (
            id UUID PRIMARY KEY, login VARCHAR(255) NOT NULL UNIQUE,
            display_name VARCHAR(200), status VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE memberships (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID NOT NULL REFERENCES users(id), role VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_memberships_tenant_user UNIQUE (tenant_id, user_id),
            CONSTRAINT ck_memberships_role CHECK (role IN ('owner','tenant_admin','member'))
        );
        CREATE TABLE workspaces (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            name VARCHAR(200) NOT NULL, description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE projects (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            workspace_id UUID REFERENCES workspaces(id), code VARCHAR(100),
            name VARCHAR(300) NOT NULL, description TEXT, status VARCHAR(30) NOT NULL,
            metadata JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_projects_tenant_status ON projects(tenant_id, status);
        CREATE INDEX ix_projects_tenant_code ON projects(tenant_id, code);
        CREATE TABLE project_memberships (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            user_id UUID NOT NULL REFERENCES users(id), role VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_memberships_project_user UNIQUE (project_id, user_id),
            CONSTRAINT ck_project_memberships_role
                CHECK (role IN ('project_manager','engineer','reviewer','viewer'))
        );
        CREATE TABLE documents (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            document_type VARCHAR(80), title VARCHAR(500) NOT NULL,
            current_version_id UUID, status VARCHAR(30) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_documents_project_status ON documents(project_id, status);
        CREATE TABLE document_versions (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            document_id UUID NOT NULL REFERENCES documents(id),
            version_label VARCHAR(100), original_filename VARCHAR(500) NOT NULL,
            media_type VARCHAR(150) NOT NULL, size_bytes BIGINT NOT NULL,
            checksum_sha256 VARCHAR(64) NOT NULL, storage_key VARCHAR(500) NOT NULL,
            status VARCHAR(30) NOT NULL, uploaded_by UUID REFERENCES users(id),
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(), metadata JSONB NOT NULL,
            CONSTRAINT uq_document_versions_storage_key UNIQUE (storage_key),
            CONSTRAINT ck_document_versions_size_nonnegative CHECK (size_bytes >= 0)
        );
        ALTER TABLE documents ADD CONSTRAINT fk_documents_current_version
            FOREIGN KEY (current_version_id) REFERENCES document_versions(id);
        CREATE INDEX ix_document_versions_project_checksum
            ON document_versions(project_id, checksum_sha256);
        CREATE INDEX ix_document_versions_document_uploaded
            ON document_versions(document_id, uploaded_at);
        CREATE TABLE processing_runs (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            document_version_id UUID NOT NULL REFERENCES document_versions(id),
            pipeline_name VARCHAR(150) NOT NULL, pipeline_version VARCHAR(100) NOT NULL,
            status VARCHAR(30) NOT NULL, manifest JSONB NOT NULL,
            started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
            error_code VARCHAR(100), error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_processing_runs_status CHECK
                (status IN ('queued','running','succeeded','partially_succeeded','failed','cancelled'))
        );
        CREATE INDEX ix_processing_runs_version_created
            ON processing_runs(document_version_id, created_at);
        CREATE INDEX ix_processing_runs_project_status ON processing_runs(project_id, status);
        CREATE TABLE processing_artifacts (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            processing_run_id UUID NOT NULL REFERENCES processing_runs(id),
            artifact_type VARCHAR(100) NOT NULL, storage_key VARCHAR(500) NOT NULL UNIQUE,
            checksum_sha256 VARCHAR(64), media_type VARCHAR(150), size_bytes BIGINT,
            metadata JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE source_fragments (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            document_version_id UUID NOT NULL REFERENCES document_versions(id),
            processing_run_id UUID NOT NULL REFERENCES processing_runs(id),
            fragment_type VARCHAR(80) NOT NULL, locator JSONB NOT NULL,
            content TEXT, content_hash VARCHAR(64) NOT NULL,
            extraction_method VARCHAR(100), extractor_version VARCHAR(100),
            quality JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_source_fragments_version_run
            ON source_fragments(document_version_id, processing_run_id);
        CREATE INDEX ix_source_fragments_project_type
            ON source_fragments(project_id, fragment_type);
        CREATE TABLE knowledge_items (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id), kind VARCHAR(100) NOT NULL,
            canonical_key VARCHAR(300), canonical_value JSONB NOT NULL,
            status VARCHAR(30) NOT NULL, metadata JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_knowledge_items_project_kind_status
            ON knowledge_items(project_id, kind, status);
        CREATE TABLE knowledge_assertions (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            knowledge_item_id UUID NOT NULL REFERENCES knowledge_items(id),
            source_fragment_id UUID NOT NULL REFERENCES source_fragments(id),
            subject VARCHAR(500), predicate VARCHAR(200) NOT NULL, value JSONB NOT NULL,
            unit VARCHAR(80), extractor VARCHAR(100), extractor_version VARCHAR(100),
            confidence NUMERIC(5,4), review_status VARCHAR(30) NOT NULL,
            valid_from DATE, valid_to DATE, reviewed_by UUID REFERENCES users(id),
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_assertions_confidence CHECK
                (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        );
        CREATE INDEX ix_assertions_item ON knowledge_assertions(knowledge_item_id);
        CREATE INDEX ix_assertions_fragment ON knowledge_assertions(source_fragment_id);
        CREATE TABLE conversations (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            project_id UUID NOT NULL REFERENCES projects(id),
            owner_user_id UUID NOT NULL REFERENCES users(id), title VARCHAR(300),
            status VARCHAR(30) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_conversations_project_owner_updated
            ON conversations(project_id, owner_user_id, updated_at);
        CREATE TABLE messages (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            conversation_id UUID NOT NULL REFERENCES conversations(id),
            role VARCHAR(20) NOT NULL, content TEXT NOT NULL, metadata JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_messages_role CHECK (role IN ('system','user','assistant','tool'))
        );
        CREATE INDEX ix_messages_conversation_created ON messages(conversation_id, created_at);
        CREATE TABLE memory_entries (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            scope_type VARCHAR(30) NOT NULL, scope_id UUID NOT NULL,
            owner_user_id UUID REFERENCES users(id), project_id UUID REFERENCES projects(id),
            kind VARCHAR(80) NOT NULL, content TEXT NOT NULL, status VARCHAR(30) NOT NULL,
            provenance JSONB NOT NULL, valid_from TIMESTAMPTZ, valid_to TIMESTAMPTZ,
            confirmed_by UUID REFERENCES users(id), confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_memory_scope CHECK
                (scope_type IN ('user','tenant','project','conversation')),
            CONSTRAINT ck_memory_status CHECK
                (status IN ('proposed','confirmed','rejected','expired','deleted'))
        );
        CREATE INDEX ix_memory_scope_lookup
            ON memory_entries(tenant_id, scope_type, scope_id, status);
        CREATE TABLE audit_events (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
            actor_user_id UUID REFERENCES users(id), action VARCHAR(120) NOT NULL,
            target_type VARCHAR(100) NOT NULL, target_id UUID, request_id VARCHAR(100),
            outcome VARCHAR(30) NOT NULL, details JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_events_tenant_created ON audit_events(tenant_id, created_at);
        CREATE INDEX ix_audit_events_target ON audit_events(target_type, target_id);
    """
    for statement in ddl.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    ddl = """
        ALTER TABLE IF EXISTS documents DROP CONSTRAINT IF EXISTS fk_documents_current_version;
        DROP TABLE IF EXISTS audit_events, memory_entries, messages, conversations,
            knowledge_assertions, knowledge_items, source_fragments, processing_artifacts,
            processing_runs, document_versions, documents, project_memberships,
            projects, workspaces, memberships, users, tenants CASCADE;
    """
    for statement in ddl.split(";"):
        if statement.strip():
            op.execute(statement)
