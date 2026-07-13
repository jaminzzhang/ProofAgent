"""Typed clients for private structured-parser service boundaries."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from typing import Annotated, Literal, Protocol, Self, cast

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    StrictBytes,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    KnowledgeModelCancellation,
    KnowledgeModelWorkScheduler,
    PrivateHostPolicy,
    WorkPriority,
    _HttpJsonTransport,
    _private_https_endpoint,
    decode_bounded_json_bytes,
    validate_bounded_json,
)


NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
MAX_PARSER_PAGES = 500
MAX_TRANSPORT_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_COLLECTION_ITEMS = 100_000
MAX_JSON_STRING_CHARACTERS = 1_000_000
MAX_JSON_NODES = 1_000_000


class _ParserServiceModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ParserServiceRequest(_ParserServiceModel):
    """Exact, replayable input envelope for one private parser invocation."""

    original_ref: ExactArtifactRef
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1, max_length=MAX_PARSER_PAGES)
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...] = Field(max_length=64)
    configuration_sha256: Sha256

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.original_ref.media_type != "application/pdf":
            raise ValueError("private parser input must be an application/pdf original")
        if tuple(sorted(self.page_numbers)) != self.page_numbers:
            raise ValueError("page_numbers must be strictly increasing")
        if len(set(self.page_numbers)) != len(self.page_numbers):
            raise ValueError("page_numbers must be unique")
        if len(set(self.model_digests)) != len(self.model_digests):
            raise ValueError("model_digests must be unique")
        if self.page_numbers[-1] > MAX_PARSER_PAGES:
            raise ValueError(f"page_numbers cannot exceed {MAX_PARSER_PAGES}")
        return self


class ParserServiceAttestation(_ParserServiceModel):
    """Service-produced identity and JSON payload; never synthesized from the request."""

    parser_adapter: Literal["docling", "paddle"]
    original_ref: ExactArtifactRef
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1, max_length=MAX_PARSER_PAGES)
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...] = Field(max_length=64)
    configuration_sha256: Sha256
    vendor_json_sha256: Sha256
    vendor_json_bytes: StrictBytes = Field(max_length=MAX_TRANSPORT_RESPONSE_BYTES)

    @model_validator(mode="after")
    def validate_vendor_payload(self) -> Self:
        if self.parser_adapter == "paddle" and len(self.page_numbers) != 1:
            raise ValueError("Paddle parser attestation requires exactly one page_number")
        if hashlib.sha256(self.vendor_json_bytes).hexdigest() != self.vendor_json_sha256:
            raise ValueError("vendor JSON digest must match the attested canonical bytes")
        _decode_attested_vendor_json(self)
        return self


class ParserServiceResponse(_ParserServiceModel):
    """Validated request plus the independent service-attested response envelope."""

    adapter: Literal["docling", "paddle"]
    request: ParserServiceRequest
    attestation: ParserServiceAttestation
    queue_time_ms: StrictFloat = Field(default=0.0, ge=0)
    service_time_ms: StrictFloat = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
        if self.adapter == "paddle" and len(self.request.page_numbers) != 1:
            raise ValueError("Paddle parser request requires exactly one page_number")
        if self.attestation.parser_adapter != self.adapter:
            raise ValueError("parser response adapter must match the requested private client")
        if self.attestation.original_ref != self.request.original_ref:
            raise ValueError("parser response original_ref must match the exact request")
        if self.attestation.page_numbers != self.request.page_numbers:
            raise ValueError("parser response pages must exactly match requested page_numbers")
        if self.attestation.parser_revision != self.request.parser_revision:
            raise ValueError("parser response parser_revision must match the exact request")
        if self.attestation.model_digests != self.request.model_digests:
            raise ValueError("parser response model_digests must match the exact request")
        if self.attestation.configuration_sha256 != self.request.configuration_sha256:
            raise ValueError("parser response configuration_sha256 must match the exact request")
        if self.vendor_json.get("source_sha256") != self.attestation.original_ref.sha256:
            raise ValueError("vendor JSON source_sha256 must match the service attestation")
        if _vendor_page_numbers(self.adapter, self.vendor_json) != self.attestation.page_numbers:
            raise ValueError("vendor JSON pages must exactly match the service attestation")
        return self

    @property
    def vendor_json(self) -> dict[str, JsonValue]:
        return _decode_attested_vendor_json(self.attestation)


class GuardedParserTransport(Protocol):
    """Injected private transport whose implementation owns endpoint allowlisting."""

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        follow_redirects: Literal[False],
    ) -> ParserServiceAttestation: ...

    def parse_scheduled(
        self,
        request: ParserServiceRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> ParserServiceAttestation: ...


class PrivateParserClient(Protocol):
    scheduler: KnowledgeModelWorkScheduler

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        priority: WorkPriority = "offline",
        timeout_seconds: float = 120.0,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ParserServiceResponse: ...


class _PrivateParserClient:
    adapter: Literal["docling", "paddle"]

    def __init__(
        self,
        *,
        transport: GuardedParserTransport,
        scheduler: KnowledgeModelWorkScheduler,
    ) -> None:
        self._transport = transport
        self.scheduler = scheduler

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        priority: WorkPriority = "offline",
        timeout_seconds: float = 120.0,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ParserServiceResponse:
        if self.adapter == "paddle" and len(request.page_numbers) != 1:
            raise ValueError("Paddle parser request requires exactly one page_number")
        scheduled = self.scheduler.submit_and_wait(
            kind="ocr" if self.adapter == "paddle" else "docling",
            priority=priority,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
            operation=lambda remaining, scheduled_cancellation: self._parse_transport(
                request,
                timeout_seconds=remaining,
                cancellation=scheduled_cancellation,
            ),
        )
        return ParserServiceResponse(
            adapter=self.adapter,
            request=request,
            attestation=scheduled.value,
            queue_time_ms=scheduled.queue_time_ms,
            service_time_ms=scheduled.service_time_ms,
        )

    def _parse_transport(
        self,
        request: ParserServiceRequest,
        *,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation,
    ) -> ParserServiceAttestation:
        scheduled_parse = getattr(self._transport, "parse_scheduled", None)
        if callable(scheduled_parse):
            operation = cast(
                Callable[..., ParserServiceAttestation],
                scheduled_parse,
            )
            return operation(
                request,
                timeout_seconds=timeout_seconds,
                follow_redirects=False,
                allow_runtime_downloads=False,
                cancellation=cancellation,
            )
        # Compatibility for the pre-Task-13 fake transport interface. It is still
        # invoked only after scheduler admission and cannot be used by production
        # composition, which constructs HttpParserTransport below.
        return self._transport.parse(request, follow_redirects=False)


def _vendor_page_numbers(
    adapter: Literal["docling", "paddle"], payload: dict[str, JsonValue]
) -> tuple[int, ...]:
    if adapter == "docling":
        pages = payload.get("pages")
        if not isinstance(pages, list):
            raise ValueError("Docling response must contain a pages array")
        if len(pages) > MAX_PARSER_PAGES:
            raise ValueError("Docling response exceeds the page limit")
        return tuple(_page_number(page) for page in pages)
    page = payload.get("page")
    if isinstance(page, dict) and "pages" not in payload:
        return (_page_number(page),)
    raise ValueError("Paddle response must contain exactly one singular page object")


def canonical_vendor_json_bytes(payload: dict[str, JsonValue]) -> bytes:
    """Return the only accepted deterministic wire representation for vendor JSON."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _decode_attested_vendor_json(
    attestation: ParserServiceAttestation,
) -> dict[str, JsonValue]:
    value = decode_bounded_json_bytes(attestation.vendor_json_bytes)
    if not isinstance(value, dict):
        raise ValueError("vendor response root must be a JSON object")
    validate_bounded_json(value)
    _validate_json_bounds(value)
    if canonical_vendor_json_bytes(value) != attestation.vendor_json_bytes:
        raise ValueError("vendor response bytes must use canonical JSON encoding")
    return value


def _validate_json_bounds(value: JsonValue) -> None:
    pending: list[tuple[JsonValue, int]] = [(value, 1)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > MAX_JSON_NODES:
            raise ValueError("vendor JSON exceeds the node limit")
        if depth > MAX_JSON_DEPTH:
            raise ValueError("vendor JSON exceeds the nesting-depth limit")
        if isinstance(current, str):
            if len(current) > MAX_JSON_STRING_CHARACTERS:
                raise ValueError("vendor JSON string exceeds the character limit")
        elif isinstance(current, list):
            if len(current) > MAX_JSON_COLLECTION_ITEMS:
                raise ValueError("vendor JSON array exceeds the item limit")
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            if len(current) > MAX_JSON_COLLECTION_ITEMS:
                raise ValueError("vendor JSON object exceeds the item limit")
            for key, item in current.items():
                if len(key) > MAX_JSON_STRING_CHARACTERS:
                    raise ValueError("vendor JSON key exceeds the character limit")
                pending.append((item, depth + 1))
        elif isinstance(current, float) and not math.isfinite(current):
            raise ValueError("vendor JSON numbers must be finite")


def _page_number(value: JsonValue) -> int:
    if not isinstance(value, dict):
        raise ValueError("parser response page entries must be JSON objects")
    page_number = value.get("page_number")
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or not 1 <= page_number <= MAX_PARSER_PAGES
    ):
        raise ValueError(f"parser response page_number must be between 1 and {MAX_PARSER_PAGES}")
    return page_number


class PrivateDoclingClient(_PrivateParserClient):
    adapter: Literal["docling"] = "docling"


class PrivatePaddleClient(_PrivateParserClient):
    adapter: Literal["paddle"] = "paddle"


class HttpParserTransport(_HttpJsonTransport):
    """Guarded no-redirect HTTP transport for a private parser service."""

    def __init__(self, *, endpoint: str, allowed_hosts: PrivateHostPolicy) -> None:
        super().__init__(max_response_bytes=MAX_TRANSPORT_RESPONSE_BYTES)
        self._endpoint = _private_https_endpoint(
            endpoint,
            field="parser endpoint",
            allowed_hosts=allowed_hosts,
        )

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        follow_redirects: Literal[False],
    ) -> ParserServiceAttestation:
        return self.parse_scheduled(
            request,
            timeout_seconds=120.0,
            follow_redirects=follow_redirects,
            allow_runtime_downloads=False,
            cancellation=KnowledgeModelCancellation(),
        )

    def parse_scheduled(
        self,
        request: ParserServiceRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> ParserServiceAttestation:
        if follow_redirects is not False or allow_runtime_downloads is not False:
            raise ValueError("parser redirects and runtime downloads are forbidden")
        payload = request.model_dump(mode="json")
        payload["allow_runtime_downloads"] = False
        raw = self._post(
            f"{self._endpoint}/v1/parse",
            payload,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
        if not isinstance(raw, dict):
            raise ValueError("private parser response root must be a JSON object")
        vendor_json = raw.pop("vendor_json", None)
        if not isinstance(vendor_json, dict):
            raise ValueError("private parser response requires a vendor_json object")
        vendor_bytes = canonical_vendor_json_bytes(cast(dict[str, JsonValue], vendor_json))
        raw["vendor_json_bytes"] = vendor_bytes
        return ParserServiceAttestation.model_validate(raw)
