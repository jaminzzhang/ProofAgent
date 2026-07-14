from __future__ import annotations

from proof_agent.contracts import ExactArtifactRef
from proof_agent.contracts.evaluation import (
    InsuranceKnowledgeEvaluationReport,
    InsuranceKnowledgeSliceMetrics,
    InsuranceRetrievalMetrics,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.gate_profiles import INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1
from proof_agent.evaluation.knowledge_gates import (
    KnowledgeAcceptanceAggregate,
    KnowledgeHardGateFacts,
)
from proof_agent.evaluation.sealed_knowledge_acceptance import (
    SealedKnowledgeAcceptanceAttestation,
    SealedKnowledgeAcceptanceEnvelope,
    SealedKnowledgeAcceptanceStore,
    SealedKnowledgeSuiteRef,
    seal_knowledge_acceptance_attestation,
)
from proof_agent.evaluation.suites import load_sealed_knowledge_acceptance_envelope

import pytest


def _metrics(
    *,
    recall_50: float = 0.96,
    complete_top_10: float = 0.92,
) -> InsuranceRetrievalMetrics:
    return InsuranceRetrievalMetrics(
        retrieval_case_count=100,
        required_evidence_recall_at_20=0.94,
        required_evidence_recall_at_50=recall_50,
        required_evidence_recall_at_100=0.99,
        complete_evidence_top_5_rate=0.88,
        complete_evidence_top_10_rate=complete_top_10,
        ndcg_at_10=0.93,
        mrr_at_10=0.95,
        citation_resolvability_rate=1.0,
    )


def _aggregate(
    *,
    hard_facts: KnowledgeHardGateFacts | None = None,
) -> KnowledgeAcceptanceAggregate:
    slices = tuple(
        InsuranceKnowledgeSliceMetrics(
            dimension="query_type",
            value=query_type,
            case_count=case_count,
            metrics=_metrics(),
        )
        for query_type, case_count in (
            ("clause_lookup", 60),
            ("conditional_guidance", 100),
            ("comparison", 40),
        )
    )
    return KnowledgeAcceptanceAggregate(
        report=InsuranceKnowledgeEvaluationReport(
            case_count=200,
            overall=_metrics(),
            slices=slices,
        ),
        hard_facts=hard_facts or KnowledgeHardGateFacts(),
        human_reviewed_support_precision=0.99,
        hybrid_retrieval_p95_seconds=4.5,
    )


def _sealed_ref() -> SealedKnowledgeSuiteRef:
    return SealedKnowledgeSuiteRef(
        suite_id="insurance-knowledge-acceptance",
        version="2026-07-14",
        case_count=200,
        artifact=ExactArtifactRef(
            artifact_uri="s3://proof-agent-private-eval/sealed/suite.yaml",
            version_id="sealed-suite-v1",
            sha256="a" * 64,
            size_bytes=4096,
            media_type="application/yaml",
        ),
    )


def _attestation(candidate_digest: str) -> SealedKnowledgeAcceptanceAttestation:
    return seal_knowledge_acceptance_attestation(
        evaluator_id="insurance-evaluator-prod",
        key_id="evaluator-key-2026-07",
        candidate_digest=candidate_digest,
        suite_ref=_sealed_ref(),
        gate_profile_id=INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1.profile_id,
        aggregate=_aggregate(),
        signature="detached-signature",
    )


def _store(candidate_digest: str) -> SealedKnowledgeAcceptanceStore:
    return SealedKnowledgeAcceptanceStore(
        attestation_provider=lambda candidate, _suite_ref, _profile_id: _attestation(candidate),
        attestation_verifier=lambda attestation: attestation.signature == "detached-signature",
    )


def test_sealed_evaluator_rejects_second_attempt_for_same_candidate() -> None:
    evaluator = _store("candidate-1")

    evaluator.run(candidate_digest="candidate-1", sealed_suite_ref=_sealed_ref())

    with pytest.raises(EvaluationInputError, match="one acceptance attempt"):
        evaluator.run(candidate_digest="candidate-1", sealed_suite_ref=_sealed_ref())


def test_sealed_result_contains_no_case_level_feedback() -> None:
    evaluator = _store("candidate-2")

    result = evaluator.run(candidate_digest="candidate-2", sealed_suite_ref=_sealed_ref())

    assert not hasattr(result, "case_results")
    assert result.hard_gate_failures == 0
    assert result.status == "passed"
    serialized = result.model_dump_json()
    assert "question" not in serialized
    assert "rule_unit_revision" not in serialized


def test_failed_provider_execution_still_consumes_the_candidate_attempt() -> None:
    def fail(*_args) -> SealedKnowledgeAcceptanceAttestation:
        raise RuntimeError("sealed worker failed")

    evaluator = SealedKnowledgeAcceptanceStore(
        attestation_provider=fail,
        attestation_verifier=lambda _attestation: True,
    )

    with pytest.raises(RuntimeError, match="sealed worker failed"):
        evaluator.run(candidate_digest="candidate-failed", sealed_suite_ref=_sealed_ref())
    with pytest.raises(EvaluationInputError, match="one acceptance attempt"):
        evaluator.run(candidate_digest="candidate-failed", sealed_suite_ref=_sealed_ref())


def test_sealed_evaluator_rejects_aggregate_from_wrong_case_count() -> None:
    aggregate = _aggregate().model_copy(
        update={"report": _aggregate().report.model_copy(update={"case_count": 199})}
    )
    evaluator = SealedKnowledgeAcceptanceStore(
        attestation_provider=lambda candidate, suite_ref, profile_id: (
            seal_knowledge_acceptance_attestation(
                evaluator_id="insurance-evaluator-prod",
                key_id="evaluator-key-2026-07",
                candidate_digest=candidate,
                suite_ref=suite_ref,
                gate_profile_id=profile_id,
                aggregate=aggregate,
                signature="detached-signature",
            )
        ),
        attestation_verifier=lambda _attestation: True,
    )

    with pytest.raises(EvaluationInputError, match="case count"):
        evaluator.run(candidate_digest="candidate-count", sealed_suite_ref=_sealed_ref())


def test_sealed_suite_ref_requires_the_frozen_two_hundred_case_cohort() -> None:
    with pytest.raises(ValueError, match="200"):
        SealedKnowledgeSuiteRef.model_validate({**_sealed_ref().model_dump(), "case_count": 199})


def test_persistent_attempt_store_rejects_same_candidate_across_instances(
    tmp_path,
) -> None:
    first = SealedKnowledgeAcceptanceStore(
        attestation_provider=lambda candidate, _suite_ref, _profile_id: _attestation(candidate),
        attestation_verifier=lambda _attestation: True,
        attempt_store=tmp_path / "attempts",
    )
    second = SealedKnowledgeAcceptanceStore(
        attestation_provider=lambda candidate, _suite_ref, _profile_id: _attestation(candidate),
        attestation_verifier=lambda _attestation: True,
        attempt_store=tmp_path / "attempts",
    )

    first.run(candidate_digest="candidate-persistent", sealed_suite_ref=_sealed_ref())

    with pytest.raises(EvaluationInputError, match="one acceptance attempt"):
        second.run(candidate_digest="candidate-persistent", sealed_suite_ref=_sealed_ref())


def test_sealed_acceptance_envelope_loader_reads_aggregate_only_input(tmp_path) -> None:
    envelope = SealedKnowledgeAcceptanceEnvelope(
        candidate_digest="candidate-loader",
        suite_ref=_sealed_ref(),
    )
    path = tmp_path / "sealed-envelope.json"
    path.write_text(envelope.model_dump_json(), encoding="utf-8")

    loaded = load_sealed_knowledge_acceptance_envelope(path)

    assert loaded == envelope
    assert "cases" not in loaded.model_dump()


def test_sealed_evaluator_rejects_tampered_attestation_before_signature_verification() -> None:
    attestation = _attestation("candidate-tampered")
    tampered = attestation.model_copy(
        update={
            "aggregate": _aggregate().model_copy(update={"human_reviewed_support_precision": 0.5})
        }
    )
    verifier_called = False

    def verify(_attestation: SealedKnowledgeAcceptanceAttestation) -> bool:
        nonlocal verifier_called
        verifier_called = True
        return True

    evaluator = SealedKnowledgeAcceptanceStore(
        attestation_provider=lambda *_args: tampered,
        attestation_verifier=verify,
    )

    with pytest.raises(EvaluationInputError, match="digest mismatch"):
        evaluator.run(
            candidate_digest="candidate-tampered",
            sealed_suite_ref=_sealed_ref(),
        )

    assert verifier_called is False
