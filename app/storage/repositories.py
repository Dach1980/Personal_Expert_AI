"""Tenant-scoped persistence operations.

Repositories deliberately require tenant/project scope in read methods. They are
not an authorization boundary by themselves; services must validate membership.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import Document, Membership, Project, ProjectMembership, Tenant


class TenantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: UUID) -> Tenant | None:
        return self.session.scalar(select(Tenant).where(Tenant.id == tenant_id))

    def add(self, tenant: Tenant) -> Tenant:
        self.session.add(tenant)
        self.session.flush()
        return tenant

    def active_membership(self, tenant_id: UUID, user_id: UUID) -> Membership | None:
        return self.session.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == user_id,
                Membership.status == "active",
            )
        )


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: UUID, project_id: UUID) -> Project | None:
        return self.session.scalar(
            select(Project).where(Project.tenant_id == tenant_id, Project.id == project_id)
        )

    def list_for_tenant(self, tenant_id: UUID) -> list[Project]:
        return list(
            self.session.scalars(
                select(Project).where(Project.tenant_id == tenant_id).order_by(Project.name)
            )
        )

    def add(self, project: Project) -> Project:
        self.session.add(project)
        self.session.flush()
        return project

    def active_membership(self, tenant_id: UUID, project_id: UUID, user_id: UUID) -> ProjectMembership | None:
        return self.session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.tenant_id == tenant_id,
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.status == "active",
            )
        )


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: UUID, project_id: UUID, document_id: UUID) -> Document | None:
        return self.session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.project_id == project_id,
                Document.id == document_id,
            )
        )

    def list_for_project(self, tenant_id: UUID, project_id: UUID) -> list[Document]:
        return list(
            self.session.scalars(
                select(Document)
                .where(Document.tenant_id == tenant_id, Document.project_id == project_id)
                .order_by(Document.title)
            )
        )

    def add(self, document: Document) -> Document:
        self.session.add(document)
        self.session.flush()
        return document
