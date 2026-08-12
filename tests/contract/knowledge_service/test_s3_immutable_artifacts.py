from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from knowledge_source_service.adapters.s3.artifacts import (
    ArtifactIntegrityError,
    S3ImmutableArtifactStore,
)


pytestmark = pytest.mark.s3_integration


def test_s3_artifact_write_is_idempotent_and_exactly_versioned(
    kss_s3_bucket: tuple[Any, str],
) -> None:
    client, bucket = kss_s3_bucket
    store = S3ImmutableArtifactStore(
        client=client,
        bucket=bucket,
        key_prefix="knowledge-source-service/",
    )
    content = b'{"schema_version":"release-manifest.v1"}'

    first = store.put_immutable(
        object_key="spaces/space-1/bases/base-1/releases/release-1/release-manifest.json",
        content=content,
        media_type="application/json",
    )
    replay = store.put_immutable(
        object_key="spaces/space-1/bases/base-1/releases/release-1/release-manifest.json",
        content=content,
        media_type="application/json",
    )

    assert replay == first
    assert store.get_exact(first) == content
    assert first.version_id
    assert first.sha256.startswith("sha256:")
    assert first.size_bytes == len(content)
    with pytest.raises(ArtifactIntegrityError):
        store.get_exact(replace(first, sha256=f"sha256:{'0' * 64}"))
