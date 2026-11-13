"""Restrict runtime reads of users and OIDC identities to the authenticated identity.

Revision ID: 0016_identity_tables_rls
"""
from alembic import op

revision = "0016_identity_tables_rls"
down_revision = "0015_bionic_retrieval_delegation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Identity lookup is scoped by issuer/subject only after JWT signature,
    # issuer and audience validation in the application auth boundary.
    op.execute("ALTER TABLE external_identities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE external_identities FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY external_identities_verified_oidc_read
        ON external_identities
        FOR SELECT
        USING (
            issuer = nullif(current_setting('app.oidc_issuer', true), '')
            AND subject = nullif(current_setting('app.oidc_subject', true), '')
            AND status = 'active'
        )
    """)

    # The application may read only the internal user row resolved from the
    # verified external identity. No runtime write policies are defined.
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY users_self_read
        ON users
        FOR SELECT
        USING (
            id = nullif(current_setting('app.user_id', true), '')::uuid
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_self_read ON users")
    op.execute("DROP POLICY IF EXISTS external_identities_verified_oidc_read ON external_identities")
    for table in ("users", "external_identities"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
