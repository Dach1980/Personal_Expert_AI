from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

from app.api.auth import Principal
from app.api.routes import get_session_info


def test_session_endpoint_returns_only_verified_principal_profile():
    user_id, tenant_id = uuid4(), uuid4()
    session = Mock()
    session.scalar.return_value = SimpleNamespace(
        id=user_id,
        status="active",
        display_name="Engineer",
        login="engineer@example.test",
    )

    result = get_session_info(
        principal=Principal(user_id=user_id, tenant_id=tenant_id),
        session=session,
    )

    assert result.authenticated is True
    assert result.user_id == user_id
    assert result.tenant_id == tenant_id
    assert result.display_name == "Engineer"
