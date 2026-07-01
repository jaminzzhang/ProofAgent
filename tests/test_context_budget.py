from __future__ import annotations

from proof_agent.contracts import (
    AgentContextConfiguration,
    ContextBudgetProfile,
    ContextConvergenceLadder,
)
from proof_agent.control.context_budget import (
    ContextBudgetCalibrationRecord,
    ContextBudgetKey,
    InMemoryContextBudgetCalibrationStore,
    context_convergence_level,
    record_context_overflow_calibration,
    resolve_context_budget,
)


def test_resolve_context_budget_prefers_explicit_agent_config() -> None:
    key = ContextBudgetKey(
        provider="deterministic",
        model="demo",
        role="final_answer",
        profile_version="context_budget.v1",
    )
    store = InMemoryContextBudgetCalibrationStore()
    store.put(
        ContextBudgetCalibrationRecord(
            key=key,
            max_tokens=4096,
            reserved_output_tokens=512,
            update_ref="calibration:old",
        )
    )

    budget = resolve_context_budget(
        context_config=AgentContextConfiguration(
            budget_profile=ContextBudgetProfile(
                max_tokens=8192,
                reserved_output_tokens=1024,
                profile_version="context_budget.v1",
            )
        ),
        calibration_store=store,
        key=key,
    )

    assert budget.max_tokens == 8192
    assert budget.available_input_tokens == 7168
    assert budget.budget_source == "agent_config"
    assert budget.calibration_update_ref is None


def test_resolve_context_budget_uses_calibrated_default_when_unconfigured() -> None:
    key = ContextBudgetKey(
        provider="deterministic",
        model="demo",
        role="final_answer",
        profile_version="context_budget.v1",
    )
    store = InMemoryContextBudgetCalibrationStore()
    store.put(
        ContextBudgetCalibrationRecord(
            key=key,
            max_tokens=6144,
            reserved_output_tokens=768,
            update_ref="calibration:deterministic:demo:final_answer",
        )
    )

    budget = resolve_context_budget(
        context_config=None,
        calibration_store=store,
        key=key,
    )

    assert budget.max_tokens == 6144
    assert budget.available_input_tokens == 5376
    assert budget.budget_source == "calibration"
    assert budget.calibration_update_ref == "calibration:deterministic:demo:final_answer"


def test_resolve_context_budget_falls_back_to_builtin_default() -> None:
    budget = resolve_context_budget(
        context_config=None,
        calibration_store=InMemoryContextBudgetCalibrationStore(),
        key=ContextBudgetKey(
            provider="deterministic",
            model="demo",
            role="final_answer",
            profile_version="context_budget.v1",
        ),
    )

    assert budget.max_tokens == 4096
    assert budget.available_input_tokens == 3584
    assert budget.budget_source == "built_in_default"


def test_context_convergence_level_uses_configured_ladder() -> None:
    budget = resolve_context_budget(
        context_config=AgentContextConfiguration(
            budget_profile=ContextBudgetProfile(max_tokens=1000),
            convergence=ContextConvergenceLadder(
                level1_ratio=0.5,
                level2_ratio=0.8,
                hard_limit_ratio=1.0,
            ),
        ),
        calibration_store=InMemoryContextBudgetCalibrationStore(),
        key=ContextBudgetKey(
            provider="deterministic",
            model="demo",
            role="final_answer",
            profile_version="context_budget.v1",
        ),
    )

    assert context_convergence_level(estimated_tokens=499, budget=budget) == "none"
    assert context_convergence_level(estimated_tokens=500, budget=budget) == "level1"
    assert context_convergence_level(estimated_tokens=800, budget=budget) == "level2"
    assert context_convergence_level(estimated_tokens=1000, budget=budget) == ("deep_compression")


def test_record_context_overflow_calibration_skips_explicit_agent_config() -> None:
    key = ContextBudgetKey(
        provider="deterministic",
        model="demo",
        role="final_answer",
        profile_version="context_budget.v1",
    )
    store = InMemoryContextBudgetCalibrationStore()

    update = record_context_overflow_calibration(
        context_config=AgentContextConfiguration(
            budget_profile=ContextBudgetProfile(max_tokens=8192)
        ),
        calibration_store=store,
        key=key,
        failed_estimated_tokens=9000,
        recovered_estimated_tokens=3500,
    )

    assert update is None
    assert store.get(key) is None


def test_record_context_overflow_calibration_persists_dynamic_default() -> None:
    key = ContextBudgetKey(
        provider="deterministic",
        model="demo",
        role="final_answer",
        profile_version="context_budget.v1",
    )
    store = InMemoryContextBudgetCalibrationStore()

    update = record_context_overflow_calibration(
        context_config=None,
        calibration_store=store,
        key=key,
        failed_estimated_tokens=9000,
        recovered_estimated_tokens=3500,
    )

    assert update is not None
    assert update.max_tokens == 7200
    assert update.reserved_output_tokens == 512
    assert update.update_ref == "calibration:deterministic:demo:final_answer:context_budget.v1"
    assert store.get(key) == update
