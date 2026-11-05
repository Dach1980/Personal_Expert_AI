from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api import auth
from app.api.routes import get_session_info


@pytest.fixture
def signing_keys(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("OIDC_ISSUER", "https://sso.example.test/realms/pea")
    monkeypatch.setenv("OIDC_AUDIENCE", "pea-api")
    monkeypatch.setenv(
        "OIDC_JWKS_URL",
        "https://sso.example.test/realms/pea/protocol/openid-connect/certs",
    )

    class Key:
        key = private_key.public_key()

    class Client:
        def get_signing_key_from_jwt(self, token):
            return Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: Client())
    monkeypatch.setattr(auth, "set_user_context", lambda _session, _user_id: None)
    monkeypatch.setattr(auth, "set_tenant_context", lambda _session, _tenant_id: None)
    return private_key


def make_token(private_key, **overrides):
    now = datetime.now(UTC)
    claims = {
        "iss": "https://sso.example.test/realms/pea",
        "aud": "pea-api",
        "sub": "keycloak-subject-123",
        "tenant_id": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_keycloak_token_is_verified_and_claims_are_returned(signing_keys):
    token = make_token(signing_keys)

    claims = auth._decode_keycloak_token(token)

    assert claims["sub"] == "keycloak-subject-123"
    assert claims["aud"] == "pea-api"


def test_keycloak_token_rejects_wrong_signature(signing_keys):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(other_key)

    with pytest.raises(HTTPException) as error:
        auth._decode_keycloak_token(token)

    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example/realm"},
        {"aud": "another-api"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
def test_keycloak_token_rejects_invalid_security_claims(signing_keys, claims):
    token = make_token(signing_keys, **claims)

    with pytest.raises(HTTPException):
        auth._decode_keycloak_token(token)


def test_principal_requires_provisioned_identity_and_active_membership(signing_keys):
    tenant_id = uuid4()
    user_id = uuid4()
    token = make_token(signing_keys, tenant_id=str(tenant_id))

    class Session:
        def __init__(self, rows):
            self.rows = iter(rows)

        def scalar(self, _statement):
            return next(self.rows)

    identity = SimpleNamespace(user_id=user_id)
    user = SimpleNamespace(id=user_id)
    tenant = SimpleNamespace(id=tenant_id, status="active")
    membership = SimpleNamespace(status="active", role="member")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    principal = auth.get_current_principal(
        credentials=credentials,
        session=Session([identity, user, membership, tenant]),
        x_tenant_id=None,
    )

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id


def test_principal_accepts_selected_tenant_without_legacy_tenant_claim(signing_keys):
    tenant_id = uuid4()
    user_id = uuid4()
    token = make_token(signing_keys, tenant_id=None)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    class Session:
        def __init__(self, rows):
            self.rows = iter(rows)

        def scalar(self, _statement):
            return next(self.rows)

    identity = SimpleNamespace(user_id=user_id)
    user = SimpleNamespace(id=user_id)
    membership = SimpleNamespace(status="active", role="admin")
    tenant = SimpleNamespace(id=tenant_id, status="active")

    principal = auth.get_current_principal(
        credentials=credentials,
        session=Session([identity, user, membership, tenant]),
        x_tenant_id=str(tenant_id),
    )

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id
    assert principal.membership_role == "admin"


def test_session_endpoint_returns_identity_without_selecting_tenant():
    user_id = uuid4()
    user = SimpleNamespace(
        id=user_id,
        status="active",
        display_name="Test User",
        login="test-user",
    )

    result = get_session_info(
        identity=SimpleNamespace(user_id=user_id),
        session=Session([user]),
    )

    assert result.user_id == user_id
    assert result.tenant_id is None


def test_principal_rejects_missing_external_identity(signing_keys):
    tenant_id = uuid4()
    token = make_token(signing_keys, tenant_id=str(tenant_id))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials=credentials, session=SessionNone(), x_tenant_id=None)

    assert error.value.status_code == 401


class SessionNone:
    def scalar(self, _statement):
        return None

def test_principal_rejects_malformed_tenant_claim(signing_keys):
    token = make_token(signing_keys, tenant_id="not-a-uuid")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials=credentials, session=SessionNone())

    assert error.value.status_code == 401


def test_principal_rejects_inactive_tenant(signing_keys):
    tenant_id = uuid4()
    user_id = uuid4()
    token = make_token(signing_keys, tenant_id=str(tenant_id))

    class Session:
        def __init__(self, rows):
            self.rows = iter(rows)

        def scalar(self, _statement):
            return next(self.rows)

    identity = SimpleNamespace(user_id=user_id)
    user = SimpleNamespace(id=user_id)
    tenant = SimpleNamespace(id=tenant_id, status="disabled")
    membership = SimpleNamespace(status="active", role="member")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(
            credentials=credentials,
            session=Session([identity, user, membership, tenant]),
            x_tenant_id=None,
        )

    assert error.value.status_code == 404


def test_keycloak_identity_token_does_not_require_legacy_tenant_claim(signing_keys):
    now = datetime.now(UTC)
    claims = {
        "iss": "https://sso.example.test/realms/pea",
        "aud": "pea-api",
        "sub": "keycloak-subject-123",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(claims, signing_keys, algorithm="RS256")
    verified = auth._decode_keycloak_token(token)
    assert "tenant_id" not in verified
