from collections import Counter
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app
from published_agent_support import publish_agent_package

JOURNEYS_PATH = Path("examples/insurance_customer_service/journeys.yaml")
STRICT_RELEASE_GATE_ENV = "PROOF_AGENT_STRICT_CUSTOMER_RELEASE_GATES"


@dataclass(frozen=True)
class JourneyRun:
    body: dict[str, Any]
    new_handoff_reasons: tuple[str, ...]


def test_customer_journey_acceptance_suite(tmp_path: Path) -> None:
    client = _create_client(tmp_path)

    for journey in _load_journeys():
        result = _run_journey(client, journey)
        _assert_customer_safe(result.body, journey["id"])
        _assert_expected(result.body, journey, result.new_handoff_reasons)


def test_customer_journey_v1_release_gates(tmp_path: Path) -> None:
    client = _create_client(tmp_path)
    failures: list[str] = []

    for journey in _load_journeys():
        if not journey.get("release_gate"):
            continue
        result = _run_journey(client, journey)
        _assert_customer_safe(result.body, journey["id"])
        failures.extend(_release_gate_failures(result, journey))

    if not failures:
        return

    message = (
        "V1 customer release gates are not yet satisfied:\n"
        + "\n".join(f"- {failure}" for failure in failures)
    )
    if os.getenv(STRICT_RELEASE_GATE_ENV) == "1":
        pytest.fail(message)
    pytest.xfail(message)


def _create_client(tmp_path: Path) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_store=publish_agent_package(
            tmp_path,
            Path("examples/insurance_customer_service/agent.yaml"),
        ),
    )
    return TestClient(app)


def _load_journeys() -> list[dict[str, Any]]:
    raw = yaml.safe_load(JOURNEYS_PATH.read_text(encoding="utf-8"))
    journeys = raw["journeys"]
    assert isinstance(journeys, list)
    return journeys


def _run_journey(client: TestClient, journey: dict[str, Any]) -> JourneyRun:
    created = client.post(
        "/api/customer/conversations",
        json={
            "agent_id": "insurance_customer_service",
            "customer_id": journey.get("customer_id"),
        },
    )
    assert created.status_code == 200, journey["id"]
    conversation_id = created.json()["conversation_id"]
    before_handoffs = Counter(_handoff_reasons(client))

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": journey["question"]},
    )

    assert response.status_code == 200, journey["id"]
    after_handoffs = Counter(_handoff_reasons(client))
    new_handoffs = tuple((after_handoffs - before_handoffs).elements())
    return JourneyRun(body=response.json(), new_handoff_reasons=new_handoffs)


def _assert_customer_safe(body: dict[str, Any], journey_id: str) -> None:
    assert "message" in body, journey_id
    assert "links" not in body, journey_id
    assert "governance_details" not in body, journey_id
    assert "approval_state" not in body, journey_id
    assert "safe_sources" in body, journey_id


def _assert_expected(
    body: dict[str, Any],
    journey: dict[str, Any],
    new_handoff_reasons: tuple[str, ...],
) -> None:
    expected = journey["expected"]
    journey_id = journey["id"]
    if expected.get("requires_authentication"):
        message = str(body["message"]).lower()
        assert "sign in" in message or "authenticate" in message, journey_id
    if expected.get("has_safe_sources"):
        assert body["safe_sources"], journey_id
    if expected.get("tool"):
        assert expected["tool"] in body["safe_sources"], journey_id
    if expected.get("safe_source_label"):
        assert expected["safe_source_label"] in body["safe_sources"], journey_id
    if expected.get("handoff_reason"):
        assert expected["handoff_reason"] in new_handoff_reasons, journey_id


def _handoff_reasons(client: TestClient) -> tuple[str, ...]:
    response = client.get("/api/handoffs")
    assert response.status_code == 200
    return tuple(str(item["reason"]) for item in response.json()["data"])


def _release_gate_failures(result: JourneyRun, journey: dict[str, Any]) -> list[str]:
    expected = journey.get("v1_expected") or {}
    if not isinstance(expected, dict):
        return [_failure_prefix(journey) + ": v1_expected must be a mapping"]

    body = result.body
    message = str(body.get("message") or "")
    safe_sources = tuple(str(source) for source in body.get("safe_sources") or ())
    failures: list[str] = []

    if journey.get("release_gate") and not _has_run_id(body):
        failures.append(_failure_prefix(journey) + ": customer turn did not return run_id")

    for key, value in expected.items():
        if key == "full_harness_run":
            if value and not _has_run_id(body):
                failures.append(_failure_prefix(journey) + ": expected full Harness run")
        elif key == "requires_authentication":
            if value and not _looks_like_auth_prompt(message):
                failures.append(_failure_prefix(journey) + ": expected authentication prompt")
        elif key == "has_safe_sources":
            if value and not safe_sources:
                failures.append(_failure_prefix(journey) + ": expected safe sources")
        elif key == "handoff_reason":
            if str(value) not in result.new_handoff_reasons:
                failures.append(_failure_prefix(journey) + f": expected handoff {value!r}")
        elif key == "handoff":
            if value is False and result.new_handoff_reasons:
                failures.append(_failure_prefix(journey) + ": expected no new handoff")
            if value is True and not result.new_handoff_reasons:
                failures.append(_failure_prefix(journey) + ": expected a new handoff")
        elif key == "answer_type":
            if not _matches_answer_type(str(value), message, safe_sources):
                failures.append(_failure_prefix(journey) + f": expected answer_type {value!r}")
        elif key == "first_run_answer_type":
            if not _matches_answer_type(str(value), message, safe_sources):
                failures.append(_failure_prefix(journey) + f": expected first run {value!r}")
        elif key == "translation_mode":
            if str(value) == "evidence_bound_translation":
                if not _contains_cjk(message):
                    failures.append(_failure_prefix(journey) + ": expected Chinese response")
                if not safe_sources:
                    failures.append(_failure_prefix(journey) + ": expected translated sources")
        elif key == "source_label_type":
            if str(value) == "customer_safe_source_label" and _exposes_tool_source(safe_sources):
                failures.append(_failure_prefix(journey) + ": exposed internal tool source label")
        elif key == "reframe_from":
            if str(value) == "outcome_optimization_advice" and not _looks_like_reframe(message):
                failures.append(_failure_prefix(journey) + ": expected safe process reframe")
        elif key == "clarification_request":
            if value and not _matches_answer_type("clarification_request", message, safe_sources):
                failures.append(_failure_prefix(journey) + ": expected clarification request")
        elif key == "safe_resource_handles_only":
            if value and _exposes_raw_resource_detail(message):
                failures.append(_failure_prefix(journey) + ": exposed raw resource detail")
        elif key == "no_tool_execution_until_resolution":
            if value and _exposes_tool_source(safe_sources):
                failures.append(_failure_prefix(journey) + ": executed lookup before resolution")
        elif key == "requires_active_disambiguation_mapping":
            if value and not _matches_answer_type("clarification_request", message, safe_sources):
                failures.append(_failure_prefix(journey) + ": expected active mapping clarification")
            if value and _exposes_tool_source(safe_sources):
                failures.append(_failure_prefix(journey) + ": used lookup without active mapping")
        elif key == "denial_type":
            if str(value) == "customer_tool_authorization_denial" and not _looks_like_refusal(message):
                failures.append(_failure_prefix(journey) + ": expected authorization denial refusal")
        elif key == "retry_run":
            if str(value) == "new_governed_run" and not _has_run_id(body):
                failures.append(_failure_prefix(journey) + ": expected retry as new governed run")
        elif key == "linked_failure_series":
            if value and "failure_series_id" not in body:
                failures.append(_failure_prefix(journey) + ": expected linked failure series")
        elif key == "forbidden":
            failures.extend(_forbidden_failures(journey, message, safe_sources, value))
        else:
            failures.append(_failure_prefix(journey) + f": unsupported v1_expected key {key!r}")

    return failures


def _failure_prefix(journey: dict[str, Any]) -> str:
    return f"{journey['id']}[{journey.get('release_gate')}]"


def _has_run_id(body: dict[str, Any]) -> bool:
    return bool(str(body.get("run_id") or "").strip())


def _looks_like_auth_prompt(message: str) -> bool:
    normalized = message.lower()
    return "sign in" in normalized or "authenticate" in normalized


def _matches_answer_type(answer_type: str, message: str, safe_sources: tuple[str, ...]) -> bool:
    normalized = message.lower()
    if answer_type == "customer_safe_refusal":
        return _looks_like_refusal(message)
    if answer_type == "clarification_request":
        return _looks_like_auth_prompt(message) or (
            "please" in normalized
            and any(term in normalized for term in ("provide", "choose", "select", "which"))
        )
    if answer_type == "insurance_product_term_interpretation":
        return bool(safe_sources) and any(
            term in normalized or term in message
            for term in ("deductible", "waiting period", "exclusion", "coverage", "免赔", "等待期")
        )
    if answer_type == "insurance_service_process_guidance":
        return bool(safe_sources) and any(
            term in normalized or term in message
            for term in ("document", "submit", "claim", "review", "process", "材料", "理赔")
        )
    if answer_type == "temporary_tool_failure":
        return any(
            term in normalized
            for term in ("temporar", "try again later", "timeout", "unavailable")
        )
    return False


def _looks_like_refusal(message: str) -> bool:
    normalized = message.lower()
    return any(
        term in normalized
        for term in (
            "can't",
            "cannot",
            "unable",
            "not able",
            "don't have enough evidence",
            "couldn't find",
            "outside",
        )
    )


def _looks_like_reframe(message: str) -> bool:
    normalized = message.lower()
    refuses_outcome = any(term in normalized for term in ("can't", "cannot", "unable"))
    mentions_outcome = any(term in normalized for term in ("approval", "odds", "likelihood"))
    gives_process = any(term in normalized for term in ("document", "submit", "process", "review"))
    return refuses_outcome and mentions_outcome and gives_process


def _contains_cjk(message: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", message))


def _exposes_tool_source(safe_sources: tuple[str, ...]) -> bool:
    return any(source.endswith("_lookup") for source in safe_sources)


def _exposes_raw_resource_detail(message: str) -> bool:
    return bool(re.search(r"\bCUST-\d+\b|\bcustomer_id\b|\bpolicy_id\b|\bclaim_id\b", message))


def _forbidden_failures(
    journey: dict[str, Any],
    message: str,
    safe_sources: tuple[str, ...],
    value: Any,
) -> list[str]:
    if not isinstance(value, list):
        return [_failure_prefix(journey) + ": forbidden must be a list"]

    failures: list[str] = []
    normalized = message.lower()
    source_text = " ".join(safe_sources).lower()
    for category in value:
        if _contains_forbidden(str(category), normalized, source_text):
            failures.append(_failure_prefix(journey) + f": contained forbidden {category!r}")
    return failures


def _contains_forbidden(category: str, message: str, source_text: str) -> bool:
    patterns = {
        "personalized_coverage_decision": (
            "your claim is covered",
            "you are covered",
            "your policy covers this",
        ),
        "personalized_eligibility_decision": ("you are eligible", "your claim is eligible"),
        "payment_guarantee": ("guaranteed payment", "will be paid", "payment is guaranteed"),
        "coverage_guarantee": ("coverage is guaranteed", "will be covered"),
        "claim_outcome_prediction": ("will be approved", "likely approved"),
        "approval_likelihood_assessment": ("approval odds are", "likely to be approved"),
        "rule_evasion_advice": ("avoid mentioning", "work around the rule"),
        "payable_amount_commitment": ("you will receive $", "payable amount is"),
        "payment_timing_guarantee": ("payment will arrive", "will be paid within"),
        "guaranteed_sla": ("guaranteed within", "sla is guaranteed"),
        "guaranteed_claim_outcome": ("claim will be approved", "claim is guaranteed"),
        "transaction_execution": ("policy has been cancelled", "claim has been submitted"),
        "bulk_status_listing": ("all claim statuses", "all policy statuses"),
        "raw_customer_id": ("cust-", "customer_id"),
        "claim_amount_or_coverage_detail": ("covered amount", "coverage amount"),
        "raw_policy_rule": ("policy_rule_id",),
        "raw_tool_arguments": ("customer_id", "policy_id", "claim_id"),
        "gateway_error_detail": ("traceback", "gateway error", "stack trace"),
        "reused_prior_authorization": ("reused authorization",),
        "direct_old_argument_replay": ("replayed prior arguments",),
        "guaranteed_recovery": ("will work next time",),
        "stale_mapping_reuse": ("using the earlier option",),
        "transcript_guessing": ("i assume you mean",),
        "case_memory_resolution": ("based on memory",),
    }
    needles = patterns.get(category, ())
    return any(needle in message or needle in source_text for needle in needles)
