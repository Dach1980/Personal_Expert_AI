"""PDF page rendering and OCR enrichment tests."""
from __future__ import annotations

import json

import pymupdf as fitz

from app.processing import pdf_enrichment
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
    assert payload["combined_text"] == payload["native_text"].strip()
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


def test_ocr_deduplication_uses_geometry_not_page_wide_word_presence(monkeypatch):
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "Valve")
    native_word = page.get_text("words")[0]
    native_bbox = [round(value) for value in native_word[:4]]
    source = document.tobytes()
    document.close()

    def fake_ocr(_image: bytes, *, language: str, config: str):
        return {
            "available": True,
            "engine": "test",
            "version": "test-1",
            "language": language,
            "word_count": 2,
            "text": "Valve\nValve",
            "words": [
                {
                    "text": "Valve", "confidence": 99.0,
                    "bbox_px": native_bbox, "block": 1, "paragraph": 1, "line": 1,
                },
                {
                    "text": "Valve", "confidence": 98.0,
                    "bbox_px": [250, 250, 280, 265],
                    "block": 1, "paragraph": 1, "line": 2,
                },
            ],
        }

    monkeypatch.setattr(pdf_enrichment, "_ocr_image", fake_ocr)
    result = enrich_pdf(source, extract_pdf(source), dpi=72)
    payload = json.loads(next(
        item.content for item in result.fragments if item.fragment_type == "structured_page"
    ) or "{}")

    assert payload["ocr_text"] == "Valve"
    assert len(payload["ocr_words"]) == 1
    assert payload["ocr_words"][0]["bbox_pdf_points"] == [250.0, 250.0, 280.0, 265.0]
    assert payload["combined_text"] == "Valve\nValve"


def test_spatial_duplicate_requires_same_token_and_overlapping_box():
    native = [("valve", (10.0, 10.0, 40.0, 25.0))]

    assert pdf_enrichment._is_spatial_duplicate(
        "Valve", (11.0, 11.0, 39.0, 24.0), native
    )
    assert not pdf_enrichment._is_spatial_duplicate(
        "Valve", (200.0, 200.0, 230.0, 215.0), native
    )
    assert not pdf_enrichment._is_spatial_duplicate(
        "Pump", (11.0, 11.0, 39.0, 24.0), native
    )
