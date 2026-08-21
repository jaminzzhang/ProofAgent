"""Run one production-shaped KSS → ProofAgent → configured-model validation question.

This is a local deployment verifier. It does not publish or activate an Agent and it
does not replace the Phase F release authority.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.application_services import (
    compose_application_persistence,
    compose_production_egress_client,
    compose_production_vault_secret_provider,
)
from proof_agent.bootstrap.knowledge_candidate_runtime import (
    compose_production_knowledge_candidate_runtime,
)
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.model_credentials import compose_model_credential_cipher
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.model_credential_repository import (
    PostgresModelCredentialRepository,
)
from proof_agent.capabilities.persistence.postgres.runtime_assets import (
    PostgresRuntimeSharedAssetReader,
)
from proof_agent.contracts import (
    InstitutionAuthorizationContext,
    ProductionSecretHandle,
    ReceiptOutcome,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    RunPurpose,
    SecretPurpose,
)
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.observability.storage.run_store import RunStore


_DEFAULT_AGENT = Path(
    "/app/deploy/production/agent_management_insurance_specialist/agent.yaml"
)
_FORBIDDEN_MODEL_KEYS = frozenset(
    {
        "api_key",
        "api_key_env",
        "credential_ref",
        "credential_secret_handle",
    }
)


def validation_manifest_payload(
    source: Path,
    *,
    connection_id: str,
) -> dict[str, Any]:
    """Select one Shared Model Connection without materializing its credential."""

    normalized_connection_id = connection_id.strip()
    if not normalized_connection_id or len(normalized_connection_id) > 255:
        raise ValueError("validation model connection id is invalid")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("validation Agent manifest must be an object")
    payload = dict(raw)
    roles = (
        _mapping(payload, "model"),
        _mapping(_mapping(payload, "react"), "planner"),
        _mapping(_mapping(payload, "review"), "subagent"),
    )
    for role in roles:
        params = _mapping(role, "params")
        if _FORBIDDEN_MODEL_KEYS.intersection(role) or _FORBIDDEN_MODEL_KEYS.intersection(
            params
        ):
            raise ValueError("validation Agent cannot contain inline model credentials")
        role["model_source"] = "shared"
        role["connection_id"] = normalized_connection_id
    return payload


def main() -> None:
    values = os.environ
    source = Path(values.get("PROOF_AGENT_QA_AGENT_PATH", str(_DEFAULT_AGENT)))
    connection_id = _required(values, "PROOF_AGENT_QA_MODEL_CONNECTION_ID")
    question = _required(values, "PROOF_AGENT_QA_QUESTION")
    release_id = _required(values, "PROOF_AGENT_KSS_RELEASE_ID")
    payload = validation_manifest_payload(source, connection_id=connection_id)

    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise RuntimeError("local production QA requires PostgreSQL persistence")
    try:
        cipher = compose_model_credential_cipher(values)
        model_credentials = PostgresModelCredentialRepository(
            persistence.engine,
            cipher=cipher,
        )
        validation = model_credentials.validate(connection_id)
        if not validation.resolvable:
            raise RuntimeError("configured encrypted model credential is unavailable")
        runtime_configuration = PostgresRuntimeSharedAssetReader(
            models=persistence.models,
            tools=persistence.tools,
        )
        if runtime_configuration.get_model_connection(connection_id) is None:
            raise RuntimeError("configured model connection is unavailable")
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        knowledge_runtime = compose_production_knowledge_candidate_runtime(
            values,
            http_client=guarded,
            secret_provider=secret_provider,
        )
        binding = ResolvedKnowledgeSourceServiceBinding(
            binding_id=_required(values, "PROOF_AGENT_KSS_BINDING_ID"),
            knowledge_base_release_id=release_id,
            client_credential_ref=ProductionSecretHandle(
                protocol_id=secret_provider.protocol_id,
                handle_id=_required(values, "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE"),
                purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                version_id=_required(
                    values,
                    "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID",
                ),
            ),
            admission_scorer_id=_required(
                values,
                "PROOF_AGENT_KSS_ADMISSION_SCORER_ID",
            ),
            admission_scorer_revision=_required(
                values,
                "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION",
            ),
        )
        _run_question(
            values=values,
            source=source,
            payload=payload,
            connection_id=connection_id,
            question=question,
            release_id=release_id,
            binding=binding,
            runtime_configuration=runtime_configuration,
            knowledge_runtime=knowledge_runtime,
            guarded=guarded,
            secret_provider=secret_provider,
            model_credentials=model_credentials,
        )
    finally:
        persistence.close()


def _run_question(
    *,
    values: Mapping[str, str],
    source: Path,
    payload: dict[str, Any],
    connection_id: str,
    question: str,
    release_id: str,
    binding: ResolvedKnowledgeSourceServiceBinding,
    runtime_configuration: PostgresRuntimeSharedAssetReader,
    knowledge_runtime: Any,
    guarded: Any,
    secret_provider: Any,
    model_credentials: PostgresModelCredentialRepository,
) -> None:
    with TemporaryDirectory(prefix="proof-agent-qa-") as directory:
        root = Path(directory)
        manifest_path = root / "agent.yaml"
        manifest_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        policy_source = source.parent / "policy.yaml"
        shutil.copyfile(policy_source, root / "policy.yaml")
        manifest = load_agent_manifest(manifest_path, require_writable_artifacts=False)
        published_agent = PublishedAgent(
            agent_id=manifest.name,
            manifest_path=manifest_path,
            display_name=manifest.name,
            purpose=manifest.purpose,
            customer_facing=False,
            agent_version_id="local-production-qa-validation",
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
                bindings=(binding,)
            ),
            source="local_production_validation",
        )
        store = RunStore(root / "history")
        execution = execute_published_agent_run(
            dependencies=RunExecutionDependencies(
                store=store,
                runs_dir=root / "latest",
                configuration_store=runtime_configuration,
                knowledge_candidate_runtime=knowledge_runtime,
                guarded_http_client=guarded,
                secret_provider=secret_provider,
                model_credential_resolver=model_credentials,
            ),
            published_agent=published_agent,
            question=question,
            run_purpose=RunPurpose.VALIDATION,
            institution_authorization=(
                InstitutionAuthorizationContext.model_validate_json(
                    _required(
                        values,
                        "PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON",
                    )
                )
            ),
        )
        accepted_citations = sum(
            1
            for chunk in execution.detail.evidence_chunks
            if str(getattr(chunk.status, "value", chunk.status)) == "accepted"
            and isinstance(chunk.citation, str)
            and chunk.citation.strip()
        )
        result = {
            "answer": execution.result.final_output,
            "accepted_citation_count": accepted_citations,
            "evidence_class": "local_production_validation_only",
            "knowledge_base_release_id": release_id,
            "model_connection_id": connection_id,
            "outcome": execution.result.outcome.value,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        if (
            execution.result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
            or accepted_citations < 1
        ):
            raise RuntimeError("local production QA did not answer with citations")


def _mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"validation Agent field {key} must be an object")
    return value


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


if __name__ == "__main__":
    main()
