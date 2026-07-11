from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from proof_agent.release.contracts import (
    DigestRef,
    GateResult,
    ProductionCandidateBinding,
    Sha256,
)


_CONTENT_ADDRESSED_URI = re.compile(r"artifact://sha256/([0-9a-f]{64})\Z")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the deterministic UTF-8 JSON representation used for release bindings."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_ref(data: bytes) -> DigestRef:
    return DigestRef(sha256=sha256_hex(data), length=len(data))


def candidate_binding_sha256(
    candidate: ProductionCandidateBinding | Mapping[str, object],
) -> Sha256:
    return sha256_hex(canonical_json_bytes(candidate))


def gate_result_sha256(result: GateResult) -> Sha256:
    return sha256_hex(canonical_json_bytes(result))


def reject_duplicate_json_keys(raw: str | bytes) -> None:
    """Reject duplicate keys recursively while leaving strict parsing to Pydantic."""

    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    json.loads(raw, object_pairs_hook=reject_pairs)


def build_content_addressed_uri(sha256: Sha256 | str) -> str:
    uri = f"artifact://sha256/{sha256}"
    parse_content_addressed_uri(uri)
    return uri


def parse_content_addressed_uri(uri: str) -> Sha256:
    match = _CONTENT_ADDRESSED_URI.fullmatch(uri)
    if match is None:
        raise ValueError("evidence URI must be artifact://sha256/<64 lowercase hex>")
    return match.group(1)
