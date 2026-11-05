from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.storage.models  # noqa: F401
from app.storage.models import Base


def test_bionic_project_binding_is_explicit_and_unique() -> None:
    table = Base.metadata.tables["bionic_project_bindings"]
    unique_sets = {
        item.name: tuple(column.name for column in item.columns)
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    }
    foreign_keys = {
        item.name: item
        for item in table.constraints
        if isinstance(item, ForeignKeyConstraint)
    }
    checks = {item.name for item in table.constraints if isinstance(item, CheckConstraint)}

    assert unique_sets["uq_bionic_project_bindings_external_project"] == (
        "bionic_instance", "bionic_project_id"
    )
    assert unique_sets["uq_bionic_project_bindings_pea_project"] == (
        "bionic_instance", "tenant_id", "project_id"
    )
    assert "fk_bionic_project_bindings_pea_project" in foreign_keys
    assert "fk_bionic_project_bindings_creator" in foreign_keys
    assert {
        "ck_bionic_project_bindings_instance",
        "ck_bionic_project_bindings_project_id",
        "ck_bionic_project_bindings_status",
    } <= checks


def test_delegation_grants_are_project_bound_and_revocable() -> None:
    table = Base.metadata.tables["delegation_grants"]
    foreign_keys = {
        item.name: item
        for item in table.constraints
        if isinstance(item, ForeignKeyConstraint)
    }
    checks = {item.name for item in table.constraints if isinstance(item, CheckConstraint)}
    unique_names = {
        item.name for item in table.constraints if isinstance(item, UniqueConstraint)
    }

    assert "fk_delegation_grants_binding_project" in foreign_keys
    assert "fk_delegation_grants_owner_membership" in foreign_keys
    assert "uq_delegation_grants_token_hash" in unique_names
    assert {
        "ck_delegation_grants_token_hash",
        "ck_delegation_grants_operation",
        "ck_delegation_grants_status",
        "ck_delegation_grants_expiry",
        "ck_delegation_grants_revoked_timestamp",
    } <= checks


def test_integration_management_is_a_separate_system_permission() -> None:
    table = Base.metadata.tables["system_admin_grants"]
    check = next(
        item for item in table.constraints
        if isinstance(item, CheckConstraint)
        and item.name == "ck_system_admin_grants_permission"
    )
    assert "system.integrations.manage" in str(check.sqltext)
