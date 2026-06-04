from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self, cast
from urllib import error, parse, request

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError

REMOTE_RETRIEVAL_PROTOCOL_VERSION = "proof-agent.remote-retrieval.v1"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_TOP_K = 5
MAX_TOP_K = 50


@dataclass(frozen=True)
class HttpJsonRequest:
    endpoint: str
    method: Literal["GET", "POST"]
    headers: Mapping[str, str]
    query_params: Mapping[str, str]
    json_body: Mapping[str, Any] | None
    timeout_seconds: float


HttpJsonTransport = Callable[[HttpJsonRequest], Mapping[str, Any]]


@dataclass(frozen=True)
class _HeaderEnvRef:
    name: str
    value_env: str
    prefix: str = ""


@dataclass(frozen=True)
class _StaticHeader:
    name: str
    value: str


class HttpJsonProvider:
    """Trusted HTTP JSON remote retrieval adapter."""

    def __init__(
        self,
        *,
        endpoint: str,
        method: str = "POST",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        default_top_k: int = DEFAULT_TOP_K,
        header_env_refs: tuple[_HeaderEnvRef, ...] = (),
        static_headers: tuple[_StaticHeader, ...] = (),
        request_mapping: Mapping[str, Any] | None = None,
        response_mapping: Mapping[str, Any] | None = None,
        transport: HttpJsonTransport | None = None,
    ) -> None:
        self.endpoint = _normalize_endpoint(endpoint)
        self._method = _normalize_method(method)
        self._timeout_seconds = _normalize_timeout(timeout_seconds)
        self._default_top_k = _normalize_top_k(default_top_k)
        self._header_env_refs = header_env_refs
        self._static_headers = static_headers
        self._request_mapping = dict(request_mapping) if request_mapping is not None else None
        self._response_mapping = dict(response_mapping) if response_mapping is not None else None
        self._transport = transport or _send_http_json_request

    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self:
        params = knowledge_config.params
        return cls(
            endpoint=_required_string_param(params, "endpoint"),
            method=_optional_string_param(params, "method", "POST"),
            timeout_seconds=_optional_float_param(
                params,
                "timeout_seconds",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            default_top_k=_optional_int_param(params, "top_k", DEFAULT_TOP_K),
            header_env_refs=_normalize_header_env_refs(params.get("header_env_refs")),
            static_headers=_normalize_static_headers(params.get("headers")),
            request_mapping=_optional_mapping_param(params.get("request_mapping"), "request_mapping"),
            response_mapping=_optional_mapping_param(
                params.get("response_mapping"),
                "response_mapping",
            ),
        )

    @property
    def provider_name(self) -> str:
        return "http_json"

    @property
    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities()

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        effective_top_k = _normalize_top_k(top_k if top_k is not None else self._default_top_k)
        http_request = self._build_request(query=query, top_k=effective_top_k)
        response = self._transport(http_request)
        if not isinstance(response, Mapping):
            raise _invalid_http_json_response("http_json response must be a JSON object.")
        return self._normalize_response(response, limit=effective_top_k)

    def _build_request(self, *, query: str, top_k: int) -> HttpJsonRequest:
        headers = self._headers()
        if self._method == "POST":
            headers.setdefault("Content-Type", "application/json")
        if self._request_mapping is None:
            if self._method == "GET":
                return HttpJsonRequest(
                    endpoint=self.endpoint,
                    method=self._method,
                    headers=headers,
                    query_params={"query": query, "top_k": str(top_k)},
                    json_body=None,
                    timeout_seconds=self._timeout_seconds,
                )
            return HttpJsonRequest(
                endpoint=self.endpoint,
                method=self._method,
                headers=headers,
                query_params={},
                json_body={"query": query, "top_k": top_k},
                timeout_seconds=self._timeout_seconds,
            )

        query_params = _render_query_params(
            self._request_mapping.get("query_params"),
            query=query,
            top_k=top_k,
        )
        json_body = _render_json_body(
            self._request_mapping.get("json_body"),
            query=query,
            top_k=top_k,
        )
        return HttpJsonRequest(
            endpoint=self.endpoint,
            method=self._method,
            headers=headers,
            query_params=query_params,
            json_body=json_body,
            timeout_seconds=self._timeout_seconds,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        for static_header in self._static_headers:
            headers[static_header.name] = static_header.value
        for header_ref in self._header_env_refs:
            value = os.environ.get(header_ref.value_env)
            if value is None:
                raise ProofAgentError(
                    "PA_KNOWLEDGE_002",
                    f"http_json header environment variable is not set: {header_ref.value_env}",
                    "Set the referenced environment variable before retrieving remote knowledge.",
                )
            headers[header_ref.name] = f"{header_ref.prefix}{value}"
        return headers

    def _normalize_response(
        self,
        response: Mapping[str, Any],
        *,
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        mapping = self._response_mapping
        if mapping is None:
            version = response.get("protocol_version")
            if version != REMOTE_RETRIEVAL_PROTOCOL_VERSION:
                raise _invalid_http_json_response(
                    "http_json default protocol response requires "
                    f"protocol_version={REMOTE_RETRIEVAL_PROTOCOL_VERSION}."
                )
            mapping = {
                "results": "/results",
                "id": "/id",
                "source": "/source",
                "content": "/content",
                "score": "/score",
                "citation": "/citation",
                "metadata": "/metadata",
                "source_ref": "/source_ref",
            }
            upstream_revision = _optional_string(response.get("upstream_revision"))
        else:
            upstream_revision = _optional_top_level_mapping_string(
                response,
                mapping,
                "upstream_revision",
            )

        results = _required_pointer_value(
            response,
            _required_mapping_pointer(mapping, "results"),
            label="http_json response results",
        )
        if not isinstance(results, list | tuple):
            raise _invalid_http_json_response("http_json response results pointer must resolve to a list.")

        chunks: list[EvidenceChunk] = []
        for item in results[:limit]:
            chunks.append(
                _normalize_result_item(
                    item,
                    mapping=mapping,
                    upstream_revision=upstream_revision,
                )
            )
        return tuple(chunks)


def _normalize_result_item(
    item: Any,
    *,
    mapping: Mapping[str, Any],
    upstream_revision: str | None,
) -> EvidenceChunk:
    if not isinstance(item, Mapping):
        raise _invalid_http_json_response("http_json result item must be a JSON object.")
    content = _required_item_string(item, mapping, "content", "http_json result content")
    score = _required_item_float(item, mapping, "score", "http_json result score")
    citation = _optional_item_string(item, mapping, "citation")
    source_ref = _optional_item_mapping(item, mapping, "source_ref")
    if citation is None and source_ref is not None:
        citation = _citation_from_source_ref(source_ref)
    if citation is None:
        raise _invalid_http_json_response(
            "http_json result requires citation or adequate source_ref."
        )
    source = _optional_item_string(item, mapping, "source") or citation
    metadata = _result_metadata(item, mapping, source_ref=source_ref, upstream_revision=upstream_revision)
    return EvidenceChunk(
        source=source,
        content=content,
        provider_name="http_json",
        provider_native_score=score,
        admission_score=score,
        status=EvidenceStatus.CANDIDATE,
        citation=citation,
        metadata=metadata,
    )


def _result_metadata(
    item: Mapping[str, Any],
    mapping: Mapping[str, Any],
    *,
    source_ref: Mapping[str, Any] | None,
    upstream_revision: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    mapped_metadata = _optional_item_mapping(item, mapping, "metadata")
    if mapped_metadata is not None:
        metadata.update(_safe_metadata(mapped_metadata))
    if source_ref is not None:
        metadata.update(_safe_metadata(source_ref))
    if upstream_revision is not None:
        metadata["upstream_revision"] = upstream_revision
    return metadata


def _send_http_json_request(http_request: HttpJsonRequest) -> Mapping[str, Any]:
    url = _with_query_params(http_request.endpoint, http_request.query_params)
    body = None
    if http_request.json_body is not None:
        body = json.dumps(http_request.json_body).encode("utf-8")
    urllib_request = request.Request(
        url,
        data=body,
        headers=dict(http_request.headers),
        method=http_request.method,
    )
    try:
        with request.urlopen(urllib_request, timeout=http_request.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            f"http_json endpoint returned HTTP {exc.code}",
            "Check the remote Knowledge Source endpoint and credentials.",
        ) from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "http_json endpoint did not return valid JSON.",
            "Check the remote Knowledge Source endpoint, network, and response contract.",
        ) from exc
    if not isinstance(payload, Mapping):
        raise _invalid_http_json_response("http_json endpoint response must be a JSON object.")
    return payload


def _with_query_params(endpoint: str, query_params: Mapping[str, str]) -> str:
    if not query_params:
        return endpoint
    parsed = parse.urlsplit(endpoint)
    existing = parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = parse.urlencode((*existing, *query_params.items()))
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _normalize_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise _invalid_http_json_config("http_json endpoint must be an absolute http(s) URL.")
    return value


def _normalize_method(method: str) -> Literal["GET", "POST"]:
    value = method.strip().upper()
    if value not in {"GET", "POST"}:
        raise _invalid_http_json_config("http_json method must be GET or POST.")
    return cast(Literal["GET", "POST"], value)


def _normalize_timeout(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0 or timeout_seconds > 60:
        raise _invalid_http_json_config("http_json timeout_seconds must be greater than 0 and at most 60.")
    return float(timeout_seconds)


def _normalize_top_k(top_k: int) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise _invalid_http_json_config(f"http_json top_k must be an integer from 1 through {MAX_TOP_K}.")
    return top_k


def _required_string_param(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_http_json_config(f"http_json params.{key} must be a non-empty string.")
    return value


def _optional_string_param(params: Mapping[str, Any], key: str, default: str) -> str:
    value = params.get(key, default)
    if not isinstance(value, str):
        raise _invalid_http_json_config(f"http_json params.{key} must be a string.")
    return value


def _optional_float_param(params: Mapping[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid_http_json_config(f"http_json params.{key} must be a number.")
    return float(value)


def _optional_int_param(params: Mapping[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid_http_json_config(f"http_json params.{key} must be an integer.")
    return value


def _optional_mapping_param(value: Any, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid_http_json_config(f"http_json params.{name} must be an object.")
    return value


def _normalize_header_env_refs(value: Any) -> tuple[_HeaderEnvRef, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise _invalid_http_json_config("http_json params.header_env_refs must be a list.")
    refs: list[_HeaderEnvRef] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise _invalid_http_json_config("http_json header_env_refs entries must be objects.")
        refs.append(
            _HeaderEnvRef(
                name=_required_mapping_string(item, "name", "http_json header_env_refs.name"),
                value_env=_required_mapping_string(
                    item,
                    "value_env",
                    "http_json header_env_refs.value_env",
                ),
                prefix=_optional_mapping_string(item, "prefix", ""),
            )
        )
    return tuple(refs)


def _normalize_static_headers(value: Any) -> tuple[_StaticHeader, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise _invalid_http_json_config("http_json params.headers must be a list.")
    headers: list[_StaticHeader] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise _invalid_http_json_config("http_json headers entries must be objects.")
        name = _required_mapping_string(item, "name", "http_json headers.name")
        if _header_name_is_sensitive(name):
            raise _invalid_http_json_config(
                "http_json sensitive headers must use header_env_refs, not static headers."
            )
        headers.append(
            _StaticHeader(
                name=name,
                value=_required_mapping_string(item, "value", "http_json headers.value"),
            )
        )
    return tuple(headers)


def _required_mapping_string(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_http_json_config(f"{label} must be a non-empty string.")
    return value


def _optional_mapping_string(mapping: Mapping[str, Any], key: str, default: str) -> str:
    value = mapping.get(key, default)
    if not isinstance(value, str):
        raise _invalid_http_json_config(f"http_json {key} must be a string.")
    return value


def _header_name_is_sensitive(name: str) -> bool:
    normalized = name.lower()
    return normalized in {"authorization", "proxy-authorization", "x-api-key", "api-key"}


def _render_query_params(value: Any, *, query: str, top_k: int) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _invalid_http_json_config("http_json request_mapping.query_params must be an object.")
    rendered = _render_template_value(value, query=query, top_k=top_k)
    if not isinstance(rendered, Mapping):
        raise _invalid_http_json_config("http_json request_mapping.query_params must render to an object.")
    return {str(key): _query_param_value(item) for key, item in rendered.items()}


def _render_json_body(value: Any, *, query: str, top_k: int) -> Mapping[str, Any] | None:
    if value is None:
        return None
    rendered = _render_template_value(value, query=query, top_k=top_k)
    if not isinstance(rendered, Mapping):
        raise _invalid_http_json_config("http_json request_mapping.json_body must render to an object.")
    return rendered


def _render_template_value(value: Any, *, query: str, top_k: int) -> Any:
    if isinstance(value, str):
        placeholders = {
            "${query}": query,
            "${top_k}": top_k,
            "${upstream_revision}": "",
        }
        if value in placeholders:
            return placeholders[value]
        if "${" in value:
            raise _invalid_http_json_config(
                "http_json request mappings support whole-value placeholders only."
            )
        return value
    if isinstance(value, Mapping):
        return {str(key): _render_template_value(item, query=query, top_k=top_k) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_render_template_value(item, query=query, top_k=top_k) for item in value]
    return value


def _query_param_value(value: Any) -> str:
    if isinstance(value, bool) or isinstance(value, str | int | float):
        return str(value)
    raise _invalid_http_json_config("http_json query parameter values must be scalar.")


def _required_mapping_pointer(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise _invalid_http_json_config(f"http_json response_mapping.{key} must be a JSON Pointer.")
    _validate_pointer(value, f"http_json response_mapping.{key}")
    return value


def _optional_mapping_pointer(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_http_json_config(f"http_json response_mapping.{key} must be a JSON Pointer.")
    _validate_pointer(value, f"http_json response_mapping.{key}")
    return value


def _required_item_string(
    item: Mapping[str, Any],
    mapping: Mapping[str, Any],
    field: str,
    label: str,
) -> str:
    pointer = _required_mapping_pointer(mapping, field)
    value = _required_pointer_value(item, pointer, label=label)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_http_json_response(f"{label} must be a non-empty string.")
    return value


def _required_item_float(
    item: Mapping[str, Any],
    mapping: Mapping[str, Any],
    field: str,
    label: str,
) -> float:
    pointer = _required_mapping_pointer(mapping, field)
    value = _required_pointer_value(item, pointer, label=label)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid_http_json_response(f"{label} must be numeric.")
    return float(value)


def _optional_item_string(
    item: Mapping[str, Any],
    mapping: Mapping[str, Any],
    field: str,
) -> str | None:
    pointer = _optional_mapping_pointer(mapping, field)
    if pointer is None:
        return None
    value = _optional_pointer_value(item, pointer)
    return _optional_string(value)


def _optional_item_mapping(
    item: Mapping[str, Any],
    mapping: Mapping[str, Any],
    field: str,
) -> Mapping[str, Any] | None:
    pointer = _optional_mapping_pointer(mapping, field)
    if pointer is None:
        return None
    value = _optional_pointer_value(item, pointer)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid_http_json_response(f"http_json result {field} must be an object.")
    return value


def _optional_top_level_mapping_string(
    response: Mapping[str, Any],
    mapping: Mapping[str, Any],
    field: str,
) -> str | None:
    pointer = _optional_mapping_pointer(mapping, field)
    if pointer is None:
        return None
    return _optional_string(_optional_pointer_value(response, pointer))


def _required_pointer_value(value: Any, pointer: str, *, label: str) -> Any:
    try:
        return _json_pointer(value, pointer)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise _invalid_http_json_response(f"{label} pointer did not resolve.") from exc


def _optional_pointer_value(value: Any, pointer: str) -> Any:
    try:
        return _json_pointer(value, pointer)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _json_pointer(value: Any, pointer: str) -> Any:
    _validate_pointer(pointer, "JSON Pointer")
    if pointer == "":
        return value
    current = value
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            current = current[token]
        elif isinstance(current, list | tuple):
            current = current[int(token)]
        else:
            raise TypeError("JSON Pointer cannot descend into scalar.")
    return current


def _validate_pointer(pointer: str, label: str) -> None:
    if pointer and not pointer.startswith("/"):
        raise _invalid_http_json_config(f"{label} must be an RFC 6901 JSON Pointer.")


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _citation_from_source_ref(source_ref: Mapping[str, Any]) -> str:
    document_id = _optional_string(source_ref.get("document_id"))
    if document_id is None:
        raise _invalid_http_json_response("http_json source_ref requires document_id.")
    citation = f"remote://document/{parse.quote(document_id, safe='')}"
    query_params: dict[str, str] = {}
    page = source_ref.get("page")
    if isinstance(page, int) and not isinstance(page, bool):
        query_params["page"] = str(page)
    chunk_id = _optional_string(source_ref.get("chunk_id"))
    if chunk_id is not None:
        query_params["chunk"] = chunk_id
    if query_params:
        citation = f"{citation}?{parse.urlencode(query_params)}"
    return citation


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            continue
        safe_value = _safe_metadata_value(value)
        if safe_value is not None:
            safe[key] = safe_value
    return safe


def _safe_metadata_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_safe_metadata_value(item) for item in value]
    if isinstance(value, Mapping):
        return _safe_metadata(value)
    return None


def _invalid_http_json_config(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        message,
        "Configure http_json with a static endpoint, safe header env refs, and JSON Pointer mappings.",
    )


def _invalid_http_json_response(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        message,
        "Return proof-agent.remote-retrieval.v1 JSON or adjust the http_json response_mapping.",
    )


__all__ = ["HttpJsonProvider", "HttpJsonRequest", "HttpJsonTransport"]
