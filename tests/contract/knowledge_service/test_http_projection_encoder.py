from __future__ import annotations

import json

import httpx

from knowledge_source_service.adapters.http.projection_encoder import (
    HttpProjectionTextEncoder,
)


def test_http_projection_encoder_pins_revisions_and_returns_distinct_vectors() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer encoder-secret-token"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "schema_version": "knowledge-projection-encoding.v1",
                "dense_revision": "private-dense-v7",
                "sparse_revision": "private-sparse-v4",
                "dense_dimension": 4,
                "dense_vector": [0.5, 0.5, -0.5, 0.5],
                "sparse_vector": {"policy": 1.2, "delay": 0.8},
            },
        )

    encoder = HttpProjectionTextEncoder(
        endpoint="https://encoder.invalid/v1/encode",
        bearer_token="encoder-secret-token",
        dense_revision="private-dense-v7",
        sparse_revision="private-sparse-v4",
        dense_dimension=4,
        transport=httpx.MockTransport(respond),
    )
    encoded = encoder.encode("Flight delay policy")
    encoder.close()

    assert encoded.dense_vector == (0.5, 0.5, -0.5, 0.5)
    assert encoded.sparse_vector == {"policy": 1.2, "delay": 0.8}
    assert requests == [
        {
            "schema_version": "knowledge-projection-encoding-request.v1",
            "text": "Flight delay policy",
            "dense_revision": "private-dense-v7",
            "sparse_revision": "private-sparse-v4",
            "dense_dimension": 4,
        }
    ]
