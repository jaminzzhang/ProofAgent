"""Real OpenSearch lexical, sparse-vector, and dense-vector projection."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx

from knowledge_source_service.domain.identities import sha256_json
from knowledge_source_service.ports.search_projection import (
    HybridProjectionResult,
    ProjectionAttestation,
    ProjectionEvidenceUnit,
    ProjectionLaneHit,
)


_INDEX_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_SPARSE_FEATURE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class SearchProjectionError(RuntimeError):
    """A rebuildable search projection operation failed closed."""


class OpenSearchHybridProjection:
    """Maintain one exact physical index per immutable projection generation."""

    def __init__(self, *, endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("OpenSearch endpoint is invalid")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("non-loopback OpenSearch endpoint must use HTTPS")
        self._client = httpx.Client(
            base_url=endpoint.rstrip("/"),
            timeout=httpx.Timeout(10, connect=3),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def rebuild(
        self,
        *,
        index_identity: str,
        dense_dimension: int,
        documents: tuple[ProjectionEvidenceUnit, ...],
    ) -> ProjectionAttestation:
        _validate_index_identity(index_identity)
        if dense_dimension < 1 or not documents:
            raise ValueError("projection generation requires documents and a dimension")
        if len({document.evidence_unit_id for document in documents}) != len(documents):
            raise ValueError("projection Evidence Unit identities must be unique")
        if any(len(document.dense_vector) != dense_dimension for document in documents):
            raise ValueError("projection dense vector dimensions do not match")
        for document in documents:
            _validate_sparse_vector(document.sparse_vector)
        corpus_digest = sha256_json(
            [
                {
                    "evidence_unit_id": document.evidence_unit_id,
                    "knowledge_source_version_id": document.knowledge_source_version_id,
                    "content_hash": document.content_hash,
                    "dense_vector": document.dense_vector,
                    "sparse_vector": dict(document.sparse_vector),
                }
                for document in documents
            ]
        )
        mapping = _mapping(dense_dimension)
        mapping_digest = sha256_json(mapping)
        mapping["mappings"]["_meta"] = {
            "schema": "knowledge-hybrid-projection.v1",
            "mapping_digest": mapping_digest,
            "corpus_digest": corpus_digest,
            "document_count": len(documents),
        }
        response = self._client.put(f"/{index_identity}", json=mapping)
        if response.status_code != 200:
            return self._verify_existing_generation(
                index_identity=index_identity,
                mapping_digest=mapping_digest,
                corpus_digest=corpus_digest,
                document_count=len(documents),
            )
        bulk_lines: list[str] = []
        for document in documents:
            bulk_lines.append(
                json.dumps(
                    {"index": {"_index": index_identity, "_id": document.evidence_unit_id}},
                    separators=(",", ":"),
                )
            )
            bulk_lines.append(
                json.dumps(
                    {
                        "knowledge_source_id": document.knowledge_source_id,
                        "knowledge_source_version_id": (
                            document.knowledge_source_version_id
                        ),
                        "evidence_unit_id": document.evidence_unit_id,
                        "text": document.text,
                        "content_hash": document.content_hash,
                        "dense_vector": document.dense_vector,
                        "sparse_vector": dict(document.sparse_vector),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        bulk = self._client.post(
            "/_bulk?refresh=wait_for",
            content=("\n".join(bulk_lines) + "\n").encode(),
            headers={"Content-Type": "application/x-ndjson"},
        )
        payload = _json_object(bulk)
        if bulk.status_code != 200 or payload.get("errors") is not False:
            self.delete_generation(index_identity)
            raise SearchProjectionError("OpenSearch projection bulk indexing failed")
        return ProjectionAttestation(
            index_identity=index_identity,
            mapping_digest=mapping_digest,
            corpus_digest=corpus_digest,
            document_count=len(documents),
        )

    def _verify_existing_generation(
        self,
        *,
        index_identity: str,
        mapping_digest: str,
        corpus_digest: str,
        document_count: int,
    ) -> ProjectionAttestation:
        mapping_response = self._client.get(f"/{index_identity}/_mapping")
        count_response = self._client.get(f"/{index_identity}/_count")
        if mapping_response.status_code != 200 or count_response.status_code != 200:
            raise SearchProjectionError(
                "OpenSearch projection generation create failed"
            )
        mapping_payload = _json_object(mapping_response)
        count_payload = _json_object(count_response)
        index_payload = mapping_payload.get(index_identity)
        if type(index_payload) is not dict:
            raise SearchProjectionError(
                "existing OpenSearch projection attestation is missing"
            )
        mappings = index_payload.get("mappings")
        metadata = mappings.get("_meta") if type(mappings) is dict else None
        expected_metadata = {
            "schema": "knowledge-hybrid-projection.v1",
            "mapping_digest": mapping_digest,
            "corpus_digest": corpus_digest,
            "document_count": document_count,
        }
        if metadata != expected_metadata or count_payload.get("count") != document_count:
            raise SearchProjectionError(
                "existing OpenSearch projection does not match the exact generation"
            )
        return ProjectionAttestation(
            index_identity=index_identity,
            mapping_digest=mapping_digest,
            corpus_digest=corpus_digest,
            document_count=document_count,
        )

    def query(
        self,
        *,
        index_identity: str,
        lexical_query: str,
        dense_vector: tuple[float, ...],
        sparse_vector: Mapping[str, float],
        top_k: int,
    ) -> HybridProjectionResult:
        _validate_index_identity(index_identity)
        if not lexical_query.strip() or not dense_vector or top_k < 1 or top_k > 1000:
            raise ValueError("hybrid projection query is invalid")
        _validate_sparse_vector(sparse_vector)
        lexical = self._search_lane(
            index_identity=index_identity,
            lane="lexical",
            top_k=top_k,
            query={"match": {"text": {"query": lexical_query, "operator": "or"}}},
        )
        sparse_should = [
            {
                "rank_feature": {
                    "field": f"sparse_vector.{feature}",
                    "boost": weight,
                }
            }
            for feature, weight in sorted(sparse_vector.items())
        ]
        sparse = self._search_lane(
            index_identity=index_identity,
            lane="sparse",
            top_k=top_k,
            query={"bool": {"should": sparse_should, "minimum_should_match": 1}},
        )
        dense = self._search_lane(
            index_identity=index_identity,
            lane="dense",
            top_k=top_k,
            query={
                "knn": {
                    "dense_vector": {
                        "vector": dense_vector,
                        "k": top_k,
                    }
                }
            },
        )
        return HybridProjectionResult(lexical=lexical, sparse=sparse, dense=dense)

    def verify_generation(self, attestation: ProjectionAttestation) -> None:
        """Fail closed unless the physical generation matches the pinned attestation."""

        verified = self._verify_existing_generation(
            index_identity=attestation.index_identity,
            mapping_digest=attestation.mapping_digest,
            corpus_digest=attestation.corpus_digest,
            document_count=attestation.document_count,
        )
        if verified != attestation:
            raise SearchProjectionError(
                "OpenSearch projection attestation verification failed"
            )

    def delete_generation(self, index_identity: str) -> None:
        _validate_index_identity(index_identity)
        response = self._client.delete(f"/{index_identity}")
        if response.status_code not in {200, 404}:
            raise SearchProjectionError("OpenSearch generation delete failed")

    def _search_lane(
        self,
        *,
        index_identity: str,
        lane: Literal["lexical", "sparse", "dense"],
        top_k: int,
        query: dict[str, Any],
    ) -> tuple[ProjectionLaneHit, ...]:
        response = self._client.post(
            f"/{index_identity}/_search",
            json={"size": top_k, "_source": False, "query": query},
        )
        payload = _json_object(response)
        if response.status_code != 200:
            raise SearchProjectionError(f"OpenSearch {lane} lane query failed")
        hits_wrapper = payload.get("hits")
        if type(hits_wrapper) is not dict or type(hits_wrapper.get("hits")) is not list:
            raise SearchProjectionError("OpenSearch lane response is malformed")
        hits = cast(list[object], hits_wrapper["hits"])
        result: list[ProjectionLaneHit] = []
        for rank, hit_value in enumerate(hits, start=1):
            if type(hit_value) is not dict:
                raise SearchProjectionError("OpenSearch lane hit is malformed")
            hit = cast(dict[str, Any], hit_value)
            evidence_unit_id = hit.get("_id")
            score = hit.get("_score")
            if type(evidence_unit_id) is not str or type(score) not in {int, float}:
                raise SearchProjectionError("OpenSearch lane hit identity is malformed")
            native_score = cast(int | float, score)
            result.append(
                ProjectionLaneHit(
                    lane=lane,
                    evidence_unit_id=evidence_unit_id,
                    native_score=float(native_score),
                    lane_rank=rank,
                    index_identity=index_identity,
                )
            )
        return tuple(result)


def _mapping(dense_dimension: int) -> dict[str, Any]:
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "knowledge_source_id": {"type": "keyword"},
                "knowledge_source_version_id": {"type": "keyword"},
                "evidence_unit_id": {"type": "keyword"},
                "text": {"type": "text"},
                "content_hash": {"type": "keyword"},
                "dense_vector": {
                    "type": "knn_vector",
                    "dimension": dense_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },
                "sparse_vector": {"type": "rank_features"},
            },
        },
    }


def _validate_index_identity(value: str) -> None:
    if _INDEX_IDENTITY.fullmatch(value) is None:
        raise ValueError("OpenSearch index identity is invalid")


def _validate_sparse_vector(value: Mapping[str, float]) -> None:
    if (
        not value
        or len(value) > 1024
        or any(
            _SPARSE_FEATURE.fullmatch(feature) is None
            or type(weight) not in {int, float}
            or weight <= 0
            for feature, weight in value.items()
        )
    ):
        raise ValueError("sparse vector is invalid")


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise SearchProjectionError("OpenSearch returned invalid JSON") from error
    if type(payload) is not dict:
        raise SearchProjectionError("OpenSearch returned a non-object response")
    return cast(dict[str, Any], payload)
