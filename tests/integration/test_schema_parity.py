"""Verify ORM table/column inventory against the migrated PostgreSQL schema."""
import os

import pytest
from sqlalchemy import create_engine, inspect

from app.storage.models import Base

DATABASE_URL = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")


def test_postgres_table_and_column_inventory_matches_orm():
    engine = create_engine(DATABASE_URL)
    try:
        inspector = inspect(engine)
        database_tables = set(inspector.get_table_names()) - {"alembic_version"}
        orm_tables = set(Base.metadata.tables)
        assert database_tables == orm_tables
        for table_name, table in Base.metadata.tables.items():
            db_columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert db_columns == set(table.columns.keys()), table_name
    finally:
        engine.dispose()
