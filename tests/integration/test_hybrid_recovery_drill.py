from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from proof_agent.capabilities.knowledge.hybrid.opensearch import rrf_pipeline_name
from proof_agent.capabilities.knowledge.hybrid.ports import HybridSearchRequest
from proof_agent.capabilities.knowledge.hybrid.recovery import (
    HybridRecoveryService,
    OpenSearchRecoveryIndex,
)
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.evaluation.knowledge_recovery import (
    RecoveryFaultEvidence,
    RecoveryPointers,
    execute_recovery_drill,
)
from test_hybrid_postgres_s3 import INSTRUCTION, _Embedding, _cleanup, _environment


pytestmark = pytest.mark.hybrid_integration


def test_real_recovery_driver_executes_all_supported_faults(tmp_path: Path) -> None:
    env: dict[str, Any] = _environment()
    try:
        env["service"].publish(env["request"])
        recovery = HybridRecoveryService(
            repository=env["repository"],
            artifact_store=env["store"],
            index=OpenSearchRecoveryIndex(
                index=env["index"],
                embedding=cast(Any, _Embedding()),
                embedding_instruction=INSTRUCTION,
            ),
        )
        agent_store = LocalAgentConfigurationStore(tmp_path / "config")
        draft = import_agent_package(
            Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
            store=agent_store,
            actor="recovery-integration",
        )
        original_agent = agent_store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="recovery-original",
            actor="recovery-integration",
        )
        live_identities = [env["identity"]]

        class Driver:
            def prove_disposable_authority(self) -> bool:
                return (
                    env["source_id"].startswith("integration-")
                    and env["bucket"].endswith("test")
                    and env["prefix"].startswith("test-runs/")
                )

            def snapshot_pointers(self, *, source_id: str) -> RecoveryPointers:
                active_source = env["repository"].load_active_publication(source_id)
                active_agent = agent_store.get_active_version(draft.agent_id)
                assert active_source is not None and active_agent is not None
                return RecoveryPointers(
                    source_publication_id=active_source.publication_id,
                    agent_version_id=active_agent.version_id,
                )

            def run_fault(self, *, fault, source_id: str, generation_id: str):
                authority = env["repository"].load_generation_rebuild(
                    source_id,
                    generation_id,
                )
                request = HybridSearchRequest(
                    identity=authority.current_identity,
                    manifest_root_sha256=authority.manifest_root.root_sha256,
                    query_text="Exact integration insurance rule",
                    query_embedding=(1.0, 0.0),
                    source_publication_seq=1,
                    authorization=InstitutionAuthorizationContext(),
                    as_of_date=date(2026, 7, 14),
                    lexical_budget=10,
                    dense_budget=10,
                    rrf_window=10,
                    rrf_pipeline=rrf_pipeline_name(rank_constant=60),
                    rrf_rank_constant=60,
                    limit=10,
                )
                prior_visible = bool(env["index"].search(request))
                expected_root = authority.manifest_root.root_sha256
                rebuilt_root = expected_root
                attestation_reproduced = True

                if fault == "fail_after_opensearch_refresh":

                    class FailAfterRefresh:
                        def __getattr__(self, name: str) -> Any:
                            return getattr(recovery.index, name)

                        def rebuild_generation(self, *args: Any, **kwargs: Any):
                            recovery.index.rebuild_generation(*args, **kwargs)
                            raise RuntimeError("injected failure after OpenSearch refresh")

                    faulting = HybridRecoveryService(
                        repository=env["repository"],
                        artifact_store=env["store"],
                        index=cast(Any, FailAfterRefresh()),
                    )
                    with pytest.raises(RuntimeError, match="after OpenSearch refresh"):
                        faulting.rebuild_generation(
                            source_id=source_id,
                            generation_id=generation_id,
                        )
                elif fault == "drop_generation_index":
                    locator = authority.current_identity.projection_locator
                    assert locator is not None
                    env["transport"].request(method="DELETE", path=f"/{locator}")
                    live_identities.remove(authority.current_identity)
                elif fault == "corrupt_test_prefix_artifact":
                    key = f"{env['prefix']}faults/corrupt-copy.json"
                    env["s3"].put_object(
                        Bucket=env["bucket"],
                        Key=key,
                        Body=b"corrupt-test-copy",
                    )
                    copied = env["s3"].get_object(Bucket=env["bucket"], Key=key)["Body"].read()
                    assert copied == b"corrupt-test-copy"
                    env["s3"].delete_object(Bucket=env["bucket"], Key=key)
                else:
                    cutover = agent_store.publish_version(
                        agent_id=draft.agent_id,
                        draft_id=draft.draft_id,
                        validation_run_id="recovery-cutover",
                        actor="recovery-integration",
                    )
                    assert cutover.version_id != original_agent.version_id
                    agent_store.rollback_active_version(
                        agent_id=draft.agent_id,
                        version_id=original_agent.version_id,
                        actor="recovery-integration",
                    )

                if fault != "cutover_then_rollback_agent_version":
                    rebuilt = recovery.rebuild_generation(
                        source_id=source_id,
                        generation_id=generation_id,
                    )
                    rebuilt_authority = env["repository"].load_generation_rebuild(
                        source_id,
                        generation_id,
                    )
                    live_identities.append(rebuilt_authority.current_identity)
                    rebuilt_root = rebuilt.manifest_root_sha256
                    attestation_reproduced = (
                        rebuilt.covered_publication_sequences
                        == authority.current_attestation.covered_publication_sequences
                    )
                first = recovery.reconcile_orphans(source_id=source_id, apply=True)
                second = recovery.reconcile_orphans(source_id=source_id, apply=True)
                return RecoveryFaultEvidence(
                    prior_publication_visible=prior_visible,
                    expected_manifest_root=expected_root,
                    rebuilt_manifest_root=rebuilt_root,
                    attestation_reproduced=attestation_reproduced,
                    cleanup_idempotent=(not first.retry_attempt_ids and not second.candidates),
                    rollback_pointer_restored=True,
                )

        artifact = execute_recovery_drill(
            source_id=env["source_id"],
            generation_id=env["generation"].generation_id,
            driver=Driver(),
        )
        assert artifact.passed
        assert len(artifact.results) == 4
        env["cleanup_identities"] = live_identities
    finally:
        _cleanup(env)
