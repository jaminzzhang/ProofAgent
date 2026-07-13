"""Typed clients for private structured-parser service boundaries."""

from __future__ import annotations

from typing import Annotated, Literal, Mapping, Protocol, Self

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


class ParserServiceResponse(_ParserServiceModel):
    """Request-bound JSON response; vendor SDK classes cannot cross this boundary."""

    adapter: Literal["docling", "paddle"]
    request: ParserServiceRequest
    vendor_json: dict[str, JsonValue]


class GuardedParserTransport(Protocol):
    """Injected private transport whose implementation owns endpoint allowlisting."""

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        follow_redirects: Literal[False],
    ) -> Mapping[str, JsonValue]: ...


class PrivateParserClient(Protocol):
    def parse(self, request: ParserServiceRequest) -> ParserServiceResponse: ...


class _PrivateParserClient:
    adapter: Literal["docling", "paddle"]

    def __init__(self, *, transport: GuardedParserTransport) -> None:
        self._transport = transport

    def parse(self, request: ParserServiceRequest) -> ParserServiceResponse:
        vendor_payload = self._transport.parse(request, follow_redirects=False)
        self._validate_payload_identity(request, vendor_payload)
        return ParserServiceResponse(
            adapter=self.adapter,
            request=request,
            vendor_json=dict(vendor_payload),
        )

    def _validate_payload_identity(
        self,
        request: ParserServiceRequest,
        payload: Mapping[str, JsonValue],
    ) -> None:
        if payload.get("source_sha256") != request.original_ref.sha256:
            raise ValueError(
                "parser response source_sha256 must match the exact original reference"
            )
        if self.adapter == "docling":
            pages = payload.get("pages")
            if not isinstance(pages, list):
                raise ValueError("Docling response must contain a pages array")
            returned_pages = tuple(_page_number(page) for page in pages)
        else:
            page = payload.get("page")
            pages = payload.get("pages")
            if isinstance(page, dict):
                returned_pages = (_page_number(page),)
            elif isinstance(pages, list):
                returned_pages = tuple(_page_number(item) for item in pages)
            else:
                raise ValueError("Paddle response must contain a page object or pages array")
        if returned_pages != request.page_numbers:
            raise ValueError("parser response pages must exactly match requested page_numbers")


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
