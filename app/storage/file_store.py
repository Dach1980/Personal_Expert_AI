"""Integrity-aware local storage for immutable source files."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable


_STORAGE_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,499}$")


class StorageIntegrityError(RuntimeError):
    """Stored bytes do not match the registered source identity."""


class StorageConflictError(FileExistsError):
    """A storage key already exists and must never be overwritten."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    storage_key: str
    checksum_sha256: str
    size_bytes: int


class LocalFileStore:
    """Store immutable files below one configured root using atomic publication."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.staging = self.root / ".staging"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.root, 0o700)
        self.staging.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _target(self, storage_key: str) -> Path:
        if not _STORAGE_KEY_RE.fullmatch(storage_key):
            raise ValueError("Invalid storage key")
        parts = storage_key.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Invalid storage key")
        target = self.root.joinpath(*parts)
        resolved_parent = target.parent.resolve()
        if not resolved_parent.is_relative_to(self.root):
            raise ValueError("Storage key escapes the configured root")
        if target.is_symlink():
            raise ValueError("Storage target must not be a symbolic link")
        return target

    def put_stream(
        self,
        storage_key: str,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
    ) -> StoredObject:
        """Write chunks to staging, hash while streaming, then publish without overwrite."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        target = self._target(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.staging, prefix="upload-", delete=False
            ) as temporary:
                temp_path = Path(temporary.name)
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise TypeError("Storage chunks must be bytes")
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("File exceeds the configured size limit")
                    digest.update(chunk)
                    temporary.write(chunk)
                if size == 0:
                    raise ValueError("Empty files are not accepted")
                temporary.flush()
                os.fsync(temporary.fileno())

            try:
                # Hard-link publication is atomic and fails if the key already exists.
                os.link(temp_path, target)
            except FileExistsError as exc:
                raise StorageConflictError(storage_key) from exc
            temp_path.unlink()
            temp_path = None
            self._fsync_directory(target.parent)
            return StoredObject(storage_key, digest.hexdigest(), size)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def verify(
        self, storage_key: str, *, expected_checksum: str, expected_size: int
    ) -> StoredObject:
        """Recompute the hash from disk and compare it with trusted database metadata."""
        target = self._target(storage_key)
        if not target.is_file() or target.is_symlink():
            raise StorageIntegrityError("Stored source file is missing or not a regular file")
        digest = hashlib.sha256()
        size = 0
        with target.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        actual = StoredObject(storage_key, digest.hexdigest(), size)
        if actual.checksum_sha256 != expected_checksum or actual.size_bytes != expected_size:
            raise StorageIntegrityError("Stored source checksum or size does not match metadata")
        return actual

    def open(self, storage_key: str) -> BinaryIO:
        """Open a registered storage object for read-only access."""
        target = self._target(storage_key)
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(storage_key)
        return target.open("rb")

    def open_verified(
        self, storage_key: str, *, expected_checksum: str, expected_size: int
    ) -> BinaryIO:
        """Verify the exact opened file handle and rewind it for a subsequent download."""
        source = self.open(storage_key)
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            if digest.hexdigest() != expected_checksum or size != expected_size:
                raise StorageIntegrityError("Stored source checksum or size does not match metadata")
            source.seek(0)
            return source
        except Exception:
            source.close()
            raise

    def delete(self, storage_key: str, *, missing_ok: bool = True) -> None:
        """Delete one validated object key; callers must first verify database references."""
        target = self._target(storage_key)
        target.unlink(missing_ok=missing_ok)
        if target.parent.exists():
            self._fsync_directory(target.parent)

    def exists(self, storage_key: str) -> bool:
        target = self._target(storage_key)
        return target.is_file() and not target.is_symlink()

    def iter_objects(self):
        """Yield regular object keys, excluding internal staging files."""
        for path in self.root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.root)
            if relative.parts[0] == ".staging":
                continue
            yield relative.as_posix()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

