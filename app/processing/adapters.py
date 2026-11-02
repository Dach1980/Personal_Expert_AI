"""Format adapters producing normalized, provenance-preserving document fragments."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

MAX_FRAGMENTS = 200_000
MAX_EMBEDDED_ASSET_BYTES = 25 * 1024 * 1024
MAX_EMBEDDED_ASSETS = 2_000


@dataclass(slots=True)
class Fragment:
    fragment_type: str
    locator: dict[str, Any]
    content: str | None
    content_hash: str
    extraction_method: str
    extractor_version: str
    quality: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddedAsset:
    name: str
    media_type: str
    data: bytes
    locator: dict[str, Any]


@dataclass(slots=True)
class ExtractionResult:
    format: str
    parser_name: str
    parser_version: str
    fragments: list[Fragment]
    assets: list[EmbeddedAsset]
    metadata: dict[str, Any]


def _fragment(
    fragments: list[Fragment], fragment_type: str, locator: dict[str, Any],
    content: str | None, method: str, version: str, quality: dict[str, Any] | None = None,
    *, binary_digest: str | None = None,
) -> None:
    if len(fragments) >= MAX_FRAGMENTS:
        raise ValueError(f"Document exceeds the {MAX_FRAGMENTS} fragment safety limit")
    digest = binary_digest or hashlib.sha256((content or "").encode("utf-8")).hexdigest()
    fragments.append(Fragment(
        fragment_type=fragment_type, locator=locator, content=content,
        content_hash=digest, extraction_method=method, extractor_version=version,
        quality=quality or {},
    ))


def _asset(assets: list[EmbeddedAsset], name: str, media_type: str, data: bytes,
           locator: dict[str, Any]) -> None:
    if not data:
        return
    if len(assets) >= MAX_EMBEDDED_ASSETS:
        raise ValueError(f"Document exceeds the {MAX_EMBEDDED_ASSETS} embedded asset limit")
    if len(data) > MAX_EMBEDDED_ASSET_BYTES:
        raise ValueError("An embedded asset exceeds the 25 MiB safety limit")
    assets.append(EmbeddedAsset(name, media_type, data, locator))


def extract_pdf(source: bytes) -> ExtractionResult:
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise RuntimeError("PDF adapter requires the 'processing' extra (PyMuPDF)") from exc

    fragments: list[Fragment] = []
    assets: list[EmbeddedAsset] = []
    document = fitz.open(stream=source, filetype="pdf")
    try:
        seen_images: set[int] = set()
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            page_text = page.get_text("text", sort=True)
            _fragment(
                fragments, "page", {"page": page_number, "width": page.rect.width,
                                    "height": page.rect.height, "rotation": page.rotation},
                page_text, "pymupdf-native-text", fitz.VersionBind,
                {"character_count": len(page_text), "has_text": bool(page_text.strip())},
            )
            structured = page.get_text("dict", sort=True)
            for block_index, block in enumerate(structured.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                lines = []
                for line in block.get("lines", []):
                    lines.append("".join(span.get("text", "") for span in line.get("spans", [])))
                text = "\n".join(lines).strip()
                if not text:
                    continue
                _fragment(
                    fragments, "text_block",
                    {"page": page_number, "block": block_index, "bbox": list(block.get("bbox", []))},
                    text, "pymupdf-native-text", fitz.VersionBind,
                    {"character_count": len(text)},
                )
            for image_info in page.get_images(full=True):
                xref = int(image_info[0])
                if xref in seen_images:
                    continue
                seen_images.add(xref)
                extracted = document.extract_image(xref)
                data = extracted.get("image", b"")
                ext = extracted.get("ext", "bin")
                mime = extracted.get("mime", "application/octet-stream")
                name = f"pdf-image-{xref}.{ext}"
                rects = [list(rect) for rect in page.get_image_rects(xref)]
                locator = {"page": page_number, "xref": xref, "rectangles": rects}
                _asset(assets, name, mime, data, locator)
                if data:
                    _fragment(
                        fragments, "image", locator, None, "pymupdf-image-extraction",
                        fitz.VersionBind, {"asset_name": name, "media_type": mime},
                        binary_digest=hashlib.sha256(data).hexdigest(),
                    )
        metadata = {
            "page_count": len(document),
            "metadata": {key: value for key, value in (document.metadata or {}).items() if value},
            "is_encrypted": bool(document.is_encrypted),
        }
    finally:
        document.close()
    return ExtractionResult("pdf", "PyMuPDF", fitz.VersionBind, fragments, assets, metadata)


def extract_docx(source: bytes) -> ExtractionResult:
    try:
        import docx
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("DOCX adapter requires the 'processing' extra (python-docx)") from exc

    document = Document(io.BytesIO(source))
    fragments: list[Fragment] = []
    assets: list[EmbeddedAsset] = []
    paragraph_index = 0
    for paragraph_index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if text:
            _fragment(
                fragments, "paragraph",
                {"paragraph": paragraph_index, "style": paragraph.style.name if paragraph.style else None},
                text, "python-docx", docx.__version__,
            )
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            for col_index, cell in enumerate(row.cells, start=1):
                text = "\n".join(p.text for p in cell.paragraphs).strip()
                if text:
                    _fragment(
                        fragments, "table_cell",
                        {"table": table_index, "row": row_index, "column": col_index},
                        text, "python-docx", docx.__version__,
                    )
    image_index = 0
    for rel_id, relationship in document.part.rels.items():
        if relationship.reltype.endswith("/image"):
            image_index += 1
            part = relationship.target_part
            data = part.blob
            content_type = part.content_type
            ext = content_type.split("/")[-1].replace("jpeg", "jpg")
            name = f"docx-image-{image_index}.{ext}"
            locator = {"relationship_id": rel_id, "part_name": str(part.partname)}
            _asset(assets, name, content_type, data, locator)
            _fragment(
                fragments, "image", locator, None, "python-docx-image-extraction",
                docx.__version__, {"asset_name": name, "media_type": content_type},
                binary_digest=hashlib.sha256(data).hexdigest(),
            )
    core = document.core_properties
    metadata = {
        "paragraph_count": len(document.paragraphs),
        "table_count": len(document.tables),
        "title": core.title, "author": core.author, "subject": core.subject,
    }
    return ExtractionResult("docx", "python-docx", docx.__version__, fragments, assets, metadata)


def extract_xlsx(source: bytes) -> ExtractionResult:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("XLSX adapter requires the 'processing' extra (openpyxl)") from exc

    workbook = openpyxl.load_workbook(io.BytesIO(source), data_only=False, read_only=False)
    fragments: list[Fragment] = []
    assets: list[EmbeddedAsset] = []
    sheet_summaries = []
    try:
        for sheet in workbook.worksheets:
            sheet_summaries.append({
                "name": sheet.title, "max_row": sheet.max_row, "max_column": sheet.max_column,
                "state": sheet.sheet_state,
            })
            for row in sheet.iter_rows():
                for cell in row:
                    value = cell.value
                    if value is None:
                        continue
                    text = str(value)
                    _fragment(
                        fragments, "spreadsheet_cell",
                        {"sheet": sheet.title, "cell": cell.coordinate, "row": cell.row,
                         "column": cell.column, "data_type": cell.data_type,
                         "number_format": cell.number_format},
                        text, "openpyxl-formula-preserving", openpyxl.__version__,
                        {"is_formula": cell.data_type == "f"},
                    )
            for merged in sheet.merged_cells.ranges:
                _fragment(
                    fragments, "merged_range",
                    {"sheet": sheet.title, "range": str(merged)}, str(merged),
                    "openpyxl", openpyxl.__version__,
                )
            for image_index, image in enumerate(getattr(sheet, "_images", []), start=1):
                data = image._data()
                anchor = image.anchor
                row = getattr(getattr(anchor, "_from", None), "row", None)
                col = getattr(getattr(anchor, "_from", None), "col", None)
                ext = getattr(image, "format", "png") or "png"
                name = f"xlsx-{sheet.title}-image-{image_index}.{ext}"
                locator = {"sheet": sheet.title, "row_zero_based": row, "column_zero_based": col}
                content_type = f"image/{'jpeg' if ext in {'jpg', 'jpeg'} else ext}"
                _asset(assets, name, content_type, data, locator)
                _fragment(
                    fragments, "image", locator, None, "openpyxl-image-extraction",
                    openpyxl.__version__, {"asset_name": name, "media_type": content_type},
                    binary_digest=hashlib.sha256(data).hexdigest(),
                )
        metadata = {"sheet_count": len(workbook.worksheets), "sheets": sheet_summaries,
                    "calculation_mode": getattr(workbook.calculation, "calcMode", None)}
    finally:
        workbook.close()
    return ExtractionResult("xlsx", "openpyxl", openpyxl.__version__, fragments, assets, metadata)


def extract_pptx(source: bytes) -> ExtractionResult:
    try:
        import pptx
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError("PPTX adapter requires the 'processing' extra (python-pptx)") from exc

    presentation = Presentation(io.BytesIO(source))
    fragments: list[Fragment] = []
    assets: list[EmbeddedAsset] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        for shape_index, shape in enumerate(slide.shapes, start=1):
            locator = {
                "slide": slide_index, "shape": shape_index, "shape_id": shape.shape_id,
                "left_emu": shape.left, "top_emu": shape.top,
                "width_emu": shape.width, "height_emu": shape.height,
            }
            if getattr(shape, "has_text_frame", False):
                text = "\n".join(p.text for p in shape.text_frame.paragraphs).strip()
                if text:
                    _fragment(fragments, "slide_text", locator, text, "python-pptx", pptx.__version__)
            if getattr(shape, "has_table", False):
                for row_index, row in enumerate(shape.table.rows, start=1):
                    for col_index, cell in enumerate(row.cells, start=1):
                        text = cell.text.strip()
                        if text:
                            _fragment(
                                fragments, "slide_table_cell",
                                {**locator, "row": row_index, "column": col_index},
                                text, "python-pptx", pptx.__version__,
                            )
            if getattr(shape, "shape_type", None) == 13:
                image = shape.image
                data = image.blob
                ext = image.ext
                name = f"pptx-slide-{slide_index}-shape-{shape_index}.{ext}"
                media_type = image.content_type
                _asset(assets, name, media_type, data, locator)
                _fragment(
                    fragments, "image", locator, None, "python-pptx-image-extraction",
                    pptx.__version__, {"asset_name": name, "media_type": media_type},
                    binary_digest=hashlib.sha256(data).hexdigest(),
                )
    metadata = {
        "slide_count": len(presentation.slides),
        "slide_width_emu": presentation.slide_width,
        "slide_height_emu": presentation.slide_height,
    }
    return ExtractionResult("pptx", "python-pptx", pptx.__version__, fragments, assets, metadata)


def extract_document(filename: str, source: bytes) -> ExtractionResult:
    """Dispatch by the already-validated filename extension, never by client MIME."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    adapters = {"pdf": extract_pdf, "docx": extract_docx, "xlsx": extract_xlsx, "pptx": extract_pptx}
    try:
        adapter = adapters[extension]
    except KeyError as exc:
        raise ValueError(f"Unsupported document extension: {extension or '(none)'}") from exc
    return adapter(source)
