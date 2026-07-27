"""Bounded streaming tests for Hybrid Knowledge upload quarantine."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge.hybrid.intake import (
    quarantine_hybrid_upload,
)
from proof_agent.errors import ProofAgentError


class _BoundedReader(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        assert 0 < size <= 64 * 1024
        self.read_sizes.append(size)
        return super().read(size)


class _InterruptedReader(BytesIO):
    def __init__(self) -> None:
        super().__init__(b"%PDF-1.7\npartial")
        self._reads = 0

    def read(self, size: int = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise OSError("client disconnected")
        return super().read(8)


def test_upload_quarantine_hashes_with_bounded_reads_and_cleans_up(
    tmp_path: Path,
) -> None:
    content = b"%PDF-1.7\n" + b"x" * (256 * 1024)
    source = _BoundedReader(content)

    with quarantine_hybrid_upload(
        source,
        max_file_bytes=len(content),
        temporary_root=tmp_path,
    ) as quarantined:
        path = quarantined.path
        assert path.exists()
        assert quarantined.size_bytes == len(content)
        assert quarantined.sha256 == hashlib.sha256(content).hexdigest()
        assert max(source.read_sizes) <= 64 * 1024

    assert path.exists() is False


def test_upload_quarantine_rejects_over_limit_without_leaving_staging_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProofAgentError) as caught:
        with quarantine_hybrid_upload(
            _BoundedReader(b"%PDF-" + b"x" * 20),
            max_file_bytes=10,
            temporary_root=tmp_path,
        ):
            raise AssertionError("oversized upload cannot be admitted")

    assert caught.value.code == "PA_HYBRID_INTAKE_002"
    assert list(tmp_path.iterdir()) == []


def test_upload_quarantine_maps_interruption_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProofAgentError) as caught:
        with quarantine_hybrid_upload(
            _InterruptedReader(),
            max_file_bytes=1024,
            temporary_root=tmp_path,
        ):
            raise AssertionError("interrupted upload cannot be admitted")

    assert caught.value.code == "PA_HYBRID_INTAKE_001"
    assert list(tmp_path.iterdir()) == []
