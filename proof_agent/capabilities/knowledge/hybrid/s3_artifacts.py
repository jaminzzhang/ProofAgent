"""Exact-version S3 storage for authoritative Hybrid Knowledge artifacts."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from proof_agent.contracts.knowledge_index import ExactArtifactRef


_KEY = re.compile(r"^hybrid-manifests/(?:roots|shards)/(?P<digest>[0-9a-f]{64})\.json$")


class S3ArtifactError(RuntimeError):
    """An exact immutable artifact operation failed closed."""


class S3ExactArtifactStore:
    """Content-addressed object adapter which never treats ETag as a digest."""

    def __init__(self, *, client: Any, bucket: str, key_prefix: str = "") -> None:
        if not bucket or any(ord(char) < 33 for char in bucket):
            raise ValueError("S3 bucket name is invalid")
        self._client = client
        self._bucket = bucket
        if key_prefix and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}/", key_prefix) is None:
            raise ValueError("S3 artifact key prefix is invalid")
        if ".." in key_prefix or "//" in key_prefix or any(ord(char) < 32 for char in key_prefix):
            raise ValueError("S3 artifact key prefix is invalid")
        self._key_prefix = key_prefix
        try:
            status = client.get_bucket_versioning(Bucket=bucket)
        except Exception as exc:
            raise S3ArtifactError("S3 bucket versioning could not be verified") from exc
        if status.get("Status") != "Enabled":
            raise S3ArtifactError("S3 bucket versioning must be enabled")

    @classmethod
    def from_environment(
        cls,
        *,
        bucket: str,
        key_prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        allow_endpoint_proxy: bool = False,
        allow_insecure_endpoint: bool = False,
    ) -> S3ExactArtifactStore:
        """Construct lazily with custom endpoints direct unless proxying is explicit."""

        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Hybrid production artifact storage requires the 'production' extra"
            ) from exc
        if endpoint_url is not None:
            parsed = urlsplit(endpoint_url)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("custom S3 endpoint is invalid")
            loopback = parsed.hostname == "localhost"
            try:
                loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                pass
            if parsed.scheme == "http" and not loopback and not allow_insecure_endpoint:
                raise ValueError("non-loopback custom S3 HTTP endpoint requires explicit opt-in")
        client_kwargs: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "region_name": region_name,
        }
        if endpoint_url is not None and not allow_endpoint_proxy:
            try:
                from botocore.config import Config  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - boto3 depends on botocore
                raise RuntimeError("Hybrid S3 client configuration is unavailable") from exc
            client_kwargs["config"] = Config(proxies={})
        client = boto3.client("s3", **client_kwargs)
        try:
            return cls(client=client, bucket=bucket, key_prefix=key_prefix)
        except BaseException:
            close = getattr(client, "close", None)
            if close is not None:
                close()
            raise

    def put_immutable(
        self,
        *,
        key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactRef:
        match = _KEY.fullmatch(key)
        if match is None or any(char in key for char in ("..", "\\", "\x00", "\r", "\n")):
            raise S3ArtifactError("artifact key is not a system-generated manifest key")
        if type(content) is not bytes or not content:
            raise S3ArtifactError("artifact content must be nonempty exact bytes")
        if not media_type or len(media_type) > 255:
            raise S3ArtifactError("artifact media type is invalid")
        digest = hashlib.sha256(content).hexdigest()
        if match.group("digest") != digest:
            raise S3ArtifactError("artifact key does not match exact content digest")

        physical_key = self._physical_key(key)
        existing = self._head_current(physical_key)
        if existing is not None:
            ref = self._ref_from_head(physical_key, existing, expected_media_type=media_type)
            if ref.sha256 != digest or ref.size_bytes != len(content):
                raise S3ArtifactError("immutable artifact key already contains different content")
            if self.get_exact(ref) != content:
                raise S3ArtifactError("immutable artifact content verification failed")
            return ref
        try:
            response = self._client.put_object(
                Bucket=self._bucket,
                Key=physical_key,
                Body=content,
                ContentType=media_type,
                Metadata={"proofagent-sha256": digest},
                IfNoneMatch="*",
            )
        except Exception as exc:
            # A racing create is safe only after exact verification.
            existing = self._head_current(physical_key)
            if existing is None:
                raise S3ArtifactError("immutable artifact write failed") from exc
            ref = self._ref_from_head(physical_key, existing, expected_media_type=media_type)
            if (
                ref.sha256 != digest
                or ref.size_bytes != len(content)
                or self.get_exact(ref) != content
            ):
                raise S3ArtifactError("immutable artifact create conflict") from exc
            return ref
        version_id = response.get("VersionId")
        if type(version_id) is not str or not version_id:
            raise S3ArtifactError("versioned S3 write did not return an opaque VersionId")
        ref = ExactArtifactRef(
            artifact_uri=self._uri(physical_key),
            version_id=version_id,
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
        )
        if self.get_exact(ref) != content:
            raise S3ArtifactError("written artifact failed exact read-back verification")
        return ref

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        key = self._key_from_ref(ref)
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=key,
                VersionId=ref.version_id,
            )
            body = response["Body"].read(ref.size_bytes + 1)
        except Exception as exc:
            raise S3ArtifactError("exact artifact version is unavailable") from exc
        if type(body) is not bytes or len(body) != ref.size_bytes:
            raise S3ArtifactError("exact artifact length does not match authority reference")
        if response.get("ContentLength") != ref.size_bytes:
            raise S3ArtifactError("exact artifact metadata length does not match")
        if response.get("ContentType") != ref.media_type:
            raise S3ArtifactError("exact artifact media type does not match")
        if response.get("VersionId") != ref.version_id:
            raise S3ArtifactError("exact artifact VersionId does not match")
        metadata = response.get("Metadata")
        if not isinstance(metadata, dict) or metadata.get("proofagent-sha256") != ref.sha256:
            raise S3ArtifactError("exact artifact digest metadata does not match")
        if hashlib.sha256(body).hexdigest() != ref.sha256:
            raise S3ArtifactError("exact artifact bytes are corrupt")
        return body

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()

    def _head_current(self, key: str) -> dict[str, object] | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            response = getattr(exc, "response", None)
            error = response.get("Error") if isinstance(response, dict) else None
            code = error.get("Code") if isinstance(error, dict) else None
            if code in {"404", "NoSuchKey", "NotFound"} or isinstance(exc, KeyError):
                return None
            raise S3ArtifactError("immutable artifact lookup failed") from exc
        return dict(response)

    def _ref_from_head(
        self,
        key: str,
        head: dict[str, object],
        *,
        expected_media_type: str,
    ) -> ExactArtifactRef:
        version_id = head.get("VersionId")
        length = head.get("ContentLength")
        metadata = head.get("Metadata")
        media_type = head.get("ContentType")
        if (
            type(version_id) is not str
            or not version_id
            or type(length) is not int
            or not isinstance(metadata, dict)
            or type(metadata.get("proofagent-sha256")) is not str
            or media_type != expected_media_type
        ):
            raise S3ArtifactError("stored artifact metadata is incomplete")
        return ExactArtifactRef(
            artifact_uri=self._uri(key),
            version_id=version_id,
            sha256=metadata["proofagent-sha256"],
            size_bytes=length,
            media_type=expected_media_type,
        )

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{quote(key, safe='/')}"

    def _key_from_ref(self, ref: ExactArtifactRef) -> str:
        parsed = urlsplit(ref.artifact_uri)
        physical_key = unquote(parsed.path.lstrip("/"))
        if not physical_key.startswith(self._key_prefix):
            raise S3ArtifactError("artifact reference is outside the configured authority prefix")
        key = physical_key[len(self._key_prefix) :]
        if parsed.scheme != "s3" or parsed.netloc != self._bucket or _KEY.fullmatch(key) is None:
            raise S3ArtifactError("artifact reference is outside the configured authority bucket")
        return physical_key

    def _physical_key(self, logical_key: str) -> str:
        return self._key_prefix + logical_key
