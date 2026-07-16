from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import pytest

from proof_agent.capabilities.artifacts import ArtifactStoreError
from proof_agent.capabilities.artifacts.s3 import S3ArtifactStore
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner, ArtifactPutRequest


NOW = datetime(2026, 7, 15, tzinfo=UTC)


class Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self, amount: int) -> bytes:
        return self.value[:amount]


class VersionedS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.current: dict[tuple[str, str], str] = {}
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.counter = 0

    def get_bucket_versioning(self, **_kwargs: Any) -> dict[str, str]:
        return {"Status": "Enabled"}

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        assert kwargs["IfNoneMatch"] == "*"
        key = (kwargs["Bucket"], kwargs["Key"])
        if key in self.current:
            raise RuntimeError("precondition failed")
        self.counter += 1
        version = f"version-{self.counter}"
        record = {
            "Body": bytes(kwargs["Body"]),
            "ContentType": kwargs["ContentType"],
            "Metadata": dict(kwargs["Metadata"]),
        }
        self.objects[(key[0], key[1], version)] = record
        self.current[key] = version
        self.puts.append(dict(kwargs))
        return {"VersionId": version}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        record = self.objects[(kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])]
        return {
            "VersionId": kwargs["VersionId"],
            "ContentLength": len(record["Body"]),
            "ContentType": record["ContentType"],
            "Metadata": dict(record["Metadata"]),
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        head = self.head_object(**kwargs)
        record = self.objects[(kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])]
        return {**head, "Body": Body(record["Body"])}

    def delete_object(self, **kwargs: Any) -> dict[str, str]:
        self.objects.pop((kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"]))
        self.deletes.append(dict(kwargs))
        return {"VersionId": kwargs["VersionId"]}

    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]:
        versions = [
            {"Key": key, "VersionId": version}
            for bucket, key, version in self.objects
            if bucket == kwargs["Bucket"] and key.startswith(kwargs["Prefix"])
        ]
        return {"Versions": versions, "IsTruncated": False}


def put_request(content: bytes = b"receipt") -> ArtifactPutRequest:
    import hashlib

    return ArtifactPutRequest(
        kind=ArtifactKind.GOVERNANCE_RECEIPT,
        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
        content_type="text/markdown",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_size_bytes=len(content),
        display_filename="receipt.md",
    )


def test_s3_store_puts_verifies_and_reads_exact_version() -> None:
    client = VersionedS3()
    store = S3ArtifactStore(client=client, bucket="proof-agent", clock=lambda: NOW)

    ref = store.put_immutable(put_request(), BytesIO(b"receipt"))

    assert ref.version_id == "version-1"
    assert store.head_exact(ref) == ref
    with store.open_exact(ref) as body:
        assert body.read() == b"receipt"
    assert client.puts[0]["IfNoneMatch"] == "*"
    assert list(
        store.iter_versions_before(prefix="objects/", before=NOW + timedelta(seconds=1))
    ) == [ref]


def test_s3_store_rejects_corrupt_exact_read_and_deletes_exact_version_only() -> None:
    client = VersionedS3()
    store = S3ArtifactStore(client=client, bucket="proof-agent", clock=lambda: NOW)
    ref = store.put_immutable(put_request(), BytesIO(b"receipt"))
    client.objects[(ref.bucket, ref.object_key, ref.version_id)]["Body"] = b"corrupt"

    with pytest.raises(ArtifactStoreError, match="length|digest"):
        store.open_exact(ref)

    store.delete_exact(ref)
    assert client.deletes == [
        {"Bucket": "proof-agent", "Key": ref.object_key, "VersionId": ref.version_id}
    ]


def test_s3_store_requires_bucket_versioning() -> None:
    client = VersionedS3()
    client.get_bucket_versioning = lambda **_kwargs: {"Status": "Suspended"}  # type: ignore[method-assign]

    with pytest.raises(ArtifactStoreError, match="versioning"):
        S3ArtifactStore(client=client, bucket="proof-agent")
