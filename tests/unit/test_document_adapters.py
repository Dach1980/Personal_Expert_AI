"""Format adapter tests using generated document fixtures."""
import base64
from io import BytesIO

import pymupdf as fitz
from docx import Document
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from pptx import Presentation
from pptx.util import Inches

from app.processing.adapters import extract_document

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII="
)


def test_pdf_page_text_and_bbox():
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=400)
    page.insert_text((40, 60), "PDF page one text")
    data = pdf.tobytes()
    pdf.close()
    result = extract_document("drawing.pdf", data)
    page_fragment = next(x for x in result.fragments if x.fragment_type == "page")
    block = next(x for x in result.fragments if x.fragment_type == "text_block")
    assert page_fragment.locator["page"] == 1
    assert "PDF page one text" in page_fragment.content
    assert len(block.locator["bbox"]) == 4
    assert result.metadata["page_count"] == 1


def test_docx_paragraph_table_and_image():
    doc = Document()
    doc.add_heading("DOCX title", level=1)
    doc.add_paragraph("Paragraph with provenance")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Cell A"
    table.cell(0, 1).text = "Cell B"
    doc.add_picture(BytesIO(PNG), width=Inches(0.1))
    output = BytesIO()
    doc.save(output)
    result = extract_document("spec.docx", output.getvalue())
    assert any(x.content == "Paragraph with provenance" for x in result.fragments)
    assert {x.content for x in result.fragments if x.fragment_type == "table_cell"} >= {"Cell A", "Cell B"}
    assert len(result.assets) == 1


def test_xlsx_formulas_merged_ranges_and_images():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Design"
    sheet["A1"] = "Quantity"
    sheet["B1"] = "=2+3"
    sheet.merge_cells("A3:B3")
    sheet["A3"] = "Merged"
    sheet.add_image(XLImage(BytesIO(PNG)), "D1")
    output = BytesIO()
    workbook.save(output)
    result = extract_document("schedule.xlsx", output.getvalue())
    formula = next(x for x in result.fragments if x.locator.get("cell") == "B1")
    assert formula.content == "=2+3" and formula.quality["is_formula"]
    assert any(x.fragment_type == "merged_range" for x in result.fragments)
    assert len(result.assets) == 1


def test_pptx_slide_text_table_and_image():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    shape.text = "Slide heading"
    table = slide.shapes.add_table(1, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "Table A"
    table.cell(0, 1).text = "Table B"
    slide.shapes.add_picture(BytesIO(PNG), Inches(1), Inches(4), width=Inches(0.1))
    output = BytesIO()
    presentation.save(output)
    result = extract_document("presentation.pptx", output.getvalue())
    assert result.metadata["slide_count"] == 1
    assert any(x.content == "Slide heading" for x in result.fragments)
    assert {x.content for x in result.fragments if x.fragment_type == "slide_table_cell"} >= {"Table A", "Table B"}
    assert len(result.assets) == 1
