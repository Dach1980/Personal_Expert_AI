"""Authentication boundary for Keycloak-issued access tokens."""
import os
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.database import get_session, set_tenant_context
from app.storage.models import ExternalIdentity, Membership, Tenant, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: UUID


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


def _unauthorized(detail: str = "Invalid access token") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _decode_keycloak_token(token: str) -> dict:
    issuer = os.getenv("OIDC_ISSUER", "").rstrip("/")
    audience = os.getenv("OIDC_AUDIENCE", "")
    jwks_url = os.getenv("OIDC_JWKS_URL", "")
    if not issuer or not audience or not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is not configured",
        )
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud", "tenant_id"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
            leeway=30,
        )
    except (jwt.PyJWTError, ValueError, TypeError):
        raise _unauthorized() from None


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> Principal:
    """Verify Keycloak signature and resolve an explicitly provisioned PEA identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_keycloak_token(credentials.credentials)
    issuer = claims.get("iss")
    subject = claims.get("sub")
    try:
        tenant_id = UUID(str(claims.get("tenant_id")))
    except (TypeError, ValueError):
        raise _unauthorized() from None
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise _unauthorized()

    identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
            ExternalIdentity.status == "active",
        )
    )
    if identity is None:
        raise _unauthorized("External identity is not provisioned")

    user = session.scalar(select(User).where(User.id == identity.user_id, User.status == "active"))
    if user is None:
        raise _unauthorized("Inactive or unknown user")

    # The tenant id comes from the verified token. Set transaction-local RLS
    # context before reading tenants or memberships, both of which are RLS-protected.
    set_tenant_context(session, tenant_id)
    tenant = session.scalar(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active")
    )
    if tenant is None or tenant.status != "active":
        raise _unauthorized("Tenant is inactive or unknown")

    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise _unauthorized("User has no active membership in this tenant")

    return Principal(user_id=user.id, tenant_id=tenant_id)
