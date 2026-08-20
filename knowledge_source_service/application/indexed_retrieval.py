"""Hybrid retrieval from a Release-pinned index with exact artifact evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Literal, cast

from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.projection_encoding import (
    ProjectionTextEncoder,
)
from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.domain.identities import content_identifier, sha256_json
from knowledge_source_service.domain.knowledge_catalog import (
    DocxParagraphDocumentCitation,
    DocxTableCellDocumentCitation,
    DocumentEvidenceUnit,
    DocumentSourceVersion,
    HtmlDomDocumentCitation,
    KnowledgeBaseReleaseSnapshot,
    KnowledgeSourceVersion,
    OcrRegionDocumentCitation,
    PptxShapeDocumentCitation,
)
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogReader
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from knowledge_source_service.ports.search_projection import (
    HybridSearchProjection,
    ProjectionAttestation,
    ProjectionLaneHit,
)


_RRF_K = 60
_LANE_WEIGHTS: dict[Literal["lexical", "sparse", "dense"], float] = {
    "lexical": 1.0,
    "sparse": 0.8,
    "dense": 0.8,
}


@dataclass
class _IndexedEvidence:
    source: DocumentSourceVersion
    unit: DocumentEvidenceUnit
    hits: dict[Literal["lexical", "sparse", "dense"], ProjectionLaneHit] = field(
        default_factory=dict
    )

    @property
    def fused_score(self) -> float:
        return sum(
            _LANE_WEIGHTS[lane] / (_RRF_K + hit.lane_rank)
            for lane, hit in self.hits.items()
        )


class IndexedHybridKnowledgeRetrievalEngine:
    """Use projection scores while treating immutable artifacts as content authority."""

    def __init__(
        self,
        *,
        catalog: KnowledgeCatalogReader,
        projection: HybridSearchProjection,
        encoder: ProjectionTextEncoder,
    ) -> None:
        self._catalog = catalog
        self._projection = projection
        self._encoder = encoder
        self._fallback = HybridKnowledgeRetrievalEngine(catalog=catalog)

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        baseline = self._fallback.retrieve(query)
        release = self._catalog.get_release(query.request.knowledge_base_release_id)
        if release is None:
            raise ValueError("unknown exact Knowledge Base Release")
        source_versions = tuple(
            self._required_source_version(source_version_id)
            for source_version_id in release.knowledge_source_version_ids
        )
        documents = tuple(
            version
            for version in source_versions
            if isinstance(version, DocumentSourceVersion)
        )
        if not documents:
            return baseline

        binding = release.retrieval_projection
        if binding is None:
            raise ValueError("document Release has no pinned retrieval projection")
        if (
            binding.dense_revision != self._encoder.dense_revision
            or binding.sparse_revision != self._encoder.sparse_revision
            or binding.dense_dimension != self._encoder.dense_dimension
        ):
            raise ValueError("configured projection encoder does not match the Release")

        exact_units = self._exact_units(documents)
        self._verify_corpus_binding(documents, binding.corpus_digest, binding.document_count)
        self._projection.verify_generation(
            ProjectionAttestation(
                index_identity=binding.index_identity,
                mapping_digest=binding.mapping_digest,
                corpus_digest=binding.corpus_digest,
                document_count=binding.document_count,
            )
        )
        encoded_query = self._encoder.encode(query.request.question)
        projection_result = self._projection.query(
            index_identity=binding.index_identity,
            lexical_query=query.request.question,
            dense_vector=encoded_query.dense_vector,
            sparse_vector=encoded_query.sparse_vector,
            top_k=query.request.execution_budget.max_candidates,
        )
        ranked = self._fuse_hits(
            index_identity=binding.index_identity,
            exact_units=exact_units,
            lanes=(
                ("lexical", projection_result.lexical),
                ("sparse", projection_result.sparse),
                ("dense", projection_result.dense),
            ),
        )[: query.request.execution_budget.max_candidates]
        query_digest = sha256_json(
            {
                "question": query.request.question,
                "constraints": query.request.query_constraints.model_dump(mode="json"),
            }
        )
        candidates = [
            self._candidate_payload(
                query=query,
                release=release,
                indexed=indexed,
                fused_rank=fused_rank,
                query_digest=query_digest,
                index_identity=binding.index_identity,
            )
            for fused_rank, indexed in enumerate(ranked, start=1)
        ]
        payload = baseline.model_dump(mode="json")
        groups = cast(list[dict[str, Any]], payload["evidence_groups"])
        relevance_group = next(
            (group for group in groups if group["group_type"] == "relevance_ranked"),
            None,
        )
        if relevance_group is None:
            raise ValueError("document Release produced no relevance evidence group")
        relevance_group["candidate_evidence"] = candidates
        remaining = query.request.execution_budget.max_candidates - len(candidates)
        for group in groups:
            if group["group_type"] == "structured":
                group["candidate_evidence"] = group["candidate_evidence"][
                    : max(0, remaining)
                ]
                remaining -= len(group["candidate_evidence"])
        candidate_count = sum(len(group["candidate_evidence"]) for group in groups)
        execution = cast(dict[str, Any], payload["execution_summary"])
        budget_usage = cast(dict[str, Any], execution["budget_usage"])
        budget_usage["candidates"] = candidate_count
        execution["stop_reason"] = (
            "no_candidates"
            if candidate_count == 0
            else (
                "single_pass_complete"
                if query.request.strategy == "single_pass"
                else "coverage_complete"
            )
        )
        return KnowledgeQueryResult.model_validate(payload)

    def _required_source_version(
        self, source_version_id: str
    ) -> KnowledgeSourceVersion:
        version = self._catalog.get_source_version(source_version_id)
        if version is None:
            raise ValueError("Release references an unavailable Source Version")
        return version

    @staticmethod
    def _exact_units(
        documents: tuple[DocumentSourceVersion, ...],
    ) -> dict[str, tuple[DocumentSourceVersion, DocumentEvidenceUnit]]:
        units: dict[str, tuple[DocumentSourceVersion, DocumentEvidenceUnit]] = {}
        for document in documents:
            for unit in document.evidence_units:
                if unit.evidence_unit_id in units:
                    raise ValueError("Release contains duplicate Evidence Unit identities")
                units[unit.evidence_unit_id] = (document, unit)
        return units

    def _verify_corpus_binding(
        self,
        documents: tuple[DocumentSourceVersion, ...],
        expected_digest: str,
        expected_count: int,
    ) -> None:
        corpus: list[dict[str, object]] = []
        for document in documents:
            for unit in document.evidence_units:
                encoded = self._encoder.encode(unit.text)
                corpus.append(
                    {
                        "evidence_unit_id": unit.evidence_unit_id,
                        "knowledge_source_version_id": (
                            document.knowledge_source_version_id
                        ),
                        "content_hash": unit.content_hash,
                        "dense_vector": encoded.dense_vector,
                        "sparse_vector": encoded.sparse_vector,
                    }
                )
        if len(corpus) != expected_count or sha256_json(corpus) != expected_digest:
            raise ValueError("exact artifacts do not match the Release projection binding")

    @staticmethod
    def _fuse_hits(
        *,
        index_identity: str,
        exact_units: dict[str, tuple[DocumentSourceVersion, DocumentEvidenceUnit]],
        lanes: tuple[
            tuple[
                Literal["lexical", "sparse", "dense"],
                tuple[ProjectionLaneHit, ...],
            ],
            ...,
        ],
    ) -> list[_IndexedEvidence]:
        fused: dict[str, _IndexedEvidence] = {}
        for expected_lane, hits in lanes:
            for hit in hits:
                exact = exact_units.get(hit.evidence_unit_id)
                if (
                    hit.index_identity != index_identity
                    or hit.lane != expected_lane
                    or hit.lane_rank < 1
                    or not isfinite(hit.native_score)
                    or exact is None
                ):
                    raise ValueError("retrieval projection returned an unbound hit")
                indexed = fused.setdefault(
                    hit.evidence_unit_id,
                    _IndexedEvidence(source=exact[0], unit=exact[1]),
                )
                if expected_lane in indexed.hits:
                    raise ValueError("retrieval projection returned a duplicate lane hit")
                indexed.hits[expected_lane] = hit
        return sorted(
            fused.values(),
            key=lambda item: (-item.fused_score, item.unit.evidence_unit_id),
        )

    @staticmethod
    def _candidate_payload(
        *,
        query: AdmittedKnowledgeQuery,
        release: KnowledgeBaseReleaseSnapshot,
        indexed: _IndexedEvidence,
        fused_rank: int,
        query_digest: str,
        index_identity: str,
    ) -> dict[str, object]:
        unit = indexed.unit
        source = indexed.source
        contributions = [
            {
                "lane": lane,
                "native_score": indexed.hits[lane].native_score,
                "lane_rank": indexed.hits[lane].lane_rank,
                "weight": weight,
                "rrf_contribution": weight / (_RRF_K + indexed.hits[lane].lane_rank),
            }
            for lane, weight in _LANE_WEIGHTS.items()
            if lane in indexed.hits
        ]
        return {
            "candidate_evidence_id": content_identifier(
                "candidate",
                sha256_json(
                    {
                        "release": release.knowledge_base_release_id,
                        "unit": unit.evidence_unit_id,
                        "query": query_digest,
                    }
                ),
            ),
            "knowledge_space_id": release.knowledge_space_id,
            "knowledge_base_id": release.knowledge_base_id,
            "knowledge_base_version_id": release.knowledge_base_version_id,
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "knowledge_source_id": source.knowledge_source_id,
            "knowledge_source_version_id": source.knowledge_source_version_id,
            "evidence_unit_id": unit.evidence_unit_id,
            "content": {"media_type": source.media_type, "text": unit.text},
            "content_hash": unit.content_hash,
            "citation_locator": _document_citation(unit),
            "context_evidence_units": [],
            "ranking": {
                "kind": "relevance",
                "lane_contributions": contributions,
                "fused_rank": fused_rank,
                "reranked_rank": None,
            },
            "retrieval_lineage": {
                "retrieval_round": 1,
                "plan_revision": 1,
                "index_identity": index_identity,
                "query_digest": query_digest,
                "access_scope_digest": query.admission.effective_access_scope_digest,
            },
        }


def _document_citation(unit: DocumentEvidenceUnit) -> dict[str, object]:
    locator = unit.citation_locator
    if locator.kind == "pdf_page":
        return {"kind": "pdf_page", "page_number": locator.page_number}
    if isinstance(locator, DocxParagraphDocumentCitation):
        return {
            "kind": "docx_paragraph",
            "paragraph_number": locator.paragraph_number,
        }
    if isinstance(locator, DocxTableCellDocumentCitation):
        return {
            "kind": "docx_table_cell",
            "table_number": locator.table_number,
            "row_number": locator.row_number,
            "column_number": locator.column_number,
        }
    if isinstance(locator, PptxShapeDocumentCitation):
        return {
            "kind": "pptx_shape",
            "slide_number": locator.slide_number,
            "shape_id": locator.shape_id,
        }
    if isinstance(locator, HtmlDomDocumentCitation):
        return {
            "kind": "html_dom",
            "dom_path": locator.dom_path,
        }
    if isinstance(locator, OcrRegionDocumentCitation):
        return {
            "kind": "ocr_region",
            "page_number": locator.page_number,
            "bounding_box": {
                "x_min": locator.x_min,
                "y_min": locator.y_min,
                "x_max": locator.x_max,
                "y_max": locator.y_max,
            },
        }
    return {
        "kind": "text_lines",
        "start_line": locator.start_line,
        "end_line": locator.end_line,
    }
