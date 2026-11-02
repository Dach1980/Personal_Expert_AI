"""Local PDF page rendering, OCR enrichment and unified page models.

OCR is optional at runtime: install the `ocr` extra and the Tesseract executable.
No remote service or cloud model is called by this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any

from app.processing.adapters import (
    MAX_EMBEDDED_ASSETS,
    MAX_EMBEDDED_ASSET_BYTES,
    EmbeddedAsset,
    ExtractionResult,
    Fragment,
)

DEFAULT_DPI = 180
MAX_DPI = 300
MAX_RENDERED_PAGE_BYTES = 20 * 1024 * 1024
MIN_NATIVE_CHARACTERS = 24
MIN_NATIVE_CHARACTERS_PER_AREA = 0.00002


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _is_duplicate(candidate: str, native_text: str) -> bool:
    candidate_norm = _normalise(candidate)
    native_norm = _normalise(native_text)
    if not candidate_norm or not native_norm:
        return False
    if candidate_norm in native_norm:
        return True
    # OCR often changes a few glyphs. Avoid fuzzy matching short fragments.
    if len(candidate_norm) >= 40 and len(native_norm) >= 40:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, candidate_norm, native_norm).ratio() >= 0.94
    return False


def _ocr_image(image_bytes: bytes, *, language: str, config: str) -> dict[str, Any]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return {"available": False, "reason": "install the optional 'ocr' dependencies"}
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            data = pytesseract.image_to_data(
                image, lang=language, config=config,
                output_type=pytesseract.Output.DICT,
            )
    except (pytesseract.TesseractNotFoundError, OSError) as exc:
        return {"available": False, "reason": f"Tesseract is unavailable: {exc}"}
    except pytesseract.TesseractError as exc:
        return {"available": False, "reason": f"Tesseract OCR failed: {exc}"}

    words: list[dict[str, Any]] = []
    grouped: dict[tuple[int, int, int], list[str]] = {}
    for index, raw_text in enumerate(data.get("text", [])):
        word = str(raw_text).strip()
        try:
            confidence = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            confidence = -1.0
        if not word or confidence < 0:
            continue
        left, top = int(data["left"][index]), int(data["top"][index])
        width, height = int(data["width"][index]), int(data["height"][index])
        block, paragraph, line = (
            int(data["block_num"][index]), int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        words.append({
            "text": word, "confidence": confidence,
            "bbox_px": [left, top, left + width, top + height],
            "block": block, "paragraph": paragraph, "line": line,
        })
        grouped.setdefault((block, paragraph, line), []).append(word)

    lines = [" ".join(parts) for parts in grouped.values() if parts]
    return {
        "available": True, "engine": "Tesseract",
        "version": str(pytesseract.get_tesseract_version()),
        "language": language, "word_count": len(words),
        "text": "\n".join(lines), "words": words,
    }


def enrich_pdf(
    source: bytes,
    result: ExtractionResult,
    *,
    dpi: int = DEFAULT_DPI,
    ocr_language: str = "rus+eng",
    ocr_config: str = "--psm 3",
) -> ExtractionResult:
    """Render every PDF page and attach OCR/page-model outputs to an extraction result."""
    if result.format != "pdf":
        return result
    if not 72 <= dpi <= MAX_DPI:
        raise ValueError(f"PDF render DPI must be between 72 and {MAX_DPI}")

    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise RuntimeError("PDF enrichment requires PyMuPDF") from exc

    document = fitz.open(stream=source, filetype="pdf")
    new_assets: list[EmbeddedAsset] = []
    new_fragments: list[Fragment] = []
    page_models: list[dict[str, Any]] = []
    render_bytes_total = 0
    ocr_available: bool | None = None
    try:
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
            rendered = pixmap.tobytes("png")
            if len(rendered) > MAX_RENDERED_PAGE_BYTES:
                raise ValueError(f"Rendered page {page_number} exceeds the 20 MiB safety limit")
            render_bytes_total += len(rendered)
            if render_bytes_total > 200 * 1024 * 1024:
                raise ValueError("Rendered PDF pages exceed the 200 MiB per-document safety limit")
            render_name = f"pdf-page-{page_number:05d}-{dpi}dpi.png"
            render_locator = {
                "page": page_number, "dpi": dpi, "width_px": pixmap.width,
                "height_px": pixmap.height, "coordinate_space": "pixel-top-left",
            }
            new_assets.append(EmbeddedAsset(
                render_name, "image/png", rendered, render_locator,
            ))
            render_digest = hashlib.sha256(rendered).hexdigest()
            new_fragments.append(Fragment(
                "page_render", render_locator, None, render_digest,
                "pymupdf-page-render", fitz.VersionBind,
                {"asset_name": render_name, "media_type": "image/png"},
            ))

            native_text = page.get_text("text", sort=True)
            area = max(float(page.rect.width * page.rect.height), 1.0)
            native_density = len(native_text.strip()) / area
            needs_ocr = (
                len(native_text.strip()) < MIN_NATIVE_CHARACTERS
                or native_density < MIN_NATIVE_CHARACTERS_PER_AREA
            )
            ocr_result: dict[str, Any] = {
                "available": False, "reason": "not_required",
                "text": "", "words": [],
            }
            if needs_ocr:
                ocr_result = _ocr_image(
                    rendered, language=ocr_language, config=ocr_config,
                )
                ocr_available = bool(ocr_result.get("available"))
                if ocr_result.get("available"):
                    scale_x = float(page.rect.width) / pixmap.width
                    scale_y = float(page.rect.height) / pixmap.height
                    unique_words = [
                        word for word in ocr_result["words"]
                        if not _is_duplicate(word["text"], native_text)
                    ]
                    for word in unique_words:
                        x0, y0, x1, y1 = word.pop("bbox_px")
                        word["bbox_pdf_points"] = [
                            round(x0 * scale_x, 3), round(y0 * scale_y, 3),
                            round(x1 * scale_x, 3), round(y1 * scale_y, 3),
                        ]
                    ocr_text = "\n".join(
                        line for line in ocr_result.get("text", "").splitlines()
                        if not _is_duplicate(line, native_text)
                    )
                    if ocr_text:
                        digest = hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()
                        new_fragments.append(Fragment(
                            "ocr_text", {"page": page_number, "coordinate_space": "pdf-points"},
                            ocr_text, digest, "tesseract-ocr", str(ocr_result.get("version", "unknown")),
                            {"language": ocr_language, "word_count": len(unique_words),
                             "mean_confidence": round(
                                 sum(w["confidence"] for w in unique_words) / len(unique_words), 2
                             ) if unique_words else None},
                        ))
                    ocr_result["words"] = unique_words

            page_model = {
                "schema_version": 1, "page": page_number,
                "geometry": {
                    "width_points": float(page.rect.width),
                    "height_points": float(page.rect.height),
                    "rotation": page.rotation,
                    "render_width_px": pixmap.width,
                    "render_height_px": pixmap.height,
                    "render_dpi": dpi,
                },
                "native_text": native_text,
                "native_text_quality": {
                    "character_count": len(native_text.strip()),
                    "character_density_per_point2": round(native_density, 8),
                    "ocr_recommended": needs_ocr,
                },
                "ocr": {
                    key: value for key, value in ocr_result.items()
                    if key not in {"words"}
                },
                "ocr_words": ocr_result.get("words", []),
                "text_source_policy": "native_text_preferred; non_duplicate_ocr_appended",
                "render_asset": {
                    "name": render_name, "sha256": render_digest,
                    "media_type": "image/png",
                },
            }
            serialized = json.dumps(
                page_model, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            new_fragments.append(Fragment(
                "structured_page", {"page": page_number}, serialized,
                hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                "pdf-page-model", "1",
                {"schema_version": 1, "ocr_attempted": needs_ocr},
            ))
            page_models.append(page_model)
    finally:
        document.close()

    if len(result.assets) + len(new_assets) > MAX_EMBEDDED_ASSETS:
        raise ValueError("PDF rendering exceeds the embedded asset count safety limit")
    if any(len(asset.data) > MAX_EMBEDDED_ASSET_BYTES for asset in new_assets):
        raise ValueError("A rendered PDF page exceeds the embedded asset size safety limit")

    result.assets.extend(new_assets)
    result.fragments.extend(new_fragments)
    result.metadata["page_rendering"] = {
        "dpi": dpi, "rendered_page_count": len(new_assets),
        "rendered_bytes": render_bytes_total,
        "ocr_language": ocr_language, "ocr_engine_available": ocr_available,
        "ocr_pages": sum(1 for item in page_models if item["native_text_quality"]["ocr_recommended"]),
        "page_model_schema_version": 1,
    }
    return result
