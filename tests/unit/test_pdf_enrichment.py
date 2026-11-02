"""PDF page rendering and OCR enrichment tests."""
from __future__ import annotations

import json

import pymupdf as fitz

from app.processing.adapters import extract_pdf
from app.processing.pdf_enrichment import enrich_pdf


def _pdf_with_native_text() -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "Native PDF text with sufficient content for extraction.")
    output = document.tobytes()
    document.close()
    return output


def test_pdf_enrichment_renders_pages_and_builds_structured_model():
    source = _pdf_with_native_text()
    result = enrich_pdf(source, extract_pdf(source), dpi=120)
    render = next(item for item in result.assets if item.name.endswith(".png"))
    page_model = next(item for item in result.fragments if item.fragment_type == "structured_page")
    payload = json.loads(page_model.content or "{}")

    assert render.media_type == "image/png"
    assert render.locator["page"] == 1
    assert payload["geometry"]["render_dpi"] == 120
    assert payload["native_text"].startswith("Native PDF text")
    assert payload["native_text_quality"]["ocr_recommended"] is False
    assert result.metadata["page_rendering"]["rendered_page_count"] == 1
    assert any(item.fragment_type == "page_render" for item in result.fragments)


def test_pdf_enrichment_handles_scan_without_tesseract_as_optional():
    document = fitz.open()
    document.new_page()
    source = document.tobytes()
    document.close()

    result = enrich_pdf(source, extract_pdf(source), dpi=100)
    payload = json.loads(next(
        item.content for item in result.fragments if item.fragment_type == "structured_page"
    ) or "{}")
    assert payload["native_text_quality"]["ocr_recommended"] is True
    assert "ocr" in payload
    assert len([item for item in result.assets if item.media_type == "image/png"]) == 1
