"""Exact-version immutable S3-compatible artifact authority."""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any

from knowledge_source_service.domain.artifacts import ExactArtifactReference


_KEY_PREFIX = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*$")


class ImmutableArtifactStoreError(RuntimeError):
    """An immutable object operation failed closed."""


class ArtifactIntegrityError(ImmutableArtifactStoreError):
    """Stored bytes or metadata do not match the exact authority reference."""


class S3ImmutableArtifactStore:
    """Store service-generated keys in a versioned S3-compatible bucket."""

    def __init__(self, *, client: Any, bucket: str, key_prefix: str = "") -> None:
        if not bucket or any(ord(character) < 33 for character in bucket):
            raise ValueError("S3 bucket name is invalid")
        if _KEY_PREFIX.fullmatch(key_prefix) is None or ".." in key_prefix:
            raise ValueError("S3 key prefix is invalid")
        try:
            versioning = client.get_bucket_versioning(Bucket=bucket)
        except Exception as error:
            raise ImmutableArtifactStoreError(
                "S3 bucket versioning could not be verified"
            ) from error
        if versioning.get("Status") != "Enabled":
            raise ImmutableArtifactStoreError("S3 bucket versioning must be enabled")
        self._client = client
        self._bucket = bucket
        self._key_prefix = key_prefix

    def put_immutable(
        self,
        *,
        object_key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactReference:
        if type(content) is not bytes or not content:
            raise ValueError("immutable artifact content must be nonempty exact bytes")
        digest_hex = sha256(content).hexdigest()
        expected = ExactArtifactReference(
            object_key=object_key,
            version_id="pending",
            sha256=f"sha256:{digest_hex}",
            size_bytes=len(content),
            media_type=media_type,
        )
        physical_key = self._physical_key(object_key)
        existing = self._head_current(object_key, physical_key)
        if existing is not None:
            self._require_same_content(existing, expected, content)
            return existing
        try:
            response = self._client.put_object(
                Bucket=self._bucket,
                Key=physical_key,
                Body=content,
                ContentType=media_type,
                Metadata={
                    "kss-sha256": digest_hex,
                    "kss-size": str(len(content)),
                },
                IfNoneMatch="*",
            )
        except Exception as error:
            raced = self._head_current(object_key, physical_key)
            if raced is None:
                raise ImmutableArtifactStoreError("immutable S3 write failed") from error
            try:
                self._require_same_content(raced, expected, content)
            except ArtifactIntegrityError as integrity_error:
                raise ImmutableArtifactStoreError(
                    "immutable S3 key create conflict"
                ) from integrity_error
            return raced
        version_id = response.get("VersionId")
        if type(version_id) is not str or not version_id:
            raise ImmutableArtifactStoreError(
                "versioned S3 write returned no opaque VersionId"
            )
        reference = ExactArtifactReference(
            object_key=object_key,
            version_id=version_id,
            sha256=expected.sha256,
            size_bytes=expected.size_bytes,
            media_type=expected.media_type,
        )
        if self.get_exact(reference) != content:
            raise ArtifactIntegrityError("written S3 artifact failed exact read-back")
        return reference

    def is_ready(self) -> bool:
        """Verify the configured bucket still has the required versioning invariant."""

        try:
            return bool(
                self._client.get_bucket_versioning(Bucket=self._bucket).get("Status")
                == "Enabled"
            )
        except Exception:
            return False

    def get_exact(self, reference: ExactArtifactReference) -> bytes:
        physical_key = self._physical_key(reference.object_key)
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=physical_key,
                VersionId=reference.version_id,
            )
        except Exception as error:
            raise ImmutableArtifactStoreError(
                "exact S3 artifact version is unavailable"
            ) from error
        body = response.get("Body")
        try:
            content = body.read(reference.size_bytes + 1)
        except Exception as error:
            raise ImmutableArtifactStoreError("exact S3 artifact read failed") from error
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                close()
        if type(content) is not bytes:
            raise ArtifactIntegrityError("exact S3 artifact returned invalid bytes")
        metadata = response.get("Metadata")
        if type(metadata) is not dict:
            raise ArtifactIntegrityError("exact S3 artifact metadata is missing")
        digest_hex = reference.sha256.removeprefix("sha256:")
        if (
            response.get("VersionId") != reference.version_id
            or response.get("ContentLength") != reference.size_bytes
            or response.get("ContentType") != reference.media_type
            or metadata.get("kss-sha256") != digest_hex
            or metadata.get("kss-size") != str(reference.size_bytes)
            or len(content) != reference.size_bytes
            or sha256(content).hexdigest() != digest_hex
        ):
            raise ArtifactIntegrityError(
                "exact S3 artifact does not match its authority reference"
            )
        return content

    def _head_current(
        self,
        object_key: str,
        physical_key: str,
    ) -> ExactArtifactReference | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=physical_key)
        except Exception as error:
            if _is_not_found(error):
                return None
            raise ImmutableArtifactStoreError("immutable S3 lookup failed") from error
        metadata = response.get("Metadata")
        version_id = response.get("VersionId")
        content_length = response.get("ContentLength")
        media_type = response.get("ContentType")
        if (
            type(metadata) is not dict
            or type(version_id) is not str
            or not version_id
            or type(content_length) is not int
            or type(media_type) is not str
            or type(metadata.get("kss-sha256")) is not str
            or metadata.get("kss-size") != str(content_length)
        ):
            raise ArtifactIntegrityError("immutable S3 object metadata is incomplete")
        try:
            return ExactArtifactReference(
                object_key=object_key,
                version_id=version_id,
                sha256=f"sha256:{metadata['kss-sha256']}",
                size_bytes=content_length,
                media_type=media_type,
            )
        except (KeyError, ValueError) as error:
            raise ArtifactIntegrityError("immutable S3 object metadata is invalid") from error

    def _require_same_content(
        self,
        existing: ExactArtifactReference,
        expected: ExactArtifactReference,
        content: bytes,
    ) -> None:
        if (
            existing.sha256 != expected.sha256
            or existing.size_bytes != expected.size_bytes
            or existing.media_type != expected.media_type
            or self.get_exact(existing) != content
        ):
            raise ArtifactIntegrityError(
                "immutable S3 key already contains different content"
            )

    def _physical_key(self, object_key: str) -> str:
        ExactArtifactReference(
            object_key=object_key,
            version_id="validation",
            sha256=f"sha256:{'0' * 64}",
            size_bytes=1,
            media_type="application/octet-stream",
        )
        return f"{self._key_prefix}{object_key}"


def _is_not_found(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if type(response) is not dict:
        return False
    error_body = response.get("Error")
    if type(error_body) is not dict:
        return False
    return str(error_body.get("Code")) in {"404", "NoSuchKey", "NotFound"}
