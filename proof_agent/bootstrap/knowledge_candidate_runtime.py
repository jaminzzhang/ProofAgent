"""Per-run boundary for the KSS-only production Knowledge authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from proof_agent.capabilities.knowledge.admission_scorer_client import (
    HttpKnowledgeCandidateAdmissionScorer,
)
from proof_agent.capabilities.knowledge.source_service_client import (
    KnowledgeSourceServiceClient,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateExecutionBudget,
)
from proof_agent.contracts.knowledge_resolution import (
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.knowledge_candidates import (
    KnowledgeCandidateAdmissionScorer,
    KnowledgeCandidateService,
)
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.secrets import (
    ProductionSecretHandle,
    SecretPurpose,
)
from proof_agent.control.knowledge.candidate_request import (
    BoundKnowledgeCandidateQueryFactory,
    KnowledgeCandidateQueryFactory,
)


@dataclass(frozen=True)
class KnowledgeCandidateRunDependencies:
    """Exact external Knowledge dependencies for one Published Agent run."""

    service: KnowledgeCandidateService
    query_factory: KnowledgeCandidateQueryFactory
    admission_scorer: KnowledgeCandidateAdmissionScorer


class KnowledgeCandidateRuntime(Protocol):
    """Bind immutable Published Agent KSS authority to executable adapters."""

    def bind_for_run(
        self,
        resolved_bindings: ResolvedKnowledgeBindingSet,
    ) -> KnowledgeCandidateRunDependencies: ...


class ProductionKnowledgeCandidateRuntime:
    """Bind one immutable Published Agent KSS reference without local fallback."""

    def __init__(
        self,
        *,
        endpoint: str,
        http_client: GuardedHttpClient,
        secret_provider: SecretProvider,
        admission_scorer: KnowledgeCandidateAdmissionScorer,
        execution_budget: KnowledgeCandidateExecutionBudget,
        deadline_after: timedelta,
        clock: Callable[[], datetime],
        max_polls: int = 120,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._endpoint = endpoint
        self._http_client = http_client
        self._secret_provider = secret_provider
        self._admission_scorer = admission_scorer
        self._execution_budget = execution_budget
        self._deadline_after = deadline_after
        self._clock = clock
        self._max_polls = max_polls
        self._timeout_seconds = timeout_seconds

    def bind_for_run(
        self,
        resolved_bindings: ResolvedKnowledgeBindingSet,
    ) -> KnowledgeCandidateRunDependencies:
        if len(resolved_bindings.bindings) != 1 or not isinstance(
            resolved_bindings.bindings[0],
            ResolvedKnowledgeSourceServiceBinding,
        ):
            raise ValueError(
                "production KSS runtime requires exactly one service binding"
            )
        binding = resolved_bindings.bindings[0]
        if binding.client_credential_ref.protocol_id != self._secret_provider.protocol_id:
            raise ValueError(
                "Published KSS credential protocol does not match the Secret Provider"
            )
        if (
            binding.admission_scorer_id != self._admission_scorer.scorer_id
            or binding.admission_scorer_revision
            != self._admission_scorer.scorer_revision
        ):
            raise ValueError(
                "Published KSS admission scorer identity does not match deployment authority"
            )
        return KnowledgeCandidateRunDependencies(
            service=KnowledgeSourceServiceClient(
                endpoint=self._endpoint,
                http_client=self._http_client,
                authorization_header_factory=lambda: _authorization_header(
                    self._secret_provider,
                    binding.client_credential_ref,
                ),
                max_polls=self._max_polls,
                timeout_seconds=self._timeout_seconds,
            ),
            query_factory=BoundKnowledgeCandidateQueryFactory(
                knowledge_base_release_id=binding.knowledge_base_release_id,
                execution_budget=self._execution_budget,
                deadline_after=self._deadline_after,
                clock=self._clock,
            ),
            admission_scorer=self._admission_scorer,
        )


def compose_production_knowledge_candidate_runtime(
    environment: Mapping[str, str],
    *,
    http_client: GuardedHttpClient,
    secret_provider: SecretProvider,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ProductionKnowledgeCandidateRuntime:
    """Require every deployment-owned input for the KSS-only runtime."""

    scorer_handle = ProductionSecretHandle(
        protocol_id=secret_provider.protocol_id,
        handle_id=_required(
            environment,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_SECRET_HANDLE",
        ),
        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        version_id=(
            environment.get(
                "PROOF_AGENT_KSS_ADMISSION_SCORER_SECRET_VERSION_ID",
                "",
            ).strip()
            or None
        ),
    )
    scorer = HttpKnowledgeCandidateAdmissionScorer(
        endpoint=_required(
            environment,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ENDPOINT",
        ),
        http_client=http_client,
        authorization_header_factory=lambda: _authorization_header(
            secret_provider,
            scorer_handle,
        ),
        scorer_id=_required(environment, "PROOF_AGENT_KSS_ADMISSION_SCORER_ID"),
        scorer_revision=_required(
            environment,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION",
        ),
    )
    return ProductionKnowledgeCandidateRuntime(
        endpoint=_required(environment, "PROOF_AGENT_KSS_ENDPOINT"),
        http_client=http_client,
        secret_provider=secret_provider,
        admission_scorer=scorer,
        execution_budget=KnowledgeCandidateExecutionBudget(
            max_rounds=_positive_int(
                environment,
                "PROOF_AGENT_KSS_QUERY_MAX_ROUNDS",
            ),
            max_model_calls=_positive_int(
                environment,
                "PROOF_AGENT_KSS_QUERY_MAX_MODEL_CALLS",
            ),
            max_candidates=_positive_int(
                environment,
                "PROOF_AGENT_KSS_QUERY_MAX_CANDIDATES",
            ),
            max_model_tokens=_positive_int(
                environment,
                "PROOF_AGENT_KSS_QUERY_MAX_MODEL_TOKENS",
            ),
            max_duration_ms=_positive_int(
                environment,
                "PROOF_AGENT_KSS_QUERY_MAX_DURATION_MS",
            ),
        ),
        deadline_after=timedelta(
            seconds=_positive_float(
                environment,
                "PROOF_AGENT_KSS_QUERY_DEADLINE_SECONDS",
            )
        ),
        clock=clock,
    )


def _authorization_header(
    provider: SecretProvider,
    handle: ProductionSecretHandle,
) -> str:
    resolved = provider.resolve(handle)
    if handle.version_id is not None and resolved.provider_version_id != handle.version_id:
        raise ValueError("Published KSS client credential version is unavailable")
    material = resolved.reveal_for_use()
    try:
        token = material.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("KSS client credential is invalid") from exc
    if (
        not token
        or len(material) > 16 * 1024
        or token != token.strip()
        or any(character.isspace() for character in token)
    ):
        raise ValueError("KSS client credential is invalid")
    return f"Bearer {token}"


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required for the production KSS runtime")
    return value


def _positive_int(values: Mapping[str, str], key: str) -> int:
    raw = _required(values, key)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _positive_float(values: Mapping[str, str], key: str) -> float:
    raw = _required(values, key)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be positive") from exc
    if not 0 < value <= 120:
        raise ValueError(f"{key} must be between 0 and 120")
    return value


__all__ = [
    "KnowledgeCandidateRunDependencies",
    "KnowledgeCandidateRuntime",
    "ProductionKnowledgeCandidateRuntime",
    "compose_production_knowledge_candidate_runtime",
]
