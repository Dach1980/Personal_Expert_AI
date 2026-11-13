"""PostgreSQL-backed HTTP and revocation tests for tenant discovery."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import auth
from app.api.auth import AuthenticatedIdentity, get_current_identity
from app.main import app
from app.storage.database import (
    build_session_factory,
    get_session,
    set_tenant_context,
    set_user_context,
)
from app.storage.models import ExternalIdentity, Membership, Tenant, User

OWNER_DATABASE_URL = os.getenv("DATABASE_URL")
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not OWNER_DATABASE_URL or not APP_DATABASE_URL,
    reason="DATABASE_URL and restricted APP_DATABASE_URL are required",
)


def _seed_user_and_tenants(user_specs, tenant_specs, membership_specs, identity_spec=None):
    """Create fixtures with the owner connection; each tenant write has explicit context."""
    owner_factory = build_session_factory(OWNER_DATABASE_URL)
    try:
        with owner_factory() as session, session.begin():
            for user_id, login in user_specs:
                session.add(User(id=user_id, login=login, status="active"))
            session.flush()

            for tenant_id, name, status in tenant_specs:
                set_tenant_context(session, tenant_id)
                session.add(Tenant(id=tenant_id, name=name, status=status))
                session.flush()

            for tenant_id, user_id, role, status in membership_specs:
                set_tenant_context(session, tenant_id)
                session.add(
                    Membership(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        user_id=user_id,
                        role=role,
                        status=status,
                    )
                )
            if identity_spec is not None:
                issuer, subject, user_id = identity_spec
                session.add(
                    ExternalIdentity(
                        id=uuid4(),
                        issuer=issuer,
                        subject=subject,
                        user_id=user_id,
                        status="active",
                    )
                )
    finally:
        owner_factory.kw["bind"].dispose()


def _http_client_for_identity(user_id):
    """Use the restricted runtime DB role and install a verified-identity test seam."""
    app_factory = build_session_factory(APP_DATABASE_URL)

    def override_session():
        with app_factory() as session, session.begin():
            yield session

    def override_identity(session=Depends(get_session)):
        set_user_context(session, user_id)
        return AuthenticatedIdentity(
            user_id=user_id,
            issuer="https://sso.integration.test/realms/pea",
            subject=f"http-test-{user_id}",
        )

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_identity] = override_identity
    client = TestClient(app)
    return client, app_factory, previous_overrides


def _close_http_client(client, app_factory, previous_overrides):
    client.close()
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)
    app_factory.kw["bind"].dispose()


def test_http_get_tenants_returns_only_active_memberships_and_tenants():
    user_id = uuid4()
    active_tenant, revoked_tenant, disabled_tenant = uuid4(), uuid4(), uuid4()
    _seed_user_and_tenants(
        [(user_id, f"tenant-list-{user_id}@test.local")],
        [
            (active_tenant, "A active tenant", "active"),
            (revoked_tenant, "B revoked membership tenant", "active"),
            (disabled_tenant, "C disabled tenant", "disabled"),
        ],
        [
            (active_tenant, user_id, "member", "active"),
            (revoked_tenant, user_id, "member", "revoked"),
            (disabled_tenant, user_id, "member", "active"),
        ],
    )

    client, app_factory, previous = _http_client_for_identity(user_id)
    try:
        response = client.get("/api/v1/tenants")
        assert response.status_code == 200
        assert response.json() == [
            {"id": str(active_tenant), "name": "A active tenant", "role": "member"}
        ]
    finally:
        _close_http_client(client, app_factory, previous)


def test_http_get_tenants_and_rls_isolate_two_users_across_tenants():
    user_a, user_b = uuid4(), uuid4()
    tenant_a, tenant_b = uuid4(), uuid4()
    _seed_user_and_tenants(
        [
            (user_a, f"tenant-user-a-{user_a}@test.local"),
            (user_b, f"tenant-user-b-{user_b}@test.local"),
        ],
        [
            (tenant_a, "Tenant visible to A", "active"),
            (tenant_b, "Tenant visible to B", "active"),
        ],
        [
            (tenant_a, user_a, "member", "active"),
            (tenant_b, user_b, "tenant_admin", "active"),
        ],
    )

    client_a, factory_a, previous_a = _http_client_for_identity(user_a)
    try:
        response_a = client_a.get("/api/v1/tenants")
        assert response_a.status_code == 200
        assert response_a.json() == [
            {"id": str(tenant_a), "name": "Tenant visible to A", "role": "member"}
        ]
    finally:
        _close_http_client(client_a, factory_a, previous_a)

    client_b, factory_b, previous_b = _http_client_for_identity(user_b)
    try:
        response_b = client_b.get("/api/v1/tenants")
        assert response_b.status_code == 200
        assert response_b.json() == [
            {"id": str(tenant_b), "name": "Tenant visible to B", "role": "tenant_admin"}
        ]
    finally:
        _close_http_client(client_b, factory_b, previous_b)


def test_revoked_membership_is_denied_on_the_next_request(monkeypatch):
    user_id, tenant_id = uuid4(), uuid4()
    issuer = "https://sso.integration.test/realms/pea"
    subject = f"revocation-{uuid4()}"
    _seed_user_and_tenants(
        [(user_id, f"revocation-{user_id}@test.local")],
        [(tenant_id, "Revocation tenant", "active")],
        [(tenant_id, user_id, "member", "active")],
        identity_spec=(issuer, subject, user_id),
    )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": "pea-api",
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    class SigningKey:
        key = private_key.public_key()

    class JwksClient:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setenv("OIDC_ISSUER", issuer)
    monkeypatch.setenv("OIDC_AUDIENCE", "pea-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://sso.integration.test/realms/pea/certs")
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: JwksClient())

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    app_factory = build_session_factory(APP_DATABASE_URL)
    owner_factory = build_session_factory(OWNER_DATABASE_URL)
    try:
        with app_factory() as session, session.begin():
            principal = auth.get_current_principal(
                credentials, session, x_tenant_id=str(tenant_id)
            )
            assert principal.user_id == user_id
            assert principal.tenant_id == tenant_id

        with owner_factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            membership = session.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == user_id,
                )
            )
            assert membership is not None
            membership.status = "revoked"

        with app_factory() as session, session.begin():
            with pytest.raises(auth.HTTPException) as denied:
                auth.get_current_principal(
                    credentials, session, x_tenant_id=str(tenant_id)
                )
            assert denied.value.status_code == 404
    finally:
        app_factory.kw["bind"].dispose()
        owner_factory.kw["bind"].dispose()
