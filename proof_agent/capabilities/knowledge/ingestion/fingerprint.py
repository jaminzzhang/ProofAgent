"""Stable compatibility fingerprint for Local Index artifact construction."""

from __future__ import annotations

import json
from hashlib import sha256

from proof_agent.contracts import KnowledgeArtifactBuildSpec


def ingestion_config_fingerprint(spec: KnowledgeArtifactBuildSpec) -> str:
    """Hash only artifact-affecting configuration, excluding revision-owned hashes."""

    payload = spec.model_dump(mode="json")
    artifact_configuration = {
        "declared_ingestion_model": payload["declared_ingestion_model"],
        "engine_name": spec.engine_name,
        "engine_version": spec.engine_version,
        "parser_fingerprint_identity": spec.parser_fingerprint_identity,
        "provider": spec.provider,
    }
    canonical_json = json.dumps(
        artifact_configuration,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()
