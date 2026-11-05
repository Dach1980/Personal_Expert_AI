"""Allow identity-scoped tenant membership discovery without broadening tenant data RLS.

Revision ID: 0013_identity_tenant_discovery
"""
from alembic import op

revision = "0013_identity_tenant_discovery"
down_revision = "0012_system_admin_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON memberships")

    # A verified user may discover only their own active memberships. Writes
    # remain restricted to the explicitly selected tenant context.
    op.execute("""
        CREATE POLICY memberships_identity_read ON memberships
        FOR SELECT
        USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR (
                user_id = nullif(current_setting('app.user_id', true), '')::uuid
                AND status = 'active'
            )
        )
    """)
    op.execute("""
        CREATE POLICY memberships_tenant_write ON memberships
        FOR ALL
        USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        )
    """)

    # Tenant rows are visible only in the selected tenant or when referenced
    # by one of the verified user's active memberships. Tenant writes still
    # require the selected tenant context.
    op.execute("""
        CREATE POLICY tenants_identity_read ON tenants
        FOR SELECT
        USING (
            id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR EXISTS (
                SELECT 1
                FROM memberships membership_row
                WHERE membership_row.tenant_id = tenants.id
                  AND membership_row.user_id =
                      nullif(current_setting('app.user_id', true), '')::uuid
                  AND membership_row.status = 'active'
            )
        )
    """)
    op.execute("""
        CREATE POLICY tenants_context_write ON tenants
        FOR ALL
        USING (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenants_identity_read ON tenants")
    op.execute("DROP POLICY IF EXISTS tenants_context_write ON tenants")
    op.execute("DROP POLICY IF EXISTS memberships_identity_read ON memberships")
    op.execute("DROP POLICY IF EXISTS memberships_tenant_write ON memberships")

    op.execute("""
        CREATE POLICY tenant_isolation ON tenants
        USING (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE POLICY tenant_isolation ON memberships
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    """)
