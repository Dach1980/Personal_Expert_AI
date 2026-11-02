# Processing queue and run lifecycle

Processing runs are durable PostgreSQL jobs tied to one immutable `DocumentVersion`.
A run can only be queued when its version has status `uploaded` and a matching
`UploadOperation` is `completed`. The enqueue transaction stores the source checksum,
size, media type, pipeline identity and parser manifest before the worker can claim it.

## API

`POST /api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/processing-runs`

Requires `Idempotency-Key` (8–128 safe ASCII characters). Body:

```json
{
  "pipeline_name": "document-ingestion",
  "pipeline_version": "1",
  "parser_manifest": {
    "pdf": "pymupdf@1.x",
    "docx": "python-docx@1.x",
    "xlsx": "openpyxl@3.x",
    "pptx": "python-pptx@1.x"
  },
  "max_attempts": 3
}
```

The manifest is a declaration of the intended parser versions; it does not imply
that those adapters are installed or enabled. Repeating the same request with the
same idempotency key returns the existing run. Reusing the key for a different
version or pipeline configuration returns HTTP 409.

`GET .../versions/{version_id}/processing-runs` lists runs for that immutable source
version. Tenant/project membership is checked on every request.

## Worker contract

Use `ProcessingService.claim_next(tenant_id, worker_id)` to atomically claim work.
PostgreSQL `FOR UPDATE SKIP LOCKED` allows multiple workers without double claims.
Claims carry a renewable lease; heartbeat, artifact registration, completion and
failure all require the current worker identity and a non-expired lease.

Expired leases become claimable again. Each claim increments `attempt_count`;
the run fails after `max_attempts`. A worker should:
1. Read the source identity from `run.manifest.source`.
2. Open the original through the verified storage API and re-check SHA-256/size.
3. Select only an explicitly registered adapter whose version matches
   `run.manifest.parsers`.
4. Persist intermediate outputs to private storage, then register each artifact
   with checksum, size, media type and provenance metadata.
5. Heartbeat during long operations and call `complete` only after all required
   stages and artifacts are durable. Call `fail` with a stable error code otherwise.

The worker lease protects queue ownership; it is not a substitute for storage
integrity verification or parser sandboxing. Parser execution and format adapters
are the next implementation increment. No LLM or parser is invoked by enqueueing.
