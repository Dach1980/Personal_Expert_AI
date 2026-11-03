from uuid import uuid4

import pytest

from fastapi import HTTPException

from app.api.auth import Principal
from app.api.routes import _check_tenant, _public_locator


def test_public_locator_removes_storage_internals_recursively():
    locator = {
        "page": 3,
        "bbox": [10, 20, 30, 40],
        "artifact_storage_key": "tenant/project/private/page.png",
        "nested": {
            "storage_key": "private/source.pdf",
            "absolute_path": "/srv/private/source.pdf",
            "cell": "B12",
        },
    }

    assert _public_locator(locator) == {
        "page": 3,
        "bbox": [10, 20, 30, 40],
        "nested": {"cell": "B12"},
    }


def test_public_locator_preserves_typed_table_and_sheet_coordinates():
    locator = {
        "sheet": "Экспликация",
        "table": 2,
        "row": 7,
        "cell": "D7",
        "page": 12,
    }

    assert _public_locator(locator) == locator


def test_tenant_scope_rejects_a_different_tenant_without_disclosing_it():
    principal = Principal(user_id=uuid4(), tenant_id=uuid4())

    with pytest.raises(HTTPException) as error:
        _check_tenant(uuid4(), principal)

    assert error.value.status_code == 404
    assert error.value.detail == "Tenant not found"


def test_tenant_scope_accepts_only_the_authenticated_tenant():
    tenant_id = uuid4()
    principal = Principal(user_id=uuid4(), tenant_id=tenant_id)

    _check_tenant(tenant_id, principal)
