"""Shared API dependency exports."""
from functools import lru_cache

from app.api.auth import Principal, get_current_principal
from app.storage.config import max_upload_bytes, storage_root
from app.storage.database import get_session_factory
from app.storage.file_store import LocalFileStore
from app.storage.upload_service import DocumentUploadService


@lru_cache(maxsize=1)
def get_document_upload_service() -> DocumentUploadService:
    """Build one process-local upload service with a private local storage root."""
    return DocumentUploadService(
        get_session_factory(),
        LocalFileStore(storage_root()),
        max_bytes=max_upload_bytes(),
    )


__all__ = ["Principal", "get_current_principal", "get_document_upload_service"]
