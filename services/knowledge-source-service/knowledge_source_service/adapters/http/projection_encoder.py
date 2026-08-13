"""Private HTTP Dense and learned-Sparse projection encoder adapter."""

from __future__ import annotations

import ipaddress
import json
from math import isfinite
import re
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, ValidationError

from knowledge_source_service.application.projection_encoding import (
    EncodedProjectionText,
)
from knowledge_source_service.contracts.base import NonBlankText, StrictContract


_MAX_REQUEST_TEXT_BYTES = 256 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SPARSE_FEATURE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class ProjectionEncoderError(RuntimeError):
    """The private encoder failed or violated its pinned contract."""


class _EncodingResponse(StrictContract):
    schema_version: Literal["knowledge-projection-encoding.v1"]
    dense_revision: NonBlankText
    sparse_revision: NonBlankText
    dense_dimension: int = Field(gt=0, le=4096)
    dense_vector: tuple[float, ...] = Field(min_length=1, max_length=4096)
    sparse_vector: dict[str, float] = Field(min_length=1, max_length=1024)


class HttpProjectionTextEncoder:
    """Encode text through one pinned private model service without fallback."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        dense_revision: str,
        sparse_revision: str,
        dense_dimension: int,
        ca_file: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        _validate_endpoint(endpoint)
        if (
            len(bearer_token) < 16
            or bearer_token != bearer_token.strip()
            or any(character.isspace() for character in bearer_token)
        ):
            raise ValueError("projection encoder Bearer credential is invalid")
        if not dense_revision.strip() or not sparse_revision.strip():
            raise ValueError("projection encoder revisions must not be blank")
        if dense_dimension < 4 or dense_dimension > 4096:
            raise ValueError("dense_dimension must be between 4 and 4096")
        self._endpoint = endpoint
        self.dense_revision = dense_revision
        self.sparse_revision = sparse_revision
        self.dense_dimension = dense_dimension
        self._client = httpx.Client(
            timeout=httpx.Timeout(30, connect=3),
            follow_redirects=False,
            trust_env=False,
            verify=True if ca_file is None else ca_file,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer_token}",
            },
        )

    def close(self) -> None:
        self._client.close()

    def encode(self, text: str) -> EncodedProjectionText:
        if (
            not text.strip()
            or len(text.encode("utf-8")) > _MAX_REQUEST_TEXT_BYTES
        ):
            raise ValueError("projection encoder text is blank or exceeds its bound")
        try:
            with self._client.stream(
                "POST",
                self._endpoint,
                json={
                    "schema_version": "knowledge-projection-encoding-request.v1",
                    "text": text,
                    "dense_revision": self.dense_revision,
                    "sparse_revision": self.sparse_revision,
                    "dense_dimension": self.dense_dimension,
                },
            ) as response:
                if response.status_code != 200:
                    raise ProjectionEncoderError(
                        "projection encoder returned a non-success status"
                    )
                if response.headers.get("Content-Type", "").partition(";")[0].casefold() != (
                    "application/json"
                ):
                    raise ProjectionEncoderError(
                        "projection encoder returned an invalid media type"
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise ProjectionEncoderError(
                            "projection encoder response exceeded its bound"
                        )
        except ProjectionEncoderError:
            raise
        except httpx.HTTPError as error:
            raise ProjectionEncoderError("projection encoder request failed") from error
        try:
            encoded = _EncodingResponse.model_validate(json.loads(content))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise ProjectionEncoderError(
                "projection encoder returned an invalid response"
            ) from error
        if (
            encoded.dense_revision != self.dense_revision
            or encoded.sparse_revision != self.sparse_revision
            or encoded.dense_dimension != self.dense_dimension
            or len(encoded.dense_vector) != self.dense_dimension
            or not all(isfinite(value) for value in encoded.dense_vector)
            or not any(value != 0 for value in encoded.dense_vector)
            or any(
                _SPARSE_FEATURE.fullmatch(feature) is None
                or not isfinite(weight)
                or weight <= 0
                for feature, weight in encoded.sparse_vector.items()
            )
        ):
            raise ProjectionEncoderError(
                "projection encoder output does not match its pinned configuration"
            )
        return EncodedProjectionText(
            dense_vector=encoded.dense_vector,
            sparse_vector=encoded.sparse_vector,
        )


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("projection encoder endpoint is invalid")
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback:
        raise ValueError("non-loopback projection encoder endpoint must use HTTPS")
