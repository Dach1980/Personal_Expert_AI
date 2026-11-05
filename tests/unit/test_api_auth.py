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


def _token(private_key, tenant_id=None) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": "keycloak-subject",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": "https://sso.example.test/realms/pea",
        "aud": "pea-api",
    }
    if tenant_id is not None:
        claims["tenant_id"] = str(tenant_id)
    return jwt.encode(claims, private_key, algorithm="RS256")


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
    monkeypatch.setattr(auth, "set_user_context", Mock())
    monkeypatch.setattr(auth, "set_tenant_context", Mock())


def _rows(user_id, tenant_id, role="member"):
    return [
        SimpleNamespace(user_id=user_id),
        SimpleNamespace(id=user_id, status="active"),
        SimpleNamespace(tenant_id=tenant_id, user_id=user_id, role=role, status="active"),
        SimpleNamespace(id=tenant_id, status="active"),
    ]


def test_principal_is_derived_from_verified_identity_and_active_membership(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id, tenant_id = uuid4(), uuid4()
    session = Mock()
    session.scalar.side_effect = _rows(user_id, tenant_id, role="tenant_admin")

    principal = auth.get_current_principal(
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_token(private_key, tenant_id),
        ),
        session,
        x_tenant_id=None,
    )

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id
    assert principal.membership_role == "tenant_admin"
    assert session.scalar.call_count == 4
    auth.set_user_context.assert_called_once_with(session, user_id)
    auth.set_tenant_context.assert_called_once_with(session, tenant_id)


def test_selected_tenant_header_overrides_legacy_claim_only_after_membership_check(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id, legacy_tenant_id, selected_tenant_id = uuid4(), uuid4(), uuid4()
    session = Mock()
    session.scalar.side_effect = _rows(user_id, selected_tenant_id)

    principal = auth.get_current_principal(
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_token(private_key, legacy_tenant_id),
        ),
        session,
        x_tenant_id=str(selected_tenant_id),
    )

    assert principal.tenant_id == selected_tenant_id
    auth.set_tenant_context.assert_called_once_with(session, selected_tenant_id)


def test_tenant_selector_without_legacy_claim_is_required(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id = uuid4()
    session = Mock()
    session.scalar.side_effect = [
        SimpleNamespace(user_id=user_id),
        SimpleNamespace(id=user_id, status="active"),
    ]

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=_token(private_key)),
            session,
            x_tenant_id=None,
        )

    assert error.value.status_code == 400
    auth.set_tenant_context.assert_not_called()


def test_invalid_tenant_header_is_rejected(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id = uuid4()
    session = Mock()
    session.scalar.side_effect = [
        SimpleNamespace(user_id=user_id),
        SimpleNamespace(id=user_id, status="active"),
    ]

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=_token(private_key)),
            session,
            x_tenant_id="not-a-uuid",
        )

    assert error.value.status_code == 400


def test_inactive_or_missing_membership_is_denied(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id, tenant_id = uuid4(), uuid4()
    session = Mock()
    session.scalar.side_effect = [
        SimpleNamespace(user_id=user_id),
        SimpleNamespace(id=user_id, status="active"),
        None,
    ]

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=_token(private_key, tenant_id)),
            session,
            x_tenant_id=None,
        )

    assert error.value.status_code == 404
    auth.set_tenant_context.assert_not_called()


def test_invalid_jwt_is_rejected(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"),
            Mock(),
            x_tenant_id=None,
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
            x_tenant_id=None,
        )
    assert error.value.status_code == 503



def test_identity_authentication_does_not_require_tenant_claim(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    user_id = uuid4()
    session = Mock()
    session.scalar.side_effect = [
        SimpleNamespace(user_id=user_id),
        SimpleNamespace(id=user_id, status="active"),
    ]

    identity = auth.get_current_identity(
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_token(private_key),
        ),
        session,
    )

    assert identity.user_id == user_id
    assert identity.legacy_tenant_id is None
    auth.set_user_context.assert_called_once_with(session, user_id)
    auth.set_tenant_context.assert_not_called()
