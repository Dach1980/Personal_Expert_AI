from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api import auth


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
    membership = SimpleNamespace(status="active")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    principal = auth.get_current_principal(
        credentials=credentials,
        session=Session([identity, user, membership]),
    )

    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id


def test_principal_rejects_missing_external_identity(signing_keys):
    tenant_id = uuid4()
    token = make_token(signing_keys, tenant_id=str(tenant_id))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials=credentials, session=SessionNone())

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
