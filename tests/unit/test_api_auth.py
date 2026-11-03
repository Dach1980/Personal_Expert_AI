from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api import auth


def _token(private_key, user_id, tenant_id) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "keycloak-subject",
            "tenant_id": str(tenant_id),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": "https://sso.example.test/realms/pea",
            "aud": "pea-api",
        },
        private_key,
        algorithm="RS256",
    )


def _configure_oidc(monkeypatch, private_key):
    monkeypatch.setenv("OIDC_ISSUER", "https://sso.example.test/realms/pea")
    monkeypatch.setenv("OIDC_AUDIENCE", "pea-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://sso.example.test/realms/pea/certs")

    class SigningKey:
        key = private_key.public_key()

    class JwksClient:
        def get_signing_key_from_jwt(self, token):
            return SigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: JwksClient())


def test_principal_is_derived_from_verified_keycloak_identity(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id, tenant_id = uuid4(), uuid4()
    session = Mock()
    session.scalar.side_effect = [
        SimpleNamespace(user_id=user_id),
        SimpleNamespace(id=user_id, status="active"),
        SimpleNamespace(status="active"),
    ]

    principal = auth.get_current_principal(
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_token(private_key, user_id, tenant_id),
        ),
        session,
    )

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id
    assert session.scalar.call_count == 3


def test_invalid_jwt_is_rejected(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"),
            Mock(),
        )
    assert error.value.status_code == 401


def test_missing_oidc_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    monkeypatch.delenv("OIDC_JWKS_URL", raising=False)
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"),
            Mock(),
        )
    assert error.value.status_code == 503
