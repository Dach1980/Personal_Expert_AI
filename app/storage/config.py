"""Local document storage configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def storage_root() -> Path:
    """Resolve a private per-user local data directory unless explicitly configured."""
    configured = os.getenv("DOCUMENT_STORAGE_ROOT")
    if configured:
        root = Path(configured).expanduser()
    elif os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        root = base / "PersonalExpertAI" / "documents"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "PersonalExpertAI" / "documents"
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        root = base / "personal-expert-ai" / "documents"
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def max_upload_bytes() -> int:
    value = int(os.getenv("DOCUMENT_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
    if value < 1:
        raise RuntimeError("DOCUMENT_MAX_UPLOAD_BYTES must be positive")
    return value
