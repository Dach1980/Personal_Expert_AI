"""Enforce tenant/project referential integrity and PostgreSQL row-level security.

Revision ID: 0002_tenant_isolation
"""
from alembic import op

revision = "0002_tenant_isolation"
down_revision = "0001_initial_domain"
branch_labels = None
depends_on = None

CONSTRAINTS = [
    "ALTER TABLE workspaces ADD CONSTRAINT uq_workspaces_tenant_id UNIQUE (tenant_id, id)",
    "ALTER TABLE projects ADD CONSTRAINT fk_projects_workspace_tenant FOREIGN KEY (tenant_id, workspace_id) REFERENCES workspaces (tenant_id, id)",
    "ALTER TABLE project_memberships ADD CONSTRAINT fk_project_memberships_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE project_memberships ADD CONSTRAINT fk_project_memberships_tenant_member FOREIGN KEY (tenant_id, user_id) REFERENCES memberships (tenant_id, user_id)",
    "ALTER TABLE documents ADD CONSTRAINT uq_documents_tenant_project_id UNIQUE (tenant_id, project_id, id)",
    "ALTER TABLE documents ADD CONSTRAINT fk_documents_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE document_versions ADD CONSTRAINT uq_document_versions_parent UNIQUE (tenant_id, project_id, document_id, id)",
    "ALTER TABLE document_versions ADD CONSTRAINT fk_document_versions_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE document_versions ADD CONSTRAINT fk_document_versions_document_parent FOREIGN KEY (tenant_id, project_id, document_id) REFERENCES documents (tenant_id, project_id, id)",
    "ALTER TABLE documents ADD CONSTRAINT fk_documents_current_version_parent FOREIGN KEY (tenant_id, project_id, id, current_version_id) REFERENCES document_versions (tenant_id, project_id, document_id, id)",
    "ALTER TABLE processing_runs ADD CONSTRAINT uq_processing_runs_parent UNIQUE (tenant_id, project_id, id)",
    "ALTER TABLE processing_runs ADD CONSTRAINT fk_processing_runs_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE processing_runs ADD CONSTRAINT fk_processing_runs_version_parent FOREIGN KEY (tenant_id, project_id, document_version_id) REFERENCES document_versions (tenant_id, project_id, id)",
    "ALTER TABLE processing_artifacts ADD CONSTRAINT fk_processing_artifacts_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE processing_artifacts ADD CONSTRAINT fk_processing_artifacts_run_parent FOREIGN KEY (tenant_id, project_id, processing_run_id) REFERENCES processing_runs (tenant_id, project_id, id)",
    "ALTER TABLE source_fragments ADD CONSTRAINT fk_source_fragments_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE source_fragments ADD CONSTRAINT fk_source_fragments_version_parent FOREIGN KEY (tenant_id, project_id, document_version_id) REFERENCES document_versions (tenant_id, project_id, id)",
    "ALTER TABLE source_fragments ADD CONSTRAINT fk_source_fragments_run_parent FOREIGN KEY (tenant_id, project_id, processing_run_id) REFERENCES processing_runs (tenant_id, project_id, id)",
    "ALTER TABLE knowledge_items ADD CONSTRAINT uq_knowledge_items_parent UNIQUE (tenant_id, project_id, id)",
    "ALTER TABLE knowledge_items ADD CONSTRAINT fk_knowledge_items_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE knowledge_assertions ADD CONSTRAINT fk_assertions_item_parent FOREIGN KEY (tenant_id, project_id, knowledge_item_id) REFERENCES knowledge_items (tenant_id, project_id, id)",
    "ALTER TABLE knowledge_assertions ADD CONSTRAINT fk_assertions_fragment_parent FOREIGN KEY (tenant_id, project_id, source_fragment_id) REFERENCES source_fragments (tenant_id, project_id, id)",
    "ALTER TABLE conversations ADD CONSTRAINT uq_conversations_tenant_id UNIQUE (tenant_id, id)",
    "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
    "ALTER TABLE messages ADD CONSTRAINT fk_messages_conversation_tenant FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations (tenant_id, id)",
    "ALTER TABLE memory_entries ADD CONSTRAINT fk_memory_entries_project_tenant FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)",
]

RLS_TABLES = [
    "memberships", "workspaces", "projects", "project_memberships", "documents",
    "document_versions", "processing_runs", "processing_artifacts", "source_fragments",
    "knowledge_items", "knowledge_assertions", "conversations", "messages",
    "memory_entries", "audit_events",
]


def upgrade() -> None:
    for statement in CONSTRAINTS:
        op.execute(statement)

    op.execute("""
        CREATE POLICY tenant_isolation ON tenants
        USING (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")

    for table in RLS_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")

    for statement in [
        ("memory_entries", "fk_memory_entries_project_tenant"),
        ("messages", "fk_messages_conversation_tenant"),
        ("conversations", "fk_conversations_project_tenant"),
        ("conversations", "uq_conversations_tenant_id"),
        ("knowledge_assertions", "fk_assertions_fragment_parent"),
        ("knowledge_assertions", "fk_assertions_item_parent"),
        ("knowledge_items", "fk_knowledge_items_project_tenant"),
        ("knowledge_items", "uq_knowledge_items_parent"),
        ("source_fragments", "fk_source_fragments_run_parent"),
        ("source_fragments", "fk_source_fragments_version_parent"),
        ("source_fragments", "fk_source_fragments_project_tenant"),
        ("processing_artifacts", "fk_processing_artifacts_run_parent"),
        ("processing_artifacts", "fk_processing_artifacts_project_tenant"),
        ("processing_runs", "fk_processing_runs_version_parent"),
        ("processing_runs", "fk_processing_runs_project_tenant"),
        ("processing_runs", "uq_processing_runs_parent"),
        ("documents", "fk_documents_current_version_parent"),
        ("document_versions", "fk_document_versions_document_parent"),
        ("document_versions", "fk_document_versions_project_tenant"),
        ("document_versions", "uq_document_versions_parent"),
        ("documents", "fk_documents_project_tenant"),
        ("documents", "uq_documents_tenant_project_id"),
        ("project_memberships", "fk_project_memberships_tenant_member"),
        ("project_memberships", "fk_project_memberships_project_tenant"),
        ("projects", "fk_projects_workspace_tenant"),
        ("workspaces", "uq_workspaces_tenant_id"),
    ]:
        table, constraint = statement
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
