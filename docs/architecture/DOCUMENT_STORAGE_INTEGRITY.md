# Document Storage Integrity

- Status: implemented foundation; upload API and recovery worker remain pending
- Date: 2026-11-01

## 1. Invariants

A registered DocumentVersion identifies one immutable source object. Its source identity is:

- tenant_id, project_id and document_id;
- original_filename and media_type as captured at ingestion;
- size_bytes;
- checksum_sha256 (lowercase SHA-256 hex, exactly 64 characters);
- storage_key;
- uploaded_by and uploaded_at.

Workflow fields such as status and version metadata may change. The source identity may not be rewritten in place. A corrected or replaced file is a new DocumentVersion with a new UUID and storage key.

The database enforces positive size, valid SHA-256 syntax and non-empty filename, media type and storage key. A PostgreSQL trigger rejects updates to source identity fields. Composite foreign keys continue to bind each version to the same tenant, project and logical document.

## 2. Local file store

`app.storage.file_store.LocalFileStore` provides the first local storage implementation:

1. Accept byte chunks and write them to a private staging directory.
2. Calculate SHA-256 and byte count during the write; enforce a caller-supplied maximum size.
3. Flush and fsync the staged file.
4. Publish by creating a hard link at the final key. Publication fails if the key already exists; it never overwrites an existing source.
5. Fsync the containing directory.
6. Re-read the stored file in bounded chunks to verify both checksum and size against database metadata.

Storage keys are relative, validated paths. Original filenames are metadata only and must never be used to construct storage paths. Empty files, traversal paths, oversize files and duplicate keys are rejected.

## 3. Consistency model and recovery boundary

PostgreSQL and the filesystem do not share a transaction. A future upload orchestration must therefore explicitly manage the two-resource boundary:

- write and verify an immutable staged object;
- persist DocumentVersion metadata and an upload operation/idempotency record;
- publish the object atomically;
- mark the operation complete only after both sides are verified;
- reconcile abandoned staging objects, unreferenced final objects and metadata rows with missing files.

Do not claim that a database commit and filesystem write are one atomic transaction. Until the upload orchestration and reconciliation worker exist, LocalFileStore is a tested storage primitive, not a complete upload workflow.

## 4. Integrity checks required before publication

- Verify checksum and size from bytes, not from client-provided metadata.
- Reject an already-used storage key.
- Do not silently deduplicate logical documents by checksum.
- Do not update an existing version when a new file arrives.
- Verify file bytes before parsing and before serving a source download.
- Treat checksum mismatch or missing source as an integrity incident; block processing/retrieval and preserve audit evidence.
- Keep original files immutable; derived artifacts use separate keys and their own checksums.

## 5. Implemented tests

- Streaming write calculates the expected SHA-256 and size.
- Reusing a storage key does not overwrite existing bytes.
- Empty, oversized and traversal-path inputs are rejected.
- Post-write tampering is detected by verification.
- PostgreSQL rejects malformed checksum/zero-size metadata.
- PostgreSQL rejects mutation of source identity while allowing workflow status changes.

## 6. Remaining work

The next increments are the authenticated multipart upload endpoint, idempotency and operation records, file-type/content validation and quarantine, download verification, and a reconciliation command/worker. Parsing and indexing must not start until the source object has passed integrity verification.
