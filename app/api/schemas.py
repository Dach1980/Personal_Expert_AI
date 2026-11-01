"""Request and response schemas for the first authenticated domain endpoints."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    code: str | None = Field(default=None, max_length=100)
    workspace_id: UUID | None = None
    description: str | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    name: str
    code: str | None
    status: str


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    document_type: str | None = Field(default=None, max_length=80)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    title: str
    document_type: str | None
    status: str
