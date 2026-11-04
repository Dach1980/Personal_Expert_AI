"""Apply tenant RLS to review domain tables and constrain review scope.

Revision ID: 0010_review_domain_rls
"""
from alembic import op

revision = "0010_review_domain_rls"
down_revision = "0009_reviews_findings_evidence"
branch_labels = None
depends_on = None

TABLES = ("reviews", "findings", "evidence")


def upgrade() -> None:
    op.create_check_constraint(
        "ck_reviews_scope",
        "reviews",
        "scope IN ('project','document_version')",
    )
    for table in TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_constraint("ck_reviews_scope", "reviews", type_="check")
