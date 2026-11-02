"""Run tenant-scoped document upload recovery and integrity reconciliation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from uuid import UUID

from app.storage.config import max_upload_bytes, storage_root
from app.storage.database import get_session_factory
from app.storage.file_store import LocalFileStore
from app.storage.upload_service import DocumentUploadService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--stale-after-seconds", type=int, default=900)
    args = parser.parse_args()

    factory = get_session_factory()
    try:
        service = DocumentUploadService(
            factory, LocalFileStore(storage_root()), max_bytes=max_upload_bytes()
        )
        report = service.reconcile(
            args.tenant_id, stale_after_seconds=args.stale_after_seconds
        )
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    finally:
        factory.kw["bind"].dispose()


if __name__ == "__main__":
    main()
