"""Request and response schemas for the first authenticated domain endpoints."""
from datetime import datetime
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


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    status: str



class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    status: str
    uploaded_at: datetime


class SourceFragmentRead(BaseModel):
    id: UUID
    document_version_id: UUID
    fragment_type: str
    locator: dict[str, object]
    excerpt: str | None
    content_hash: str
    extraction_method: str | None
    extractor_version: str | None
    quality: dict[str, object]
    created_at: datetime


class ProcessingArtifactRead(BaseModel):
    id: UUID
    document_version_id: UUID
    artifact_type: str
    media_type: str | None
    size_bytes: int | None
    locator: dict[str, object]
    checksum_sha256: str | None
    created_at: datetime


class KnowledgeItemRead(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    canonical_key: str | None
    canonical_value: dict[str, object]
    status: str
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class ReviewCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    document_version_id: UUID | None = None
    scope: str = Field(default="project", pattern="^(project|document_version)$")
    assigned_to: UUID | None = None
    summary: str | None = None


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    document_version_id: UUID | None
    title: str
    scope: str
    status: str
    created_by: UUID
    assigned_to: UUID | None
    summary: str | None
    created_at: datetime
    updated_at: datetime


class FindingCreate(BaseModel):
    classification: str = Field(pattern="^(violation|evidence_gap|inconsistency|observation)$")
    severity: str = Field(pattern="^(info|minor|major|critical)$")
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1)
    normative_reference: str | None = Field(default=None, max_length=500)
    requirement_reference: str | None = Field(default=None, max_length=500)
    recommendation: str | None = None


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    review_id: UUID
    classification: str
    severity: str
    status: str
    title: str
    description: str
    normative_reference: str | None
    requirement_reference: str | None
    recommendation: str | None
    created_by: UUID
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EvidenceCreate(BaseModel):
    evidence_type: str = Field(pattern="^(source_fragment|note|external_reference)$")
    relation: str = Field(default="supports", pattern="^(supports|contradicts|context)$")
    source_fragment_id: UUID | None = None
    locator: dict[str, object] = Field(default_factory=dict)
    excerpt: str | None = None
    reference_label: str | None = Field(default=None, max_length=500)
    reference_uri: str | None = Field(default=None, max_length=2000)


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    finding_id: UUID
    evidence_type: str
    relation: str
    source_fragment_id: UUID | None
    locator: dict[str, object]
    excerpt: str | None
    reference_label: str | None
    reference_uri: str | None
    created_by: UUID
    created_at: datetime


class ReviewStatusUpdate(BaseModel):
    status: str = Field(pattern="^(draft|in_progress|completed|approved|rejected|cancelled)$")
    summary: str | None = None


class FindingStatusUpdate(BaseModel):
    status: str = Field(pattern="^(open|accepted|rejected|resolved|waived)$")
