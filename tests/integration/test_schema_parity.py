"""Compare migrated PostgreSQL schema objects with SQLAlchemy metadata.

The check intentionally covers named constraints and indexes in addition to
columns. Alembic's autogenerate check remains a separate, complementary gate.
"""
import os

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, create_engine, inspect

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


def test_named_constraints_and_indexes_match_orm():
    """Detect schema drift hidden by a table/column-only comparison."""
    engine = create_engine(DATABASE_URL)
    try:
        inspector = inspect(engine)
        for table_name, table in Base.metadata.tables.items():
            db_fks = {
                item["name"]: (
                    tuple(item["constrained_columns"]),
                    item["referred_table"],
                    tuple(item["referred_columns"]),
                    (item.get("options") or {}).get("ondelete"),
                )
                for item in inspector.get_foreign_keys(table_name)
                if item.get("name")
            }
            orm_fks = {
                item.name: (
                    tuple(column.name for column in item.columns),
                    item.elements[0].column.table.name,
                    tuple(element.column.name for element in item.elements),
                    item.ondelete,
                )
                for item in table.constraints
                if isinstance(item, ForeignKeyConstraint) and item.name
            }
            assert db_fks == orm_fks, f"{table_name}: foreign keys"

            db_uniques = {
                item["name"]: tuple(item["column_names"])
                for item in inspector.get_unique_constraints(table_name)
                if item.get("name")
            }
            orm_uniques = {
                item.name: tuple(column.name for column in item.columns)
                for item in table.constraints
                if isinstance(item, UniqueConstraint) and item.name
            }
            assert db_uniques == orm_uniques, f"{table_name}: unique constraints"

            db_checks = {
                item["name"]
                for item in inspector.get_check_constraints(table_name)
                if item.get("name")
            }
            orm_checks = {
                item.name
                for item in table.constraints
                if isinstance(item, CheckConstraint) and item.name
            }
            assert db_checks == orm_checks, f"{table_name}: check constraints"

            db_indexes = {
                item["name"]: (tuple(item["column_names"]), bool(item.get("unique", False)))
                for item in inspector.get_indexes(table_name)
                if item.get("name") and not item.get("duplicates_constraint", False)
            }
            orm_indexes = {
                item.name: (
                    tuple(expression.name for expression in item.expressions),
                    item.unique,
                )
                for item in table.indexes
                if isinstance(item, Index) and item.name
            }
            assert db_indexes == orm_indexes, f"{table_name}: indexes"
    finally:
        engine.dispose()
