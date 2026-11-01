"""Application services enforcing tenant and project access checks."""
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.storage.models import Document, Project, Tenant, Workspace
from app.storage.repositories import DocumentRepository, ProjectRepository, TenantRepository


class AccessDeniedError(PermissionError):
    """Raised when a principal is not authorized for a scoped resource."""


class ResourceNotFoundError(LookupError):
    """Raised when a scoped resource does not exist."""


class TenantService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)

    def get(self, tenant_id: UUID, user_id: UUID) -> Tenant:
        if self.tenants.active_membership(tenant_id, user_id) is None:
            raise ResourceNotFoundError("Tenant not found")
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise ResourceNotFoundError("Tenant not found")
        return tenant

    def create(self, name: str, owner_user_id: UUID) -> Tenant:
        tenant = Tenant(id=uuid4(), name=name, status="active")
        self.tenants.add(tenant)
        # Membership is created in the same transaction as the tenant.
        from app.storage.models import Membership
        self.session.add(
            Membership(
                id=uuid4(), tenant_id=tenant.id, user_id=owner_user_id,
                role="owner", status="active",
            )
        )
        self.session.flush()
        return tenant


class ProjectService:
    TENANT_ADMIN_ROLES = {"owner", "tenant_admin"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.projects = ProjectRepository(session)

    def get(self, tenant_id: UUID, project_id: UUID, user_id: UUID) -> Project:
        if self.tenants.active_membership(tenant_id, user_id) is None:
            raise ResourceNotFoundError("Project not found")
        if self.projects.active_membership(tenant_id, project_id, user_id) is None:
            raise ResourceNotFoundError("Project not found")
        project = self.projects.get(tenant_id, project_id)
        if project is None:
            raise ResourceNotFoundError("Project not found")
        return project

    def list(self, tenant_id: UUID, user_id: UUID) -> list[Project]:
        if self.tenants.active_membership(tenant_id, user_id) is None:
            raise ResourceNotFoundError("Tenant not found")
        # Return only projects for which the caller has an active project grant.
        from sqlalchemy import select
        from app.storage.models import ProjectMembership
        return list(
            self.session.scalars(
                select(Project)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .where(
                    Project.tenant_id == tenant_id,
                    ProjectMembership.tenant_id == tenant_id,
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.status == "active",
                )
                .order_by(Project.name)
            )
        )

    def create(
        self, tenant_id: UUID, user_id: UUID, *, name: str,
        code: str | None = None, workspace_id: UUID | None = None,
        description: str | None = None,
    ) -> Project:
        membership = self.tenants.active_membership(tenant_id, user_id)
        if membership is None or membership.role not in self.TENANT_ADMIN_ROLES:
            raise AccessDeniedError("Tenant administrator role is required to create projects")
        if workspace_id is not None:
            from sqlalchemy import select
            workspace = self.session.scalar(
                select(Workspace).where(
                    Workspace.id == workspace_id, Workspace.tenant_id == tenant_id
                )
            )
            if workspace is None:
                raise ResourceNotFoundError("Workspace not found in tenant")
        project = Project(
            id=uuid4(), tenant_id=tenant_id, workspace_id=workspace_id,
            code=code, name=name, description=description, status="active",
            project_metadata={},
        )
        self.projects.add(project)
        from app.storage.models import ProjectMembership
        self.session.add(
            ProjectMembership(
                id=uuid4(), tenant_id=tenant_id, project_id=project.id,
                user_id=user_id, role="project_manager", status="active",
            )
        )
        self.session.flush()
        return project


class DocumentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.tenants = TenantRepository(session)
        self.documents = DocumentRepository(session)

    def _require_project_access(self, tenant_id: UUID, project_id: UUID, user_id: UUID) -> None:
        if self.tenants.active_membership(tenant_id, user_id) is None:
            raise ResourceNotFoundError("Project not found")
        if self.projects.active_membership(tenant_id, project_id, user_id) is None:
            # Do not reveal whether an inaccessible project exists.
            raise ResourceNotFoundError("Project not found")

    def get(
        self, tenant_id: UUID, project_id: UUID, document_id: UUID, user_id: UUID
    ) -> Document:
        self._require_project_access(tenant_id, project_id, user_id)
        document = self.documents.get(tenant_id, project_id, document_id)
        if document is None:
            raise ResourceNotFoundError("Document not found")
        return document

    def list(self, tenant_id: UUID, project_id: UUID, user_id: UUID) -> list[Document]:
        self._require_project_access(tenant_id, project_id, user_id)
        return self.documents.list_for_project(tenant_id, project_id)

    def create(
        self, tenant_id: UUID, project_id: UUID, user_id: UUID, *,
        title: str, document_type: str | None = None,
    ) -> Document:
        self._require_project_access(tenant_id, project_id, user_id)
        if self.projects.get(tenant_id, project_id) is None:
            raise ResourceNotFoundError("Project not found")
        document = Document(
            id=uuid4(), tenant_id=tenant_id, project_id=project_id,
            title=title, document_type=document_type, status="active",
        )
        self.documents.add(document)
        return document
