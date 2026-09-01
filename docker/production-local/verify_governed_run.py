"""Verify one fixed synthetic Candidate through the governed Run entry."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Literal

import proof_agent
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    EvidenceStatus,
    ReceiptOutcome,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    RunPurpose,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)

from verify_admission_scorer import (
    _ExactSyntheticAdmissionScorer,
    _SYNTHETIC_CANDIDATE_ID,
    _SYNTHETIC_QUESTION,
    _run_in_production_composition,
    _sha256,
    _synthetic_result,
)


GovernedRunVerificationReason = Literal[
    "runtime_binding",
    "fixture_path",
    "fixture_manifest",
    "fixture_models",
    "run_execution",
    "ephemeral_audit",
    "outcome_validation",
]


class GovernedRunVerificationError(RuntimeError):
    """Classify a safe verification stage without exposing failure detail."""

    def __init__(
        self,
        reason_code: GovernedRunVerificationReason,
        message: str,
    ) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def verify_production_local_governed_run(
    *,
    runtime: Any,
    binding: ResolvedKnowledgeSourceServiceBinding,
) -> dict[str, object]:
    """Execute one content-free fixed-synthetic governed Run verification."""

    resolved_bindings = ResolvedKnowledgeBindingSet(bindings=(binding,))
    try:
        dependencies = runtime.bind_for_run(resolved_bindings)
        scorer = dependencies.admission_scorer
    except Exception as exc:
        raise GovernedRunVerificationError(
            "runtime_binding",
            "production-local governed Run dependencies could not be bound",
        ) from exc
    if (
        scorer.scorer_id != binding.admission_scorer_id
        or scorer.scorer_revision != binding.admission_scorer_revision
    ):
        raise GovernedRunVerificationError(
            "runtime_binding",
            "production-local scorer identity changed",
        )

    try:
        agent_yaml = _deterministic_agent_yaml()
    except Exception as exc:
        raise GovernedRunVerificationError(
            "fixture_path",
            "fixed synthetic governed Run fixture path is unavailable",
        ) from exc
    try:
        manifest = load_agent_manifest(
            agent_yaml,
            require_writable_artifacts=False,
        )
    except Exception as exc:
        raise GovernedRunVerificationError(
            "fixture_manifest",
            "fixed synthetic governed Run fixture manifest is invalid",
        ) from exc
    try:
        _require_deterministic_models(manifest)
    except Exception as exc:
        raise GovernedRunVerificationError(
            "fixture_models",
            "fixed synthetic governed Run providers are not deterministic",
        ) from exc
    candidate_service = _SyntheticGovernedRunCandidateService()

    try:
        with TemporaryDirectory(
            prefix="proof-agent-synthetic-governed-run-"
        ) as directory:
            result = execute_agent_package_run(
                AgentPackageRunRequest(
                    agent_yaml=agent_yaml,
                    manifest=manifest,
                    question=_SYNTHETIC_QUESTION,
                    runs_dir=Path(directory),
                    run_id="run-production-local-synthetic-governed-v1",
                    resolved_knowledge_bindings=resolved_bindings,
                    run_purpose=RunPurpose.VALIDATION,
                    knowledge_candidate_service=candidate_service,
                    knowledge_candidate_query_factory=dependencies.query_factory,
                    knowledge_candidate_admission_scorer=(
                        _ExactSyntheticAdmissionScorer(scorer)
                    ),
                )
            )
            if not result.trace_path.is_file() or not result.receipt_path.is_file():
                raise GovernedRunVerificationError(
                    "ephemeral_audit",
                    "governed Run did not produce its ephemeral audit files",
                )
    except GovernedRunVerificationError:
        raise
    except Exception as exc:
        raise GovernedRunVerificationError(
            "run_execution",
            "fixed synthetic governed Run execution failed",
        ) from exc

    execution = result.workflow_template_execution_result
    if execution is None:
        raise GovernedRunVerificationError(
            "outcome_validation",
            "governed Run did not produce a workflow result",
        )
    accepted_evidence = tuple(
        chunk for chunk in execution.evidence if chunk.status is EvidenceStatus.ACCEPTED
    )
    citations = tuple(chunk.citation for chunk in accepted_evidence if chunk.citation is not None)
    if (
        result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
        or len(accepted_evidence) != 1
        or len(citations) != 1
        or candidate_service.query_count != 1
    ):
        raise GovernedRunVerificationError(
            "outcome_validation",
            "governed Run did not produce a cited answer from one Candidate",
        )

    return {
        "schema_version": "production-local-governed-run-verification.v1",
        "evidence_class": "local_synthetic_dependency_validation_only",
        "status": "passed",
        "outcome": result.outcome.value.casefold(),
        "scorer_id": scorer.scorer_id,
        "scorer_revision": scorer.scorer_revision,
        "accepted_evidence_count": len(accepted_evidence),
        "citation_count": len(citations),
        "question_sha256": _sha256(_SYNTHETIC_QUESTION),
        "candidate_set_sha256": _sha256(_SYNTHETIC_CANDIDATE_ID),
        "kss_query_created": False,
        "external_answer_model_called": False,
        "artifact_store_written": False,
        "phase_f_authorized": False,
        "publication_authorized": False,
    }


class _SyntheticGovernedRunCandidateService:
    """Return the fixed Candidate Result without contacting KSS."""

    def __init__(self) -> None:
        self.query_count = 0

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult:
        if (
            request.question != _SYNTHETIC_QUESTION
            or request.knowledge_base_release_id != "synthetic-admission-release-v1"
            or request.strategy != "single_pass"
        ):
            raise RuntimeError("governed Run changed the fixed synthetic Candidate Query")
        self.query_count += 1
        return _synthetic_result()


def _deterministic_agent_yaml() -> Path:
    package_file = proof_agent.__file__
    if package_file is None:
        raise RuntimeError("proof_agent package path is unavailable")
    return (
        Path(package_file).resolve().parent
        / "evaluation"
        / "demo"
        / "fixtures"
        / "react_enterprise_qa_v3"
        / "agent.yaml"
    )


def _require_deterministic_models(manifest: Any) -> None:
    react = manifest.react
    review = manifest.review
    providers = (
        manifest.model.provider,
        react.planner.provider if react is not None else None,
        review.subagent.provider if review is not None and review.subagent is not None else None,
    )
    if providers != ("deterministic", "deterministic", "deterministic"):
        raise RuntimeError("governed Run verifier requires deterministic model providers")


def main() -> None:
    result = _run_in_production_composition(verify_production_local_governed_run)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


def cli() -> int:
    """Run with one bounded failure projection and no internal detail."""

    try:
        main()
    except Exception as exc:
        payload = {
            "schema_version": "production-local-governed-run-verification-failure.v1",
            "status": "failed",
            "error_code": "governed_run_verification_failed",
        }
        if isinstance(exc, GovernedRunVerificationError):
            payload["reason_code"] = exc.reason_code
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
