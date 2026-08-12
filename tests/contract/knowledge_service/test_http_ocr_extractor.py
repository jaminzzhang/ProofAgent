from __future__ import annotations

import base64
import json

import httpx

from knowledge_source_service.adapters.http.ocr_extractor import (
    HttpDocumentOcrExtractor,
)


def test_http_ocr_extractor_pins_revision_and_requires_passed_quality() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ocr-secret-token"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "schema_version": "knowledge-document-ocr.v1",
                "model_revision": "ocr-private-v3",
                "quality_state": "passed",
                "regions": [
                    {
                        "page_number": 1,
                        "bounding_box": {
                            "x_min": 10,
                            "y_min": 12,
                            "x_max": 190,
                            "y_max": 42,
                        },
                        "text": "Flight delay benefit is 300 CNY.",
                        "confidence": 0.99,
                    }
                ],
            },
        )

    extractor = HttpDocumentOcrExtractor(
        endpoint="https://ocr.invalid/v1/extract",
        bearer_token="ocr-secret-token",
        model_revision="ocr-private-v3",
        transport=httpx.MockTransport(respond),
    )
    document = extractor.extract(media_type="image/png", content=b"exact-png-bytes")
    extractor.close()

    assert document.model_revision == "ocr-private-v3"
    assert document.regions[0].text == "Flight delay benefit is 300 CNY."
    assert requests == [
        {
            "schema_version": "knowledge-document-ocr-request.v1",
            "media_type": "image/png",
            "content_base64": base64.b64encode(b"exact-png-bytes").decode("ascii"),
            "model_revision": "ocr-private-v3",
        }
    ]
