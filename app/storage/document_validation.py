"""Content-based validation for supported project document formats."""

from __future__ import annotations

import zipfile
from pathlib import Path


class UnsupportedDocumentError(ValueError):
    """The uploaded bytes do not match a supported document format."""


OFFICE_TYPES = {
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "word/document.xml"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xl/workbook.xml"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "ppt/presentation.xml"),
}


def detect_document_type(path: Path, original_filename: str) -> str:
    """Determine MIME from file signatures and package structure, never from client MIME."""
    suffix = Path(original_filename).suffix.lower()
    with path.open("rb") as stream:
        header = stream.read(1024)
    if suffix == ".pdf" and b"%PDF-" in header:
        return "application/pdf"
    if suffix not in OFFICE_TYPES or not zipfile.is_zipfile(path):
        raise UnsupportedDocumentError("Unsupported or mismatched document format")

    media_type, required_member = OFFICE_TYPES[suffix]
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or required_member not in names:
                raise UnsupportedDocumentError("Office package does not match its filename")
            if len(names) > 20_000:
                raise UnsupportedDocumentError("Office package contains too many entries")
            total_uncompressed = 0
            for item in archive.infolist():
                if item.filename.startswith("/") or ".." in Path(item.filename.replace("\\", "/")).parts:
                    raise UnsupportedDocumentError("Unsafe path in Office package")
                total_uncompressed += item.file_size
                if total_uncompressed > 1024 * 1024 * 1024:
                    raise UnsupportedDocumentError("Office package expands beyond the safety limit")
                if item.file_size > 0 and item.compress_size == 0:
                    raise UnsupportedDocumentError("Invalid compressed Office package")
                if item.compress_size and item.file_size / item.compress_size > 500:
                    raise UnsupportedDocumentError("Office package compression ratio is unsafe")
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsupportedDocumentError("Invalid Office document package") from exc
    return media_type
