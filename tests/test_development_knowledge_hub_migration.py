"""One-shot Development Knowledge Hub migration evidence."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import BinaryIO

import pytest
from typer.testing import CliRunner

import proof_agent.configuration.development_knowledge_hub_migration as migration_module
from proof_agent.configuration.development_knowledge_hub_migration import (
    DevelopmentKnowledgeHubBackupError,
    migrate_development_knowledge_hub,
    write_development_knowledge_hub_migration_manifest,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import AuditActorFacts
from proof_agent.contracts import KnowledgeSourceLifecycleState
from proof_agent.delivery.cli import app


_ACTOR = AuditActorFacts(
    subject="migration-operator",
    identity_provider="migration-cli",
    session_id="one-shot",
    permissions=("knowledge_source.edit",),
)
_NOW = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


class _Target:
    def __init__(
        self,
        *,
        existing: set[str] | None = None,
        fail_create: set[str] | None = None,
    ) -> None:
        self.existing = set(existing or ())
        self.fail_create = set(fail_create or ())
        self.created: list[dict[str, object]] = []
        self.uploaded: list[dict[str, object]] = []

    def source_exists(self, source_id: str) -> bool:
        return source_id in self.existing

    def create_source(self, **kwargs: object) -> int:
        source_id = str(kwargs["source_id"])
        if source_id in self.fail_create:
            raise RuntimeError("injected target failure")
        self.created.append(dict(kwargs))
        self.existing.add(source_id)
        return 1

    def upload_original(
        self,
        *,
        content: BinaryIO,
        **kwargs: object,
    ) -> int:
        payload = content.read()
        self.uploaded.append({**kwargs, "content": payload})
        return int(kwargs["expected_revision"]) + 1

    def finalize_source_lifecycle(
        self,
        *,
        lifecycle_state: KnowledgeSourceLifecycleState,
        expected_revision: int,
        **kwargs: object,
    ) -> int:
        del kwargs
        return (
            expected_revision + 1
            if lifecycle_state is KnowledgeSourceLifecycleState.ARCHIVED
            else expected_revision
        )


def _local_index_source(root: Path, source_id: str = "ks_local") -> None:
    store = LocalAgentConfigurationStore(root)
    store.create_knowledge_source(
        source_id=source_id,
        name=f"Source {source_id}",
        provider="local_index",
        params={"worker_concurrency": 1},
        actor="operator",
    )
    document = store.add_knowledge_document(
        source_id=source_id,
        filename="policy.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7 migration original",
        state="READY",
        actor="operator",
    )
    store.update_knowledge_document_routing_metadata(
        source_id=source_id,
        document_id=document.document_id,
        routing_metadata={"title": "Policy", "tags": ["motor"]},
        actor="operator",
    )


def _backup(source_root: Path, backup_root: Path) -> None:
    shutil.copytree(source_root, backup_root)


def test_dry_run_verifies_backup_and_never_mutates_target(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    backup_root = tmp_path / "backup"
    _local_index_source(source_root)
    _backup(source_root, backup_root)
    target = _Target()

    result = migrate_development_knowledge_hub(
        source_root=source_root,
        backup_root=backup_root,
        target=target,
        actor=_ACTOR,
        dry_run=True,
        clock=lambda: _NOW,
    )

    assert result.backup_verified is True
    assert result.source_sha256 == result.backup_sha256
    assert result.status == "planned"
    assert result.items[0].status == "planned"
    assert result.items[0].target_provider == "hybrid_index"
    assert target.created == []
    assert target.uploaded == []


def test_apply_imports_only_original_and_validated_metadata_and_writes_both_manifests(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    backup_root = tmp_path / "backup"
    _local_index_source(source_root)
    _backup(source_root, backup_root)
    target = _Target()

    result = migrate_development_knowledge_hub(
        source_root=source_root,
        backup_root=backup_root,
        target=target,
        actor=_ACTOR,
        dry_run=False,
        clock=lambda: _NOW,
    )
    json_path, text_path = write_development_knowledge_hub_migration_manifest(
        result,
        tmp_path / "migration.json",
    )

    assert result.status == "succeeded"
    assert target.created[0]["provider"] == "hybrid_index"
    assert target.uploaded[0]["content"] == b"%PDF-1.7 migration original"
    assert target.uploaded[0]["routing_metadata"] == {
        "title": "Policy",
        "tags": ("motor",),
    }
    assert "artifact_path" not in target.uploaded[0]
    assert json.loads(json_path.read_text())["status"] == "succeeded"
    assert "succeeded: 1" in text_path.read_text()


def test_backup_mismatch_fails_before_any_target_observation(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    backup_root = tmp_path / "backup"
    _local_index_source(source_root)
    _backup(source_root, backup_root)
    (backup_root / "knowledge_sources" / "ks_local" / "source.json").write_text("{}")
    target = _Target()

    with pytest.raises(DevelopmentKnowledgeHubBackupError):
        migrate_development_knowledge_hub(
            source_root=source_root,
            backup_root=backup_root,
            target=target,
            actor=_ACTOR,
            dry_run=False,
            clock=lambda: _NOW,
        )

    assert target.created == []


def test_source_id_conflict_and_missing_original_are_item_failures(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    backup_root = tmp_path / "backup"
    _local_index_source(source_root, "ks_conflict")
    _local_index_source(source_root, "ks_missing")
    missing_store = LocalAgentConfigurationStore(source_root)
    missing_document = missing_store.list_knowledge_documents("ks_missing")[0]
    missing_store.knowledge_document_original_path(missing_document).unlink()
    _backup(source_root, backup_root)
    target = _Target(existing={"ks_conflict"})

    result = migrate_development_knowledge_hub(
        source_root=source_root,
        backup_root=backup_root,
        target=target,
        actor=_ACTOR,
        dry_run=False,
        clock=lambda: _NOW,
    )

    by_id = {item.source_id: item for item in result.items}
    assert result.status == "failed"
    assert by_id["ks_conflict"].code == "source_id_conflict"
    assert by_id["ks_missing"].code == "document_original_missing"
    assert target.created == []


def test_http_json_secret_value_is_rejected_but_reference_config_is_imported(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    store = LocalAgentConfigurationStore(source_root)
    store.create_knowledge_source(
        source_id="ks_http_safe",
        name="Safe remote",
        provider="http_json",
        params={
            "endpoint": "https://knowledge.example/retrieve",
            "header_env_refs": [
                {"name": "Authorization", "value_env": "KNOWLEDGE_TOKEN", "prefix": "Bearer "}
            ],
        },
        actor="operator",
    )
    store.create_knowledge_source(
        source_id="ks_http_secret",
        name="Unsafe remote",
        provider="http_json",
        params={
            "endpoint": "https://knowledge.example/retrieve",
            "headers": [{"name": "Authorization", "value": "Bearer literal-secret"}],
        },
        actor="operator",
    )
    backup_root = tmp_path / "backup"
    _backup(source_root, backup_root)
    target = _Target()

    result = migrate_development_knowledge_hub(
        source_root=source_root,
        backup_root=backup_root,
        target=target,
        actor=_ACTOR,
        dry_run=False,
        clock=lambda: _NOW,
    )

    by_id = {item.source_id: item for item in result.items}
    assert result.status == "partial_failure"
    assert by_id["ks_http_safe"].status == "migrated"
    assert by_id["ks_http_safe"].requires_fresh_verification is True
    assert by_id["ks_http_secret"].code == "secret_value_rejected"
    safe = next(item for item in target.created if item["source_id"] == "ks_http_safe")
    assert safe["provider"] == "http_json"
    assert "KNOWLEDGE_TOKEN" in json.dumps(safe["params"])
    assert "literal-secret" not in result.model_dump_json()


def test_partial_target_failure_does_not_stop_independent_items(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    backup_root = tmp_path / "backup"
    _local_index_source(source_root, "ks_bad")
    _local_index_source(source_root, "ks_good")
    _backup(source_root, backup_root)
    target = _Target(fail_create={"ks_bad"})

    result = migrate_development_knowledge_hub(
        source_root=source_root,
        backup_root=backup_root,
        target=target,
        actor=_ACTOR,
        dry_run=False,
        clock=lambda: _NOW,
    )

    by_id = {item.source_id: item for item in result.items}
    assert result.status == "partial_failure"
    assert by_id["ks_bad"].code == "target_mutation_failed"
    assert by_id["ks_good"].status == "migrated"
    assert [item["source_id"] for item in target.created] == ["ks_good"]


def test_cli_defaults_to_dry_run_and_emits_machine_and_operator_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    backup_root = tmp_path / "backup"
    _local_index_source(source_root)
    _backup(source_root, backup_root)
    target = _Target()
    target.close = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(
        migration_module,
        "compose_development_knowledge_hub_migration_target",
        lambda _environment: target,
    )
    manifest = tmp_path / "result.json"

    result = CliRunner().invoke(
        app,
        [
            "knowledge",
            "migrate-development-hub",
            "--source-dir",
            str(source_root),
            "--backup-dir",
            str(backup_root),
            "--manifest",
            str(manifest),
            "--actor",
            "operator-1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Migration status: planned" in result.output
    assert json.loads(manifest.read_text())["dry_run"] is True
    assert manifest.with_suffix(".txt").is_file()
    assert target.created == []
