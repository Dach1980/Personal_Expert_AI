import hashlib

import pytest

from app.storage.file_store import (
    LocalFileStore,
    StorageConflictError,
    StorageIntegrityError,
)


def test_stream_write_and_verify_checksum(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    result = store.put_stream("tenant/project/version/source.bin", [b"abc", b"123"], max_bytes=6)

    assert result.checksum_sha256 == hashlib.sha256(b"abc123").hexdigest()
    assert result.size_bytes == 6
    verified = store.verify(
        result.storage_key,
        expected_checksum=result.checksum_sha256,
        expected_size=result.size_bytes,
    )
    assert verified == result


def test_existing_storage_key_is_never_overwritten(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    original = store.put_stream("tenant/project/version/source.bin", [b"original"], max_bytes=100)

    with pytest.raises(StorageConflictError):
        store.put_stream("tenant/project/version/source.bin", [b"replacement"], max_bytes=100)

    assert store.verify(
        original.storage_key,
        expected_checksum=original.checksum_sha256,
        expected_size=original.size_bytes,
    ) == original


def test_rejects_empty_oversized_and_unsafe_keys(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    with pytest.raises(ValueError, match="Empty"):
        store.put_stream("a/b/c.bin", [b"", b""], max_bytes=100)
    with pytest.raises(ValueError, match="size limit"):
        store.put_stream("a/b/d.bin", [b"1234"], max_bytes=3)
    with pytest.raises(ValueError, match="Invalid storage key"):
        store.put_stream("../outside.bin", [b"x"], max_bytes=10)


def test_detects_post_write_tampering(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    stored = store.put_stream("tenant/project/version/source.bin", [b"trusted"], max_bytes=100)
    (tmp_path / "objects" / stored.storage_key).write_bytes(b"tampered")

    with pytest.raises(StorageIntegrityError, match="checksum or size"):
        store.verify(
            stored.storage_key,
            expected_checksum=stored.checksum_sha256,
            expected_size=stored.size_bytes,
        )



def test_storage_root_cannot_be_filesystem_root(tmp_path):
    with pytest.raises(ValueError, match="filesystem root"):
        LocalFileStore(tmp_path.anchor)


def test_open_verified_returns_rewound_verified_handle(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    stored = store.put_stream("tenant/project/version/source.pdf", [b"%PDF-1.7"], max_bytes=100)
    with store.open_verified(
        stored.storage_key,
        expected_checksum=stored.checksum_sha256,
        expected_size=stored.size_bytes,
    ) as source:
        assert source.read() == b"%PDF-1.7"
