# Document Upload, Storage and Recovery

## Scope

This increment implements the first end-to-end document source lifecycle:

- private local storage;
- authenticated multipart upload scoped to tenant, project and document;
- idempotent upload operation records;
- quarantine and content-based format validation;
- durable coordination across PostgreSQL and filesystem writes;
- tenant-scoped reconciliation after process crashes;
- authenticated original download with SHA-256 verification.

Supported initial formats: PDF, DOCX, XLSX and PPTX. The detected MIME type is derived from file signatures/package structure; the multipart Content-Type supplied by the client is ignored. This is format identification and package safety validation, not antivirus scanning or full document parsing.

## Configuration

Set the following environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `DATABASE_URL` | none | PostgreSQL connection for the application/runtime role |
| `DOCUMENT_STORAGE_ROOT` | Per-user OS application-data directory | Optional absolute local filesystem root override |
| `DOCUMENT_MAX_UPLOAD_BYTES` | `104857600` | Maximum file size (100 MiB) |
| `JWT_SECRET` | none | HS256 secret issued/managed by trusted identity provider |
| `JWT_ISSUER` | none | Expected JWT issuer |
| `JWT_AUDIENCE` | none | Expected JWT audience |

The storage root and staging directory are created with owner-only permissions on POSIX systems; published objects are made read-only (0400) on POSIX. Staging files are written on the same filesystem as the final objects, flushed and fsynced, then atomically published using a no-overwrite hard link. Files are never stored using the user-supplied filename as a path.

Use a dedicated runtime database role: it must not own the tables and must not have SUPERUSER or BYPASSRLS. Run Alembic migrations separately with the migration role. Keep the storage root outside the Git repository and include it in a protected backup plan.

The ASGI middleware bounds multipart request bytes before Starlette spools the body; the upload service independently enforces the exact file-byte limit. A reverse proxy should also set a matching request-body limit.

## API

Upload a new immutable version to an existing document:

```http
POST /api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions
Authorization: Bearer <access-token>
Idempotency-Key: <8-128 safe ASCII characters>
Content-Type: multipart/form-data

file=<binary>
```

Example:

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: design-upload-0001" \
  -F "file=@./project.pdf" \
  "http://127.0.0.1:8000/api/v1/tenants/$TENANT_ID/projects/$PROJECT_ID/documents/$DOCUMENT_ID/versions"
```

A new upload returns HTTP 201. Repeating the same idempotency key, document, filename and bytes returns the original version with HTTP 200. Reusing the key for different bytes, a different filename/document, or an unfinished/failed operation returns HTTP 409. Viewer/reviewer roles cannot upload.

Download a specific original version:

```http
GET /api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/content
Authorization: Bearer <access-token>
```

The endpoint checks active tenant and project membership, opens the exact file handle, recomputes SHA-256 and size, rewinds that handle, and only then starts streaming. A missing or mismatched source is not returned; the endpoint responds with HTTP 503. The response uses attachment disposition, no-store caching and nosniff.

## Durable upload state machine

```text
receiving -> quarantined -> publishing -> completed
     |             |             |
     +-------------+-------------+----> failed (validation/terminal failure)
```

The upload operation row is committed before file ingestion. The quarantine object is written and hashed, validated, and its checksum/size are committed to the operation. The operation is then committed as `publishing` before the final object is atomically published. Only after the final object is re-verified does one PostgreSQL transaction insert DocumentVersion, update Document.current_version_id, attach the version to UploadOperation, write the `document.version_uploaded` AuditEvent and mark the operation completed.

PostgreSQL and the filesystem do not share a distributed transaction. Recovery is therefore explicit:

| Crash point | Durable state | Recovery |
|---|---|---|
| Before quarantine publication | receiving, no quarantine object | Mark stale operation failed |
| After quarantine publication, before metadata update | receiving + quarantine object | Recompute checksum/size, validate, continue |
| After quarantine metadata commit | quarantined + quarantine object | Publish final object |
| After publishing commit, before final object | publishing + quarantine object | Publish final object |
| After final object publication, before DB finalization | publishing + final object | Verify final object and finalize DB transaction |
| After DB finalization, before quarantine cleanup | completed + both objects | Verify source and remove quarantine copy |

The original source is immutable. A replacement is always a new DocumentVersion and storage key.

## Reconciliation

Run once for each tenant after a crash, during maintenance, or from a scheduled local task:

```bash
python -m app.storage.reconcile --tenant-id <TENANT_UUID>
```

Optional stale threshold:

```bash
python -m app.storage.reconcile --tenant-id <TENANT_UUID> --stale-after-seconds 900
```

The command:
- resumes recoverable receiving/quarantined/publishing operations;
- marks stale receiving operations without quarantine bytes as failed;
- verifies every registered DocumentVersion against its SHA-256 and size;
- removes leftover quarantine copies for completed uploads;
- reports missing/corrupt originals and unreferenced final/quarantine objects.

It does not automatically delete orphan final objects: those are reported for operator review to avoid destroying evidence or data after an interrupted database transaction. The command is tenant-scoped because PostgreSQL RLS is forced; run it separately for each tenant. Schedule it with the least-privileged runtime role and retain its output in the local operational log.

## Integrity and security boundaries

- Database constraints and the source-identity trigger remain authoritative for immutable version metadata.
- Composite foreign keys and RLS bind upload operations to the same tenant/project/document.
- Upload permission requires active tenant membership and an upload-capable tenant/project role.
- Download permits active project members, including read-only roles.
- The caller-supplied MIME type is never trusted.
- Office ZIP packages are checked for required package members, traversal entries, excessive entry counts, uncompressed size and suspicious compression ratios; encrypted packages, VBA macro payloads and external relationships are rejected.
- Client filenames are sanitized and are metadata only.
- Storage keys are generated by the server and cannot escape the configured root.
- Checksum mismatch blocks download and must be treated as a data-integrity incident.
- Parsing/indexing must be queued only after an operation is completed; no parser is invoked by the upload endpoint.

This is a local-first implementation. It does not call cloud storage, external malware scanning services or hosted document processors.
