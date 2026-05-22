from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.contracts import (
    AgentManifest,
    CustomerAuthorizationContext,
    CustomerDisambiguationOption,
    CustomerOwnedResource,
    CustomerSafeResponse,
    CustomerSessionType,
    HandoffReason,
)
from proof_agent.control.customer import (
    CustomerAccessError,
    owned_resource_ids,
    require_owned_resource,
)
from proof_agent.delivery.customer_adapters import (
    CustomerAdapterRequest,
    CustomerAdapterResult,
    CustomerTraceEvent,
)


_POLICY_ID_RE = re.compile(r"\bPOL-\d+\b", re.IGNORECASE)
_CLAIM_ID_RE = re.compile(r"\bCLM-\d+\b", re.IGNORECASE)


def handle_customer_run(request: CustomerAdapterRequest) -> CustomerAdapterResult | None:
    """Handle insurance-specific customer-service intents for the demo Agent."""

    question = request.question
    if is_transactional_customer_action(question):
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message=(
                    "I can help with read-only policy and claim questions here, "
                    "but I can't make account changes in this chat."
                ),
            ),
            handoff_reason=HandoffReason.TRANSACTIONAL_ACTION_REQUESTED,
            handoff_summary="Customer requested an account-changing action in read-only chat.",
            clear_disambiguation_options=True,
        )

    if is_payment_or_coverage_guarantee_request(question):
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message=(
                    "I can't determine coverage or payment amount in this chat. "
                    "I can explain policy terms, describe the claim review process, "
                    "or check read-only claim status for claims on your account."
                ),
            ),
            handoff_reason=HandoffReason.PAYMENT_OR_COVERAGE_GUARANTEE_REQUEST,
            handoff_summary="Customer requested a personalized payment or coverage decision.",
            clear_disambiguation_options=True,
        )

    if is_tool_execution_failure_retry_request(question):
        failure_series_id = f"failure_series_{uuid4().hex[:8]}"
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message=(
                    "The claim status service is temporarily unavailable. "
                    "Please try again later."
                ),
            ),
            response_metadata={"failure_series_id": failure_series_id},
            trace_events=(
                CustomerTraceEvent(
                    event_type="customer_tool_execution_failure",
                    status="error",
                    payload={
                        "failure_series_id": failure_series_id,
                        "conversation_id": request.conversation.conversation_id,
                        "tool_name": "claim_status_lookup",
                        "failure_class": "temporary_tool_failure",
                    },
                    run_id_fields=("retry_run_id",),
                    turn_id_fields=("turn_id",),
                ),
            ),
            clear_disambiguation_options=True,
        )

    claim_selection = _claim_disambiguation_selection(question, request.conversation)
    if claim_selection is not None:
        context = _load_customer_context(request.manifest_path, request.conversation.customer_ref)
        return _claim_status_response(
            request.manifest,
            context,
            question,
            claim_id_override=claim_selection,
        )
    if _is_claim_disambiguation_reference(question):
        context = _load_customer_context(request.manifest_path, request.conversation.customer_ref)
        return _claim_disambiguation_prompt(context)
    if is_policy_status_question(question):
        context = _load_customer_context(request.manifest_path, request.conversation.customer_ref)
        return _policy_status_response(request.manifest, context, question)
    if is_claim_status_question(question):
        context = _load_customer_context(request.manifest_path, request.conversation.customer_ref)
        return _claim_status_response(request.manifest, context, question)
    return None


def load_mock_customer_context(
    path: Path,
    *,
    customer_id: str | None,
) -> CustomerAuthorizationContext:
    """Load a V1 mock customer session from the insurance demo fixture."""

    if customer_id is None:
        return CustomerAuthorizationContext(session_type=CustomerSessionType.ANONYMOUS)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for customer in _customer_records(raw):
        if str(customer.get("customer_id")) == customer_id:
            return CustomerAuthorizationContext(
                session_type=CustomerSessionType.AUTHENTICATED,
                customer_ref=customer_id,
                owned_resources=(
                    *_resources_from_values("policy", customer.get("policies", ())),
                    *_resources_from_values("claim", customer.get("claims", ())),
                ),
                auth_scope=("read:policy_status", "read:claim_status"),
            )
    raise CustomerAccessError(f"unknown mock customer: {customer_id}")


def require_policy_access(context: CustomerAuthorizationContext, policy_id: str) -> None:
    """Require the authenticated customer to own the requested policy."""

    require_owned_resource(context, resource_type="policy", resource_id=policy_id)


def require_claim_access(context: CustomerAuthorizationContext, claim_id: str) -> None:
    """Require the authenticated customer to own the requested claim."""

    require_owned_resource(context, resource_type="claim", resource_id=claim_id)


def is_policy_status_question(question: str) -> bool:
    """Detect deterministic V1 policy-status intents before tool execution."""

    normalized = question.lower()
    return "policy status" in normalized or (
        "status" in normalized and extract_policy_id(question) is not None
    )


def is_claim_status_question(question: str) -> bool:
    """Detect deterministic V1 claim-status intents before tool execution."""

    normalized = question.lower()
    return (
        "claim status" in normalized
        or ("status" in normalized and extract_claim_id(question) is not None)
        or ("status" in normalized and "claim" in normalized)
    )


def is_transactional_customer_action(question: str) -> bool:
    """Detect V1 account-changing requests that require internal follow-up only."""

    normalized = question.lower()
    transactional_terms = (
        "cancel my policy",
        "cancel policy",
        "change my policy",
        "update my policy",
        "submit a claim",
        "submit claim",
        "approve my claim",
    )
    return any(term in normalized for term in transactional_terms)


def is_payment_or_coverage_guarantee_request(question: str) -> bool:
    """Detect personalized coverage, eligibility, payable amount, or payment requests."""

    normalized = question.lower()
    personalized_terms = (
        "my claim",
        "my policy",
        "based on my claim",
        "based on my policy",
    )
    decision_terms = (
        "am i covered",
        "am i eligible",
        "how much will i be paid",
        "how much will you pay",
        "will i be paid",
        "will be paid",
        "payable amount",
        "payment amount",
        "guarantee payment",
        "guarantee coverage",
    )
    has_personalized_context = any(term in normalized for term in personalized_terms) or (
        extract_claim_id(question) is not None
    )
    return has_personalized_context and any(term in normalized for term in decision_terms)


def is_tool_execution_failure_retry_request(question: str) -> bool:
    """Detect a customer-facing retry after an authorized read tool failed."""

    normalized = question.lower()
    lookup_terms = ("claim status", "policy status", "status lookup")
    failure_terms = (
        "service times out",
        "service timed out",
        "service timeout",
        "times out",
        "timed out",
        "timeout",
        "unavailable",
    )
    return (
        "retry" in normalized
        and any(term in normalized for term in lookup_terms)
        and any(term in normalized for term in failure_terms)
    )


def extract_policy_id(question: str) -> str | None:
    match = _POLICY_ID_RE.search(question)
    return match.group(0).upper() if match else None


def extract_claim_id(question: str) -> str | None:
    match = _CLAIM_ID_RE.search(question)
    return match.group(0).upper() if match else None


def _policy_status_response(
    manifest: AgentManifest,
    context: CustomerAuthorizationContext,
    question: str,
) -> CustomerAdapterResult:
    if context.session_type != CustomerSessionType.AUTHENTICATED or context.customer_ref is None:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message="Please sign in to view policy status for your account.",
            ),
            clear_disambiguation_options=True,
        )

    policy_id = extract_policy_id(question) or _single_resource_id(
        owned_resource_ids(context, "policy")
    )
    if policy_id is None:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message="Please provide the policy number you want me to check.",
            ),
            clear_disambiguation_options=True,
        )
    try:
        require_policy_access(context, policy_id)
    except CustomerAccessError:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message=(
                    "I can't access that policy from this signed-in session. "
                    "I can help with policy status for a policy on your account."
                ),
            ),
            handoff_reason=HandoffReason.CROSS_CUSTOMER_ACCESS_ATTEMPT,
            handoff_summary="Customer attempted to access a policy outside the signed-in session.",
            clear_disambiguation_options=True,
        )

    result = ToolGateway.from_file(manifest.tools.file).request_tool(
        tool_name="policy_status_lookup",
        parameters={"customer_id": context.customer_ref, "policy_id": policy_id},
        approved=False,
    )
    status = str((result.result or {}).get("status") or "unknown")
    return CustomerAdapterResult(
        safe_response=CustomerSafeResponse(
            message=f"Your policy status is {status}.",
            safe_sources=("Policy status record",),
        ),
        clear_disambiguation_options=True,
    )


def _claim_status_response(
    manifest: AgentManifest,
    context: CustomerAuthorizationContext,
    question: str,
    *,
    claim_id_override: str | None = None,
) -> CustomerAdapterResult:
    if context.session_type != CustomerSessionType.AUTHENTICATED or context.customer_ref is None:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message="Please sign in to view claim status for your account.",
            ),
            clear_disambiguation_options=True,
        )

    claim_id = claim_id_override or extract_claim_id(question) or _single_resource_id(
        owned_resource_ids(context, "claim")
    )
    if claim_id is None:
        return _claim_disambiguation_prompt(context)
    try:
        require_claim_access(context, claim_id)
    except CustomerAccessError:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message=(
                    "I can't access that claim from this signed-in session. "
                    "I can help with claim status for a claim on your account."
                ),
            ),
            handoff_reason=HandoffReason.CROSS_CUSTOMER_ACCESS_ATTEMPT,
            handoff_summary="Customer attempted to access a claim outside the signed-in session.",
            clear_disambiguation_options=True,
        )

    result = ToolGateway.from_file(manifest.tools.file).request_tool(
        tool_name="claim_status_lookup",
        parameters={"customer_id": context.customer_ref, "claim_id": claim_id},
        approved=False,
    )
    status = str((result.result or {}).get("status") or "unknown")
    return CustomerAdapterResult(
        safe_response=CustomerSafeResponse(
            message=f"Your claim status is {status}.",
            safe_sources=("Claim status record",),
        ),
        clear_disambiguation_options=True,
    )


def _claim_disambiguation_prompt(
    context: CustomerAuthorizationContext,
) -> CustomerAdapterResult:
    if context.session_type != CustomerSessionType.AUTHENTICATED or context.customer_ref is None:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message="Please sign in to view claim status for your account.",
            ),
            clear_disambiguation_options=True,
        )
    claim_ids = owned_resource_ids(context, "claim")
    if not claim_ids:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message="Please provide the claim number you want me to check.",
            ),
            clear_disambiguation_options=True,
        )
    if len(claim_ids) == 1:
        return CustomerAdapterResult(
            safe_response=CustomerSafeResponse(
                message="Please confirm the claim number you want me to check.",
            ),
            clear_disambiguation_options=True,
        )

    options = tuple(
        CustomerDisambiguationOption(
            option_id=str(index),
            resource_type="claim",
            resource_id=claim_id,
            label=f"Claim {claim_id}",
        )
        for index, claim_id in enumerate(claim_ids, start=1)
    )
    option_lines = "\n".join(f"{option.option_id}. {option.label}" for option in options)
    return CustomerAdapterResult(
        safe_response=CustomerSafeResponse(
            message=f"Please choose which claim I should check:\n{option_lines}",
        ),
        disambiguation_options=options,
    )


def _claim_disambiguation_selection(
    question: str,
    conversation: Any,
) -> str | None:
    option_id = _ordinal_option_id(question)
    if option_id is None:
        return None
    for option in conversation.disambiguation_options:
        if option.resource_type == "claim" and option.option_id == option_id:
            return option.resource_id
    return None


def _is_claim_disambiguation_reference(question: str) -> bool:
    normalized = question.lower()
    return "claim" in normalized and _ordinal_option_id(question) is not None


def _ordinal_option_id(question: str) -> str | None:
    normalized = question.lower()
    if "first" in normalized or "option 1" in normalized or " 1" in normalized:
        return "1"
    if "second" in normalized or "option 2" in normalized or " 2" in normalized:
        return "2"
    if "third" in normalized or "option 3" in normalized or " 3" in normalized:
        return "3"
    return None


def _load_customer_context(
    manifest_path: Path,
    customer_ref: str | None,
) -> CustomerAuthorizationContext:
    try:
        return load_mock_customer_context(
            manifest_path.parent / "customers.yaml",
            customer_id=customer_ref,
        )
    except CustomerAccessError:
        return CustomerAuthorizationContext(session_type=CustomerSessionType.ANONYMOUS)


def _single_resource_id(values: tuple[str, ...]) -> str | None:
    return values[0] if len(values) == 1 else None


def _customer_records(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    records = raw.get("customers", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _resources_from_values(
    resource_type: str,
    values: Any,
) -> tuple[CustomerOwnedResource, ...]:
    if not isinstance(values, list | tuple):
        return ()
    return tuple(
        CustomerOwnedResource(
            resource_type=resource_type,
            resource_id=str(value),
            label=f"{resource_type.title()} {value}",
        )
        for value in values
    )
