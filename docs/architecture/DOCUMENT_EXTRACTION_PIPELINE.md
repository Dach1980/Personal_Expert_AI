# Document extraction pipeline

The worker consumes only durable \`ProcessingRun\` rows. Before parsing it opens the original
through \`LocalFileStore.open_verified\`, verifying SHA-256 and byte size against the immutable
\`DocumentVersion\` record. Parser output is persisted under the same private storage root.

## Supported adapters

| Format | Adapter | Extracted structure |
|---|---|---|
| PDF | PyMuPDF | Page text, page dimensions/rotation, text blocks with PDF point bounding boxes, embedded images and image rectangles |
| DOCX | python-docx | Paragraphs/styles, table cells, embedded image relationships |
| XLSX | openpyxl | Worksheets, cell coordinates and values, formula strings, merged ranges, embedded worksheet images |
| PPTX | python-pptx | Slide text, text shape geometry, table cells, embedded images |

XLSX is opened with \`data_only=False\`; formulas remain formulas, rather than being replaced
with cached calculated values. Complex constructs such as nested tables, chart series,
comments, headers/footers, SmartArt, equations and CAD/vector content are not fully normalized.

## PDF rendering, OCR and structured pages

PDF pages are rendered locally with PyMuPDF at 180 DPI by default (configurable per
`ProcessingRun` manifest as `pdf.render_dpi`, range 72–300). PNG page images are stored as
checksummed processing artifacts; rendering is bounded to 20 MiB per page and 200 MiB per PDF.
The `structured_page` fragment contains page geometry, native text, text-density diagnostics,
render reference and OCR status. Pixel coordinates are retained for the render; OCR word boxes
are additionally converted to PDF points using the page/render scale.

OCR is an optional local capability. Install `pip install -e ".[database,processing,ocr]"` and
install the Tesseract executable separately on the host. Russian and English are selected by
default (`ocr.language`, e.g. `rus+eng`); Tesseract page segmentation can be changed with
`ocr.config`. OCR is attempted on pages with fewer than 24 native characters or low native-text
density. Native PDF text remains preferred; duplicate OCR lines/words are filtered before
`ocr_text` fragments are emitted. Missing Python OCR packages or Tesseract are recorded as
unavailable in the structured page model; rendering and native extraction still succeed.

Embedded raster images extracted from PDFs are independently inspected for OCR text when the
OCR extra is installed. OCR word boxes use embedded-image pixel coordinates and retain the
original PDF locator. This provides deterministic text evidence, not semantic image captioning. A local vision-language model adapter for interpreting symbols,
engineering drawings and visual relationships remains a separate benchmark-driven task; no
cloud vision service is called.

## Provenance and output

Each \`SourceFragment\` is tied to tenant, project, immutable document version and processing run.
Its locator identifies page/block, paragraph/table cell, worksheet/cell/merged range, or slide/shape.
PDF bounding boxes use PDF points; PPTX geometry is retained in EMU; XLSX cells use sheet names
and A1 coordinates. Content hash, extraction method and exact parser version are recorded.

The worker writes an \`extraction-manifest.json\` and embedded images to private local storage.
\`ProcessingArtifact\` records checksums, sizes, media types and source provenance. Fragment keys
are deterministic and unique within a run, so retrying persistence does not duplicate fragments.
Existing deterministic objects are accepted only after checksum and size verification.

## Run a worker

Install parser dependencies:

\`\`\`powershell
pip install -e ".[database,processing]"
\`\`\`

Process one job:

\`\`\`powershell
personal-expert-ai-worker --tenant-id <TENANT_UUID> --worker-id local-worker-01
\`\`\`

Poll continuously:

\`\`\`powershell
personal-expert-ai-worker --tenant-id <TENANT_UUID> --worker-id local-worker-01 --watch
\`\`\`

Configure \`DATABASE_URL\` and \`DOCUMENT_STORAGE_ROOT\` exactly as used by the API.
The worker requires a runtime DB role with tenant RLS permissions. It does not call an LLM.
Parser execution should still be isolated with OS-level resource limits for untrusted documents.
