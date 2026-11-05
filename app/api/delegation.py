"""PEA-owned Bionic project bindings and scheduled retrieval delegation."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import (
    AuthenticatedIdentity,
    Principal,
    WorkloadPrincipal,
    get_current_identity,
    get_current_principal,
    get_current_workload,
    require_system_permission,
)
from app.api.routes import search_project_sources
from app.api.schemas import SearchRequest, SearchResponse
from app.storage.database import (
    get_session,
    set_bionic_workload_context,
    set_tenant_context,
    set_user_context,
)
from app.storage.models import (
    AuditEvent,
    BionicProjectBinding,
    DelegationGrant,
    Membership,
    Project,
    SystemAuditEvent,
    User,
)
from app.storage.services import ProjectService, ResourceNotFoundError

router = APIRouter(prefix="/api/v1", tags=["Bionic retrieval delegation"])


def _bionic_instance() -> str:
    value = os.getenv("PEA_BIONIC_INSTANCE_ID", "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PEA Bionic instance identity is not configured",
        )
    if len(value) > 100:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PEA Bionic instance identity is invalid",
        )
    return value


class BindingCreate(BaseModel):
    bionic_project_id: int = Field(gt=0)
    tenant_id: UUID
    project_id: UUID


class BindingRead(BaseModel):
    id: UUID
    bionic_instance: str
    bionic_project_id: int
    tenant_id: UUID
    project_id: UUID
    status: str


class DelegationGrantCreate(BaseModel):
    bionic_project_id: int = Field(gt=0)
    bionic_task_id: int = Field(gt=0)
    ttl_seconds: int = Field(default=3600, ge=60, le=604800)


class DelegationGrantIssued(BaseModel):
    id: UUID
    token: str
    expires_at: datetime
    operation: str = "search"


class DelegationGrantRevoked(BaseModel):
    id: UUID
    status: str


class BionicRetrievalRequest(BaseModel):
    grant_token: str = Field(min_length=32, max_length=128)
    bionic_project_id: int = Field(gt=0)
    bionic_task_id: int = Field(gt=0)
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=8, ge=1, le=20)


@router.post(
    "/admin/bionic-project-bindings",
    response_model=BindingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_bionic_project_binding(
    payload: BindingCreate,
    identity: AuthenticatedIdentity = Depends(
        require_system_permission("system.integrations.manage")
    ),
    session: Session = Depends(get_session),
) -> BindingRead:
    """Create an explicit mapping; callers cannot choose the Bionic instance."""
    instance = _bionic_instance()
    set_tenant_context(session, payload.tenant_id)
    project = session.scalar(
        select(Project).where(
            Project.tenant_id == payload.tenant_id,
            Project.id == payload.project_id,
            Project.status == "active",
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="PEA project not found")

    existing = session.scalar(
        select(BionicProjectBinding).where(
            BionicProjectBinding.bionic_instance == instance,
            BionicProjectBinding.bionic_project_id == payload.bionic_project_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Bionic project already has a binding")

    binding = BionicProjectBinding(
        id=uuid4(),
        bionic_instance=instance,
        bionic_project_id=payload.bionic_project_id,
        tenant_id=payload.tenant_id,
        project_id=payload.project_id,
        status="active",
        created_by=identity.user_id,
    )
    session.add(binding)
    session.flush()
    session.add(
        SystemAuditEvent(
            id=uuid4(),
            actor_user_id=identity.user_id,
            action="bionic_project_binding.created",
            target_type="bionic_project_binding",
            target_id=binding.id,
            tenant_id=payload.tenant_id,
            outcome="success",
            details={
                "bionic_instance": instance,
                "bionic_project_id": payload.bionic_project_id,
                "pea_project_id": str(payload.project_id),
            },
        )
    )
    return BindingRead(
        id=binding.id,
        bionic_instance=binding.bionic_instance,
        bionic_project_id=binding.bionic_project_id,
        tenant_id=binding.tenant_id,
        project_id=binding.project_id,
        status=binding.status,
    )


@router.delete(
    "/admin/bionic-project-bindings/{binding_id}",
    response_model=BindingRead,
)
def disable_bionic_project_binding(
    binding_id: UUID,
    identity: AuthenticatedIdentity = Depends(
        require_system_permission("system.integrations.manage")
    ),
    session: Session = Depends(get_session),
) -> BindingRead:
    """Disable a binding without deleting history or invalidating its audit trail."""
    binding = session.get(BionicProjectBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Bionic project binding not found")
    set_tenant_context(session, binding.tenant_id)
    binding.status = "disabled"
    session.flush()
    session.add(
        SystemAuditEvent(
            id=uuid4(),
            actor_user_id=identity.user_id,
            action="bionic_project_binding.disabled",
            target_type="bionic_project_binding",
            target_id=binding.id,
            tenant_id=binding.tenant_id,
            outcome="success",
            details={"bionic_project_id": binding.bionic_project_id},
        )
    )
    return BindingRead(
        id=binding.id,
        bionic_instance=binding.bionic_instance,
        bionic_project_id=binding.bionic_project_id,
        tenant_id=binding.tenant_id,
        project_id=binding.project_id,
        status=binding.status,
    )


@router.post(
    "/tenants/{tenant_id}/projects/{project_id}/delegation-grants",
    response_model=DelegationGrantIssued,
    status_code=status.HTTP_201_CREATED,
)
def issue_delegation_grant(
    tenant_id: UUID,
    project_id: UUID,
    payload: DelegationGrantCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> DelegationGrantIssued:
    """Issue a one-time secret for a task after verifying the user's project access."""
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        ProjectService(session).get(tenant_id, project_id, principal.user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None

    instance = _bionic_instance()
    binding = session.scalar(
        select(BionicProjectBinding).where(
            BionicProjectBinding.bionic_instance == instance,
            BionicProjectBinding.bionic_project_id == payload.bionic_project_id,
            BionicProjectBinding.tenant_id == tenant_id,
            BionicProjectBinding.project_id == project_id,
            BionicProjectBinding.status == "active",
        )
    )
    if binding is None:
        raise HTTPException(status_code=409, detail="No active Bionic project binding exists")

    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=payload.ttl_seconds)
    grant = DelegationGrant(
        id=uuid4(),
        binding_id=binding.id,
        tenant_id=tenant_id,
        project_id=project_id,
        owner_user_id=principal.user_id,
        bionic_task_id=payload.bionic_task_id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        operation="search",
        status="active",
        expires_at=expires_at,
        created_at=now,
    )
    session.add(grant)
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=principal.user_id,
            action="delegation_grant.created",
            target_type="delegation_grant",
            target_id=grant.id,
            outcome="success",
            details={
                "bionic_project_id": payload.bionic_project_id,
                "bionic_task_id": payload.bionic_task_id,
                "operation": "search",
                "expires_at": expires_at.isoformat(),
            },
        )
    )
    session.flush()
    # The raw secret is returned once. Only its SHA-256 hash is persisted.
    return DelegationGrantIssued(id=grant.id, token=token, expires_at=expires_at)


@router.delete(
    "/tenants/{tenant_id}/projects/{project_id}/delegation-grants/{grant_id}",
    response_model=DelegationGrantRevoked,
)
def revoke_delegation_grant(
    tenant_id: UUID,
    project_id: UUID,
    grant_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> DelegationGrantRevoked:
    """Allow only the grant owner to revoke their task's delegation."""
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Delegation grant not found")
    grant = session.scalar(
        select(DelegationGrant).where(
            DelegationGrant.id == grant_id,
            DelegationGrant.tenant_id == tenant_id,
            DelegationGrant.project_id == project_id,
            DelegationGrant.owner_user_id == principal.user_id,
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Delegation grant not found")
    if grant.status == "active":
        grant.status = "revoked"
        grant.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                actor_user_id=principal.user_id,
                action="delegation_grant.revoked",
                target_type="delegation_grant",
                target_id=grant.id,
                outcome="success",
                details={"project_id": str(project_id)},
            )
        )
        session.flush()
    return DelegationGrantRevoked(id=grant.id, status=grant.status)


@router.post(
    "/internal/bionic/retrieval/search",
    response_model=SearchResponse,
    tags=["internal"],
)
def bionic_delegated_search(
    payload: BionicRetrievalRequest,
    workload: WorkloadPrincipal = Depends(get_current_workload),
    session: Session = Depends(get_session),
) -> SearchResponse:
    """Resolve a PEA-owned grant and search only its bound project for Bionic."""
    instance = _bionic_instance()
    set_bionic_workload_context(session)
    token_hash = hashlib.sha256(payload.grant_token.encode("utf-8")).hexdigest()
    grant = session.scalar(
        select(DelegationGrant).where(
            DelegationGrant.token_hash == token_hash,
            DelegationGrant.bionic_task_id == payload.bionic_task_id,
            DelegationGrant.status == "active",
            DelegationGrant.operation == "search",
        )
    )
    if grant is None:
        raise HTTPException(status_code=403, detail="Delegation grant is invalid or revoked")

    binding = session.scalar(
        select(BionicProjectBinding).where(
            BionicProjectBinding.id == grant.binding_id,
            BionicProjectBinding.bionic_instance == instance,
            BionicProjectBinding.bionic_project_id == payload.bionic_project_id,
            BionicProjectBinding.tenant_id == grant.tenant_id,
            BionicProjectBinding.project_id == grant.project_id,
            BionicProjectBinding.status == "active",
        )
    )
    if binding is None:
        raise HTTPException(status_code=403, detail="Bionic project binding is inactive or mismatched")

    now = datetime.now(UTC)
    if grant.expires_at <= now:
        raise HTTPException(status_code=403, detail="Delegation grant has expired")

    # Resolve the original owner from the grant, then re-check current PEA access.
    set_user_context(session, grant.owner_user_id)
    set_tenant_context(session, grant.tenant_id)
    owner = session.scalar(
        select(User).where(User.id == grant.owner_user_id, User.status == "active")
    )
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == grant.tenant_id,
            Membership.user_id == grant.owner_user_id,
            Membership.status == "active",
        )
    )
    if owner is None or membership is None:
        raise HTTPException(status_code=403, detail="Grant owner no longer has tenant access")
    issuer = os.getenv("OIDC_ISSUER", "").rstrip("/")
    if not issuer:
        raise HTTPException(status_code=503, detail="PEA OIDC issuer is not configured")
    owner_identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.user_id == grant.owner_user_id,
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == payload.owner_subject,
            ExternalIdentity.status == "active",
        )
    )
    if owner_identity is None:
        raise HTTPException(status_code=403, detail="Bionic task owner does not match the delegation owner")
    try:
        ProjectService(session).get(grant.tenant_id, grant.project_id, grant.owner_user_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=403, detail="Grant owner no longer has project access") from None

    grant.last_used_at = now
    session.flush()
    principal = Principal(
        user_id=grant.owner_user_id,
        tenant_id=grant.tenant_id,
        membership_role=membership.role,
    )
    return search_project_sources(
        tenant_id=grant.tenant_id,
        project_id=grant.project_id,
        payload=SearchRequest(query=payload.query, top_k=payload.top_k),
        principal=principal,
        session=session,
    )
