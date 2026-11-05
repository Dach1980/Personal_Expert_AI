"""Authentication boundary for Keycloak-issued access tokens."""
import os
from dataclasses import dataclass
from typing import Annotated
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.database import get_session, set_tenant_context, set_user_context
from app.storage.models import ExternalIdentity, Membership, SystemAdminGrant, Tenant, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Verified PEA user identity before an active tenant is selected."""

    user_id: UUID
    issuer: str
    subject: str
    legacy_tenant_id: UUID | None = None


@dataclass(frozen=True)
class Principal:
    """Verified user identity bound to an actively authorized tenant."""

    user_id: UUID
    tenant_id: UUID
    membership_role: str


@dataclass(frozen=True)
class SystemAdminPrincipal:
    """Verified identity with one or more active global PEA permissions."""

    user_id: UUID
    permissions: tuple[str, ...]


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
                "require": ["exp", "iat", "sub", "iss", "aud"],
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


def _resolve_identity(
    credentials: HTTPAuthorizationCredentials | None,
    session: Session,
) -> AuthenticatedIdentity:
    """Verify token and resolve the provisioned user without selecting a tenant."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_keycloak_token(credentials.credentials)
    issuer = claims.get("iss")
    subject = claims.get("sub")
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise _unauthorized()

    legacy_tenant_id = None
    if claims.get("tenant_id") is not None:
        try:
            legacy_tenant_id = UUID(str(claims["tenant_id"]))
        except (TypeError, ValueError):
            raise _unauthorized("Malformed legacy tenant claim") from None

    external_identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
            ExternalIdentity.status == "active",
        )
    )
    if external_identity is None:
        raise _unauthorized("External identity is not provisioned")

    user = session.scalar(
        select(User).where(
            User.id == external_identity.user_id,
            User.status == "active",
        )
    )
    if user is None:
        raise _unauthorized("Inactive or unknown user")

    # This context is derived only from the verified ExternalIdentity mapping.
    # RLS uses it solely for self-membership and self-grant discovery.
    set_user_context(session, user.id)
    return AuthenticatedIdentity(
        user_id=user.id,
        issuer=issuer,
        subject=subject,
        legacy_tenant_id=legacy_tenant_id,
    )


def get_current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> AuthenticatedIdentity:
    """Authenticate a user without requiring an active tenant selection."""
    return _resolve_identity(credentials, session)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> Principal:
    """Authenticate and revalidate the selected tenant membership on every request."""
    identity = _resolve_identity(credentials, session)
    selected_tenant_id = identity.legacy_tenant_id
    if x_tenant_id is not None:
        try:
            selected_tenant_id = UUID(x_tenant_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="X-Tenant-ID must be a UUID") from None

    if selected_tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Tenant selection required; call GET /api/v1/tenants and send X-Tenant-ID",
        )

    # The identity-scoped RLS policy allows this user to inspect only their own
    # active membership rows before a tenant context has been selected.
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == selected_tenant_id,
            Membership.user_id == identity.user_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    set_tenant_context(session, selected_tenant_id)
    tenant = session.scalar(
        select(Tenant).where(
            Tenant.id == selected_tenant_id,
            Tenant.status == "active",
        )
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return Principal(
        user_id=identity.user_id,
        tenant_id=selected_tenant_id,
        membership_role=membership.role,
    )



def get_current_system_admin(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
) -> SystemAdminPrincipal:
    """Require at least one active, database-backed PEA system permission."""
    permissions = tuple(
        session.scalars(
            select(SystemAdminGrant.permission).where(
                SystemAdminGrant.user_id == identity.user_id,
                SystemAdminGrant.status == "active",
            ).order_by(SystemAdminGrant.permission)
        ).all()
    )
    if not permissions:
        raise HTTPException(status_code=403, detail="System administrator permission required")
    return SystemAdminPrincipal(user_id=identity.user_id, permissions=permissions)


def require_system_permission(permission: str):
    """Build a dependency that checks one exact active PEA system permission."""

    def dependency(
        identity: AuthenticatedIdentity = Depends(get_current_identity),
        session: Session = Depends(get_session),
    ) -> AuthenticatedIdentity:
        grant_id = session.scalar(
            select(SystemAdminGrant.id).where(
                SystemAdminGrant.user_id == identity.user_id,
                SystemAdminGrant.permission == permission,
                SystemAdminGrant.status == "active",
            )
        )
        if grant_id is None:
            raise HTTPException(
                status_code=403,
                detail=f"Missing system permission: {permission}",
            )
        return identity

    return dependency
