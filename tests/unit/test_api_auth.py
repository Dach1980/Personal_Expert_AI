from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth import get_current_principal


def _token(secret: str, user_id, tenant_id) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": "test-issuer",
            "aud": "test-audience",
        },
        secret,
        algorithm="HS256",
    )


def test_principal_is_derived_from_verified_jwt(monkeypatch):
    secret = "test-secret-that-is-longer-than-thirty-two-characters"
    user_id, tenant_id = uuid4(), uuid4()
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.setenv("JWT_ISSUER", "test-issuer")
    monkeypatch.setenv("JWT_AUDIENCE", "test-audience")
    session = Mock()
    session.scalar.return_value = Mock(status="active")

    principal = get_current_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=_token(secret, user_id, tenant_id)),
        session,
    )

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id


def test_invalid_jwt_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-longer-than-thirty-two-characters")
    monkeypatch.setenv("JWT_ISSUER", "test-issuer")
    monkeypatch.setenv("JWT_AUDIENCE", "test-audience")
    with pytest.raises(HTTPException) as error:
        get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"),
            Mock(),
        )
    assert error.value.status_code == 401


def test_missing_jwt_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_ISSUER", raising=False)
    monkeypatch.delenv("JWT_AUDIENCE", raising=False)
    with pytest.raises(HTTPException) as error:
        get_current_principal(None, Mock())
    assert error.value.status_code == 503
