from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from proof_agent.contracts import (
    AgentContextConfiguration,
    ContextBudgetProfile,
    ContextConvergenceLadder,
)


ContextBudgetSource = Literal["agent_config", "calibration", "built_in_default"]
ContextConvergenceLevel = Literal["none", "level1", "level2", "deep_compression"]

DEFAULT_CONTEXT_MAX_TOKENS = 4096
DEFAULT_RESERVED_OUTPUT_TOKENS = 512


@dataclass(frozen=True)
class ContextBudgetKey:
    provider: str
    model: str
    role: str
    profile_version: str = "context_budget.v1"


@dataclass(frozen=True)
class ContextBudgetCalibrationRecord:
    key: ContextBudgetKey
    max_tokens: int
    reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS
    update_ref: str | None = None


@dataclass(frozen=True)
class ResolvedContextBudget:
    max_tokens: int
    reserved_output_tokens: int
    available_input_tokens: int
    estimation_strategy: str
    profile_version: str
    convergence: ContextConvergenceLadder
    budget_source: ContextBudgetSource
    dynamic_calibration: bool
    calibration_update_ref: str | None = None


class InMemoryContextBudgetCalibrationStore:
    """Small runtime store for provider/model context-limit calibration facts."""

    def __init__(self) -> None:
        self._records: dict[ContextBudgetKey, ContextBudgetCalibrationRecord] = {}

    def get(self, key: ContextBudgetKey) -> ContextBudgetCalibrationRecord | None:
        return self._records.get(key)

    def put(self, record: ContextBudgetCalibrationRecord) -> None:
        self._records[record.key] = record


def resolve_context_budget(
    *,
    context_config: AgentContextConfiguration | None,
    calibration_store: InMemoryContextBudgetCalibrationStore,
    key: ContextBudgetKey,
) -> ResolvedContextBudget:
    """Resolve the Control Plane context assembly budget for one model-call role."""

    convergence = (
        context_config.convergence if context_config is not None else ContextConvergenceLadder()
    )
    if context_config is not None and context_config.budget_profile is not None:
        return _resolved_from_profile(
            context_config.budget_profile,
            convergence=convergence,
            budget_source="agent_config",
            dynamic_calibration=False,
            calibration_update_ref=None,
        )

    dynamic_calibration = context_config.dynamic_calibration if context_config is not None else True
    if dynamic_calibration:
        calibration = calibration_store.get(key)
        if calibration is not None:
            profile = ContextBudgetProfile(
                max_tokens=calibration.max_tokens,
                reserved_output_tokens=calibration.reserved_output_tokens,
                estimation_strategy="heuristic",
                profile_version=key.profile_version,
            )
            return _resolved_from_profile(
                profile,
                convergence=convergence,
                budget_source="calibration",
                dynamic_calibration=True,
                calibration_update_ref=calibration.update_ref,
            )

    return _resolved_from_profile(
        ContextBudgetProfile(
            max_tokens=DEFAULT_CONTEXT_MAX_TOKENS,
            reserved_output_tokens=DEFAULT_RESERVED_OUTPUT_TOKENS,
            estimation_strategy="heuristic",
            profile_version=key.profile_version,
        ),
        convergence=convergence,
        budget_source="built_in_default",
        dynamic_calibration=dynamic_calibration,
        calibration_update_ref=None,
    )


def context_convergence_level(
    *,
    estimated_tokens: int,
    budget: ResolvedContextBudget,
) -> ContextConvergenceLevel:
    limit = max(1, budget.available_input_tokens)
    ratio = estimated_tokens / limit
    if ratio >= budget.convergence.hard_limit_ratio:
        return "deep_compression"
    if ratio >= budget.convergence.level2_ratio:
        return "level2"
    if ratio >= budget.convergence.level1_ratio:
        return "level1"
    return "none"


def record_context_overflow_calibration(
    *,
    context_config: AgentContextConfiguration | None,
    calibration_store: InMemoryContextBudgetCalibrationStore,
    key: ContextBudgetKey,
    failed_estimated_tokens: int,
    recovered_estimated_tokens: int,
) -> ContextBudgetCalibrationRecord | None:
    """Record a dynamic default budget after a provider context-limit overflow."""

    if context_config is not None and context_config.budget_profile is not None:
        return None
    if context_config is not None and not context_config.dynamic_calibration:
        return None

    calibrated_max_tokens = max(
        recovered_estimated_tokens + DEFAULT_RESERVED_OUTPUT_TOKENS,
        int(failed_estimated_tokens * 0.8),
    )
    record = ContextBudgetCalibrationRecord(
        key=key,
        max_tokens=calibrated_max_tokens,
        reserved_output_tokens=DEFAULT_RESERVED_OUTPUT_TOKENS,
        update_ref=(f"calibration:{key.provider}:{key.model}:{key.role}:{key.profile_version}"),
    )
    calibration_store.put(record)
    return record


def _resolved_from_profile(
    profile: ContextBudgetProfile,
    *,
    convergence: ContextConvergenceLadder,
    budget_source: ContextBudgetSource,
    dynamic_calibration: bool,
    calibration_update_ref: str | None,
) -> ResolvedContextBudget:
    available_input_tokens = max(
        1,
        profile.max_tokens - profile.reserved_output_tokens,
    )
    return ResolvedContextBudget(
        max_tokens=profile.max_tokens,
        reserved_output_tokens=profile.reserved_output_tokens,
        available_input_tokens=available_input_tokens,
        estimation_strategy=profile.estimation_strategy,
        profile_version=profile.profile_version,
        convergence=convergence,
        budget_source=budget_source,
        dynamic_calibration=dynamic_calibration,
        calibration_update_ref=calibration_update_ref,
    )
