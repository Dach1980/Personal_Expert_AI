"""Bootstrap initial relational schema from the initial model registry.

Revision ID: 0001_initial_domain
"""

from alembic import op

from app.storage.models import Base
import app.storage.models  # noqa: F401

revision = "0001_initial_domain"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the initial schema on the configured PostgreSQL database."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop the initial schema in dependency order."""
    Base.metadata.drop_all(bind=op.get_bind())
