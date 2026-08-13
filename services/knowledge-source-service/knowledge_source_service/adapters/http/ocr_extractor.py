"""Private HTTP OCR adapter with pinned revision and quality gate."""

from __future__ import annotations

import base64
import ipaddress
import json
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, ValidationError

from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.ports.ocr import OcrDocument, OcrPage, OcrRegion


_MAX_REQUEST_BYTES = 50 * 1024 * 1024
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_OCR_MEDIA_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/tiff"}


class OcrExtractorError(RuntimeError):
    """The private OCR service failed or violated its pinned contract."""


class _BoundingBox(StrictContract):
    x_min: int = Field(ge=0)
    y_min: int = Field(ge=0)
    x_max: int = Field(ge=1)
    y_max: int = Field(ge=1)


class _OcrRegionResponse(StrictContract):
    page_number: int = Field(ge=1, le=1000)
    bounding_box: _BoundingBox
    text: NonBlankText
    confidence: float = Field(ge=0, le=1)


class _OcrPageResponse(StrictContract):
    page_number: int = Field(ge=1, le=1000)
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)


class _OcrResponse(StrictContract):
    schema_version: Literal["knowledge-document-ocr.v1"]
    model_revision: NonBlankText
    quality_state: Literal["passed"]
    pages: tuple[_OcrPageResponse, ...] = Field(default=(), max_length=1000)
    regions: tuple[_OcrRegionResponse, ...] = Field(
        min_length=1,
        max_length=100_000,
    )


class HttpDocumentOcrExtractor:
    """Extract reviewed OCR regions through one private, pinned model endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        model_revision: str,
        ca_file: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        _validate_endpoint(endpoint)
        if (
            len(bearer_token) < 16
            or bearer_token != bearer_token.strip()
            or any(character.isspace() for character in bearer_token)
        ):
            raise ValueError("OCR Bearer credential is invalid")
        if not model_revision.strip():
            raise ValueError("OCR model revision must not be blank")
        self._endpoint = endpoint
        self._model_revision = model_revision
        self._client = httpx.Client(
            timeout=httpx.Timeout(60, connect=3),
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

    def extract(self, *, media_type: str, content: bytes) -> OcrDocument:
        if media_type not in _OCR_MEDIA_TYPES:
            raise ValueError("OCR media type is unsupported")
        if type(content) is not bytes or not content or len(content) > _MAX_REQUEST_BYTES:
            raise ValueError("OCR content is empty or exceeds its bound")
        try:
            with self._client.stream(
                "POST",
                self._endpoint,
                json={
                    "schema_version": "knowledge-document-ocr-request.v1",
                    "media_type": media_type,
                    "content_base64": base64.b64encode(content).decode("ascii"),
                    "model_revision": self._model_revision,
                },
            ) as response:
                if response.status_code != 200:
                    raise OcrExtractorError("OCR service returned a non-success status")
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.casefold() != "application/json":
                    raise OcrExtractorError("OCR service returned an invalid media type")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise OcrExtractorError("OCR response exceeded its bound")
        except OcrExtractorError:
            raise
        except httpx.HTTPError as error:
            raise OcrExtractorError("OCR request failed") from error
        try:
            payload = _OcrResponse.model_validate(json.loads(body))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise OcrExtractorError("OCR service returned an invalid response") from error
        if payload.model_revision != self._model_revision:
            raise OcrExtractorError("OCR response revision does not match the request")
        try:
            return OcrDocument(
                model_revision=payload.model_revision,
                pages=tuple(
                    OcrPage(
                        page_number=page.page_number,
                        width=page.width,
                        height=page.height,
                    )
                    for page in payload.pages
                ),
                regions=tuple(
                    OcrRegion(
                        page_number=region.page_number,
                        x_min=region.bounding_box.x_min,
                        y_min=region.bounding_box.y_min,
                        x_max=region.bounding_box.x_max,
                        y_max=region.bounding_box.y_max,
                        text=region.text,
                    )
                    for region in payload.regions
                ),
            )
        except ValueError as error:
            raise OcrExtractorError("OCR regions failed integrity validation") from error


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
        raise ValueError("OCR endpoint is invalid")
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback:
        raise ValueError("non-loopback OCR endpoint must use HTTPS")
