"""Local document storage configuration."""

from __future__ import annotations

import os
from pathlib import Path


def storage_root() -> Path:
    """Resolve a local absolute storage root; no network-backed storage is supported."""
    raw = os.getenv("DOCUMENT_STORAGE_ROOT", "./var/documents")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def max_upload_bytes() -> int:
    value = int(os.getenv("DOCUMENT_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
    if value < 1:
        raise RuntimeError("DOCUMENT_MAX_UPLOAD_BYTES must be positive")
    return value
