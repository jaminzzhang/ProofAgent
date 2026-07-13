"""Typed clients for private structured-parser service boundaries."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.knowledge_index import ExactArtifactRef


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class _ParserServiceModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ParserServiceRequest(_ParserServiceModel):
    """Exact, replayable input envelope for one private parser invocation."""

    original_ref: ExactArtifactRef
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1)
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...]
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
        return self


class ParserServiceAttestation(_ParserServiceModel):
    """Service-produced identity and JSON payload; never synthesized from the request."""

    parser_adapter: Literal["docling", "paddle"]
    original_ref: ExactArtifactRef
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1)
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...]
    configuration_sha256: Sha256
    vendor_json: dict[str, JsonValue]


class ParserServiceResponse(_ParserServiceModel):
    """Validated request plus the independent service-attested response envelope."""

    adapter: Literal["docling", "paddle"]
    request: ParserServiceRequest
    attestation: ParserServiceAttestation

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
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
        return self.attestation.vendor_json


class GuardedParserTransport(Protocol):
    """Injected private transport whose implementation owns endpoint allowlisting."""

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        follow_redirects: Literal[False],
    ) -> ParserServiceAttestation: ...


class PrivateParserClient(Protocol):
    def parse(self, request: ParserServiceRequest) -> ParserServiceResponse: ...


class _PrivateParserClient:
    adapter: Literal["docling", "paddle"]

    def __init__(self, *, transport: GuardedParserTransport) -> None:
        self._transport = transport

    def parse(self, request: ParserServiceRequest) -> ParserServiceResponse:
        attestation = self._transport.parse(request, follow_redirects=False)
        return ParserServiceResponse(
            adapter=self.adapter,
            request=request,
            attestation=attestation,
        )


def _vendor_page_numbers(
    adapter: Literal["docling", "paddle"], payload: dict[str, JsonValue]
) -> tuple[int, ...]:
    if adapter == "docling":
        pages = payload.get("pages")
        if not isinstance(pages, list):
            raise ValueError("Docling response must contain a pages array")
        return tuple(_page_number(page) for page in pages)
    page = payload.get("page")
    pages = payload.get("pages")
    if isinstance(page, dict):
        return (_page_number(page),)
    if isinstance(pages, list):
        return tuple(_page_number(item) for item in pages)
    raise ValueError("Paddle response must contain a page object or pages array")


def _page_number(value: JsonValue) -> int:
    if not isinstance(value, dict):
        raise ValueError("parser response page entries must be JSON objects")
    page_number = value.get("page_number")
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number <= 0:
        raise ValueError("parser response page_number must be a positive integer")
    return page_number


class PrivateDoclingClient(_PrivateParserClient):
    adapter: Literal["docling"] = "docling"


class PrivatePaddleClient(_PrivateParserClient):
    adapter: Literal["paddle"] = "paddle"
