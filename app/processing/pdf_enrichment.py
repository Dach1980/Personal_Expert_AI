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
    MAX_EMBEDDED_ASSET_BYTES,
    MAX_EMBEDDED_ASSETS,
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
    import unicodedata

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _native_word_regions(page: Any) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Return native PDF words with their own page-space bounding boxes."""
    regions: list[tuple[str, tuple[float, float, float, float]]] = []
    for item in page.get_text("words", sort=True):
        if len(item) < 5:
            continue
        token = _normalise(str(item[4]))
        if token:
            regions.append((token, (float(item[0]), float(item[1]), float(item[2]), float(item[3]))))
    return regions


def _overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    smallest = min(first_area, second_area)
    return intersection / smallest if smallest > 0 else 0.0


def _pixel_bbox_to_pdf_points(
    bbox_px: tuple[float, float, float, float],
    *,
    page: Any,
    pixmap: Any,
) -> tuple[float, float, float, float]:
    """Map rendered (rotation-aware) pixel bounds to unrotated PDF page points."""
    import pymupdf

    scale_x = float(page.rect.width) / pixmap.width
    scale_y = float(page.rect.height) / pixmap.height
    x0, y0, x1, y1 = bbox_px
    rotated_corners = (
        (x0 * scale_x, y0 * scale_y),
        (x1 * scale_x, y0 * scale_y),
        (x0 * scale_x, y1 * scale_y),
        (x1 * scale_x, y1 * scale_y),
    )
    unrotated = [
        pymupdf.Point(x, y) * page.derotation_matrix
        for x, y in rotated_corners
    ]
    return (
        min(point.x for point in unrotated),
        min(point.y for point in unrotated),
        max(point.x for point in unrotated),
        max(point.y for point in unrotated),
    )


def _is_spatial_duplicate(
    candidate: str,
    bbox_pdf_points: tuple[float, float, float, float],
    native_words: list[tuple[str, tuple[float, float, float, float]]],
) -> bool:
    """Deduplicate only the same token at the same physical page location."""
    candidate_norm = _normalise(candidate)
    if not candidate_norm:
        return False
    return any(
        candidate_norm == native_token and _overlap_ratio(bbox_pdf_points, native_bbox) >= 0.5
        for native_token, native_bbox in native_words
    )


def _lines_from_ocr_words(words: list[dict[str, Any]]) -> str:
    grouped: dict[tuple[int, int, int], list[str]] = {}
    for word in words:
        key = (int(word.get("block", 0)), int(word.get("paragraph", 0)), int(word.get("line", 0)))
        grouped.setdefault(key, []).append(str(word["text"]))
    return "\n".join(" ".join(parts) for parts in grouped.values() if parts)


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
            ocr_text = ""
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
                    native_words = _native_word_regions(page)
                    unique_words: list[dict[str, Any]] = []
                    for raw_word in ocr_result["words"]:
                        word = dict(raw_word)
                        bbox_px = tuple(float(value) for value in word.pop("bbox_px"))
                        bbox_pdf = _pixel_bbox_to_pdf_points(
                            bbox_px, page=page, pixmap=pixmap,
                        )
                        if _is_spatial_duplicate(word["text"], bbox_pdf, native_words):
                            continue
                        word["bbox_pdf_points"] = [round(value, 3) for value in bbox_pdf]
                        unique_words.append(word)
                    ocr_text = _lines_from_ocr_words(unique_words)
                    ocr_result["text"] = ocr_text
                    ocr_result["word_count"] = len(unique_words)
                    if ocr_text:
                        digest = hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()
                        new_fragments.append(Fragment(
                            "ocr_text", {"page": page_number, "coordinate_space": "pdf-points-unrotated"},
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
                "ocr_text": ocr_text,
                "combined_text": "\n".join(part for part in (native_text.strip(), ocr_text.strip()) if part),
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

    embedded_ocr_count = 0
    for asset in result.assets:
        if not asset.media_type.startswith("image/"):
            continue
        inspected = _ocr_image(asset.data, language=ocr_language, config=ocr_config)
        if not inspected.get("available"):
            continue
        embedded_ocr_count += 1
        image_text = str(inspected.get("text", "")).strip()
        if not image_text:
            continue
        digest = hashlib.sha256(image_text.encode("utf-8")).hexdigest()
        new_fragments.append(Fragment(
            "image_ocr",
            {**asset.locator, "asset_name": asset.name,
             "coordinate_space": "embedded-image-pixels"},
            image_text, digest, "tesseract-image-ocr",
            str(inspected.get("version", "unknown")),
            {
                "language": ocr_language,
                "word_count": inspected.get("word_count", 0),
                "words": inspected.get("words", []),
            },
        ))

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
        "embedded_images_ocr_inspected": embedded_ocr_count,
    }
    return result
