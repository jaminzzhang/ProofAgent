"""OpenSearch adapter for the rebuildable Hybrid Knowledge search projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re
import ssl
from typing import Any, Iterator, Protocol, cast
from urllib.parse import urlsplit

import httpx

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    PrivateAddressResolver,
    PrivateNetworkPolicy,
    _PinnedNetworkBackend,
)

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridSearchHit,
    HybridSearchRequest,
    ProjectionBulkRequest,
    ProjectionBulkResult,
    ProjectionDocument,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    TaxonomyCondition,
)
from proof_agent.contracts.knowledge_index import RuleUnitManifestEntry
from proof_agent.contracts.knowledge_index import KnowledgeIndexGeneration


class OpenSearchProjectionError(RuntimeError):
    """OpenSearch projection or response failed closed validation."""


@dataclass(frozen=True, slots=True)
class OpenSearchTransportResponse:
    status_code: int
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("OpenSearch status_code must be an HTTP status integer")
        if not isinstance(self.body, Mapping):
            raise TypeError("OpenSearch response body must be a mapping")


class OpenSearchTransport(Protocol):
    """Vendor transport seam; SDK and HTTP response types terminate here."""

    def request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
        content: bytes | None = None,
        content_type: str = "application/json",
        query_params: Mapping[str, str] | None = None,
    ) -> OpenSearchTransportResponse: ...


@dataclass(frozen=True, slots=True)
class OpenSearchSecretMaterial:
    headers: Mapping[str, str]
    client_certificate_path: str | None = None
    client_key_path: str | None = None
    ca_bundle_path: str | None = None


class OpenSearchSecretProvider(Protocol):
    def resolve(self, secret_handle: str) -> OpenSearchSecretMaterial: ...


def _validate_bounded_json(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > 200_000 or depth > 64:
            raise OpenSearchProjectionError("OpenSearch JSON exceeds structural limits")
        if isinstance(current, dict):
            if len(current) > 20_000:
                raise OpenSearchProjectionError("OpenSearch JSON object exceeds item limits")
            for key, item in current.items():
                if type(key) is not str or len(key) > 20_000:
                    raise OpenSearchProjectionError("OpenSearch JSON key is invalid")
                pending.append((item, depth + 1))
        elif isinstance(current, list):
            if len(current) > 20_000:
                raise OpenSearchProjectionError("OpenSearch JSON array exceeds item limits")
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, str) and len(current) > 100_000:
            raise OpenSearchProjectionError("OpenSearch JSON string exceeds limits")
        elif isinstance(current, float) and not math.isfinite(current):
            raise OpenSearchProjectionError("OpenSearch JSON number must be finite")


class HttpxOpenSearchTransport:
    """Guarded internal HTTP transport with redirects and proxy inheritance disabled."""

    def __init__(
        self,
        *,
        endpoint: str,
        allowed_hosts: tuple[str, ...],
        timeout_seconds: float = 10.0,
        allow_insecure_loopback: bool = False,
        max_response_bytes: int = 8 * 1024 * 1024,
        network_policy: PrivateNetworkPolicy | None = None,
        resolver: PrivateAddressResolver | None = None,
        secret_handle: str | None = None,
        secret_provider: OpenSearchSecretProvider | None = None,
    ) -> None:
        if type(endpoint) is not str or not endpoint.strip():
            raise ValueError("OpenSearch endpoint must be a nonblank string")
        try:
            parsed = urlsplit(endpoint)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("OpenSearch endpoint is malformed") from exc
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("OpenSearch endpoint must not contain credentials, path, or query")
        hostname = parsed.hostname
        if hostname is None or hostname.endswith("."):
            raise ValueError("OpenSearch endpoint requires a canonical hostname")
        hostname = hostname.casefold()
        canonical_allowed = tuple(item.casefold() for item in allowed_hosts)
        if (
            not canonical_allowed
            or hostname not in canonical_allowed
            or len(canonical_allowed) != len(set(canonical_allowed))
        ):
            raise ValueError("OpenSearch endpoint host must be explicitly allowlisted")
        loopback = hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and allow_insecure_loopback and loopback
        ):
            raise ValueError("OpenSearch requires internal HTTPS outside explicit loopback tests")
        if not loopback and (network_policy is None or resolver is None):
            raise ValueError("production OpenSearch requires pinned private DNS/CIDR policy")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("OpenSearch endpoint port is invalid")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 60
        ):
            raise ValueError("OpenSearch timeout must be within 60 seconds")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("OpenSearch response limit is invalid")
        base_url = endpoint.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._max_request_bytes = 64 * 1024 * 1024
        material = OpenSearchSecretMaterial(headers={})
        if (secret_handle is None) != (secret_provider is None):
            raise ValueError("OpenSearch secret handle and provider must be supplied together")
        if secret_handle is not None and secret_provider is not None:
            if not secret_handle.strip():
                raise ValueError("OpenSearch secret handle must be nonblank")
            material = secret_provider.resolve(secret_handle)
        self._auth_headers = self._validate_secret_material(material)
        ssl_context = ssl.create_default_context(cafile=material.ca_bundle_path)
        if (material.client_certificate_path is None) != (material.client_key_path is None):
            raise ValueError("OpenSearch mTLS requires both certificate and key handles")
        if material.client_certificate_path is not None:
            ssl_context.load_cert_chain(
                material.client_certificate_path,
                material.client_key_path,
            )
        if loopback:
            self._client = httpx.Client(
                base_url=base_url,
                timeout=float(timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            )
        else:
            assert network_policy is not None and resolver is not None
            self._client = self._pinned_client(
                base_url=base_url,
                timeout_seconds=float(timeout_seconds),
                ssl_context=ssl_context,
                network_policy=network_policy,
                resolver=resolver,
            )

    @staticmethod
    def _validate_secret_material(material: OpenSearchSecretMaterial) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in material.headers.items():
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or not value
                or "\r" in key + value
                or "\n" in key + value
                or len(key) > 128
                or len(value) > 8_192
            ):
                raise ValueError("OpenSearch secret provider returned invalid headers")
            headers[key] = value
        return headers

    @staticmethod
    def _pinned_client(
        *,
        base_url: str,
        timeout_seconds: float,
        ssl_context: ssl.SSLContext,
        network_policy: PrivateNetworkPolicy,
        resolver: PrivateAddressResolver,
    ) -> httpx.Client:
        import httpcore

        backend = _PinnedNetworkBackend(
            policy=network_policy,
            resolver=resolver,
            backend=httpcore.SyncBackend(),
        )
        pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=4,
            max_keepalive_connections=4,
            retries=0,
            network_backend=cast(Any, backend),
        )

        class ResponseStream(httpx.SyncByteStream):
            def __init__(self, stream: Any) -> None:
                self._stream = stream

            def __iter__(self) -> Iterator[bytes]:
                yield from self._stream

            def close(self) -> None:
                self._stream.close()

        class PinnedTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                core_response = pool.handle_request(
                    httpcore.Request(
                        method=request.method,
                        url=httpcore.URL(
                            scheme=request.url.raw_scheme,
                            host=request.url.raw_host,
                            port=request.url.port,
                            target=request.url.raw_path,
                        ),
                        headers=request.headers.raw,
                        content=request.stream,
                        extensions=request.extensions,
                    )
                )
                return httpx.Response(
                    status_code=core_response.status,
                    headers=core_response.headers,
                    stream=ResponseStream(core_response.stream),
                    extensions=core_response.extensions,
                )

            def close(self) -> None:
                pool.close()

        return httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=PinnedTransport(),
        )

    def request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
        content: bytes | None = None,
        content_type: str = "application/json",
        query_params: Mapping[str, str] | None = None,
    ) -> OpenSearchTransportResponse:
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise ValueError("OpenSearch HTTP method is not allowed")
        if (
            type(path) is not str
            or not path.startswith("/")
            or "//" in path
            or "?" in path
            or "#" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            raise ValueError("OpenSearch request path must be canonical")
        if json_body is not None and content is not None:
            raise ValueError("OpenSearch request must use either JSON or bytes")
        if query_params is not None:
            if set(query_params) != {"search_pipeline"}:
                raise ValueError("OpenSearch query parameters are not allowed")
            pipeline = query_params.get("search_pipeline")
            if (
                type(pipeline) is not str
                or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", pipeline) is None
            ):
                raise ValueError("OpenSearch search pipeline parameter is invalid")
        encoded_content: bytes | None
        if json_body is not None:
            encoded_content = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        else:
            encoded_content = content
        if encoded_content is not None and len(encoded_content) > self._max_request_bytes:
            raise OpenSearchProjectionError("OpenSearch request exceeds the configured limit")
        headers = {
            **self._auth_headers,
            "Content-Type": content_type,
            "Accept": "application/json",
        }
        try:
            with self._client.stream(
                method,
                path,
                content=encoded_content,
                headers=headers,
                params=query_params,
            ) as response:
                if response.is_redirect:
                    raise OpenSearchProjectionError("OpenSearch redirects are forbidden")
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > self._max_response_bytes:
                        raise OpenSearchProjectionError(
                            "OpenSearch response exceeds the configured limit"
                        )
                status_code = response.status_code
        except httpx.HTTPError as exc:
            raise OpenSearchProjectionError("OpenSearch transport request failed") from exc
        try:
            decoded = json.loads(payload) if payload else {}
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise OpenSearchProjectionError("OpenSearch returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise OpenSearchProjectionError("OpenSearch response must be a JSON object")
        _validate_bounded_json(decoded)
        return OpenSearchTransportResponse(status_code=status_code, body=decoded)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpxOpenSearchTransport:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


_INDEX_SLUG = re.compile(r"[^a-z0-9]+")


def _safe_slug(value: str, *, field_name: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError(f"{field_name} must be a nonblank string")
    slug = _INDEX_SLUG.sub("-", value.casefold()).strip("-")[:40]
    return slug or "id"


def physical_index_name(source_id: str, generation_id: str) -> str:
    """Return one safe, collision-resistant physical Source-generation index name."""

    source_slug = _safe_slug(source_id, field_name="source_id")
    generation_slug = _safe_slug(generation_id, field_name="generation_id")
    identity = f"{source_id}\0{generation_id}".encode()
    suffix = hashlib.sha256(identity).hexdigest()[:20]
    return f"pa-knowledge-{source_slug}-{generation_slug}-{suffix}"


RULE_UNIT_ANALYZER = "proof_agent_cjk_v1"


def rule_unit_analysis_settings() -> dict[str, object]:
    """Return the exact versioned analysis configuration bound to a generation."""

    return {
        "analyzer": {
            RULE_UNIT_ANALYZER: {
                "type": "custom",
                "tokenizer": "standard",
                "char_filter": [],
                "filter": [
                    "lowercase",
                    "cjk_width",
                    "proof_agent_cjk_bigram_v1",
                ],
            }
        },
        "filter": {"proof_agent_cjk_bigram_v1": {"type": "cjk_bigram"}},
        "normalizer": {
            "proof_agent_keyword_v1": {
                "type": "custom",
                "filter": ["lowercase", "asciifolding"],
            }
        },
    }


def rule_unit_index_mapping(*, dimension: int) -> dict[str, object]:
    """Build the pinned Rule Unit mapping without accepting backend-native input."""

    if type(dimension) is not int or dimension <= 0 or dimension > 65_535:
        raise ValueError("dimension must be a positive integer no greater than 65535")
    keyword = {"type": "keyword", "ignore_above": 512}
    properties: dict[str, dict[str, object]] = {
        name: dict(keyword)
        for name in (
            "projection_id",
            "source_id",
            "document_id",
            "revision_id",
            "logical_rule_key",
            "rule_unit_revision_id",
            "structured_artifact_build_identity",
            "index_generation_id",
            "manifest_entry_sha256",
            "metadata_revision_id",
            "metadata_revision_digest",
            "visibility_revision_id",
            "visibility_revision_digest",
            "content_sha256",
            "authority_sha256",
            "citation_uri",
            "visibility",
            "institution_mode",
            "region_mode",
            "channel_mode",
            "role_mode",
            "business_line_mode",
            "allowed_institutions",
            "allowed_regions",
            "allowed_channels",
            "allowed_roles",
            "allowed_business_lines",
            "taxonomy_id",
            "taxonomy_revision_id",
            "authority_tier",
            "precedence_policy_revision",
            "projection_revision",
            "immutable_projection_sha256",
            "projection_sha256",
            "publication_attempt_id",
            "embedding_sha256",
            "block_ids",
            "table_id",
            "table_continuation_id",
            "cell_coordinates",
            "product_codes",
            "rule_type",
            "authority",
            "supersedes_rule_unit_revision_ids",
        )
    }
    properties.update(
        {
            "publication_seq_from": {"type": "long"},
            "publication_seq_to": {"type": "long"},
            "precedence_order": {"type": "long"},
            "page_numbers": {"type": "integer"},
            "effective_from": {"type": "date", "format": "strict_date"},
            "effective_to": {"type": "date", "format": "strict_date"},
            "applicability_predicates": {
                "type": "nested",
                "properties": {
                    "key": dict(keyword),
                    "operator": dict(keyword),
                    "value_tokens": dict(keyword),
                    "numeric_values": {"type": "double"},
                },
            },
            "approved_metadata": {"type": "object", "enabled": False},
            "approved_visibility": {"type": "object", "enabled": False},
            "lexical_text": {"type": "text", "analyzer": RULE_UNIT_ANALYZER},
            "content": {"type": "text", "index": False},
            "title": {"type": "text", "analyzer": RULE_UNIT_ANALYZER},
            "heading_path": {"type": "text", "analyzer": RULE_UNIT_ANALYZER},
            "definitions": {"type": "text", "analyzer": RULE_UNIT_ANALYZER},
            "table_context": {"type": "text", "analyzer": RULE_UNIT_ANALYZER},
            "dense_vector": {
                "type": "knn_vector",
                "dimension": dimension,
                "method": {
                    "name": "hnsw",
                    "engine": "lucene",
                    "space_type": "cosinesimil",
                },
            },
        }
    )
    return {"dynamic": "strict", "properties": properties}


def _rule_unit_index_definition(*, dimension: int) -> dict[str, object]:
    return {
        "settings": {
            "index": {"knn": True, "analysis": rule_unit_analysis_settings()}
        },
        "mappings": rule_unit_index_mapping(dimension=dimension),
    }


def rule_unit_analyzer_sha256() -> str:
    return stable_digest(rule_unit_analysis_settings())


def rule_unit_mapping_sha256(*, dimension: int) -> str:
    return stable_digest(rule_unit_index_mapping(dimension=dimension))


def _bounded_text(value: str, *, field_name: str, maximum: int) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a nonblank string")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds the maximum length")
    return value


def _visibility_fields(
    visibility: ApprovedInsuranceKnowledgeVisibilityScope,
) -> dict[str, object]:
    result: dict[str, object] = {
        "visibility": visibility.visibility,
        "visibility_revision_id": visibility.revision_id,
        "visibility_revision_digest": stable_digest(visibility.model_dump(mode="json")),
    }
    if visibility.visibility == "PUBLIC":
        return result
    dimensions = (
        ("institution", visibility.institutions),
        ("region", visibility.regions),
        ("channel", visibility.channels),
        ("role", visibility.roles),
        ("business_line", visibility.business_lines),
    )
    for field, scope in dimensions:
        if scope is None:  # defensive against model_construct bypasses
            raise ValueError("restricted visibility requires every approved dimension")
        result[f"{field}_mode"] = scope.mode
        result[f"allowed_{field}s"] = list(scope.values)
    return result


def _cell_coordinate_tokens(document: ProjectionDocument) -> list[str]:
    lineage = document.rule_unit.lineage
    coordinates = (*lineage.header_cell_coordinates, *lineage.cell_coordinates)
    return [
        f"p{item.page_number}:r{item.row}:c{item.column}:rs{item.row_span}:cs{item.column_span}"
        for item in coordinates
    ]


def _authority_projection_fields(
    metadata: ApprovedInsuranceRuleMetadataRevision,
    visibility: ApprovedInsuranceKnowledgeVisibilityScope,
) -> dict[str, object]:
    conditions = tuple(sorted(metadata.applicability.conditions, key=lambda item: item.key))
    if len(conditions) > 256 or sum(len(item.values) for item in conditions) > 1_024:
        raise ValueError("approved applicability exceeds projection limits")
    predicates = [
        {
            "key": condition.key,
            "operator": condition.operator,
            "value_tokens": sorted(_fact_token(value) for value in condition.values),
            "numeric_values": [
                value for value in condition.values if type(value) in {int, float}
            ],
        }
        for condition in conditions
    ]
    product_codes = sorted(
        {
            value
            for condition in conditions
            if condition.key in {"product_code", "product_codes"}
            for value in condition.values
            if type(value) is str
        }
    )
    metadata_payload = metadata.model_dump(mode="json")
    visibility_payload = visibility.model_dump(mode="json")
    result: dict[str, object] = {
        "metadata_revision_id": metadata.metadata_revision_id,
        "metadata_revision_digest": stable_digest(metadata_payload),
        "taxonomy_id": metadata.applicability.taxonomy_id,
        "taxonomy_revision_id": metadata.applicability.taxonomy_revision_id,
        "applicability_predicates": predicates,
        "product_codes": product_codes,
        "authority": metadata.authority,
        "authority_tier": metadata.precedence.authority_tier,
        "precedence_policy_revision": metadata.precedence.policy_revision_id,
        "precedence_order": metadata.precedence.order,
        "supersedes_rule_unit_revision_ids": list(
            metadata.supersedes_rule_unit_revision_ids
        ),
        "approved_metadata": metadata_payload,
        "approved_visibility": visibility_payload,
        **_visibility_fields(visibility),
    }
    if metadata.effective_from is not None:
        result["effective_from"] = metadata.effective_from.isoformat()
    if metadata.effective_to is not None:
        result["effective_to"] = metadata.effective_to.isoformat()
    return result


def project_rule_unit_document(
    document: ProjectionDocument,
    *,
    identity: SearchIndexIdentity,
    publication_attempt_id: str,
) -> dict[str, object]:
    """Project one approved Rule Unit without vendor payloads or review drafts."""

    document = ProjectionDocument.model_validate(document.model_dump(mode="python"))
    identity = SearchIndexIdentity.model_validate(identity.model_dump(mode="python"))
    rule = document.rule_unit
    entry = document.manifest_entry
    metadata = document.approved_metadata
    generation = identity.generation
    if rule.lineage.source_id != generation.source_id:
        raise ValueError("Rule Unit source must match the exact index generation")
    if len(document.embedding) != generation.embedding_dimension:
        raise ValueError("projection embedding must match the exact generation dimension")
    if document.projection_revision != generation.search_projection_version:
        raise ValueError("projection revision must match the exact index generation")
    _bounded_text(publication_attempt_id, field_name="publication_attempt_id", maximum=512)
    _bounded_text(rule.content, field_name="Rule Unit content", maximum=50_000)
    expected_content_sha256 = hashlib.sha256(rule.content.encode()).hexdigest()
    if rule.content_sha256 != expected_content_sha256:
        raise ValueError("Rule Unit content digest does not match exact content")
    approved_metadata_payload = metadata.model_dump(mode="json")
    approved_visibility_payload = rule.visibility_scope.model_dump(mode="json")
    expected_authority_sha256 = stable_digest(
        {
            "approved_metadata": approved_metadata_payload,
            "approved_visibility": approved_visibility_payload,
        }
    )
    if rule.authority_sha256 != expected_authority_sha256:
        raise ValueError("Rule Unit authority digest does not match approved facts")
    _validate_citation_binding(
        entry.citation_uri,
        source_id=generation.source_id,
        document_id=rule.document_id,
        revision_id=rule.revision_id,
    )

    authority_fields = _authority_projection_fields(metadata, rule.visibility_scope)
    lineage = rule.lineage
    title = lineage.heading_path[-1] if lineage.heading_path else rule.logical_rule_key
    table_context = "\n".join(
        item
        for item in (
            lineage.table_title,
            " | ".join(lineage.table_headers) if lineage.table_headers else None,
            lineage.row_header,
        )
        if item is not None
    )
    lexical_parts = (
        title,
        *lineage.heading_path,
        rule.content,
        *lineage.definitions,
        table_context,
    )
    lexical_text = "\n".join(item for item in lexical_parts if item)
    _bounded_text(lexical_text, field_name="lexical_text", maximum=100_000)
    bounded_identifiers = {
        "projection_id": document.projection_id,
        "source_id": generation.source_id,
        "document_id": rule.document_id,
        "revision_id": rule.revision_id,
        "logical_rule_key": rule.logical_rule_key,
        "rule_unit_revision_id": rule.rule_unit_revision_id,
        "structured_build_id": rule.structured_build_id,
        "generation_id": generation.generation_id,
        "metadata_revision_id": metadata.metadata_revision_id,
        "visibility_revision_id": rule.visibility_scope.revision_id,
        "citation_uri": entry.citation_uri,
        "projection_revision": document.projection_revision,
    }
    for field_name, value in bounded_identifiers.items():
        _bounded_text(value, field_name=field_name, maximum=512)
    projected: dict[str, object] = {
        "projection_id": document.projection_id,
        "source_id": generation.source_id,
        "document_id": rule.document_id,
        "revision_id": rule.revision_id,
        "logical_rule_key": rule.logical_rule_key,
        "rule_unit_revision_id": rule.rule_unit_revision_id,
        "structured_artifact_build_identity": rule.structured_build_id,
        "index_generation_id": generation.generation_id,
        "manifest_entry_sha256": stable_digest(entry.model_dump(mode="json")),
        "content_sha256": rule.content_sha256,
        "authority_sha256": rule.authority_sha256,
        "publication_seq_from": entry.publication_seq_from,
        "citation_uri": entry.citation_uri,
        "page_numbers": list(lineage.page_numbers),
        "block_ids": list(lineage.block_ids),
        "cell_coordinates": _cell_coordinate_tokens(document),
        "content": rule.content,
        "title": title,
        "heading_path": list(lineage.heading_path),
        "definitions": list(lineage.definitions),
        "table_context": table_context,
        "rule_type": rule.unit_kind,
        "lexical_text": lexical_text,
        "dense_vector": list(document.embedding),
        "embedding_sha256": stable_digest({"embedding": list(document.embedding)}),
        "projection_revision": document.projection_revision,
        "publication_attempt_id": publication_attempt_id,
        **authority_fields,
    }
    if entry.publication_seq_to is not None:
        projected["publication_seq_to"] = entry.publication_seq_to
    if lineage.table_id is not None:
        projected["table_id"] = lineage.table_id
    if lineage.table_continuation_id is not None:
        projected["table_continuation_id"] = lineage.table_continuation_id

    projected["immutable_projection_sha256"] = _immutable_projection_sha256(projected)
    projected["projection_sha256"] = _mutable_projection_sha256(projected)
    return projected


def _taxonomy_value(value: object) -> dict[str, object]:
    if type(value) is bool:
        return {"type": "boolean", "value": value}
    if type(value) is int:
        return {"type": "integer", "value": value}
    if type(value) is float:
        return {"type": "number", "value": value}
    if type(value) is str:
        return {"type": "string", "value": value}
    raise TypeError("taxonomy values must be exact supported scalar types")


def _fact_token(value: object) -> str:
    return stable_digest({"fact": _taxonomy_value(value)})


_IMMUTABLE_EXCLUDED_FIELDS = frozenset(
    {
        "manifest_entry_sha256",
        "publication_seq_to",
        "publication_attempt_id",
        "immutable_projection_sha256",
        "projection_sha256",
        "dense_vector",
        "lexical_text",
    }
)


def _immutable_projection_sha256(projected: Mapping[str, object]) -> str:
    return stable_digest(
        {key: value for key, value in projected.items() if key not in _IMMUTABLE_EXCLUDED_FIELDS}
    )


def _mutable_projection_sha256(projected: Mapping[str, object]) -> str:
    return stable_digest(
        {
            "immutable_projection_sha256": projected["immutable_projection_sha256"],
            "manifest_entry_sha256": projected["manifest_entry_sha256"],
            "publication_seq_from": projected["publication_seq_from"],
            "publication_seq_to": projected.get("publication_seq_to"),
        }
    )


def _optional_bound_filter(field: str, operator: str, value: object) -> dict[str, object]:
    return {
        "bool": {
            "should": [
                {"range": {field: {operator: value}}},
                {"bool": {"must_not": [{"exists": {"field": field}}]}},
            ],
            "minimum_should_match": 1,
        }
    }


def _visibility_filter(authorization: InstitutionAuthorizationContext) -> dict[str, object]:
    if authorization.public_only:
        return {"term": {"visibility": "PUBLIC"}}

    dimensions = (
        ("institution", authorization.institutions),
        ("region", authorization.regions),
        ("channel", authorization.channels),
        ("role", authorization.roles),
        ("business_line", authorization.business_lines),
    )
    restricted_filters: list[dict[str, object]] = [{"term": {"visibility": "RESTRICTED"}}]
    for field, admitted in dimensions:
        should: list[dict[str, object]] = [{"term": {f"{field}_mode": "ALL"}}]
        if admitted:
            should.append(
                {
                    "bool": {
                        "filter": [
                            {"term": {f"{field}_mode": "ALLOWLIST"}},
                            {"terms": {f"allowed_{field}s": list(admitted)}},
                        ]
                    }
                }
            )
        restricted_filters.append(
            {"bool": {"should": should, "minimum_should_match": 1}}
        )
    return {
        "bool": {
            "should": [
                {"term": {"visibility": "PUBLIC"}},
                {"bool": {"filter": restricted_filters}},
            ],
            "minimum_should_match": 1,
        }
    }


def _applicability_fact_filter(condition: TaxonomyCondition) -> dict[str, object]:
    fact_token = _fact_token(condition.values[0])
    path = "applicability_predicates"
    key_field = f"{path}.key"
    operator_field = f"{path}.operator"
    values_field = f"{path}.value_tokens"
    return {
        "bool": {
            "should": [
                {
                    "bool": {
                        "must_not": [
                            {"nested": {"path": path, "query": {"term": {key_field: condition.key}}}}
                        ]
                    }
                },
                {
                    "nested": {
                        "path": path,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"term": {key_field: condition.key}},
                                    {"terms": {operator_field: ["EQ", "IN"]}},
                                    {"term": {values_field: fact_token}},
                                ]
                            }
                        },
                    }
                },
                {
                    "nested": {
                        "path": path,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"term": {key_field: condition.key}},
                                    {"terms": {operator_field: ["NOT_EQ", "NOT_IN"]}},
                                ],
                                "must_not": [{"term": {values_field: fact_token}}],
                            }
                        },
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


def build_common_filter(request: HybridSearchRequest) -> list[dict[str, object]]:
    """Translate governed authority filters once for both retrieval lanes."""

    sequence = request.source_publication_seq
    filters: list[dict[str, object]] = [
        {"term": {"source_id": request.identity.generation.source_id}},
        {"term": {"index_generation_id": request.identity.generation.generation_id}},
        {"range": {"publication_seq_from": {"lte": sequence}}},
        _optional_bound_filter("publication_seq_to", "gte", sequence),
        _optional_bound_filter("effective_from", "lte", request.as_of_date.isoformat()),
        _optional_bound_filter("effective_to", "gte", request.as_of_date.isoformat()),
        _visibility_filter(request.authorization),
    ]
    filters.extend(_applicability_fact_filter(condition) for condition in request.applicability_filters)
    return filters


def build_hybrid_query(request: HybridSearchRequest) -> dict[str, object]:
    """Build Source-local BM25+kNN retrieval with identical prefilters."""

    common_filter = build_common_filter(request)
    return {
        "size": request.rrf_window,
        "_source": sorted(
            set(
                _mapping(
                    rule_unit_index_mapping(dimension=1)["properties"],
                    field_name="mapping properties",
                )
            )
            - {"dense_vector", "lexical_text"}
        ),
        "query": {
            "hybrid": {
                "pagination_depth": request.lexical_budget,
                "queries": [
                    {
                        "bool": {
                            "must": [
                                {
                                    "match": {
                                        "lexical_text": {
                                            "query": request.query_text,
                                        }
                                    }
                                }
                            ],
                            "filter": common_filter,
                        }
                    },
                    {
                        "knn": {
                            "dense_vector": {
                                "vector": list(request.query_embedding),
                                "k": request.dense_budget,
                                "filter": {"bool": {"filter": common_filter}},
                            }
                        }
                    },
                ],
            }
        },
        "search_pipeline": request.rrf_pipeline,
    }


_INTERVAL_UPDATE_SCRIPT = """
if (ctx.op == 'create') {
  ctx._source = params.doc;
} else {
  if (ctx._source.immutable_projection_sha256 != params.doc.immutable_projection_sha256) {
    throw new IllegalArgumentException('immutable projection conflict');
  }
  boolean oldClosed = ctx._source.containsKey('publication_seq_to');
  boolean newClosed = params.doc.containsKey('publication_seq_to');
  if (oldClosed && (!newClosed || ctx._source.publication_seq_to != params.doc.publication_seq_to)) {
    throw new IllegalArgumentException('closed interval cannot reopen or change');
  }
  if (!oldClosed && newClosed && params.doc.publication_seq_to < params.doc.publication_seq_from) {
    throw new IllegalArgumentException('invalid interval close');
  }
  if (ctx._source.projection_sha256 == params.doc.projection_sha256) {
    ctx.op = 'noop';
  } else {
    if (newClosed) {
      ctx._source.publication_seq_to = params.doc.publication_seq_to;
      ctx._source.manifest_entry_sha256 = params.doc.manifest_entry_sha256;
    }
    ctx._source.projection_sha256 = params.doc.projection_sha256;
    ctx._source.publication_attempt_id = params.doc.publication_attempt_id;
  }
}
""".strip()


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OpenSearchProjectionError(f"{field_name} must be an object")
    return value


def _exact_string(
    value: object,
    *,
    field_name: str,
    maximum: int = 512,
) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise OpenSearchProjectionError(f"{field_name} must be a bounded nonblank string")
    return value


def _sha256(value: object, *, field_name: str) -> str:
    result = _exact_string(value, field_name=field_name, maximum=64)
    if re.fullmatch(r"[0-9a-f]{64}", result) is None:
        raise OpenSearchProjectionError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _exact_integer(value: object, *, field_name: str) -> int:
    if type(value) is not int:
        raise OpenSearchProjectionError(f"{field_name} must be an exact integer")
    return value


def _finite_score(value: object, *, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise OpenSearchProjectionError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise OpenSearchProjectionError(f"{field_name} must be finite and nonnegative")
    return result


def _string_list(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise OpenSearchProjectionError(f"{field_name} must be an array")
    result = tuple(
        _exact_string(item, field_name=f"{field_name} item") for item in value
    )
    if len(result) != len(set(result)):
        raise OpenSearchProjectionError(f"{field_name} must contain unique values")
    if result != tuple(sorted(result)):
        raise OpenSearchProjectionError(f"{field_name} must use canonical ordering")
    return result


def _validate_citation_binding(
    citation_uri: str,
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
) -> None:
    parsed = urlsplit(citation_uri)
    if parsed.scheme != "knowledge":
        raise OpenSearchProjectionError("Hybrid citations must use the knowledge scheme")
    expected_path = f"/{source_id}/document/{document_id}/revision/{revision_id}"
    if parsed.netloc != "source" or parsed.path != expected_path:
        raise OpenSearchProjectionError("search hit citation does not bind its exact lineage")


def _response_index_identity(
    response: OpenSearchTransportResponse,
    *,
    index_name: str,
    expected: SearchIndexIdentity,
) -> SearchIndexIdentity:
    if response.status_code != 200:
        raise OpenSearchProjectionError("exact OpenSearch index identity is unavailable")
    if set(response.body) != {index_name}:
        raise OpenSearchProjectionError("OpenSearch returned an unexpected physical index")
    details = _mapping(response.body[index_name], field_name="index identity")
    settings = _mapping(details.get("settings"), field_name="index settings")
    index_settings = _mapping(settings.get("index"), field_name="index settings.index")
    actual_uuid = _exact_string(index_settings.get("uuid"), field_name="index UUID")
    if actual_uuid != expected.index_uuid:
        raise OpenSearchProjectionError("OpenSearch index UUID does not match the binding")
    mappings = _mapping(details.get("mappings"), field_name="index mappings")
    metadata = _mapping(mappings.get("_meta"), field_name="index mapping metadata")
    generation = expected.generation
    if metadata.get("source_id") != generation.source_id:
        raise OpenSearchProjectionError("OpenSearch index Source identity does not match")
    if metadata.get("generation_id") != generation.generation_id:
        raise OpenSearchProjectionError("OpenSearch index generation does not match")
    if metadata.get("embedding_dimension") != generation.embedding_dimension:
        raise OpenSearchProjectionError("OpenSearch index vector dimension does not match")
    if metadata.get("mapping_sha256") != generation.mapping_sha256:
        raise OpenSearchProjectionError("OpenSearch index mapping digest does not match")
    if metadata.get("analyzer_sha256") != generation.analyzer_sha256:
        raise OpenSearchProjectionError("OpenSearch index analyzer digest does not match")
    actual_mapping = {key: value for key, value in mappings.items() if key != "_meta"}
    if stable_digest(actual_mapping) != generation.mapping_sha256:
        raise OpenSearchProjectionError("OpenSearch actual mapping digest does not match")
    actual_analysis = _mapping(
        index_settings.get("analysis"), field_name="index analysis settings"
    )
    if stable_digest(actual_analysis) != generation.analyzer_sha256:
        raise OpenSearchProjectionError("OpenSearch actual analyzer settings do not match")
    properties = _mapping(actual_mapping.get("properties"), field_name="mapping properties")
    analyzer_fields = (
        "lexical_text",
        "title",
        "heading_path",
        "definitions",
        "table_context",
    )
    actual_analyzers = {
        _exact_string(
            _mapping(properties.get(field), field_name=f"mapping field {field}").get(
                "analyzer"
            ),
            field_name=f"mapping analyzer {field}",
        )
        for field in analyzer_fields
    }
    if actual_analyzers != {RULE_UNIT_ANALYZER}:
        raise OpenSearchProjectionError("OpenSearch mapping analyzer identity does not match")
    return expected


def _validated_shard_state(
    value: object,
    *,
    field_name: str,
    allow_zero: bool,
) -> dict[str, int]:
    shards = _mapping(value, field_name=field_name)
    total = _exact_integer(shards.get("total"), field_name=f"{field_name} total")
    successful = _exact_integer(
        shards.get("successful"), field_name=f"{field_name} successful"
    )
    failed = _exact_integer(shards.get("failed"), field_name=f"{field_name} failed")
    minimum = 0 if allow_zero else 1
    if total < minimum or successful < 0 or failed != 0 or successful != total:
        raise OpenSearchProjectionError(f"{field_name} are incomplete or invalid")
    return {"total": total, "successful": successful, "failed": failed}


def _refresh_checkpoint(
    response: OpenSearchTransportResponse,
    *,
    identity: SearchIndexIdentity,
    manifest_root_sha256: str,
    projection_set_sha256: str,
    bulk_markers: tuple[Mapping[str, object], ...],
) -> str:
    if response.status_code != 200:
        raise OpenSearchProjectionError("OpenSearch refresh failed")
    shard_state = _validated_shard_state(
        response.body.get("_shards"), field_name="refresh shards", allow_zero=False
    )
    return "refresh-sha256:" + stable_digest(
        {
            "schema": "proof-agent-projection-refresh.v1",
            "index_uuid": identity.index_uuid,
            "manifest_root_sha256": manifest_root_sha256,
            "projection_set_sha256": projection_set_sha256,
            "bulk_markers": list(bulk_markers),
            "refresh_shards": shard_state,
            "refresh_result_sha256": stable_digest(response.body),
        }
    )


def _bulk_payload(request: ProjectionBulkRequest) -> tuple[bytes, str]:
    lines: list[str] = []
    projection_states: list[dict[str, object]] = []
    for document in request.documents:
        projected = project_rule_unit_document(
            document,
            identity=request.identity,
            publication_attempt_id=request.publication_attempt_id,
        )
        projection_states.append(
            {
                "projection_id": projected["projection_id"],
                "immutable_projection_sha256": projected[
                    "immutable_projection_sha256"
                ],
                "projection_sha256": projected["projection_sha256"],
                "manifest_entry_sha256": projected["manifest_entry_sha256"],
                "publication_seq_from": projected["publication_seq_from"],
                "publication_seq_to": projected.get("publication_seq_to"),
            }
        )
        lines.append(
            json.dumps(
                {"update": {"_id": document.projection_id}},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        lines.append(
            json.dumps(
                {
                    "scripted_upsert": True,
                    "script": {
                        "lang": "painless",
                        "source": _INTERVAL_UPDATE_SCRIPT,
                        "params": {"doc": projected},
                    },
                    "upsert": {},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    projection_states.sort(key=lambda item: str(item["projection_id"]))
    return ("\n".join(lines) + "\n").encode(), stable_digest(
        {"schema": "proof-agent-projection-set.v1", "documents": projection_states}
    )


def _validate_bulk_result(
    response: OpenSearchTransportResponse,
    *,
    expected_ids: tuple[str, ...],
    expected_index: str,
) -> tuple[Mapping[str, object], ...]:
    if response.status_code != 200 or response.body.get("errors") is not False:
        raise OpenSearchProjectionError("OpenSearch rejected one or more projection writes")
    items = response.body.get("items")
    if not isinstance(items, list) or len(items) != len(expected_ids):
        raise OpenSearchProjectionError("OpenSearch bulk result count does not match the request")
    markers: list[Mapping[str, object]] = []
    for expected_id, item in zip(expected_ids, items, strict=True):
        update = _mapping(
            _mapping(item, field_name="bulk item").get("update"),
            field_name="bulk update result",
        )
        status = _exact_integer(update.get("status"), field_name="bulk item status")
        if update.get("_id") != expected_id or update.get("_index") != expected_index:
            raise OpenSearchProjectionError("OpenSearch bulk item identity does not match")
        if "error" in update:
            raise OpenSearchProjectionError("OpenSearch bulk item contains an error")
        result = _exact_string(update.get("result"), field_name="bulk item result")
        if (result == "created" and status != 201) or (
            result in {"updated", "noop"} and status != 200
        ):
            raise OpenSearchProjectionError("OpenSearch bulk item status/result is invalid")
        if result not in {"created", "updated", "noop"}:
            raise OpenSearchProjectionError("OpenSearch bulk item result is invalid")
        sequence_number = _exact_integer(
            update.get("_seq_no"), field_name="bulk item sequence number"
        )
        primary_term = _exact_integer(
            update.get("_primary_term"), field_name="bulk item primary term"
        )
        version = _exact_integer(update.get("_version"), field_name="bulk item version")
        if sequence_number < 0 or primary_term <= 0 or version <= 0:
            raise OpenSearchProjectionError("OpenSearch bulk item version markers are invalid")
        shard_state = _validated_shard_state(
            update.get("_shards"), field_name="bulk item shards", allow_zero=True
        )
        markers.append(
            {
                "_id": expected_id,
                "_index": expected_index,
                "result": result,
                "_seq_no": sequence_number,
                "_primary_term": primary_term,
                "_version": version,
                "_shards": shard_state,
            }
        )
    return tuple(markers)


def _date_is_effective(source: Mapping[str, object], as_of: date) -> bool:
    for field, lower_bound in (("effective_from", True), ("effective_to", False)):
        raw = source.get(field)
        if raw is None:
            continue
        try:
            parsed = date.fromisoformat(_exact_string(raw, field_name=field, maximum=10))
        except ValueError as exc:
            raise OpenSearchProjectionError(f"{field} must be a strict ISO date") from exc
        if lower_bound and parsed > as_of:
            return False
        if not lower_bound and parsed < as_of:
            return False
    return True


def _is_authorized(
    source: Mapping[str, object], authorization: InstitutionAuthorizationContext
) -> bool:
    visibility = _exact_string(source.get("visibility"), field_name="visibility")
    if visibility == "PUBLIC":
        return True
    if visibility != "RESTRICTED" or authorization.public_only:
        return False
    dimensions = (
        ("institution", authorization.institutions),
        ("region", authorization.regions),
        ("channel", authorization.channels),
        ("role", authorization.roles),
        ("business_line", authorization.business_lines),
    )
    for field, admitted in dimensions:
        mode = _exact_string(source.get(f"{field}_mode"), field_name=f"{field}_mode")
        values = _string_list(
            source.get(f"allowed_{field}s"), field_name=f"allowed_{field}s"
        )
        if mode == "ALL":
            if values:
                return False
        elif mode == "ALLOWLIST":
            if not values or not set(values).intersection(admitted):
                return False
        else:
            return False
    return True


def _applicability_allows(
    source: Mapping[str, object], facts: tuple[TaxonomyCondition, ...]
) -> bool:
    raw = source.get("applicability_predicates")
    if not isinstance(raw, list):
        raise OpenSearchProjectionError("applicability_predicates must be an array")
    predicates: dict[str, tuple[str, tuple[str, ...]]] = {}
    for item in raw:
        raw_predicate = _mapping(item, field_name="applicability predicate")
        key = _exact_string(raw_predicate.get("key"), field_name="applicability key")
        operator = _exact_string(
            raw_predicate.get("operator"), field_name="applicability operator"
        )
        if operator not in {"EQ", "IN", "NOT_EQ", "NOT_IN"} or key in predicates:
            raise OpenSearchProjectionError("applicability predicate is invalid")
        tokens = _string_list(
            raw_predicate.get("value_tokens"), field_name="applicability value tokens"
        )
        predicates[key] = (operator, tokens)
    for fact in facts:
        predicate_entry = predicates.get(fact.key)
        if predicate_entry is None:
            continue
        operator, tokens = predicate_entry
        present = _fact_token(fact.values[0]) in tokens
        if operator in {"EQ", "IN"} and not present:
            return False
        if operator in {"NOT_EQ", "NOT_IN"} and present:
            return False
    return True


_FLATTENED_AUTHORITY_FIELDS = frozenset(
    {
        "metadata_revision_id",
        "metadata_revision_digest",
        "visibility_revision_id",
        "visibility_revision_digest",
        "visibility",
        "institution_mode",
        "region_mode",
        "channel_mode",
        "role_mode",
        "business_line_mode",
        "allowed_institutions",
        "allowed_regions",
        "allowed_channels",
        "allowed_roles",
        "allowed_business_lines",
        "taxonomy_id",
        "taxonomy_revision_id",
        "applicability_predicates",
        "product_codes",
        "authority",
        "authority_tier",
        "precedence_policy_revision",
        "precedence_order",
        "supersedes_rule_unit_revision_ids",
        "effective_from",
        "effective_to",
        "approved_metadata",
        "approved_visibility",
    }
)


def _strict_authority_payloads(
    source: Mapping[str, object],
) -> tuple[
    ApprovedInsuranceRuleMetadataRevision,
    ApprovedInsuranceKnowledgeVisibilityScope,
    dict[str, object],
]:
    approved_metadata = _mapping(
        source.get("approved_metadata"), field_name="approved_metadata"
    )
    approved_visibility = _mapping(
        source.get("approved_visibility"), field_name="approved_visibility"
    )
    try:
        metadata = ApprovedInsuranceRuleMetadataRevision.model_validate_json(
            json.dumps(approved_metadata, ensure_ascii=False, separators=(",", ":"))
        )
        visibility = ApprovedInsuranceKnowledgeVisibilityScope.model_validate_json(
            json.dumps(approved_visibility, ensure_ascii=False, separators=(",", ":"))
        )
        expected = _authority_projection_fields(metadata, visibility)
    except (TypeError, ValueError) as exc:
        raise OpenSearchProjectionError(
            "search hit approved authority payload is invalid"
        ) from exc
    for field in _FLATTENED_AUTHORITY_FIELDS:
        if field in expected:
            if field not in source or source[field] != expected[field]:
                raise OpenSearchProjectionError(
                    "search hit flattened authority does not match approved payload"
                )
        elif field in source:
            raise OpenSearchProjectionError(
                "search hit contains an inapplicable flattened authority field"
            )
    return metadata, visibility, expected


def _normalize_search_hits(
    response: OpenSearchTransportResponse,
    *,
    request: HybridSearchRequest,
    index_name: str,
) -> tuple[HybridSearchHit, ...]:
    if response.status_code != 200:
        raise OpenSearchProjectionError("OpenSearch search failed")
    if response.body.get("timed_out") is not False:
        raise OpenSearchProjectionError("OpenSearch search timed out or omitted completeness")
    _validated_shard_state(
        response.body.get("_shards"), field_name="search shards", allow_zero=False
    )
    hits_envelope = _mapping(response.body.get("hits"), field_name="search hits")
    raw_hits = hits_envelope.get("hits")
    if not isinstance(raw_hits, list) or len(raw_hits) > request.rrf_window:
        raise OpenSearchProjectionError("OpenSearch returned an invalid candidate count")
    allowed_fields = set(
        _mapping(
            rule_unit_index_mapping(dimension=1)["properties"],
            field_name="mapping properties",
        )
    )
    result: list[HybridSearchHit] = []
    seen_rule_units: set[str] = set()
    for rank, raw_hit in enumerate(raw_hits, start=1):
        hit = _mapping(raw_hit, field_name="search hit")
        fused_score = _finite_score(hit.get("_score"), field_name="fused score")
        if hit.get("_index") != index_name:
            raise OpenSearchProjectionError("search hit came from an unexpected physical index")
        source = _mapping(hit.get("_source"), field_name="search hit source")
        if not set(source).issubset(allowed_fields):
            raise OpenSearchProjectionError("search hit contains an unknown projection field")
        projection_id = _exact_string(source.get("projection_id"), field_name="projection_id")
        if hit.get("_id") != projection_id:
            raise OpenSearchProjectionError("search hit id does not match its projection")
        generation = request.identity.generation
        source_id = _exact_string(source.get("source_id"), field_name="source_id")
        generation_id = _exact_string(
            source.get("index_generation_id"), field_name="index_generation_id"
        )
        if source_id != generation.source_id or generation_id != generation.generation_id:
            raise OpenSearchProjectionError("search hit is outside the exact Source generation")
        manifest_entry_sha256 = _sha256(
            source.get("manifest_entry_sha256"), field_name="manifest_entry_sha256"
        )
        sequence_from = _exact_integer(
            source.get("publication_seq_from"), field_name="publication_seq_from"
        )
        raw_sequence_to = source.get("publication_seq_to")
        sequence_to = (
            None
            if raw_sequence_to is None
            else _exact_integer(raw_sequence_to, field_name="publication_seq_to")
        )
        requested_sequence = request.source_publication_seq
        if sequence_from > requested_sequence or (
            sequence_to is not None and sequence_to < requested_sequence
        ):
            raise OpenSearchProjectionError("search hit is outside publication membership")
        immutable_projection_sha256 = _sha256(
            source.get("immutable_projection_sha256"),
            field_name="immutable_projection_sha256",
        )
        projection_sha256 = _sha256(
            source.get("projection_sha256"), field_name="projection_sha256"
        )
        _exact_string(
            source.get("publication_attempt_id"), field_name="publication_attempt_id"
        )
        projection_revision = _exact_string(
            source.get("projection_revision"), field_name="projection_revision"
        )
        if projection_revision != generation.search_projection_version:
            raise OpenSearchProjectionError("search hit projection revision does not match")

        rule_unit_id = _exact_string(
            source.get("rule_unit_revision_id"), field_name="rule_unit_revision_id"
        )
        if rule_unit_id in seen_rule_units:
            raise OpenSearchProjectionError("search response contains duplicate Rule Units")
        seen_rule_units.add(rule_unit_id)
        document_id = _exact_string(source.get("document_id"), field_name="document_id")
        revision_id = _exact_string(source.get("revision_id"), field_name="revision_id")
        structured_build_id = _exact_string(
            source.get("structured_artifact_build_identity"),
            field_name="structured_artifact_build_identity",
        )
        metadata_revision_id = _exact_string(
            source.get("metadata_revision_id"), field_name="metadata_revision_id"
        )
        visibility_revision_id = _exact_string(
            source.get("visibility_revision_id"), field_name="visibility_revision_id"
        )
        content_sha256 = _sha256(source.get("content_sha256"), field_name="content_sha256")
        authority_sha256 = _sha256(
            source.get("authority_sha256"), field_name="authority_sha256"
        )
        citation_uri = _exact_string(
            source.get("citation_uri"), field_name="citation_uri", maximum=512
        )
        try:
            manifest_entry = RuleUnitManifestEntry(
                rule_unit_revision_id=rule_unit_id,
                document_id=document_id,
                revision_id=revision_id,
                structured_build_id=structured_build_id,
                metadata_revision_id=metadata_revision_id,
                visibility_revision_id=visibility_revision_id,
                content_sha256=content_sha256,
                authority_sha256=authority_sha256,
                citation_uri=citation_uri,
                publication_seq_from=sequence_from,
                publication_seq_to=sequence_to,
            )
        except ValueError as exc:
            raise OpenSearchProjectionError("search hit citation or lineage is invalid") from exc
        if stable_digest(manifest_entry.model_dump(mode="json")) != manifest_entry_sha256:
            raise OpenSearchProjectionError("search hit manifest entry digest does not match")
        _validate_citation_binding(
            citation_uri,
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        content = _exact_string(
            source.get("content"), field_name="content", maximum=50_000
        )
        if hashlib.sha256(content.encode()).hexdigest() != content_sha256:
            raise OpenSearchProjectionError("search hit content digest does not match")
        metadata, visibility, _expected_authority = _strict_authority_payloads(source)
        if metadata.metadata_revision_id != metadata_revision_id:
            raise OpenSearchProjectionError("search hit metadata revision does not match")
        if visibility.revision_id != visibility_revision_id:
            raise OpenSearchProjectionError("search hit visibility revision does not match")
        metadata_digest = _sha256(
            source.get("metadata_revision_digest"), field_name="metadata_revision_digest"
        )
        visibility_digest = _sha256(
            source.get("visibility_revision_digest"), field_name="visibility_revision_digest"
        )
        if stable_digest(
            {
                "approved_metadata": metadata.model_dump(mode="json"),
                "approved_visibility": visibility.model_dump(mode="json"),
            }
        ) != authority_sha256:
            raise OpenSearchProjectionError("search hit authority digest does not match")
        if not _date_is_effective(source, request.as_of_date):
            raise OpenSearchProjectionError("search hit is outside its effective period")
        if not _is_authorized(source, request.authorization):
            raise OpenSearchProjectionError("search hit is unauthorized")
        if not _applicability_allows(source, request.applicability_filters):
            raise OpenSearchProjectionError("search hit is outside approved applicability")
        if _immutable_projection_sha256(source) != immutable_projection_sha256:
            raise OpenSearchProjectionError("search hit immutable projection digest does not match")
        if _mutable_projection_sha256(source) != projection_sha256:
            raise OpenSearchProjectionError("search hit mutable projection digest does not match")
        if rank > request.limit:
            continue
        result.append(
            HybridSearchHit(
                rank=rank,
                source_id=source_id,
                index_generation_id=generation_id,
                index_uuid=request.identity.index_uuid,
                projection_id=projection_id,
                rule_unit_revision_id=rule_unit_id,
                document_id=document_id,
                revision_id=revision_id,
                manifest_entry_sha256=manifest_entry_sha256,
                metadata_revision_digest=metadata_digest,
                visibility_revision_digest=visibility_digest,
                content_sha256=content_sha256,
                authority_sha256=authority_sha256,
                citation_uri=citation_uri,
                content=content,
                fused_score=fused_score,
            )
        )
    return tuple(result)


def rrf_pipeline_body(*, rank_constant: int) -> dict[str, object]:
    if type(rank_constant) is not int or not 1 <= rank_constant <= 1_000:
        raise ValueError("RRF rank constant must be between 1 and 1000")
    return {
        "description": "Proof Agent Source-local reciprocal-rank fusion",
        "phase_results_processors": [
            {
                "score-ranker-processor": {
                    "combination": {
                        "technique": "rrf",
                        "rank_constant": rank_constant,
                    }
                }
            }
        ],
    }


def rrf_pipeline_name(*, rank_constant: int) -> str:
    digest = stable_digest(rrf_pipeline_body(rank_constant=rank_constant))
    return f"pa-source-local-rrf-{digest[:24]}"


class OpenSearchHybridIndex:
    """Deep adapter implementing the provider-neutral HybridSearchIndex seam."""

    def __init__(self, *, transport: OpenSearchTransport) -> None:
        self._transport = transport

    def _validate_generation(self, generation: KnowledgeIndexGeneration) -> None:
        if generation.mapping_sha256 != rule_unit_mapping_sha256(
            dimension=generation.embedding_dimension,
        ):
            raise OpenSearchProjectionError("generation mapping digest does not match actual mapping")
        if generation.analyzer_sha256 != rule_unit_analyzer_sha256():
            raise OpenSearchProjectionError(
                "generation analyzer digest does not match actual analyzer configuration"
            )

    def _verify_pipeline(self, *, pipeline: str, rank_constant: int) -> None:
        expected_name = rrf_pipeline_name(rank_constant=rank_constant)
        if pipeline != expected_name:
            raise OpenSearchProjectionError("RRF pipeline identity is not content-addressed")
        response = self._transport.request(method="GET", path=f"/_search/pipeline/{pipeline}")
        if response.status_code != 200 or set(response.body) != {pipeline}:
            raise OpenSearchProjectionError("exact RRF pipeline is unavailable")
        if response.body[pipeline] != rrf_pipeline_body(rank_constant=rank_constant):
            raise OpenSearchProjectionError("RRF pipeline content does not match its identity")

    def _ensure_pipeline(self, *, pipeline: str, rank_constant: int) -> None:
        expected_name = rrf_pipeline_name(rank_constant=rank_constant)
        if pipeline != expected_name:
            raise OpenSearchProjectionError("RRF pipeline identity is not content-addressed")
        existing = self._transport.request(method="GET", path=f"/_search/pipeline/{pipeline}")
        if existing.status_code == 200:
            self._verify_pipeline(pipeline=pipeline, rank_constant=rank_constant)
            return
        if existing.status_code != 404:
            raise OpenSearchProjectionError("RRF pipeline lookup failed")
        created = self._transport.request(
            method="PUT",
            path=f"/_search/pipeline/{pipeline}",
            json_body=rrf_pipeline_body(rank_constant=rank_constant),
        )
        if created.status_code not in {200, 201} or created.body.get("acknowledged") is not True:
            raise OpenSearchProjectionError("OpenSearch RRF pipeline creation failed")
        self._verify_pipeline(pipeline=pipeline, rank_constant=rank_constant)

    def create_index(
        self,
        generation: KnowledgeIndexGeneration,
        *,
        rrf_pipeline: str,
        rrf_rank_constant: int,
    ) -> SearchIndexIdentity:
        """Create one exact physical generation and its Source-local RRF pipeline."""

        generation = KnowledgeIndexGeneration.model_validate(
            generation.model_dump(mode="python")
        )
        self._validate_generation(generation)
        self._ensure_pipeline(pipeline=rrf_pipeline, rank_constant=rrf_rank_constant)
        definition = _rule_unit_index_definition(
            dimension=generation.embedding_dimension,
        )
        mappings = _mapping(definition["mappings"], field_name="index mappings")
        mappings["_meta"] = {  # type: ignore[index]
            "source_id": generation.source_id,
            "generation_id": generation.generation_id,
            "embedding_dimension": generation.embedding_dimension,
            "mapping_sha256": generation.mapping_sha256,
            "analyzer_sha256": generation.analyzer_sha256,
        }
        index_name = physical_index_name(generation.source_id, generation.generation_id)
        create_response = self._transport.request(
            method="PUT",
            path=f"/{index_name}",
            json_body=definition,
        )
        if (
            create_response.status_code not in {200, 201}
            or create_response.body.get("acknowledged") is not True
        ):
            raise OpenSearchProjectionError("OpenSearch physical index creation failed")
        identity_response = self._transport.request(method="GET", path=f"/{index_name}")
        if identity_response.status_code != 200:
            raise OpenSearchProjectionError("created OpenSearch index identity is unavailable")
        details = _mapping(
            identity_response.body.get(index_name), field_name="created index identity"
        )
        settings = _mapping(details.get("settings"), field_name="created index settings")
        index_settings = _mapping(
            settings.get("index"), field_name="created index settings.index"
        )
        identity = SearchIndexIdentity(
            generation=generation,
            index_uuid=_exact_string(index_settings.get("uuid"), field_name="index UUID"),
        )
        return _response_index_identity(
            identity_response,
            index_name=index_name,
            expected=identity,
        )

    def verify_identity(self, expected: SearchIndexIdentity) -> SearchIndexIdentity:
        expected = SearchIndexIdentity.model_validate(expected.model_dump(mode="python"))
        generation = expected.generation
        self._validate_generation(generation)
        index_name = physical_index_name(generation.source_id, generation.generation_id)
        response = self._transport.request(method="GET", path=f"/{index_name}")
        return _response_index_identity(
            response,
            index_name=index_name,
            expected=expected,
        )

    def bulk_upsert(self, request: ProjectionBulkRequest) -> ProjectionBulkResult:
        validated = ProjectionBulkRequest.model_validate(request.model_dump(mode="python"))
        if validated != request:
            raise OpenSearchProjectionError("bulk request is not in canonical contract form")
        self.verify_identity(request.identity)
        generation = request.identity.generation
        index_name = physical_index_name(generation.source_id, generation.generation_id)
        payload, projection_set_sha256 = _bulk_payload(request)
        response = self._transport.request(
            method="POST",
            path=f"/{index_name}/_bulk",
            content=payload,
            content_type="application/x-ndjson",
        )
        bulk_markers = _validate_bulk_result(
            response,
            expected_ids=tuple(item.projection_id for item in request.documents),
            expected_index=index_name,
        )
        refresh = self._transport.request(method="POST", path=f"/{index_name}/_refresh")
        self.verify_identity(request.identity)
        checkpoint = _refresh_checkpoint(
            refresh,
            identity=request.identity,
            manifest_root_sha256=request.manifest_root_sha256,
            projection_set_sha256=projection_set_sha256,
            bulk_markers=bulk_markers,
        )
        return ProjectionBulkResult(
            request=request,
            accepted_count=len(request.documents),
            refresh_checkpoint=checkpoint,
        )

    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]:
        validated = HybridSearchRequest.model_validate(request.model_dump(mode="python"))
        if validated != request:
            raise OpenSearchProjectionError("search request is not in canonical contract form")
        self.verify_identity(request.identity)
        self._verify_pipeline(
            pipeline=request.rrf_pipeline,
            rank_constant=request.rrf_rank_constant,
        )
        generation = request.identity.generation
        index_name = physical_index_name(generation.source_id, generation.generation_id)
        query_body = build_hybrid_query(request)
        pipeline = _exact_string(
            query_body.pop("search_pipeline"), field_name="search_pipeline", maximum=128
        )
        response = self._transport.request(
            method="POST",
            path=f"/{index_name}/_search",
            json_body=query_body,
            query_params={"search_pipeline": pipeline},
        )
        self.verify_identity(request.identity)
        self._verify_pipeline(
            pipeline=request.rrf_pipeline,
            rank_constant=request.rrf_rank_constant,
        )
        return _normalize_search_hits(
            response,
            request=request,
            index_name=index_name,
        )


__all__ = [
    "HttpxOpenSearchTransport",
    "OpenSearchHybridIndex",
    "OpenSearchProjectionError",
    "OpenSearchSecretMaterial",
    "OpenSearchSecretProvider",
    "OpenSearchTransport",
    "OpenSearchTransportResponse",
    "build_common_filter",
    "build_hybrid_query",
    "physical_index_name",
    "project_rule_unit_document",
    "rrf_pipeline_body",
    "rrf_pipeline_name",
    "rule_unit_analysis_settings",
    "rule_unit_analyzer_sha256",
    "rule_unit_index_mapping",
    "rule_unit_mapping_sha256",
]
