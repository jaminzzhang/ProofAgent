from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from typer.testing import CliRunner

from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.contracts.release_registry import ReleaseTrustIdentity
from proof_agent.delivery import cli as cli_module
from proof_agent.release.contracts import (
    DigestRef,
    EvidenceRef,
    GateResult,
    ProductionCandidateBinding,
    ReleaseGateManifest,
)
from proof_agent.release.assembler import assemble_release_manifest
from proof_agent.release.digests import (
    build_content_addressed_uri,
    candidate_binding_sha256,
    digest_ref,
    gate_result_sha256,
    sha256_hex,
)
from proof_agent.release.attestation import (
    Ed25519EvidenceAttestationVerifier,
    build_evidence_attestation,
    load_evidence_attestation_verifier,
)
from proof_agent.release.gate_engine import evaluate_gate
from proof_agent.release.profile import (
    INITIAL_PRIVATE_PILOT_PROFILE,
    initial_private_pilot_profile_bytes,
)
from proof_agent.release.evidence_store import (
    ArtifactStoreEvidenceReader,
    persist_release_evidence,
    persist_release_evidence_attestation,
)


SHA_A = "a" * 64
SOURCE_COMMIT = "c" * 40
NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _digest() -> DigestRef:
    return DigestRef(sha256=SHA_A, length=1)


def _candidate() -> ProductionCandidateBinding:
    return ProductionCandidateBinding(
        schema_version="proofagent.candidate-binding.v2",
        source_commit=SOURCE_COMMIT,
        clean_tree=True,
        product_version="0.1.0",
        oci_digest=f"sha256:{SHA_A}",
        python_distribution=_digest(),
        dashboard_assets=_digest(),
        operator_chat_assets=_digest(),
        migration_set=_digest(),
        knowledge_source_service={
            "product_version": "0.1.0",
            "oci_digest": f"sha256:{SHA_A}",
            "python_distribution": _digest(),
            "migration_set": _digest(),
            "openapi_contract": _digest(),
        },
        agent_id="agent_management_insurance_specialist",
        agent_version="2026.08.13",
        agent_bundle=_digest(),
        evaluation_contract=_digest(),
        configuration_snapshot=_digest(),
        gate_profile=digest_ref(initial_private_pilot_profile_bytes()),
        deployment_compatibility_manifest=_digest(),
    )


def test_candidate_integrity_fails_when_only_quality_facts_are_present() -> None:
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    content = b'{"commands":"passed","coverage":92}'
    content_digest = digest_ref(content)
    quality = EvidenceRef(
        evidence_id="candidate-quality",
        kind="candidate_quality",
        uri=build_content_addressed_uri(content_digest.sha256),
        digest=content_digest,
        candidate_binding_sha256=binding,
        produced_at=NOW,
    )

    result = evaluate_gate(
        candidate=candidate,
        gate_id="candidate_integrity",
        evidence=(quality,),
        metrics={
            "quality_line_coverage_percent": 92,
            "quality_required_command_failures": 0,
            "quality_required_integration_skips": 0,
        },
        evaluated_at=NOW,
    )

    assert result.status == "failed"
    assert "evidence.missing:candidate_integrity:distribution_image" in result.blocker_codes
    assert "evidence.missing:candidate_integrity:supply_chain_security" in result.blocker_codes
    assert (
        "metric.missing:candidate_integrity:distribution_clean_install_passed"
        in result.blocker_codes
    )


def test_gate_profile_requires_knowledge_service_distribution_and_compatibility() -> None:
    metrics = {
        rule.key
        for gate in INITIAL_PRIVATE_PILOT_PROFILE.gates
        for rule in gate.metrics
    }

    assert {
        "distribution_knowledge_service_clean_install_passed",
        "distribution_knowledge_service_image_readiness_passed",
        "security_knowledge_service_runtime_hardening_passed",
        "security_knowledge_service_sbom_present",
        "security_knowledge_service_provenance_verified",
        "compatibility_knowledge_source_service_bound",
        "compatibility_opensearch_bound",
        "compatibility_knowledge_model_plane_bound",
        "compatibility_knowledge_service_openapi_sha256",
        "deployment_metadata_v2_transition_safe",
        "deployment_knowledge_service_migration_set_sha256",
        "recovery_knowledge_service_migration_set_sha256",
    } <= metrics


def test_candidate_integrity_passes_only_after_all_profile_facts_pass() -> None:
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)

    def evidence(kind: str, *, expiring: bool = False) -> EvidenceRef:
        content = f'{{"kind":"{kind}"}}'.encode()
        content_digest = digest_ref(content)
        return EvidenceRef(
            evidence_id=f"{kind}-evidence",
            kind=kind,
            uri=build_content_addressed_uri(content_digest.sha256),
            digest=content_digest,
            candidate_binding_sha256=binding,
            produced_at=NOW,
            expires_at=NOW + timedelta(hours=24) if expiring else None,
        )

    result = evaluate_gate(
        candidate=candidate,
        gate_id="candidate_integrity",
        evidence=(
            evidence("candidate_quality"),
            evidence("distribution_image"),
            evidence("supply_chain_security", expiring=True),
        ),
        metrics={
            "quality_line_coverage_percent": 92,
            "quality_required_command_failures": 0,
            "quality_required_integration_skips": 0,
            "distribution_clean_install_passed": True,
            "distribution_image_readiness_passed": True,
            "distribution_knowledge_service_clean_install_passed": True,
            "distribution_knowledge_service_image_readiness_passed": True,
            "security_unresolved_critical_findings": 0,
            "security_unresolved_high_findings": 0,
            "security_runtime_hardening_passed": True,
            "security_sbom_present": True,
            "security_provenance_verified": True,
            "security_knowledge_service_runtime_hardening_passed": True,
            "security_knowledge_service_sbom_present": True,
            "security_knowledge_service_provenance_verified": True,
        },
        evaluated_at=NOW,
    )

    assert result.status == "passed"
    assert result.blocker_codes == ()


def test_manifest_assembly_marks_unreported_gates_not_run() -> None:
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    failed_candidate_integrity = GateResult(
        gate_id="candidate_integrity",
        status="failed",
        candidate_binding_sha256=binding,
        evidence=(),
        metrics={},
        blocker_codes=("evidence.missing:candidate_integrity:distribution_image",),
    )

    manifest = assemble_release_manifest(
        candidate=candidate,
        results=(failed_candidate_integrity,),
        generated_at=NOW,
    )

    assert manifest.schema_version == "proofagent.release-gate-manifest.v2"
    assert manifest.profile_id == "initial-private-pilot-v2"
    assert tuple(result.gate_id for result in manifest.results) == (
        "candidate_integrity",
        "access_security",
        "governed_behavior",
        "operational_readiness",
        "deployment_recovery",
    )
    assert tuple(result.status for result in manifest.results) == (
        "failed",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
    )


def test_release_evidence_uses_the_existing_exact_version_artifact_store(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)

    stored = persist_release_evidence(
        store=store,
        release_id="proofagent-2026.08.13-rc1",
        candidate=candidate,
        gate_id="candidate_integrity",
        evidence_id="candidate-quality",
        artifact_name="candidate-integrity-quality.json",
        kind="candidate_quality",
        content=b'{"coverage":92}',
        produced_at=NOW,
    )

    assert stored.artifact.version_id
    assert stored.artifact.owner.owner_type == "release"
    assert stored.artifact.owner.owner_id == "proofagent-2026.08.13-rc1"
    assert stored.artifact.display_filename == "candidate-integrity-quality.json"
    assert stored.evidence.digest.sha256 == stored.artifact.sha256
    reader = ArtifactStoreEvidenceReader(
        store=store,
        exact_versions={stored.evidence.evidence_id: stored.artifact},
    )
    assert reader.read(stored.evidence) == b'{"coverage":92}'


def test_evidence_attestation_binds_workload_identity_artifact_candidate_and_result() -> None:
    private_key = Ed25519PrivateKey.generate()
    trust = ReleaseTrustIdentity(
        protocol_id="ed25519-sha256-v1",
        issuer="https://ci.example.test",
        subject="repo:proofagent:release",
        key_id="ci-release-key-1",
    )
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    artifact = b'{"coverage":92}'
    artifact_digest = digest_ref(artifact)
    evidence = EvidenceRef(
        evidence_id="candidate-quality",
        kind="candidate_quality",
        uri=build_content_addressed_uri(artifact_digest.sha256),
        digest=artifact_digest,
        candidate_binding_sha256=binding,
        produced_at=NOW,
    )
    result = GateResult(
        gate_id="candidate_integrity",
        status="failed",
        candidate_binding_sha256=binding,
        evidence=(evidence,),
        metrics={},
        blocker_codes=("metric.missing:candidate_integrity:quality_line_coverage_percent",),
    )
    envelope = build_evidence_attestation(
        result=result,
        evidence=evidence,
        artifact=artifact,
        trust_identity=trust,
        signer=private_key.sign,
    )
    verifier = Ed25519EvidenceAttestationVerifier(
        public_keys={trust.key_id: private_key.public_key().public_bytes_raw()},
        trust_identities={trust.key_id: trust},
        envelopes={evidence.evidence_id: envelope},
    )

    claims = verifier.verify(
        result=result,
        evidence=evidence,
        artifact=artifact,
        candidate_binding_sha256=binding,
    )

    assert claims is not None
    assert claims.artifact_sha256 == sha256_hex(artifact)
    assert claims.candidate_binding_sha256 == binding
    assert claims.gate_result_sha256 == gate_result_sha256(result)
    assert (
        verifier.verify(
            result=result.model_copy(update={"status": "passed"}),
            evidence=evidence,
            artifact=artifact,
            candidate_binding_sha256=binding,
        )
        is None
    )


def test_detached_evidence_attestation_is_an_exact_release_artifact(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust = ReleaseTrustIdentity(
        protocol_id="ed25519-sha256-v1",
        issuer="https://ci.example.test",
        subject="repo:proofagent:release",
        key_id="ci-release-key-1",
    )
    candidate = _candidate()
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    stored = persist_release_evidence(
        store=store,
        release_id="proofagent-2026.08.13-rc1",
        candidate=candidate,
        gate_id="candidate_integrity",
        evidence_id="candidate-quality",
        artifact_name="candidate-integrity-quality.json",
        kind="candidate_quality",
        content=b'{"coverage":92}',
        produced_at=NOW,
    )
    result = GateResult(
        gate_id="candidate_integrity",
        status="failed",
        candidate_binding_sha256=candidate_binding_sha256(candidate),
        evidence=(stored.evidence,),
        metrics={},
        blocker_codes=("metric.missing:candidate_integrity:quality_line_coverage_percent",),
    )
    envelope = build_evidence_attestation(
        result=result,
        evidence=stored.evidence,
        artifact=b'{"coverage":92}',
        trust_identity=trust,
        signer=private_key.sign,
    )

    attestation = persist_release_evidence_attestation(
        store=store,
        release_id="proofagent-2026.08.13-rc1",
        evidence=stored.evidence,
        envelope=envelope,
    )

    assert attestation.version_id
    assert attestation.owner == stored.artifact.owner
    assert attestation.display_filename == (
        f"{stored.evidence.digest.sha256}.attestation.json"
    )


def test_evidence_attestation_loader_rejects_symlink_escape(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust = ReleaseTrustIdentity(
        protocol_id="ed25519-sha256-v1",
        issuer="https://ci.example.test",
        subject="repo:proofagent:release",
        key_id="ci-release-key-1",
    )
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    artifact = b'{"coverage":92}'
    artifact_digest = digest_ref(artifact)
    evidence = EvidenceRef(
        evidence_id="candidate-quality",
        kind="candidate_quality",
        uri=build_content_addressed_uri(artifact_digest.sha256),
        digest=artifact_digest,
        candidate_binding_sha256=binding,
        produced_at=NOW,
    )
    result = GateResult(
        gate_id="candidate_integrity",
        status="failed",
        candidate_binding_sha256=binding,
        evidence=(evidence,),
        metrics={},
        blocker_codes=("metric.missing:candidate_integrity:quality_line_coverage_percent",),
    )
    outside = tmp_path / "outside-attestation.json"
    outside.write_bytes(
        build_evidence_attestation(
            result=result,
            evidence=evidence,
            artifact=artifact,
            trust_identity=trust,
            signer=private_key.sign,
        )
    )
    root = tmp_path / "attestations"
    root.mkdir()
    (root / f"{artifact_digest.sha256}.attestation.json").symlink_to(outside)
    trust_policy = json.dumps(
        {
            "schema_version": "proofagent.release-evidence-trust.v1",
            "identities": [
                {
                    **trust.model_dump(mode="json"),
                    "public_key_base64": base64.b64encode(
                        private_key.public_key().public_bytes_raw()
                    ).decode("ascii"),
                }
            ],
        }
    ).encode()

    with pytest.raises(ValueError, match="symlink"):
        load_evidence_attestation_verifier(
            trust_policy=trust_policy,
            attestation_root=root,
            evidence=(evidence,),
        )


def test_release_evaluate_gate_cli_computes_status_from_raw_facts(tmp_path: Path) -> None:
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    content_digest = digest_ref(b'{"coverage":92}')
    facts = {
        "schema_version": "proofagent.gate-facts.v1",
        "gate_id": "candidate_integrity",
        "evidence": [
            {
                "evidence_id": "candidate-quality",
                "kind": "candidate_quality",
                "uri": build_content_addressed_uri(content_digest.sha256),
                "digest": content_digest.model_dump(mode="json"),
                "candidate_binding_sha256": binding,
                "produced_at": NOW.isoformat(),
                "expires_at": None,
            }
        ],
        "metrics": {
            "quality_line_coverage_percent": 92,
            "quality_required_command_failures": 0,
            "quality_required_integration_skips": 0,
        },
    }
    candidate_path = tmp_path / "candidate.json"
    facts_path = tmp_path / "facts.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    facts_path.write_text(json.dumps(facts), encoding="utf-8")

    result = CliRunner().invoke(
        cli_module.app,
        [
            "release",
            "evaluate-gate",
            "--candidate",
            str(candidate_path),
            "--facts",
            str(facts_path),
            "--at",
            NOW.isoformat().replace("+00:00", "Z"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert "evidence.missing:candidate_integrity:distribution_image" in payload[
        "blocker_codes"
    ]


def test_release_bind_candidate_cli_pins_the_packaged_profile(tmp_path: Path) -> None:
    inventory = _candidate().model_dump(mode="json")
    del inventory["schema_version"]
    del inventory["gate_profile"]
    inventory_path = tmp_path / "build-inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    result = CliRunner().invoke(
        cli_module.app,
        ["release", "bind-candidate", "--inventory", str(inventory_path)],
    )

    assert result.exit_code == 0
    candidate = ProductionCandidateBinding.model_validate_json(result.stdout)
    assert candidate.gate_profile == digest_ref(initial_private_pilot_profile_bytes())


def test_release_assemble_manifest_cli_closes_partial_results(tmp_path: Path) -> None:
    candidate = _candidate()
    result = GateResult(
        gate_id="candidate_integrity",
        status="failed",
        candidate_binding_sha256=candidate_binding_sha256(candidate),
        evidence=(),
        metrics={},
        blocker_codes=("evidence.missing:candidate_integrity:distribution_image",),
    )
    candidate_path = tmp_path / "candidate.json"
    result_path = tmp_path / "candidate-integrity-result.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    result_path.write_text(result.model_dump_json(), encoding="utf-8")

    command = CliRunner().invoke(
        cli_module.app,
        [
            "release",
            "assemble-manifest",
            "--candidate",
            str(candidate_path),
            "--result",
            str(result_path),
            "--at",
            NOW.isoformat().replace("+00:00", "Z"),
        ],
    )

    assert command.exit_code == 0
    manifest = ReleaseGateManifest.model_validate_json(command.stdout)
    assert tuple(item.status for item in manifest.results) == (
        "failed",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
    )


def test_release_verify_cli_can_reach_go_with_deployment_owned_trust(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust = ReleaseTrustIdentity(
        protocol_id="ed25519-sha256-v1",
        issuer="https://ci.example.test",
        subject="repo:proofagent:release",
        key_id="ci-release-key-1",
    )
    candidate = _candidate()
    binding = candidate_binding_sha256(candidate)
    evidence_root = tmp_path / "evidence"
    attestation_root = tmp_path / "attestations"
    evidence_root.mkdir()
    attestation_root.mkdir()
    gate_results: list[GateResult] = []
    artifacts: dict[str, bytes] = {}

    for gate_rule in INITIAL_PRIVATE_PILOT_PROFILE.gates:
        evidence_items: list[EvidenceRef] = []
        for evidence_rule in gate_rule.evidence:
            artifact = json.dumps(
                {"gate": gate_rule.gate_id, "kind": evidence_rule.kind},
                sort_keys=True,
            ).encode()
            artifact_digest = digest_ref(artifact)
            artifacts[artifact_digest.sha256] = artifact
            evidence_items.append(
                EvidenceRef(
                    evidence_id=f"{gate_rule.gate_id}-{evidence_rule.kind}",
                    kind=evidence_rule.kind,
                    uri=build_content_addressed_uri(artifact_digest.sha256),
                    digest=artifact_digest,
                    candidate_binding_sha256=binding,
                    produced_at=NOW - timedelta(hours=1),
                    expires_at=(
                        None
                        if evidence_rule.max_age_seconds is None
                        else NOW
                        - timedelta(hours=1)
                        + timedelta(seconds=evidence_rule.max_age_seconds)
                    ),
                )
            )
        metrics: dict[str, bool | int | float | str] = {}
        for metric_rule in gate_rule.metrics:
            if metric_rule.comparison == "binding":
                metrics[metric_rule.key] = {
                    "migration_set": candidate.migration_set.sha256,
                    "knowledge_service_migration_set": (
                        candidate.knowledge_source_service.migration_set.sha256
                    ),
                    "knowledge_service_openapi_contract": (
                        candidate.knowledge_source_service.openapi_contract.sha256
                    ),
                    "deployment_compatibility_manifest": (
                        candidate.deployment_compatibility_manifest.sha256
                    ),
                }[metric_rule.binding_target]
            elif metric_rule.comparison == "format":
                metrics[metric_rule.key] = SHA_A
            else:
                assert metric_rule.expected is not None
                metrics[metric_rule.key] = metric_rule.expected
        gate_results.append(
            evaluate_gate(
                candidate=candidate,
                gate_id=gate_rule.gate_id,
                evidence=evidence_items,
                metrics=metrics,
                evaluated_at=NOW,
            )
        )

    manifest = assemble_release_manifest(
        candidate=candidate,
        results=gate_results,
        generated_at=NOW,
    )
    for result in manifest.results:
        assert result.status == "passed"
        for evidence in result.evidence:
            artifact = artifacts[evidence.digest.sha256]
            (evidence_root / evidence.digest.sha256).write_bytes(artifact)
            envelope = build_evidence_attestation(
                result=result,
                evidence=evidence,
                artifact=artifact,
                trust_identity=trust,
                signer=private_key.sign,
            )
            (attestation_root / f"{evidence.digest.sha256}.attestation.json").write_bytes(
                envelope
            )
    manifest_path = tmp_path / "release-gate-manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    trust_path = tmp_path / "release-trust.json"
    trust_path.write_text(
        json.dumps(
            {
                "schema_version": "proofagent.release-evidence-trust.v1",
                "identities": [
                    {
                        **trust.model_dump(mode="json"),
                        "public_key_base64": base64.b64encode(
                            private_key.public_key().public_bytes_raw()
                        ).decode("ascii"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    command = CliRunner().invoke(
        cli_module.app,
        [
            "release",
            "verify",
            "--manifest",
            str(manifest_path),
            "--evidence-root",
            str(evidence_root),
            "--attestation-root",
            str(attestation_root),
            "--trust-policy",
            str(trust_path),
            "--at",
            NOW.isoformat().replace("+00:00", "Z"),
        ],
    )

    assert command.exit_code == 0
    assert json.loads(command.stdout)["decision"] == "GO"
