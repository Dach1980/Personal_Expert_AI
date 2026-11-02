import zipfile
from pathlib import Path

import pytest

from app.storage.document_validation import (
    UnsupportedDocumentError,
    detect_document_type,
)


def test_pdf_is_detected_from_signature_not_client_mime(tmp_path: Path):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-1.7\nnot-a-complete-pdf-but-a-recognizable-header")
    assert detect_document_type(path, "source.pdf") == "application/pdf"


@pytest.mark.parametrize(
    ("filename", "member", "expected"),
    [
        ("plan.docx", "word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("schedule.xlsx", "xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("slides.pptx", "ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ],
)
def test_office_type_is_detected_from_package_contents(tmp_path, filename, member, expected):
    path = tmp_path / filename
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(member, "<document/>")
    assert detect_document_type(path, filename) == expected


def test_mismatched_extension_and_package_are_rejected(tmp_path):
    path = tmp_path / "wrong.docx"
    path.write_bytes(b"%PDF-1.7\n")
    with pytest.raises(UnsupportedDocumentError):
        detect_document_type(path, "wrong.docx")


def test_unsafe_windows_archive_paths_are_rejected(tmp_path):
    path = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("..\\outside.txt", "unsafe")
    with pytest.raises(UnsupportedDocumentError):
        detect_document_type(path, "unsafe.docx")
