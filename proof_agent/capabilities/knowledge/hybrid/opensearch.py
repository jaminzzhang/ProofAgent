"""OpenSearch adapter for the rebuildable Hybrid Knowledge search projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re
from typing import Protocol
from urllib.parse import urlsplit

import httpx

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
from proof_agent.contracts.insurance_rules import TaxonomyCondition
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
        self._client = httpx.Client(
            base_url=base_url,
            timeout=float(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
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
        headers = {"Content-Type": content_type, "Accept": "application/json"}
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
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenSearchProjectionError("OpenSearch returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise OpenSearchProjectionError("OpenSearch response must be a JSON object")
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


def rule_unit_index_mapping(*, dimension: int, analyzer: str = "cjk") -> dict[str, object]:
    """Build the pinned Rule Unit mapping without accepting backend-native input."""

    if type(dimension) is not int or dimension <= 0 or dimension > 65_535:
        raise ValueError("dimension must be a positive integer no greater than 65535")
    if type(analyzer) is not str or not analyzer.strip():
        raise ValueError("analyzer must be a nonblank string")
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
            "authority_manifest_digest",
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
            "applicability_tokens",
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
            "applicability_numbers": {
                "type": "nested",
                "properties": {
                    "key": dict(keyword),
                    "operator": dict(keyword),
                    "value": {"type": "double"},
                },
            },
            "lexical_text": {"type": "text", "analyzer": analyzer},
            "content": {"type": "text", "index": False},
            "title": {"type": "text", "analyzer": analyzer},
            "heading_path": {"type": "text", "analyzer": analyzer},
            "definitions": {"type": "text", "analyzer": analyzer},
            "table_context": {"type": "text", "analyzer": analyzer},
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


def _rule_unit_index_definition(*, dimension: int, analyzer: str) -> dict[str, object]:
    return {
        "settings": {"index": {"knn": True}},
        "mappings": rule_unit_index_mapping(dimension=dimension, analyzer=analyzer),
    }


def _bounded_text(value: str, *, field_name: str, maximum: int) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a nonblank string")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds the maximum length")
    return value


def _visibility_fields(document: ProjectionDocument) -> dict[str, object]:
    visibility = document.rule_unit.visibility_scope
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


def project_rule_unit_document(
    document: ProjectionDocument,
    *,
    identity: SearchIndexIdentity,
    manifest_root_sha256: str,
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
    _bounded_text(manifest_root_sha256, field_name="manifest_root_sha256", maximum=64)
    if re.fullmatch(r"[0-9a-f]{64}", manifest_root_sha256) is None:
        raise ValueError("manifest_root_sha256 must be a lowercase SHA-256 digest")
    _bounded_text(publication_attempt_id, field_name="publication_attempt_id", maximum=512)
    _bounded_text(rule.content, field_name="Rule Unit content", maximum=50_000)

    conditions = tuple(sorted(metadata.applicability.conditions, key=lambda item: item.key))
    if len(conditions) > 256 or sum(len(item.values) for item in conditions) > 1_024:
        raise ValueError("approved applicability exceeds projection limits")
    applicability_tokens = sorted(_applicability_token(condition) for condition in conditions)
    numeric_values = [
        {"key": condition.key, "operator": condition.operator, "value": value}
        for condition in conditions
        for value in condition.values
        if type(value) in {int, float}
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
        "authority_manifest_digest": manifest_root_sha256,
        "metadata_revision_id": metadata.metadata_revision_id,
        "metadata_revision_digest": stable_digest(metadata.model_dump(mode="json")),
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
        "taxonomy_id": metadata.applicability.taxonomy_id,
        "taxonomy_revision_id": metadata.applicability.taxonomy_revision_id,
        "applicability_tokens": applicability_tokens,
        "applicability_numbers": numeric_values,
        "product_codes": product_codes,
        "rule_type": rule.unit_kind,
        "authority": metadata.authority,
        "authority_tier": metadata.precedence.authority_tier,
        "precedence_policy_revision": metadata.precedence.policy_revision_id,
        "precedence_order": metadata.precedence.order,
        "supersedes_rule_unit_revision_ids": list(
            metadata.supersedes_rule_unit_revision_ids
        ),
        "lexical_text": lexical_text,
        "dense_vector": list(document.embedding),
        "projection_revision": document.projection_revision,
        "publication_attempt_id": publication_attempt_id,
        **_visibility_fields(document),
    }
    if entry.publication_seq_to is not None:
        projected["publication_seq_to"] = entry.publication_seq_to
    if metadata.effective_from is not None:
        projected["effective_from"] = metadata.effective_from.isoformat()
    if metadata.effective_to is not None:
        projected["effective_to"] = metadata.effective_to.isoformat()
    if lineage.table_id is not None:
        projected["table_id"] = lineage.table_id
    if lineage.table_continuation_id is not None:
        projected["table_continuation_id"] = lineage.table_continuation_id

    immutable = {key: value for key, value in projected.items() if key != "publication_seq_to"}
    immutable.pop("publication_attempt_id")
    projected["immutable_projection_sha256"] = stable_digest(immutable)
    projected["projection_sha256"] = stable_digest(
        {key: value for key, value in projected.items() if key != "publication_attempt_id"}
    )
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


def _applicability_token(condition: TaxonomyCondition) -> str:
    payload = {
        "key": condition.key,
        "operator": condition.operator,
        "values": [_taxonomy_value(value) for value in condition.values],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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


def build_common_filter(request: HybridSearchRequest) -> list[dict[str, object]]:
    """Translate governed authority filters once for both retrieval lanes."""

    sequence = request.source_publication_seq
    filters: list[dict[str, object]] = [
        {"term": {"source_id": request.identity.generation.source_id}},
        {"term": {"index_generation_id": request.identity.generation.generation_id}},
        {"term": {"authority_manifest_digest": request.manifest_root_sha256}},
        {"range": {"publication_seq_from": {"lte": sequence}}},
        _optional_bound_filter("publication_seq_to", "gte", sequence),
        _optional_bound_filter("effective_from", "lte", request.as_of_date.isoformat()),
        _optional_bound_filter("effective_to", "gte", request.as_of_date.isoformat()),
        _visibility_filter(request.authorization),
    ]
    filters.extend(
        {"term": {"applicability_tokens": _applicability_token(condition)}}
        for condition in request.applicability_filters
    )
    return filters


def build_hybrid_query(request: HybridSearchRequest) -> dict[str, object]:
    """Build Source-local BM25+kNN retrieval with identical prefilters."""

    common_filter = build_common_filter(request)
    return {
        "size": request.rrf_window,
        "_source": True,
        "query": {
            "hybrid": {
                "pagination_depth": max(
                    request.lexical_budget,
                    request.dense_budget,
                ),
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
} else if (ctx._source.projection_sha256 == params.doc.projection_sha256) {
  ctx.op = 'noop';
} else if (
  ctx._source.immutable_projection_sha256 == params.doc.immutable_projection_sha256 &&
  !ctx._source.containsKey('publication_seq_to') &&
  params.doc.containsKey('publication_seq_to') &&
  params.doc.publication_seq_to >= params.doc.publication_seq_from
) {
  ctx._source.publication_seq_to = params.doc.publication_seq_to;
  ctx._source.projection_sha256 = params.doc.projection_sha256;
  ctx._source.publication_attempt_id = params.doc.publication_attempt_id;
} else {
  throw new IllegalArgumentException('projection conflict');
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
        return
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
    return expected


def _refresh_checkpoint(response: OpenSearchTransportResponse) -> str:
    if response.status_code != 200:
        raise OpenSearchProjectionError("OpenSearch refresh failed")
    shards = _mapping(response.body.get("_shards"), field_name="refresh shards")
    failed = _exact_integer(shards.get("failed"), field_name="refresh failed shard count")
    if failed != 0:
        raise OpenSearchProjectionError("OpenSearch refresh reported failed shards")
    return f"refresh-sha256:{stable_digest(response.body)}"


def _bulk_payload(request: ProjectionBulkRequest) -> bytes:
    lines: list[str] = []
    for document in request.documents:
        projected = project_rule_unit_document(
            document,
            identity=request.identity,
            manifest_root_sha256=request.manifest_root_sha256,
            publication_attempt_id=request.publication_attempt_id,
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
    return ("\n".join(lines) + "\n").encode()


def _validate_bulk_result(
    response: OpenSearchTransportResponse,
    *,
    expected_count: int,
) -> None:
    if response.status_code != 200 or response.body.get("errors") is not False:
        raise OpenSearchProjectionError("OpenSearch rejected one or more projection writes")
    items = response.body.get("items")
    if not isinstance(items, list) or len(items) != expected_count:
        raise OpenSearchProjectionError("OpenSearch bulk result count does not match the request")
    for item in items:
        update = _mapping(
            _mapping(item, field_name="bulk item").get("update"),
            field_name="bulk update result",
        )
        status = _exact_integer(update.get("status"), field_name="bulk item status")
        if status not in {200, 201}:
            raise OpenSearchProjectionError("OpenSearch bulk item did not succeed")


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


def _normalize_search_hits(
    response: OpenSearchTransportResponse,
    *,
    request: HybridSearchRequest,
    index_name: str,
) -> tuple[HybridSearchHit, ...]:
    if response.status_code != 200:
        raise OpenSearchProjectionError("OpenSearch search failed")
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
    for rank, raw_hit in enumerate(raw_hits[: request.limit], start=1):
        hit = _mapping(raw_hit, field_name="search hit")
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
        manifest_digest = _sha256(
            source.get("authority_manifest_digest"),
            field_name="authority_manifest_digest",
        )
        if manifest_digest != request.manifest_root_sha256:
            raise OpenSearchProjectionError("search hit manifest digest does not match")
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
        if not _date_is_effective(source, request.as_of_date):
            raise OpenSearchProjectionError("search hit is outside its effective period")
        if not _is_authorized(source, request.authorization):
            raise OpenSearchProjectionError("search hit is unauthorized")
        applicability_tokens = _string_list(
            source.get("applicability_tokens"), field_name="applicability_tokens"
        )
        if any(
            _applicability_token(condition) not in applicability_tokens
            for condition in request.applicability_filters
        ):
            raise OpenSearchProjectionError("search hit is outside approved applicability")
        _sha256(
            source.get("immutable_projection_sha256"),
            field_name="immutable_projection_sha256",
        )
        _sha256(source.get("projection_sha256"), field_name="projection_sha256")
        _exact_string(
            source.get("publication_attempt_id"), field_name="publication_attempt_id"
        )
        _exact_string(source.get("projection_revision"), field_name="projection_revision")

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
            RuleUnitManifestEntry(
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
        _validate_citation_binding(
            citation_uri,
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        content = _exact_string(
            source.get("content"), field_name="content", maximum=50_000
        )
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
                authority_manifest_digest=manifest_digest,
                metadata_revision_digest=_sha256(
                    source.get("metadata_revision_digest"),
                    field_name="metadata_revision_digest",
                ),
                visibility_revision_digest=_sha256(
                    source.get("visibility_revision_digest"),
                    field_name="visibility_revision_digest",
                ),
                content_sha256=content_sha256,
                authority_sha256=authority_sha256,
                citation_uri=citation_uri,
                content=content,
                fused_score=_finite_score(hit.get("_score"), field_name="fused score"),
            )
        )
    return tuple(result)


class OpenSearchHybridIndex:
    """Deep adapter implementing the provider-neutral HybridSearchIndex seam."""

    def __init__(self, *, transport: OpenSearchTransport) -> None:
        self._transport = transport

    def create_index(
        self,
        generation: KnowledgeIndexGeneration,
        *,
        rrf_pipeline: str,
        rrf_rank_constant: int,
        analyzer: str = "cjk",
    ) -> SearchIndexIdentity:
        """Create one exact physical generation and its Source-local RRF pipeline."""

        generation = KnowledgeIndexGeneration.model_validate(
            generation.model_dump(mode="python")
        )
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", rrf_pipeline) is None:
            raise ValueError("rrf_pipeline must be a safe explicit pipeline identity")
        if type(rrf_rank_constant) is not int or not 1 <= rrf_rank_constant <= 1_000:
            raise ValueError("rrf_rank_constant must be between 1 and 1000")
        pipeline_response = self._transport.request(
            method="PUT",
            path=f"/_search/pipeline/{rrf_pipeline}",
            json_body={
                "description": "Proof Agent Source-local reciprocal-rank fusion",
                "phase_results_processors": [
                    {
                        "score-ranker-processor": {
                            "combination": {
                                "technique": "rrf",
                                "rank_constant": rrf_rank_constant,
                            }
                        }
                    }
                ],
            },
        )
        if (
            pipeline_response.status_code not in {200, 201}
            or pipeline_response.body.get("acknowledged") is not True
        ):
            raise OpenSearchProjectionError("OpenSearch RRF pipeline creation failed")
        definition = _rule_unit_index_definition(
            dimension=generation.embedding_dimension,
            analyzer=analyzer,
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
        response = self._transport.request(
            method="POST",
            path=f"/{index_name}/_bulk",
            content=_bulk_payload(request),
            content_type="application/x-ndjson",
        )
        _validate_bulk_result(response, expected_count=len(request.documents))
        refresh = self._transport.request(method="POST", path=f"/{index_name}/_refresh")
        return ProjectionBulkResult(
            request=request,
            accepted_count=len(request.documents),
            refresh_checkpoint=_refresh_checkpoint(refresh),
        )

    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]:
        validated = HybridSearchRequest.model_validate(request.model_dump(mode="python"))
        if validated != request:
            raise OpenSearchProjectionError("search request is not in canonical contract form")
        self.verify_identity(request.identity)
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
        return _normalize_search_hits(
            response,
            request=request,
            index_name=index_name,
        )


__all__ = [
    "HttpxOpenSearchTransport",
    "OpenSearchHybridIndex",
    "OpenSearchProjectionError",
    "OpenSearchTransport",
    "OpenSearchTransportResponse",
    "build_common_filter",
    "build_hybrid_query",
    "physical_index_name",
    "project_rule_unit_document",
    "rule_unit_index_mapping",
]
