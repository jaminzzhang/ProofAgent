"""Verify private TLS routes from the production API network boundary."""

from __future__ import annotations

import json
import urllib.request


def _post(url: str, payload: dict[str, object]) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
    print(f"PASS {url}")


def main() -> None:
    parser_common: dict[str, object] = {
        "document_id": "deployment-smoke-document",
        "revision_id": "deployment-smoke-revision",
        "original_ref": {"sha256": "a" * 64},
        "page_numbers": [1],
        "configuration_sha256": "a" * 64,
        "allow_runtime_downloads": False,
    }
    _post(
        "https://models.internal:9443/v1/work/acquire",
        {
            "namespace": "proof-agent-local-production",
            "kind": "embedding",
            "priority": 1,
            "timeout_seconds": 5,
        },
    )
    _post(
        "https://models.internal:9444/v1/parse",
        {
            **parser_common,
            "parser_revision": "docling@sha256:localproductionv1",
            "model_digests": ["docling@sha256:localproductionv1"],
        },
    )
    _post(
        "https://models.internal:9445/v1/parse",
        {
            **parser_common,
            "parser_revision": "paddle@sha256:localproductionv1",
            "model_digests": ["paddle@sha256:localproductionv1"],
        },
    )
    _post(
        "https://models.internal:9446/v1/embeddings",
        {
            "texts": ["等待期"],
            "model_revision": "embedding@sha256:localproductionv1",
            "instruction": "Represent insurance rules.",
            "dimension": 64,
            "normalized": True,
            "allow_runtime_downloads": False,
        },
    )
    _post(
        "https://models.internal:9447/v1/rerank",
        {
            "query": "等待期",
            "candidates": [{"candidate_id": "c1", "text": "等待期规则"}],
            "model_revision": "reranker@sha256:localproductionv1",
            "max_input_tokens": 512,
            "allow_runtime_downloads": False,
        },
    )
    _post(
        "https://models.internal:9448/v1/knowledge-evaluation/release/verify",
        {},
    )
    with urllib.request.urlopen(
        "https://opensearch.internal:9200/_cluster/health",
        timeout=10,
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"OpenSearch returned HTTP {response.status}")
    print("PASS https://opensearch.internal:9200/_cluster/health")


if __name__ == "__main__":
    main()
