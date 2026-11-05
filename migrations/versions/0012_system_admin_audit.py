"""Add global PEA system-admin grants and append-only audit events.

Revision ID: 0012_system_admin_audit
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_system_admin_audit"
down_revision = "0011_chat_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_admin_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "permission IN ('system.audit.read','system.roadmap.read','system.tenants.read',"
            "'system.tenants.manage','system.admins.manage')",
            name="ck_system_admin_grants_permission",
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_system_admin_grants_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_system_admin_grants_user"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name="fk_system_admin_grants_granted_by"),
        sa.PrimaryKeyConstraint("id", name="pk_system_admin_grants"),
        sa.UniqueConstraint("user_id", "permission", name="uq_system_admin_grants_user_permission"),
    )
    op.create_index(
        "ix_system_admin_grants_user_status",
        "system_admin_grants", ["user_id", "status"],
    )

    op.create_table(
        "system_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success','denied','failure')",
            name="ck_system_audit_events_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_system_audit_events_actor", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_system_audit_events_tenant", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_system_audit_events"),
    )
    op.create_index("ix_system_audit_events_created", "system_audit_events", ["created_at"])
    op.create_index(
        "ix_system_audit_events_tenant_created",
        "system_audit_events", ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_system_audit_events_target",
        "system_audit_events", ["target_type", "target_id"],
    )

    # A user can inspect only their own grants. No application write policy is
    # installed: grant provisioning is an explicit out-of-band operator action.
    op.execute("""
        CREATE POLICY system_admin_grants_self_read ON system_admin_grants
        FOR SELECT
        USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid)
    """)
    op.execute("ALTER TABLE system_admin_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE system_admin_grants FORCE ROW LEVEL SECURITY")

    # Insert is actor-bound to the authenticated application identity. Reads
    # require an active database grant for system.audit.read. No UPDATE/DELETE
    # policy exists, making the ledger append-only for the runtime role.
    op.execute("""
        CREATE POLICY system_audit_events_actor_insert ON system_audit_events
        FOR INSERT
        WITH CHECK (
            actor_user_id = nullif(current_setting('app.user_id', true), '')::uuid
        )
    """)
    op.execute("""
        CREATE POLICY system_audit_events_admin_read ON system_audit_events
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM system_admin_grants grant_row
                WHERE grant_row.user_id =
                    nullif(current_setting('app.user_id', true), '')::uuid
                  AND grant_row.permission = 'system.audit.read'
                  AND grant_row.status = 'active'
            )
        )
    """)
    op.execute("ALTER TABLE system_audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE system_audit_events FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ("system_audit_events", "system_admin_grants"):
        op.execute(f"DROP POLICY IF EXISTS system_audit_events_actor_insert ON {table}") if table == "system_audit_events" else None
        op.execute(f"DROP POLICY IF EXISTS system_audit_events_admin_read ON {table}") if table == "system_audit_events" else None
        op.execute(f"DROP POLICY IF EXISTS system_admin_grants_self_read ON {table}") if table == "system_admin_grants" else None
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_system_audit_events_target", table_name="system_audit_events")
    op.drop_index("ix_system_audit_events_tenant_created", table_name="system_audit_events")
    op.drop_index("ix_system_audit_events_created", table_name="system_audit_events")
    op.drop_table("system_audit_events")
    op.drop_index("ix_system_admin_grants_user_status", table_name="system_admin_grants")
    op.drop_table("system_admin_grants")
