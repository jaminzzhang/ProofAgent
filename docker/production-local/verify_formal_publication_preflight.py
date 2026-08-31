"""Assemble one exact production-local Formal Candidate without publication writes."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateRejected,
)
from proof_agent.errors import ProofAgentError


_EXACT_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def verify_formal_publication_preflight(
    *,
    agent_id: str,
    draft_id: str,
    draft_revision: int,
    service: Any,
) -> dict[str, object]:
    """Return a secret-free exact-candidate summary without publication authority."""

    exact_agent_id = _preflight_identifier(agent_id)
    exact_draft_id = _preflight_identifier(draft_id)
    exact_draft_revision = _preflight_revision(draft_revision)
    candidate = service.preflight(
        agent_id=exact_agent_id,
        draft_id=exact_draft_id,
        draft_revision=exact_draft_revision,
    )
    if (
        candidate.agent_id != exact_agent_id
        or candidate.draft_id != exact_draft_id
        or candidate.draft_revision != exact_draft_revision
    ):
        raise RuntimeError("preflight candidate identity changed")

    release = candidate.knowledge_release_candidate
    bindings = candidate.resolved_knowledge_bindings.bindings
    if len(bindings) != 1:
        raise RuntimeError("preflight candidate must contain one resolved binding")
    binding = bindings[0]
    if binding.knowledge_base_release_id != release.knowledge_base_release_id:
        raise RuntimeError("preflight candidate Release binding changed")

    return {
        "schema_version": "production-local-formal-publication-preflight.v1",
        "evidence_class": "local_production_validation_only",
        "status": "candidate_assembled",
        "publication_authorized": False,
        "agent_id": exact_agent_id,
        "draft_id": exact_draft_id,
        "draft_revision": exact_draft_revision,
        "knowledge_space_id": _preflight_identifier(release.knowledge_space_id),
        "knowledge_base_id": _preflight_identifier(release.knowledge_base_id),
        "knowledge_base_version_id": _preflight_identifier(release.knowledge_base_version_id),
        "knowledge_base_release_id": _preflight_identifier(release.knowledge_base_release_id),
        "knowledge_service_catalog_revision": _preflight_identifier(
            candidate.knowledge_service_catalog_revision
        ),
        "binding_id": _preflight_identifier(binding.binding_id),
        "admission_scorer_id": _preflight_identifier(binding.admission_scorer_id),
        "admission_scorer_revision": _preflight_identifier(binding.admission_scorer_revision),
        "knowledge_release_candidate_sha256": _preflight_sha256(
            candidate.knowledge_release_candidate_sha256
        ),
        "formal_candidate_sha256": _preflight_sha256(candidate.formal_candidate_sha256),
    }


def main() -> None:
    values = os.environ
    agent_id = _required(values, "PROOF_AGENT_PREFLIGHT_AGENT_ID")
    draft_id = _required(values, "PROOF_AGENT_PREFLIGHT_DRAFT_ID")
    draft_revision = _environment_revision(
        _required(values, "PROOF_AGENT_PREFLIGHT_DRAFT_REVISION")
    )
    result = asyncio.run(
        _compose_and_preflight(
            values=values,
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


async def _compose_and_preflight(
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
        service = application.state.formal_production_agent_publication_command
        if service is None:
            raise RuntimeError("formal publication composition is unavailable")
        return verify_formal_publication_preflight(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            service=service,
        )


def cli() -> int:
    """Run the preflight with bounded, secret-free failure output."""

    blocker_codes: tuple[str, ...] = ()
    try:
        main()
    except FormalProductionAgentCandidateRejected as error:
        error_code = _failure_code(error.code)
        blocker_codes = tuple(_failure_code(code) for code in error.blocker_codes)
    except ProofAgentError as error:
        error_code = _failure_code(error.code)
    except ValueError:
        error_code = "invalid_preflight_input"
    except Exception:
        error_code = "formal_candidate_preflight_failed"
    else:
        return 0

    result: dict[str, object] = {
        "schema_version": "production-local-formal-publication-preflight-failure.v1",
        "status": "failed",
        "error_code": error_code,
    }
    if blocker_codes:
        result["blocker_codes"] = list(blocker_codes)
    print(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )
    return 1


def _preflight_identifier(value: str) -> str:
    normalized = value.strip()
    if not _EXACT_IDENTIFIER.fullmatch(normalized):
        raise ValueError("preflight identifier is invalid")
    return normalized


def _preflight_revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("preflight draft revision is invalid")
    return value


def _environment_revision(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("preflight draft revision is invalid")
    return _preflight_revision(int(value))


def _preflight_sha256(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise RuntimeError("preflight candidate digest is invalid")
    return value


def _failure_code(value: str) -> str:
    normalized = value.strip()
    if not _EXACT_IDENTIFIER.fullmatch(normalized):
        return "formal_candidate_preflight_failed"
    return normalized


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(cli())
