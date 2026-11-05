from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.api.auth import AuthenticatedIdentity
from app.api.routes import get_session_info


def test_session_endpoint_returns_only_verified_principal_profile():
    user_id = uuid4()
    session = Mock()
    session.scalar.return_value = SimpleNamespace(
        id=user_id,
        status="active",
        display_name="Engineer",
        login="engineer@example.test",
    )

    result = get_session_info(
        identity=AuthenticatedIdentity(
            user_id=user_id,
            issuer="https://sso.example.test/realms/pea",
            subject="keycloak-subject",
        ),
        session=session,
    )

    assert result.authenticated is True
    assert result.user_id == user_id
    assert result.tenant_id is None
    assert result.display_name == "Engineer"
