from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from proof_agent.contracts import ResolvedKnowledgeBindingSet
from proof_agent.delivery.cli import app
from proof_agent.observability.api.app import create_app


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_hybrid_published_binding_is_not_deserializable() -> None:
    with pytest.raises(ValueError):
        ResolvedKnowledgeBindingSet.model_validate(
            {
                "bindings": [
                    {
                        "binding_kind": "hybrid",
                        "binding_id": "removed-binding",
                        "source_scope": "shared",
                        "source_id": "removed-source",
                        "provider": "hybrid_index",
                        "source_publication_id": "publication-1",
                        "source_snapshot_id": "snapshot-1",
                        "index_generation_id": "generation-1",
                        "source_publication_seq": 1,
                        "retrieval_profile_revision_id": "profile-1",
                        "manifest_ref": {
                            "artifact_uri": "s3://removed/manifest.json",
                            "version_id": "version-1",
                            "sha256": "a" * 64,
                            "size_bytes": 1,
                            "media_type": "application/json",
                        },
                        "publication_attestation_id": "attestation-1",
                        "failure_mode": "required",
                        "fusion_weight": 1.0,
                    }
                ]
            }
        )


def test_legacy_embedded_published_binding_is_not_deserializable() -> None:
    with pytest.raises(ValueError):
        ResolvedKnowledgeBindingSet.model_validate(
            {
                "bindings": [
                    {
                        "binding_kind": "legacy",
                        "binding_id": "removed-binding",
                        "source_scope": "package",
                        "source_id": "removed-source",
                        "source_version_id": "package",
                        "provider": "local_markdown",
                    }
                ]
            }
        )


def test_proof_agent_no_longer_exposes_legacy_knowledge_worker_command() -> None:
    result = CliRunner().invoke(app, ["knowledge-worker", "--once"])

    assert result.exit_code == 2
    assert "No such command 'knowledge-worker'" in result.output


def test_proof_agent_no_longer_exposes_embedded_knowledge_commands() -> None:
    result = CliRunner().invoke(app, ["knowledge"])

    assert result.exit_code == 2
    assert "No such command 'knowledge'" in result.output


def test_configuration_api_has_no_embedded_knowledge_binding_routes(
    tmp_path: Path,
) -> None:
    application = create_app(agent_configuration_dir=tmp_path)
    routes = {route.path for route in application.routes}

    assert not any("knowledge-bindings" in route for route in routes)
    assert not any("knowledge-release-records" in route for route in routes)


def test_production_slot_has_no_proof_agent_knowledge_worker() -> None:
    compose = yaml.safe_load(
        (ROOT / "deploy/production/slot/compose.yaml").read_text(encoding="utf-8")
    )

    assert "knowledge-worker" not in compose["services"]
