from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import re
from typing import Any, BinaryIO
from urllib.parse import quote, unquote
from uuid import uuid4

from pydantic import ValidationError

from proof_agent.capabilities.artifacts import ArtifactStoreError
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactPutRequest,
)


class S3ArtifactStore:
    """Provider-neutral exact-version adapter over one versioned S3-compatible bucket."""

    def __init__(
        self,
        *,
        client: Any,
        bucket: str,
        key_prefix: str = "",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) is None:
            raise ValueError("S3 artifact bucket name is invalid")
        if key_prefix and (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}/", key_prefix) is None
            or ".." in key_prefix
            or "//" in key_prefix
        ):
            raise ValueError("S3 artifact key prefix is invalid")
        self._client = client
        self._bucket = bucket
        self._key_prefix = key_prefix
        self._clock = clock or (lambda: datetime.now(UTC))
        try:
            status = client.get_bucket_versioning(Bucket=bucket)
        except Exception as exc:
            raise ArtifactStoreError("S3 bucket versioning could not be verified") from exc
        if status.get("Status") != "Enabled":
            raise ArtifactStoreError("S3 bucket versioning must be enabled")

    @classmethod
    def from_environment(
        cls,
        *,
        bucket: str,
        key_prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> S3ArtifactStore:
        try:
            import boto3  # type: ignore[import-untyped]
            from botocore.config import Config  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - optional production extra
            raise RuntimeError("S3 artifact authority requires the production extra") from exc
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            config=Config(proxies={}, retries={"max_attempts": 1, "mode": "standard"}),
        )
        try:
            return cls(client=client, bucket=bucket, key_prefix=key_prefix)
        except BaseException:
            client.close()
            raise

    def put_immutable(
        self,
        request: ArtifactPutRequest,
        body: BinaryIO,
    ) -> ArtifactObjectVersion:
        content = body.read(request.expected_size_bytes + 1)
        if not isinstance(content, bytes) or len(content) != request.expected_size_bytes:
            raise ArtifactStoreError("artifact body length does not match put request")
        if hashlib.sha256(content).hexdigest() != request.expected_sha256:
            raise ArtifactStoreError("artifact body digest does not match put request")
        object_uuid = uuid4()
        object_key = f"objects/{object_uuid.hex[:2]}/{object_uuid}"
        now = self._clock()
        provisional = ArtifactObjectVersion(
            object_id=str(object_uuid),
            bucket=self._bucket,
            object_key=object_key,
            version_id="pending-version",
            sha256=request.expected_sha256,
            size_bytes=request.expected_size_bytes,
            kind=request.kind,
            owner=request.owner,
            content_type=request.content_type,
            created_at=now,
            expires_at=request.expires_at,
            display_filename=request.display_filename,
        )
        try:
            response = self._client.put_object(
                Bucket=self._bucket,
                Key=self._physical_key(object_key),
                Body=content,
                ContentType=request.content_type,
                Metadata=self._metadata_for(provisional),
                IfNoneMatch="*",
            )
        except Exception as exc:
            raise ArtifactStoreError("immutable S3 artifact write failed") from exc
        version_id = response.get("VersionId")
        if not isinstance(version_id, str) or not version_id:
            raise ArtifactStoreError("versioned S3 put returned no opaque VersionId")
        ref = provisional.model_copy(update={"version_id": version_id})
        self.head_exact(ref)
        with self.open_exact(ref) as exact:
            if exact.read(request.expected_size_bytes + 1) != content:
                raise ArtifactStoreError("written S3 artifact failed exact read-back")
        return ref

    def head_exact(self, ref: ArtifactObjectVersion) -> ArtifactObjectVersion:
        self._require_authority(ref)
        try:
            response = self._client.head_object(
                Bucket=self._bucket,
                Key=self._physical_key(ref.object_key),
                VersionId=ref.version_id,
            )
        except Exception as exc:
            raise ArtifactStoreError("exact S3 artifact version is unavailable") from exc
        self._verify_response_metadata(ref, response)
        return ref

    def open_exact(self, ref: ArtifactObjectVersion) -> BinaryIO:
        self._require_authority(ref)
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=self._physical_key(ref.object_key),
                VersionId=ref.version_id,
            )
            content = response["Body"].read(ref.size_bytes + 1)
        except Exception as exc:
            raise ArtifactStoreError("exact S3 artifact version is unavailable") from exc
        self._verify_response_metadata(ref, response)
        if not isinstance(content, bytes) or len(content) != ref.size_bytes:
            raise ArtifactStoreError("exact S3 artifact length does not match")
        if hashlib.sha256(content).hexdigest() != ref.sha256:
            raise ArtifactStoreError("exact S3 artifact digest does not match")
        return BytesIO(content)

    def delete_exact(self, ref: ArtifactObjectVersion) -> None:
        self.head_exact(ref)
        try:
            response = self._client.delete_object(
                Bucket=self._bucket,
                Key=self._physical_key(ref.object_key),
                VersionId=ref.version_id,
            )
        except Exception as exc:
            raise ArtifactStoreError("exact S3 artifact delete failed") from exc
        returned_version = response.get("VersionId")
        if returned_version is not None and returned_version != ref.version_id:
            raise ArtifactStoreError("S3 deleted an unexpected artifact version")

    def iter_versions_before(
        self,
        *,
        prefix: str,
        before: datetime,
    ) -> Iterator[ArtifactObjectVersion]:
        if prefix != "objects/" or before.utcoffset() is None:
            raise ValueError("S3 artifact iteration requires objects/ and aware time")
        key_marker: str | None = None
        version_marker: str | None = None
        refs: list[ArtifactObjectVersion] = []
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": self._physical_key(prefix),
            }
            if key_marker is not None:
                kwargs["KeyMarker"] = key_marker
                kwargs["VersionIdMarker"] = version_marker
            try:
                response = self._client.list_object_versions(**kwargs)
            except Exception as exc:
                raise ArtifactStoreError("S3 artifact version listing failed") from exc
            for item in response.get("Versions", ()):
                if not isinstance(item, dict):
                    raise ArtifactStoreError("S3 artifact version listing is malformed")
                ref = self._ref_from_list_item(item)
                if ref.created_at < before:
                    refs.append(ref)
            if response.get("IsTruncated") is not True:
                break
            key_marker = response.get("NextKeyMarker")
            version_marker = response.get("NextVersionIdMarker")
            if not isinstance(key_marker, str) or not isinstance(version_marker, str):
                raise ArtifactStoreError("S3 artifact listing pagination is malformed")
        yield from sorted(refs, key=lambda item: (item.created_at, item.object_id))

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def check_ready(self) -> bool:
        """Recheck the versioned bucket contract without exposing provider details."""

        try:
            status = self._client.get_bucket_versioning(Bucket=self._bucket)
        except Exception:
            return False
        return bool(status.get("Status") == "Enabled")

    def _ref_from_list_item(self, item: dict[str, Any]) -> ArtifactObjectVersion:
        key = item.get("Key")
        version_id = item.get("VersionId")
        if not isinstance(key, str) or not isinstance(version_id, str):
            raise ArtifactStoreError("S3 artifact version listing is malformed")
        if not key.startswith(self._key_prefix):
            raise ArtifactStoreError("S3 artifact listing escaped configured prefix")
        logical_key = key[len(self._key_prefix) :]
        try:
            response = self._client.head_object(
                Bucket=self._bucket,
                Key=key,
                VersionId=version_id,
            )
            ref = self._ref_from_metadata(
                logical_key=logical_key,
                version_id=version_id,
                response=response,
            )
        except ArtifactStoreError:
            raise
        except Exception as exc:
            raise ArtifactStoreError("listed S3 artifact metadata is unavailable") from exc
        self._verify_response_metadata(ref, response)
        return ref

    def _ref_from_metadata(
        self,
        *,
        logical_key: str,
        version_id: str,
        response: dict[str, Any],
    ) -> ArtifactObjectVersion:
        metadata = response.get("Metadata")
        if not isinstance(metadata, dict):
            raise ArtifactStoreError("S3 artifact metadata is incomplete")
        try:
            expires_at = metadata.get("proofagent-expires-at") or None
            display_name = metadata.get("proofagent-display-name") or None
            return ArtifactObjectVersion(
                object_id=metadata["proofagent-object-id"],
                bucket=self._bucket,
                object_key=logical_key,
                version_id=version_id,
                sha256=metadata["proofagent-sha256"],
                size_bytes=response["ContentLength"],
                kind=ArtifactKind(metadata["proofagent-kind"]),
                owner=ArtifactOwner(
                    owner_type=metadata["proofagent-owner-type"],
                    owner_id=unquote(metadata["proofagent-owner-id"]),
                ),
                content_type=response["ContentType"],
                created_at=datetime.fromisoformat(metadata["proofagent-created-at"]),
                expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
                display_filename=unquote(display_name) if display_name else None,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ArtifactStoreError("S3 artifact metadata is invalid") from exc

    @staticmethod
    def _metadata_for(ref: ArtifactObjectVersion) -> dict[str, str]:
        result = {
            "proofagent-object-id": ref.object_id,
            "proofagent-sha256": ref.sha256,
            "proofagent-kind": ref.kind.value,
            "proofagent-owner-type": ref.owner.owner_type,
            "proofagent-owner-id": quote(ref.owner.owner_id, safe=""),
            "proofagent-created-at": ref.created_at.isoformat(),
        }
        if ref.expires_at is not None:
            result["proofagent-expires-at"] = ref.expires_at.isoformat()
        if ref.display_filename is not None:
            result["proofagent-display-name"] = quote(ref.display_filename, safe="")
        return result

    def _verify_response_metadata(
        self,
        ref: ArtifactObjectVersion,
        response: dict[str, Any],
    ) -> None:
        metadata = response.get("Metadata")
        if (
            response.get("VersionId") != ref.version_id
            or response.get("ContentLength") != ref.size_bytes
            or response.get("ContentType") != ref.content_type
            or not isinstance(metadata, dict)
            or metadata.get("proofagent-sha256") != ref.sha256
            or metadata.get("proofagent-object-id") != ref.object_id
        ):
            raise ArtifactStoreError("exact S3 artifact metadata does not match authority")

    def _require_authority(self, ref: ArtifactObjectVersion) -> None:
        if ref.bucket != self._bucket:
            raise ArtifactStoreError("artifact reference is outside the configured S3 bucket")

    def _physical_key(self, logical_key: str) -> str:
        return self._key_prefix + logical_key


__all__ = ["S3ArtifactStore"]
