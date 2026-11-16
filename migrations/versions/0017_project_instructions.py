"""Add editable project instructions.

Revision ID: 0017_project_instructions
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_project_instructions"
down_revision = "0016_identity_tables_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "instructions")
