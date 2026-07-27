"""Streaming behavior tests for exact Hybrid S3 artifacts."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import (
    S3ExactArtifactStore,
)


class _BoundedSource(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        assert 0 < size <= 1024 * 1024
        self.read_sizes.append(size)
        return super().read(size)


class _ProgressiveBody(BytesIO):
    def read(self, size: int = -1) -> bytes:
        assert 0 < size <= 1024 * 1024
        return super().read(size)


class _StreamingS3:
    def __init__(self) -> None:
        self.object: dict[str, Any] | None = None
        self.received_bytes_body = False

    def get_bucket_versioning(self, **_: Any) -> dict[str, str]:
        return {"Status": "Enabled"}

    def head_object(self, **_: Any) -> dict[str, Any]:
        if self.object is None:
            raise KeyError("not found")
        return {key: value for key, value in self.object.items() if key != "Body"}

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        body = kwargs["Body"]
        self.received_bytes_body = isinstance(body, bytes)
        chunks: list[bytes] = []
        while chunk := body.read(64 * 1024):
            chunks.append(chunk)
        content = b"".join(chunks)
        assert kwargs["ContentLength"] == len(content)
        self.object = {
            "VersionId": "opaque-version-1",
            "ContentLength": len(content),
            "ContentType": kwargs["ContentType"],
            "Metadata": dict(kwargs["Metadata"]),
            "Body": content,
        }
        return {"VersionId": "opaque-version-1"}

    def get_object(self, **_: Any) -> dict[str, Any]:
        assert self.object is not None
        return {
            **self.object,
            "Body": _ProgressiveBody(self.object["Body"]),
        }


def test_exact_s3_upload_and_verification_stay_streaming() -> None:
    content = b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024)
    source = _BoundedSource(content)
    client = _StreamingS3()
    store = S3ExactArtifactStore(client=client, bucket="proof-agent")
    digest = hashlib.sha256(content).hexdigest()

    ref = store.put_immutable_stream(
        key=f"hybrid/{digest}/{'b' * 64}/original.pdf",
        content=source,
        media_type="application/pdf",
        expected_sha256=digest,
        expected_size_bytes=len(content),
    )

    assert ref.sha256 == digest
    assert client.received_bytes_body is False
    assert max(source.read_sizes) <= 1024 * 1024
