"""Protocol-compatible local private-model plane for deployment smoke tests.

This service exercises the real HTTPS transports and strict response validators. It is
deliberately deterministic and its release verifier always denies authorization, so it
cannot be confused with real-model or Phase F evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import secrets
from typing import Any, cast

from fastapi import FastAPI, Header, HTTPException, Response


app = FastAPI(title="Proof Agent local private-model compatibility plane")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ready", "evidence_class": "local_compatibility_only"}


@app.post("/scheduler/v1/work/acquire")
def acquire(payload: dict[str, Any]) -> dict[str, object]:
    _require_fields(payload, {"namespace", "kind", "priority", "timeout_seconds"})
    material = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "work_id": f"local-{hashlib.sha256(material).hexdigest()[:24]}",
        "lease_token": secrets.token_urlsafe(32),
        "queue_time_ms": 0.0,
    }


@app.post("/scheduler/v1/work/complete", status_code=204)
def complete(payload: dict[str, Any]) -> Response:
    _require_fields(payload, {"namespace", "work_id", "lease_token"})
    return Response(status_code=204)


@app.post("/scheduler/v1/work/cancel", status_code=204)
def cancel(payload: dict[str, Any]) -> Response:
    _require_fields(payload, {"namespace", "work_id", "lease_token"})
    return Response(status_code=204)


@app.post("/embedding/v1/embeddings")
def embeddings(payload: dict[str, Any]) -> dict[str, object]:
    _require_fields(
        payload,
        {
            "texts",
            "model_revision",
            "instruction",
            "dimension",
            "normalized",
            "allow_runtime_downloads",
        },
    )
    texts = payload["texts"]
    dimension = payload["dimension"]
    if (
        not isinstance(texts, list)
        or not texts
        or not isinstance(dimension, int)
        or not 1 <= dimension <= 4096
        or payload["allow_runtime_downloads"] is not False
    ):
        raise HTTPException(status_code=422, detail="invalid embedding request")
    vectors = [
        _deterministic_vector(
            f"{payload['instruction']}\n{text}",
            dimension=dimension,
            normalized=payload["normalized"] is True,
        )
        for text in texts
        if isinstance(text, str) and text
    ]
    if len(vectors) != len(texts):
        raise HTTPException(status_code=422, detail="invalid embedding texts")
    return {"model_revision": payload["model_revision"], "vectors": vectors}


@app.post("/reranker/v1/rerank")
def rerank(payload: dict[str, Any]) -> dict[str, object]:
    _require_fields(
        payload,
        {
            "query",
            "candidates",
            "model_revision",
            "max_input_tokens",
            "allow_runtime_downloads",
        },
    )
    query = payload["query"]
    candidates = payload["candidates"]
    if (
        not isinstance(query, str)
        or not isinstance(candidates, list)
        or not candidates
        or payload["allow_runtime_downloads"] is not False
    ):
        raise HTTPException(status_code=422, detail="invalid reranker request")
    query_terms = set(query.lower().split())
    scores: list[list[object]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise HTTPException(status_code=422, detail="invalid reranker candidate")
        candidate_id = candidate.get("candidate_id")
        text = candidate.get("text")
        if not isinstance(candidate_id, str) or not isinstance(text, str):
            raise HTTPException(status_code=422, detail="invalid reranker candidate")
        overlap = len(query_terms.intersection(text.lower().split()))
        scores.append([candidate_id, float(overlap) + 1.0 / float(index + 1)])
    return {"model_revision": payload["model_revision"], "scores": scores}


@app.post("/docling/v1/parse")
def docling_parse(payload: dict[str, Any]) -> dict[str, object]:
    return _parser_response(payload, adapter="docling")


@app.post("/paddle/v1/parse")
def paddle_parse(payload: dict[str, Any]) -> dict[str, object]:
    return _parser_response(payload, adapter="paddle")


@app.post("/evaluation/v1/knowledge-evaluation/release/verify")
def verify_release() -> dict[str, object]:
    return {
        "authorized": False,
        "reason": "local compatibility plane cannot authorize Phase F release evidence",
    }


@app.post("/openai/v1/chat/completions")
def chat_completions(payload: dict[str, Any]) -> dict[str, object]:
    """Minimal OpenAI wire compatibility for connection checks, not acceptance evidence."""

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise HTTPException(status_code=422, detail="model is required")
    return {
        "id": "chatcmpl-local-compatibility",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Local compatibility response; not production model evidence.",
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@app.post("/kss/projection/v1/encode")
def kss_projection_encode(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Serve the strict KSS projection contract for local compatibility checks."""

    _require_kss_model_bearer(authorization)
    _require_fields(
        payload,
        {
            "schema_version",
            "text",
            "dense_revision",
            "sparse_revision",
            "dense_dimension",
        },
    )
    text = payload["text"]
    dense_revision = payload["dense_revision"]
    sparse_revision = payload["sparse_revision"]
    dimension = payload["dense_dimension"]
    if (
        payload["schema_version"] != "knowledge-projection-encoding-request.v1"
        or not isinstance(text, str)
        or not text.strip()
        or len(text.encode("utf-8")) > 256 * 1024
        or not isinstance(dense_revision, str)
        or not dense_revision.strip()
        or not isinstance(sparse_revision, str)
        or not sparse_revision.strip()
        or not isinstance(dimension, int)
        or not 4 <= dimension <= 4096
    ):
        raise HTTPException(status_code=422, detail="invalid KSS projection request")
    digest = hashlib.sha256(text.encode()).hexdigest()
    sparse_vector = {
        f"f_{digest[offset:offset + 8]}": float(index + 1)
        for index, offset in enumerate(range(0, 64, 8))
    }
    return {
        "schema_version": "knowledge-projection-encoding.v1",
        "dense_revision": dense_revision,
        "sparse_revision": sparse_revision,
        "dense_dimension": dimension,
        "dense_vector": _deterministic_vector(
            text,
            dimension=dimension,
            normalized=True,
        ),
        "sparse_vector": sparse_vector,
    }


@app.post("/kss/agentic/v1/next")
def kss_agentic_decide(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Return one bounded Agentic decision without receiving candidate content."""

    _require_kss_model_bearer(authorization)
    _require_fields(
        payload,
        {
            "schema_version",
            "retrieval_round",
            "question",
            "knowledge_base_release_id",
            "access_scope_digest",
            "candidate_count",
            "candidate_evidence_ids",
            "remaining_rounds",
            "remaining_model_calls",
            "remaining_model_tokens",
            "remaining_duration_ms",
        },
    )
    string_fields = (
        "question",
        "knowledge_base_release_id",
        "access_scope_digest",
    )
    integer_fields = (
        "retrieval_round",
        "candidate_count",
        "remaining_rounds",
        "remaining_model_calls",
        "remaining_model_tokens",
        "remaining_duration_ms",
    )
    candidate_ids = payload["candidate_evidence_ids"]
    if (
        payload["schema_version"] != "agentic-retrieval-observation.v1"
        or any(
            not isinstance(payload[field], str) or not payload[field].strip()
            for field in string_fields
        )
        or any(
            not isinstance(payload[field], int) or payload[field] < 0
            for field in integer_fields
        )
        or not isinstance(candidate_ids, list)
        or any(not isinstance(value, str) or not value for value in candidate_ids)
        or len(candidate_ids) != payload["candidate_count"]
    ):
        raise HTTPException(status_code=422, detail="invalid KSS Agentic request")
    return {
        "schema_version": "agentic-retrieval-decision.v1",
        "action": "complete",
        "revised_question": None,
        "model_tokens_used": 0,
    }


@app.post("/kss/ocr/v1/extract")
def kss_ocr_extract(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Serve the pinned OCR response shape for deployment connectivity checks."""

    _require_kss_model_bearer(authorization)
    _require_fields(
        payload,
        {"schema_version", "media_type", "content_base64", "model_revision"},
    )
    media_type = payload["media_type"]
    model_revision = payload["model_revision"]
    try:
        content = base64.b64decode(payload["content_base64"], validate=True)
    except (TypeError, ValueError):
        content = b""
    if (
        payload["schema_version"] != "knowledge-document-ocr-request.v1"
        or media_type not in {
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/tiff",
        }
        or not isinstance(model_revision, str)
        or not model_revision.strip()
        or not content
        or len(content) > 50 * 1024 * 1024
    ):
        raise HTTPException(status_code=422, detail="invalid KSS OCR request")
    return {
        "schema_version": "knowledge-document-ocr.v1",
        "model_revision": model_revision,
        "quality_state": "passed",
        "pages": [{"page_number": 1, "width": 1000, "height": 1400}],
        "regions": [
            {
                "page_number": 1,
                "bounding_box": {
                    "x_min": 40,
                    "y_min": 80,
                    "x_max": 960,
                    "y_max": 180,
                },
                "text": "本地 OCR 协议兼容结果，仅用于类生产部署连通性验证。",
                "confidence": 1.0,
            }
        ],
    }


def _parser_response(payload: dict[str, Any], *, adapter: str) -> dict[str, object]:
    _require_fields(
        payload,
        {
            "document_id",
            "revision_id",
            "original_ref",
            "page_numbers",
            "parser_revision",
            "model_digests",
            "configuration_sha256",
            "allow_runtime_downloads",
        },
    )
    document_id = payload["document_id"]
    revision_id = payload["revision_id"]
    original_ref = payload["original_ref"]
    page_numbers = payload["page_numbers"]
    if (
        not isinstance(document_id, str)
        or not document_id
        or not isinstance(revision_id, str)
        or not revision_id
        or not isinstance(original_ref, dict)
        or not isinstance(original_ref.get("sha256"), str)
        or not isinstance(page_numbers, list)
        or not page_numbers
        or any(type(value) is not int or value < 1 for value in page_numbers)
        or payload["allow_runtime_downloads"] is not False
    ):
        raise HTTPException(status_code=422, detail="invalid parser request")
    if adapter == "paddle" and len(page_numbers) != 1:
        raise HTTPException(status_code=422, detail="paddle accepts one page")
    vendor = (
        _docling_vendor(document_id, revision_id, original_ref["sha256"], page_numbers)
        if adapter == "docling"
        else _paddle_vendor(
            document_id,
            revision_id,
            original_ref["sha256"],
            int(page_numbers[0]),
        )
    )
    vendor_bytes = json.dumps(
        vendor,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return {
        "parser_adapter": adapter,
        "original_ref": original_ref,
        "page_numbers": page_numbers,
        "parser_revision": payload["parser_revision"],
        "model_digests": payload["model_digests"],
        "configuration_sha256": payload["configuration_sha256"],
        "vendor_json_sha256": hashlib.sha256(vendor_bytes).hexdigest(),
        "vendor_json": vendor,
    }


def _docling_vendor(
    document_id: str,
    revision_id: str,
    source_sha256: str,
    page_numbers: list[object],
) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    proposals: list[dict[str, object]] = []
    ai_default: dict[str, object] = {
        "canonical_anchor": None,
        "authority": "national",
        "effective_from": None,
        "effective_to": None,
        "taxonomy_id": "insurance-product-applicability",
        "taxonomy_revision_id": "taxonomy-2026-01",
        "precedence_policy_revision_id": "precedence-2026-01",
        "precedence_authority_tier": "policy_terms",
        "precedence_order": 0,
    }
    for value in page_numbers:
        page_number = cast(int, value)
        heading = f"Local Production Rule Page {page_number}"
        pages.append(
            {
                "page_number": page_number,
                "width": 612.0,
                "height": 792.0,
                "native_text_ratio": 1.0,
                "blocks": [
                    {
                        "id": f"heading-{page_number}",
                        "label": "section_header",
                        "text": heading,
                        "bbox": [40.0, 40.0, 572.0, 70.0],
                        "reading_order": 0,
                        "heading_level": 1,
                        "heading_path": [heading],
                    },
                    {
                        "id": f"paragraph-{page_number}",
                        "label": "text",
                        "text": "本页由本地协议兼容解析服务生成，仅用于部署连通性验证。",
                        "bbox": [40.0, 85.0, 572.0, 125.0],
                        "reading_order": 1,
                        "heading_path": [heading],
                    },
                ],
                "tables": [],
            }
        )
        for canonical_anchor in (
            f"heading-{page_number}",
            f"paragraph-{page_number}",
        ):
            proposals.append(
                {
                    "canonical_anchor": canonical_anchor,
                    "authority": ai_default["authority"],
                    "effective_from": None,
                    "effective_to": None,
                    "taxonomy_id": ai_default["taxonomy_id"],
                    "taxonomy_revision_id": ai_default["taxonomy_revision_id"],
                    "precedence_policy_revision_id": ai_default[
                        "precedence_policy_revision_id"
                    ],
                    "precedence_authority_tier": ai_default[
                        "precedence_authority_tier"
                    ],
                    "precedence_order": ai_default["precedence_order"],
                }
            )
    return {
        "document_id": document_id,
        "revision_id": revision_id,
        "source_sha256": source_sha256,
        "pages": pages,
        "warnings": [],
        "insurance_metadata_default": ai_default,
        "insurance_metadata_drafts": proposals,
    }


def _paddle_vendor(
    document_id: str,
    revision_id: str,
    source_sha256: str,
    page_number: int,
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "revision_id": revision_id,
        "source_sha256": source_sha256,
        "page": {
            "page_number": page_number,
            "width": 612.0,
            "height": 792.0,
            "blocks": [
                {
                    "id": f"ocr-{page_number}",
                    "label": "text",
                    "text": "本地 OCR 协议兼容结果。",
                    "bbox": [40.0, 85.0, 572.0, 125.0],
                    "reading_order": 1,
                    "heading_path": [f"Local Production Rule Page {page_number}"],
                }
            ],
            "tables": [],
        },
        "warnings": [],
    }


def _deterministic_vector(text: str, *, dimension: int, normalized: bool) -> list[float]:
    seed = text.encode()
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend((float(byte) / 127.5) - 1.0 for byte in digest)
        counter += 1
    vector = values[:dimension]
    if normalized:
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vector = [value / norm for value in vector]
    return vector


def _require_fields(payload: dict[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise HTTPException(status_code=422, detail="request fields do not match contract")


def _require_kss_model_bearer(authorization: str | None) -> None:
    expected = os.environ.get("KSS_MODEL_BEARER_TOKEN", "")
    presented = "" if authorization is None else authorization
    if (
        len(expected) < 16
        or not secrets.compare_digest(presented, f"Bearer {expected}")
    ):
        raise HTTPException(
            status_code=401,
            detail="KSS model credential is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
