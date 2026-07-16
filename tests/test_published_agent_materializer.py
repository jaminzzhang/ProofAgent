from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import stat

import pytest

from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.contracts.agent_configuration import ActiveAgentVersion, PublishedAgentVersion
from proof_agent.delivery.published_agent_materializer import (
    PublishedAgentAuthority,
    PublishedAgentMaterializationError,
    PublishedAgentMaterializer,
)


AGENT_ID = "react_enterprise_qa_v3"
VERSION_ID = "019ba001-1111-7000-8000-000000000001"


def _version() -> PublishedAgentVersion:
    bundle = build_agent_package_contract_bundle(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    bundle = bundle.model_copy(
        update={
            "agent_yaml": bundle.agent_yaml.replace(
                "../../runs/latest/trace.jsonl",
                "trace.jsonl",
            ).replace(
                "../../runs/latest/governance_receipt.md",
                "governance_receipt.md",
            )
        }
    )
    return PublishedAgentVersion(
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        source_draft_id="019ba001-1111-7000-8000-000000000002",
        validation_run_id="019ba001-1111-7000-8000-000000000003",
        display_name="Enterprise QA",
        purpose="Answer governed enterprise questions",
        contract_bundle=bundle,
        published_at=datetime(2026, 7, 15, tzinfo=UTC).isoformat(),
        published_by="publisher",
    )


class Agents:
    def __init__(self, version: PublishedAgentVersion) -> None:
        self.version = version
        self.active = ActiveAgentVersion(
            agent_id=version.agent_id,
            version_id=version.version_id,
            activated_at=version.published_at,
            activated_by="publisher",
        )

    def get_published(self, agent_id: str, version_id: str):
        if (agent_id, version_id) == (self.version.agent_id, self.version.version_id):
            return self.version
        return None

    def get_active(self, agent_id: str):
        return self.active if agent_id == self.active.agent_id else None

    def list_active(self):
        return (self.active,)


def test_materializes_exact_digest_keyed_read_only_package_and_active_directory(
    tmp_path: Path,
) -> None:
    agents = Agents(_version())
    materializer = PublishedAgentMaterializer(
        agents=agents,  # type: ignore[arg-type]
        cache_dir=tmp_path / "cache",
    )
    authority = PublishedAgentAuthority(
        materializer=materializer,
        agents=agents,  # type: ignore[arg-type]
    )

    first = materializer.resolve_exact(agent_id=AGENT_ID, version_id=VERSION_ID)
    second = authority.resolve(AGENT_ID)

    assert first is not None and second is not None
    assert first.manifest_path == second.manifest_path
    assert first.agent_version_id == VERSION_ID
    assert stat.S_IMODE(first.manifest_path.stat().st_mode) == 0o400
    assert authority.list_agent_ids() == (AGENT_ID,)
    assert authority.list_active_agent_ids() == (AGENT_ID,)
    assert authority.get_active_version(AGENT_ID) == agents.version


def test_materializer_rejects_contract_path_traversal(tmp_path: Path) -> None:
    version = _version()
    unsafe_bundle = version.contract_bundle.model_copy(
        update={"extra_files": {"../escape.txt": "must not escape"}}
    )
    agents = Agents(version.model_copy(update={"contract_bundle": unsafe_bundle}))
    materializer = PublishedAgentMaterializer(
        agents=agents,  # type: ignore[arg-type]
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(PublishedAgentMaterializationError, match="unsafe"):
        materializer.resolve_exact(agent_id=AGENT_ID, version_id=VERSION_ID)

    assert not (tmp_path / "escape.txt").exists()


def test_materializer_rejects_audit_path_traversal(tmp_path: Path) -> None:
    version = _version()
    unsafe_bundle = version.contract_bundle.model_copy(
        update={
            "agent_yaml": version.contract_bundle.agent_yaml.replace(
                "trace_path: trace.jsonl",
                "trace_path: ../escape.jsonl",
            )
        }
    )
    agents = Agents(version.model_copy(update={"contract_bundle": unsafe_bundle}))
    materializer = PublishedAgentMaterializer(
        agents=agents,  # type: ignore[arg-type]
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(PublishedAgentMaterializationError, match="unsafe"):
        materializer.resolve_exact(agent_id=AGENT_ID, version_id=VERSION_ID)

    assert not (tmp_path / "escape.jsonl").exists()
