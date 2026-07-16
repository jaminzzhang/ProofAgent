from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import os

import pytest

from proof_agent.capabilities.artifacts.s3 import S3ArtifactStore
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner, ArtifactPutRequest


pytestmark = pytest.mark.hybrid_integration


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for real S3 artifact integration")
    return value


def test_real_versioned_s3_exact_put_list_read_and_delete() -> None:
    endpoint = required("PROOF_AGENT_TEST_S3_ENDPOINT")
    bucket = required("PROOF_AGENT_TEST_S3_BUCKET")
    prefix = f"generic-artifacts-{os.getpid()}/"
    store = S3ArtifactStore.from_environment(
        bucket=bucket,
        key_prefix=prefix,
        endpoint_url=endpoint,
        region_name="us-east-1",
    )
    content = b"real versioned S3 artifact"
    now = datetime.now(UTC)
    try:
        ref = store.put_immutable(
            ArtifactPutRequest(
                kind=ArtifactKind.RELEASE_MANIFEST,
                owner=ArtifactOwner(owner_type="release", owner_id="candidate-real-s3"),
                content_type="application/json",
                expected_sha256=hashlib.sha256(content).hexdigest(),
                expected_size_bytes=len(content),
            ),
            BytesIO(content),
        )
        assert store.head_exact(ref) == ref
        with store.open_exact(ref) as body:
            assert body.read() == content
        listed = tuple(
            store.iter_versions_before(
                prefix="objects/",
                before=now + timedelta(minutes=1),
            )
        )
        assert listed == (ref,)
        store.delete_exact(ref)
        assert tuple(
            store.iter_versions_before(
                prefix="objects/",
                before=now + timedelta(minutes=1),
            )
        ) == ()
    finally:
        store.close()
