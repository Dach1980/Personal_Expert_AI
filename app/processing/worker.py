"""One-job worker that extracts documents and persists artifacts/fragments locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict
from io import BytesIO
from typing import Any
from uuid import UUID

from app.processing.adapters import ExtractionResult, extract_document
from app.processing.service import ProcessingService
from app.storage.config import storage_root
from app.storage.database import get_session_factory, set_tenant_context
from app.storage.file_store import LocalFileStore
from app.storage.models import DocumentVersion, ProcessingRun

LOGGER = logging.getLogger("personal_expert_ai.processing")


class DocumentProcessingWorker:
    def __init__(self, *, worker_id: str, lease_seconds: int = 300) -> None:
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.factory = get_session_factory()
        self.service = ProcessingService(self.factory)
        self.store = LocalFileStore(storage_root())

    def process_one(self, tenant_id: UUID) -> UUID | None:
        run = self.service.claim_next(tenant_id, self.worker_id, lease_seconds=self.lease_seconds)
        if run is None:
            return None
        run_id = run.id
        try:
            with self.factory() as session, session.begin():
                set_tenant_context(session, tenant_id)
                persisted = session.get(ProcessingRun, run_id)
                if persisted is None:
                    raise RuntimeError("Claimed processing run disappeared")
                version = session.get(DocumentVersion, persisted.document_version_id)
                if version is None:
                    raise RuntimeError("Source DocumentVersion disappeared")
                source_key = version.storage_key
                checksum = version.checksum_sha256
                size = version.size_bytes
                filename = version.original_filename
            with self.store.open_verified(
                source_key, expected_checksum=checksum, expected_size=size
            ) as source:
                source_bytes = source.read()
            result = extract_document(filename, source_bytes)
            parser_expected = run.manifest.get("parsers", {}).get(result.format)
            if parser_expected and parser_expected not in {
                result.parser_version, f"{result.parser_name}@{result.parser_version}",
                f"{result.parser_name.lower()}@{result.parser_version}",
            }:
                raise RuntimeError(
                    f"Parser version mismatch: requested {parser_expected}, "
                    f"installed {result.parser_name}@{result.parser_version}"
                )
            self._persist(tenant_id, run_id, result, checksum, size)
            self.service.complete(tenant_id, run_id, self.worker_id)
            return run_id
        except Exception as exc:
            LOGGER.exception("Processing run %s failed", run_id)
            try:
                self.service.fail(
                    tenant_id, run_id, self.worker_id,
                    error_code=type(exc).__name__[:100],
                    error_message=str(exc)[:2000],
                    retry_delay_seconds=30,
                )
            except Exception:
                LOGGER.exception("Could not transition failed run %s; lease recovery will handle it", run_id)
            return run_id

    def _persist(
        self, tenant_id: UUID, run_id: UUID, result: ExtractionResult,
        source_checksum: str, source_size: int,
    ) -> None:
        with self.factory() as session, session.begin():
            set_tenant_context(session, tenant_id)
            run = session.get(ProcessingRun, run_id)
            if run is None:
                raise RuntimeError("Processing run not found")
            project_id = run.project_id
            version_id = run.document_version_id
            manifest = {
                "schema_version": 1, "format": result.format,
                "parser": {"name": result.parser_name, "version": result.parser_version},
                "source": {"sha256": source_checksum, "size_bytes": source_size},
                "metadata": result.metadata,
                "fragment_count": len(result.fragments), "embedded_asset_count": len(result.assets),
            }
        artifact_entries: list[dict[str, Any]] = []
        artifact_prefix = f"{tenant_id}/{project_id}/processing/{run_id}"
        for asset in result.assets:
            key = f"{artifact_prefix}/assets/{hashlib.sha256(asset.data).hexdigest()}-{asset.name}"
            stored = self.store.put_stream(key, [asset.data], max_bytes=25 * 1024 * 1024)
            artifact_entries.append({
                "artifact_type": "embedded_image", "storage_key": key,
                "checksum_sha256": stored.checksum_sha256, "size_bytes": stored.size_bytes,
                "media_type": asset.media_type, "metadata": {
                    "source_version_id": str(version_id), "locator": asset.locator,
                    "original_asset_name": asset.name,
                },
            })
            for fragment in result.fragments:
                if fragment.fragment_type == "image" and fragment.quality.get("asset_name") == asset.name:
                    fragment.locator["artifact_storage_key"] = key
                    fragment.locator["artifact_checksum_sha256"] = stored.checksum_sha256

        normalized = {
            **manifest,
            "assets": [
                {"storage_key": item["storage_key"], "checksum_sha256": item["checksum_sha256"],
                 "size_bytes": item["size_bytes"], "media_type": item["media_type"]}
                for item in artifact_entries
            ],
        }
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        key = f"{artifact_prefix}/extraction-manifest.json"
        stored = self.store.put_stream(key, [payload], max_bytes=20 * 1024 * 1024)
        artifact_entries.append({
            "artifact_type": "extraction_manifest", "storage_key": key,
            "checksum_sha256": stored.checksum_sha256, "size_bytes": stored.size_bytes,
            "media_type": "application/json", "metadata": {
                "source_version_id": str(version_id), "schema_version": 1,
                "parser_name": result.parser_name, "parser_version": result.parser_version,
            },
        })
        fragment_entries = [{
            "fragment_type": item.fragment_type, "locator": item.locator,
            "content": item.content, "content_hash": item.content_hash,
            "extraction_method": item.extraction_method, "extractor_version": item.extractor_version,
            "quality": item.quality,
        } for item in result.fragments]
        self.service.persist_extraction(
            tenant_id, run_id, self.worker_id,
            artifacts=artifact_entries, fragments=fragment_entries,
            extraction_summary=manifest,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one queued document for a tenant.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--watch", action="store_true", help="Poll continuously until interrupted")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    args = parser.parse_args()
    if args.poll_seconds < 0.25:
        parser.error("--poll-seconds must be at least 0.25")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker = DocumentProcessingWorker(worker_id=args.worker_id, lease_seconds=args.lease_seconds)
    while True:
        run_id = worker.process_one(args.tenant_id)
        if run_id is None and not args.watch:
            break
        if run_id is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
