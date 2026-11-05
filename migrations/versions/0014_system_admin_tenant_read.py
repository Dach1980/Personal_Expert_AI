"""Allow explicitly granted system administrators to list tenant metadata.

Revision ID: 0014_system_admin_tenant_read
"""
from alembic import op

revision = "0014_system_admin_tenant_read"
down_revision = "0013_identity_tenant_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE POLICY tenants_system_admin_read ON tenants
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM system_admin_grants grant_row
                WHERE grant_row.user_id =
                    nullif(current_setting('app.user_id', true), '')::uuid
                  AND grant_row.permission = 'system.tenants.read'
                  AND grant_row.status = 'active'
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenants_system_admin_read ON tenants")
