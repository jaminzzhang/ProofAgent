"""Probe one exact Formal Candidate through real KSS/model dependencies only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import ExactArtifactRef, ReceiptOutcome
from proof_agent.contracts.ports.knowledge_candidates import (
    KnowledgeCandidateAdmissionFailureReason,
)
from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateRejected,
)
from proof_agent.errors import ProofAgentError
from proof_agent.delivery.published_agent_materializer import (
    PublishedAgentMaterializationError,
)
from proof_agent.delivery.production_agent_validation import (
    FormalCandidateExternalSmokeDiagnosticError,
)


_EXACT_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PROBE_QUESTION = "航班延误保险如何理赔？"


def verify_formal_candidate_external_smoke(
    *,
    agent_id: str,
    draft_id: str,
    draft_revision: int,
    preflight_service: Any,
    runner: Any,
) -> dict[str, object]:
    """Return trace-safe evidence for one exact Candidate dependency probe."""

    exact_agent_id = _identifier(agent_id)
    exact_draft_id = _identifier(draft_id)
    exact_draft_revision = _revision(draft_revision)
    candidate = preflight_service.preflight(
        agent_id=exact_agent_id,
        draft_id=exact_draft_id,
        draft_revision=exact_draft_revision,
    )
    if (
        candidate.agent_id != exact_agent_id
        or candidate.draft_id != exact_draft_id
        or candidate.draft_revision != exact_draft_revision
    ):
        raise RuntimeError("formal candidate external smoke identity changed")

    result = runner.validate_candidate_external_smoke(
        candidate,
        question=_PROBE_QUESTION,
    )
    release_id = _identifier(candidate.knowledge_release_candidate.knowledge_base_release_id)
    candidate_sha256 = _sha256(candidate.formal_candidate_sha256)
    release_candidate_sha256 = _sha256(candidate.knowledge_release_candidate_sha256)
    if (
        result.agent_id != exact_agent_id
        or result.draft_id != exact_draft_id
        or result.draft_revision != exact_draft_revision
        or result.formal_candidate_sha256 != candidate_sha256
        or result.knowledge_release_candidate_sha256 != release_candidate_sha256
        or result.knowledge_base_release_id != release_id
    ):
        raise RuntimeError("formal candidate external smoke result identity changed")
    if (
        result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
        or isinstance(result.accepted_citation_count, bool)
        or result.accepted_citation_count < 1
    ):
        raise RuntimeError("formal candidate external smoke did not pass")

    model_connection_ids = tuple(_identifier(value) for value in result.model_connection_ids)
    if not model_connection_ids or len(set(model_connection_ids)) != len(model_connection_ids):
        raise RuntimeError("formal candidate external smoke model identity is invalid")
    trace_ref = ExactArtifactRef.model_validate(result.trace_ref.model_dump(mode="python"))
    receipt_ref = ExactArtifactRef.model_validate(result.receipt_ref.model_dump(mode="python"))
    if trace_ref == receipt_ref:
        raise RuntimeError("formal candidate external smoke artifacts are invalid")

    return {
        "schema_version": "production-local-formal-candidate-external-smoke.v1",
        "evidence_class": "local_external_dependency_validation_only",
        "status": "passed",
        "phase_f_authorized": False,
        "publication_authorized": False,
        "agent_id": exact_agent_id,
        "draft_id": exact_draft_id,
        "draft_revision": exact_draft_revision,
        "formal_candidate_sha256": candidate_sha256,
        "knowledge_release_candidate_sha256": release_candidate_sha256,
        "knowledge_base_release_id": release_id,
        "question_sha256": hashlib.sha256(_PROBE_QUESTION.encode("utf-8")).hexdigest(),
        "model_connection_ids": list(model_connection_ids),
        "validation_run_id": _identifier(result.validation_run_id),
        "outcome": result.outcome.value,
        "accepted_citation_count": result.accepted_citation_count,
        "trace_ref": trace_ref.model_dump(mode="json"),
        "receipt_ref": receipt_ref.model_dump(mode="json"),
    }


def main() -> None:
    values = os.environ
    result = asyncio.run(
        _compose_and_probe(
            values=values,
            agent_id=_required(values, "PROOF_AGENT_EXTERNAL_SMOKE_AGENT_ID"),
            draft_id=_required(values, "PROOF_AGENT_EXTERNAL_SMOKE_DRAFT_ID"),
            draft_revision=_environment_revision(
                _required(values, "PROOF_AGENT_EXTERNAL_SMOKE_DRAFT_REVISION")
            ),
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


async def _compose_and_probe(
    *,
    values: Mapping[str, str],
    agent_id: str,
    draft_id: str,
    draft_revision: int,
) -> dict[str, object]:
    import warnings

    from authlib.deprecate import (  # type: ignore[import-untyped]
        AuthlibDeprecationWarning,
    )

    warnings.simplefilter("ignore", AuthlibDeprecationWarning)
    from proof_agent.bootstrap.production_roles import create_production_api_application

    application = create_production_api_application(environment=values)
    async with application.router.lifespan_context(application):
        preflight_service = application.state.formal_production_agent_publication_command
        runner = application.state.formal_production_agent_candidate_external_smoke_runner
        if preflight_service is None or runner is None:
            raise RuntimeError("formal candidate external smoke composition is unavailable")
        return verify_formal_candidate_external_smoke(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            preflight_service=preflight_service,
            runner=runner,
        )


def cli() -> int:
    """Run the probe with bounded, secret-free failure output."""

    blocker_codes: tuple[str, ...] = ()
    reason_code: str | None = None
    try:
        main()
    except PublishedAgentMaterializationError:
        error_code = "formal_candidate_contract_bundle_not_materializable"
    except FormalCandidateExternalSmokeDiagnosticError as error:
        error_code = _failure_code(error.code)
        reason_code = _admission_reason_code(error.reason_code)
    except FormalProductionAgentCandidateRejected as error:
        error_code = _failure_code(error.code)
        blocker_codes = tuple(_failure_code(code) for code in error.blocker_codes)
    except ProofAgentError as error:
        error_code = _failure_code(error.code)
    except ValueError:
        error_code = "invalid_external_smoke_input"
    except Exception:
        error_code = "formal_candidate_external_smoke_failed"
    else:
        return 0

    result: dict[str, object] = {
        "schema_version": "production-local-formal-candidate-external-smoke-failure.v2",
        "status": "failed",
        "error_code": error_code,
    }
    if blocker_codes:
        result["blocker_codes"] = list(blocker_codes)
    if reason_code is not None:
        result["reason_code"] = reason_code
    print(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )
    return 1


def _identifier(value: str) -> str:
    normalized = value.strip()
    if not _EXACT_IDENTIFIER.fullmatch(normalized):
        raise ValueError("formal candidate external smoke identifier is invalid")
    return normalized


def _revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("formal candidate external smoke revision is invalid")
    return value


def _environment_revision(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("formal candidate external smoke revision is invalid")
    return _revision(int(value))


def _sha256(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise RuntimeError("formal candidate external smoke digest is invalid")
    return value


def _failure_code(value: str) -> str:
    normalized = value.strip()
    if not _EXACT_IDENTIFIER.fullmatch(normalized):
        return "formal_candidate_external_smoke_failed"
    return normalized


def _admission_reason_code(value: str | None) -> str | None:
    allowed = {reason.value for reason in KnowledgeCandidateAdmissionFailureReason}
    return value if value in allowed else None


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(cli())


__all__ = ["cli", "verify_formal_candidate_external_smoke"]
