"""Add explicit Bionic project bindings and revocable PEA retrieval grants.

Revision ID: 0015_bionic_retrieval_delegation
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_bionic_retrieval_delegation"
down_revision = "0014_system_admin_tenant_read"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_system_admin_grants_permission",
        "system_admin_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_system_admin_grants_permission",
        "system_admin_grants",
        "permission IN ('system.audit.read','system.roadmap.read','system.tenants.read',"
        "'system.tenants.manage','system.admins.manage','system.integrations.manage')",
    )

    op.create_table(
        "bionic_project_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bionic_instance", sa.String(length=100), nullable=False),
        sa.Column("bionic_project_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(trim(bionic_instance)) BETWEEN 1 AND 100",
            name="ck_bionic_project_bindings_instance",
        ),
        sa.CheckConstraint(
            "bionic_project_id > 0",
            name="ck_bionic_project_bindings_project_id",
        ),
        sa.CheckConstraint(
            "status IN ('active','disabled')",
            name="ck_bionic_project_bindings_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="fk_bionic_project_bindings_pea_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_bionic_project_bindings_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bionic_project_bindings"),
        sa.UniqueConstraint(
            "bionic_instance", "bionic_project_id",
            name="uq_bionic_project_bindings_external_project",
        ),
        sa.UniqueConstraint(
            "bionic_instance", "tenant_id", "project_id",
            name="uq_bionic_project_bindings_pea_project",
        ),
        sa.UniqueConstraint(
            "id", "tenant_id", "project_id",
            name="uq_bionic_project_bindings_parent",
        ),
    )
    op.create_index(
        "ix_bionic_project_bindings_pea_project",
        "bionic_project_bindings",
        ["tenant_id", "project_id", "status"],
    )

    op.create_table(
        "delegation_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("bionic_task_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=30), server_default="search", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND translate(token_hash, '0123456789abcdef', '') = ''",
            name="ck_delegation_grants_token_hash",
        ),
        sa.CheckConstraint("operation = 'search'", name="ck_delegation_grants_operation"),
        sa.CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_delegation_grants_status",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_delegation_grants_expiry"),
        sa.CheckConstraint(
            "status <> 'revoked' OR revoked_at IS NOT NULL",
            name="ck_delegation_grants_revoked_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id", "tenant_id", "project_id"],
            ["bionic_project_bindings.id", "bionic_project_bindings.tenant_id", "bionic_project_bindings.project_id"],
            name="fk_delegation_grants_binding_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_delegation_grants_owner_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_delegation_grants"),
        sa.UniqueConstraint("token_hash", name="uq_delegation_grants_token_hash"),
        sa.UniqueConstraint(
            "id", "tenant_id", "project_id",
            name="uq_delegation_grants_parent",
        ),
    )
    op.create_index(
        "ix_delegation_grants_owner_status",
        "delegation_grants",
        ["tenant_id", "project_id", "owner_user_id", "status"],
    )
    op.create_index(
        "ix_delegation_grants_binding_task",
        "delegation_grants",
        ["binding_id", "bionic_task_id", "status"],
    )
    op.create_index(
        "ix_delegation_grants_expiry",
        "delegation_grants",
        ["expires_at", "status"],
    )

    # The tables are reachable only through authenticated PEA endpoints.
    # RLS adds defense in depth for user-owned grants and workload resolution.
    op.execute("ALTER TABLE bionic_project_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bionic_project_bindings FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY bionic_project_bindings_read ON bionic_project_bindings
        FOR SELECT
        USING (
            current_setting('app.bionic_workload', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM system_admin_grants g
                WHERE g.user_id = nullif(current_setting('app.user_id', true), '')::uuid
                  AND g.permission = 'system.integrations.manage'
                  AND g.status = 'active'
            )
        )
    """)
    op.execute("""
        CREATE POLICY bionic_project_bindings_admin_write ON bionic_project_bindings
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM system_admin_grants g
                WHERE g.user_id = nullif(current_setting('app.user_id', true), '')::uuid
                  AND g.permission = 'system.integrations.manage'
                  AND g.status = 'active'
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM system_admin_grants g
                WHERE g.user_id = nullif(current_setting('app.user_id', true), '')::uuid
                  AND g.permission = 'system.integrations.manage'
                  AND g.status = 'active'
            )
        )
    """)

    op.execute("ALTER TABLE delegation_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delegation_grants FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY delegation_grants_read ON delegation_grants
        FOR SELECT
        USING (
            owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid
            OR current_setting('app.bionic_workload', true) = 'true'
        )
    """)
    op.execute("""
        CREATE POLICY delegation_grants_owner_insert ON delegation_grants
        FOR INSERT
        WITH CHECK (
            owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid
            AND tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        )
    """)
    op.execute("""
        CREATE POLICY delegation_grants_owner_update ON delegation_grants
        FOR UPDATE
        USING (
            owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid
            OR current_setting('app.bionic_workload', true) = 'true'
        )
        WITH CHECK (
            owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid
            OR current_setting('app.bionic_workload', true) = 'true'
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS delegation_grants_owner_update ON delegation_grants")
    op.execute("DROP POLICY IF EXISTS delegation_grants_owner_insert ON delegation_grants")
    op.execute("DROP POLICY IF EXISTS delegation_grants_read ON delegation_grants")
    op.execute("DROP POLICY IF EXISTS bionic_project_bindings_admin_write ON bionic_project_bindings")
    op.execute("DROP POLICY IF EXISTS bionic_project_bindings_read ON bionic_project_bindings")
    for table in ("delegation_grants", "bionic_project_bindings"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_delegation_grants_expiry", table_name="delegation_grants")
    op.drop_index("ix_delegation_grants_binding_task", table_name="delegation_grants")
    op.drop_index("ix_delegation_grants_owner_status", table_name="delegation_grants")
    op.drop_table("delegation_grants")
    op.drop_index("ix_bionic_project_bindings_pea_project", table_name="bionic_project_bindings")
    op.drop_table("bionic_project_bindings")

    op.drop_constraint(
        "ck_system_admin_grants_permission",
        "system_admin_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_system_admin_grants_permission",
        "system_admin_grants",
        "permission IN ('system.audit.read','system.roadmap.read','system.tenants.read',"
        "'system.tenants.manage','system.admins.manage')",
    )
