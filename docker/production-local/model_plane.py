"""Protocol-compatible local private-model plane for deployment smoke tests.

This service exercises the real HTTPS transports and strict response validators. It is
deliberately deterministic and its release verifier always denies authorization, so it
cannot be confused with real-model or Phase F evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from typing import Any

from fastapi import FastAPI, HTTPException, Response


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
        page_number = int(value)
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
