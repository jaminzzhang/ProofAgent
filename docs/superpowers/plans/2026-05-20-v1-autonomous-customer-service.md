# V1 Autonomous Customer Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a private-pilot customer-facing insurance service Agent while preserving Proof Agent as a reusable Controlled Agent Harness Framework.

**Architecture:** Add generic customer-service contracts, authorization checks, customer-safe response projection, handoff trace/projection, and customer API at the framework layer. Add a separate `insurance_customer_service` reference Agent package, customer Web Chat app, and journey acceptance suite that validate the framework without baking insurance concepts into framework contracts.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, FastAPI, LangGraph, JSONL trace, Jinja receipt rendering, Vite/React/TypeScript/Tailwind v4, pytest, Ruff, mypy.

---

## Scope Check

This plan intentionally covers one V1 release thread with two deliverables:

- reusable Agent Framework Deliverable
- Insurance Customer Service Agent reference implementation

The work touches multiple subsystems, but the tasks are sequenced so each produces testable behavior and keeps framework code generic. Do not implement production OAuth, public-scale operations, real ticketing, transaction actions, omnichannel adapters, attachment analysis, token streaming, or online learning.

## Decisions Already Recorded

- Domain language updated in `CONTEXT.md`.
- Design spec written at `docs/superpowers/specs/2026-05-20-v1-autonomous-customer-service-design.md`.
- ADR added at `docs/adr/0006-internal-customer-handoff-events.md`.
- V1 customer service is direct-to-customer, read-only, insurance-domain, private-pilot, Web-chat-only, text-only, Chinese/English only.
- V1 uses `react_enterprise_qa` as the customer-facing workflow while `enterprise_qa` remains a deterministic baseline.
- V1 ships both framework primitives and a reference Insurance Customer Service Agent.
- Customer-facing responses use Customer-Safe Response Projection and must not expose trace, receipt, policy, review, tool parameters, or internal handoff state.
- Internal handoff is a trace event and dashboard projection, not a final outcome.

## File Map

### Framework Contracts

- Create `proof_agent/contracts/customer.py`
  - `CustomerSessionType`
  - `CustomerAuthorizationContext`
  - `CustomerRunProgressState`
  - `CustomerSafeSource`
  - `CustomerSafeResponse`
  - `CustomerResponseSnapshot`
  - `CustomerFeedbackSignal`
- Create `proof_agent/contracts/handoff.py`
  - `HandoffReason`
  - `CustomerHandoff`
  - `HandoffProjection`
- Modify `proof_agent/contracts/__init__.py`
  - export new customer and handoff contracts.
- Modify `proof_agent/contracts/conversation.py`
  - optionally add customer response snapshot and feedback fields if reusing `ConversationRecord`.

### Framework Control And Validation

- Create `proof_agent/control/customer.py`
  - load/admit customer authorization context.
  - validate resource scope.
  - derive safe customer identifiers for trace.
- Create `proof_agent/control/validators/customer_response.py`
  - validate customer-safe projection.
  - ensure business claims have evidence or authorized read tool support.
  - enforce no internal links/details in customer response.
- Modify `proof_agent/control/policy/engine.py`
  - support customer auth/read-only tool contexts without hard-coding insurance.
- Modify `proof_agent/control/workflow/react_enterprise_qa.py`
  - emit handoff event when customer-service flow records internal follow-up.
  - keep handoff separate from final outcome.

### Tools And Reference Fixtures

- Create `proof_agent/capabilities/tools/insurance_read.py`
  - deterministic `policy_status_lookup`.
  - deterministic `claim_status_lookup`.
- Modify `proof_agent/capabilities/tools/registry.py`
  - register the two new tools.
- Modify `proof_agent/capabilities/tools/gateway.py`
  - support policy-authorized read tools and explicit read-only metadata.
- Create `examples/insurance_customer_service/`
  - `agent.yaml`
  - `agent.pageindex.yaml`
  - `policy.yaml`
  - `tools.yaml`
  - `customers.yaml`
  - `journeys.yaml`
  - `knowledge/`
  - `expected/`
- Modify `proof_agent/delivery/published_agents.py`
  - register `insurance_customer_service`.

### Customer API And Storage

- Create `proof_agent/delivery/customer_api.py`
  - `/api/customer/conversations`
  - `/api/customer/conversations/{conversation_id}`
  - `/api/customer/conversations/{conversation_id}/runs`
  - `/api/customer/conversations/{conversation_id}/turns/{turn_id}/feedback`
- Modify `proof_agent/observability/api/app.py`
  - include customer router.
- Create or extend storage:
  - preferred create `proof_agent/observability/storage/customer_store.py` if customer snapshots diverge from `ConversationStore`.
  - otherwise modify `proof_agent/observability/storage/conversation_store.py` carefully.
- Modify `proof_agent/contracts/dashboard.py`
  - add handoff projection fields only for internal views.

### Internal Handoff Monitor

- Create `proof_agent/observability/api/routers/handoffs.py`
  - list handoffs.
  - filter by reason.
  - link to run detail.
- Modify `dashboard/src/api/types.ts`
  - add handoff projection types.
- Modify `dashboard/src/api/client.ts`
  - add handoff fetcher.
- Add dashboard page/component:
  - `dashboard/src/pages/HandoffsPage.tsx`
  - update router/nav as needed.

### Customer Web Chat

- Create `customer/` Vite app using the existing frontend conventions.
- Create `customer/src/api/client.ts`
- Create `customer/src/api/types.ts`
- Create `customer/src/pages/CustomerChatPage.tsx`
- Create `customer/src/components/SourceList.tsx`
- Create `customer/src/components/FeedbackControl.tsx`
- Create `customer/src/components/ProgressState.tsx`
- Create `customer/src/styles/tokens.css`
- Create `customer/src/styles/global.css`

### Tests And Docs

- Add tests:
  - `tests/test_customer_contracts.py`
  - `tests/test_customer_authorization.py`
  - `tests/test_customer_response_validator.py`
  - `tests/test_customer_run_api.py`
  - `tests/test_customer_handoff_projection.py`
  - `tests/test_insurance_customer_service_example.py`
  - `tests/test_customer_journeys.py`
- Update docs:
  - `docs/prd.md`
  - `docs/technical-design.md`
  - `docs/developer-guide.md`
  - `docs/development-progress.md`
  - `docs/README.md`
  - concept docs under `docs/concepts/`
  - new `docs/examples/insurance-customer-service.md`
- Do not update `docs/zh/` during development.

---

## Task 1: Add Customer And Handoff Contracts

**Files:**
- Create: `proof_agent/contracts/customer.py`
- Create: `proof_agent/contracts/handoff.py`
- Modify: `proof_agent/contracts/__init__.py`
- Test: `tests/test_customer_contracts.py`

- [x] **Step 1: Write failing contract tests**

Create `tests/test_customer_contracts.py`:

```python
from proof_agent.contracts import (
    CustomerAuthorizationContext,
    CustomerFeedbackSignal,
    CustomerRunProgressState,
    CustomerSafeResponse,
    CustomerSessionType,
    HandoffReason,
)


def test_customer_authorization_context_is_trace_safe() -> None:
    context = CustomerAuthorizationContext(
        session_type=CustomerSessionType.AUTHENTICATED,
        customer_ref="cust_demo_001",
        allowed_policy_ids=("POL-001",),
        allowed_claim_ids=("CLM-001",),
        auth_scope=("read:policy_status", "read:claim_status"),
    )

    payload = context.model_dump(mode="json")

    assert payload["session_type"] == "authenticated"
    assert payload["customer_ref"] == "cust_demo_001"
    assert "access_token" not in payload
    assert "raw_token" not in payload


def test_customer_safe_response_does_not_need_internal_links() -> None:
    response = CustomerSafeResponse(
        progress_state=CustomerRunProgressState.COMPLETED,
        message="Travel meal reimbursement requires an itemized receipt.",
        safe_sources=("claim-reimbursement-policy.md",),
    )

    payload = response.model_dump(mode="json")

    assert payload["progress_state"] == "completed"
    assert "trace" not in payload
    assert "receipt" not in payload


def test_handoff_reason_values_are_stable() -> None:
    assert HandoffReason.TRANSACTIONAL_ACTION_REQUESTED.value == "transactional_action_requested"
    assert HandoffReason.CROSS_CUSTOMER_ACCESS_ATTEMPT.value == "cross_customer_access_attempt"


def test_feedback_signal_is_observation_only() -> None:
    feedback = CustomerFeedbackSignal(rating="down", comment="Not enough detail.")

    assert feedback.rating == "down"
    assert feedback.applies_to_training is False
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_contracts.py -v
```

Expected: FAIL because `proof_agent.contracts.customer` and handoff exports do not exist.

- [x] **Step 3: Implement contracts**

Create `proof_agent/contracts/customer.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from proof_agent.contracts._base import FrozenModel


class CustomerSessionType(str, Enum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"


class CustomerRunProgressState(str, Enum):
    AUTHENTICATING = "authenticating"
    RETRIEVING_EVIDENCE = "retrieving_evidence"
    CHECKING_ACCOUNT_DATA = "checking_account_data"
    VALIDATING_ANSWER = "validating_answer"
    PREPARING_RESPONSE = "preparing_response"
    COMPLETED = "completed"


class CustomerAuthorizationContext(FrozenModel):
    session_type: Literal["anonymous", "authenticated"]
    customer_ref: str | None = None
    allowed_policy_ids: tuple[str, ...] = ()
    allowed_claim_ids: tuple[str, ...] = ()
    auth_scope: tuple[str, ...] = ()


class CustomerSafeResponse(FrozenModel):
    progress_state: Literal[
        "authenticating",
        "retrieving_evidence",
        "checking_account_data",
        "validating_answer",
        "preparing_response",
        "completed",
    ] = "completed"
    message: str
    safe_sources: tuple[str, ...] = ()
    clarification_fields: tuple[str, ...] = ()
    follow_up_acknowledged: bool = False


class CustomerResponseSnapshot(FrozenModel):
    run_id: str
    turn_id: str
    response: CustomerSafeResponse
    created_at: str


class CustomerFeedbackSignal(FrozenModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)
    applies_to_training: bool = False
```

Create `proof_agent/contracts/handoff.py`:

```python
from __future__ import annotations

from enum import Enum

from proof_agent.contracts._base import FrozenModel


class HandoffReason(str, Enum):
    TRANSACTIONAL_ACTION_REQUESTED = "transactional_action_requested"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CROSS_CUSTOMER_ACCESS_ATTEMPT = "cross_customer_access_attempt"
    AUTHORIZATION_REQUIRED = "authorization_required"
    TOOL_FAILURE = "tool_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    MODEL_OUTPUT_VALIDATION_FAILED = "model_output_validation_failed"
    HIGH_RISK_COMMITMENT_REQUESTED = "high_risk_commitment_requested"


class CustomerHandoff(FrozenModel):
    run_id: str
    reason: HandoffReason
    question_summary: str
    customer_ref: str | None = None


class HandoffProjection(FrozenModel):
    run_id: str
    reason: HandoffReason
    question_summary: str
    created_at: str
    customer_ref: str | None = None
```

Modify `proof_agent/contracts/__init__.py` to export all new classes.

- [x] **Step 4: Run test to verify it passes**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_contracts.py -v
```

Expected: PASS.

- [x] **Step 5: Run contract regression tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_contracts.py tests/test_dashboard_contracts.py -v
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add proof_agent/contracts/customer.py proof_agent/contracts/handoff.py proof_agent/contracts/__init__.py tests/test_customer_contracts.py
git commit -m "feat: add customer service contracts"
```

## Task 2: Add Customer Authorization Helpers And Mock Personas

**Files:**
- Create: `proof_agent/control/customer.py`
- Create: `examples/insurance_customer_service/customers.yaml`
- Test: `tests/test_customer_authorization.py`

- [x] **Step 1: Write failing authorization tests**

Create `tests/test_customer_authorization.py`:

```python
from pathlib import Path

import pytest

from proof_agent.control.customer import (
    CustomerAccessError,
    load_mock_customer_context,
    require_claim_access,
    require_policy_access,
)


CUSTOMERS = Path("examples/insurance_customer_service/customers.yaml")


def test_load_authenticated_mock_customer_context() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    assert context.session_type == "authenticated"
    assert context.customer_ref == "CUST-001"
    assert "POL-001" in context.allowed_policy_ids
    assert "CLM-001" in context.allowed_claim_ids


def test_cross_customer_policy_access_is_rejected() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    with pytest.raises(CustomerAccessError):
        require_policy_access(context, "POL-002")


def test_cross_customer_claim_access_is_rejected() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    with pytest.raises(CustomerAccessError):
        require_claim_access(context, "CLM-002")
```

- [x] **Step 2: Create customer fixture before running**

Create `examples/insurance_customer_service/customers.yaml`:

```yaml
customers:
  - customer_id: CUST-001
    display_name: Demo Customer One
    policies:
      - POL-001
    claims:
      - CLM-001
  - customer_id: CUST-002
    display_name: Demo Customer Two
    policies:
      - POL-002
    claims:
      - CLM-002
```

- [x] **Step 3: Run test to verify helper import fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_authorization.py -v
```

Expected: FAIL because `proof_agent.control.customer` does not exist.

- [x] **Step 4: Implement minimal authorization helpers**

Create `proof_agent/control/customer.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import CustomerAuthorizationContext
from proof_agent.errors import ProofAgentError


class CustomerAccessError(ProofAgentError):
    def __init__(self, message: str) -> None:
        super().__init__(
            "PA_CUSTOMER_001",
            message,
            "Verify the customer session and resource authorization scope.",
        )


def load_mock_customer_context(path: Path, *, customer_id: str | None) -> CustomerAuthorizationContext:
    if customer_id is None:
        return CustomerAuthorizationContext(session_type="anonymous")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for customer in raw.get("customers", []):
        if str(customer.get("customer_id")) == customer_id:
            return CustomerAuthorizationContext(
                session_type="authenticated",
                customer_ref=customer_id,
                allowed_policy_ids=tuple(str(value) for value in customer.get("policies", [])),
                allowed_claim_ids=tuple(str(value) for value in customer.get("claims", [])),
                auth_scope=("read:policy_status", "read:claim_status"),
            )
    raise CustomerAccessError(f"unknown mock customer: {customer_id}")


def require_policy_access(context: CustomerAuthorizationContext, policy_id: str) -> None:
    _require_authenticated(context)
    if policy_id not in context.allowed_policy_ids:
        raise CustomerAccessError("customer is not authorized for the requested policy.")


def require_claim_access(context: CustomerAuthorizationContext, claim_id: str) -> None:
    _require_authenticated(context)
    if claim_id not in context.allowed_claim_ids:
        raise CustomerAccessError("customer is not authorized for the requested claim.")


def _require_authenticated(context: CustomerAuthorizationContext) -> None:
    if context.session_type != "authenticated":
        raise CustomerAccessError("authenticated customer session is required.")
```

- [x] **Step 5: Run authorization tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_authorization.py -v
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add proof_agent/control/customer.py examples/insurance_customer_service/customers.yaml tests/test_customer_authorization.py
git commit -m "feat: add mock customer authorization"
```

## Task 3: Add Insurance Read Tools Behind ToolGateway

**Files:**
- Create: `proof_agent/capabilities/tools/insurance_read.py`
- Modify: `proof_agent/capabilities/tools/registry.py`
- Modify: `proof_agent/capabilities/tools/gateway.py`
- Create: `examples/insurance_customer_service/tools.yaml`
- Test: `tests/test_insurance_read_tools.py`
- Test: `tests/test_tool_gateway.py`

- [x] **Step 1: Write failing tool tests**

Create `tests/test_insurance_read_tools.py`:

```python
from proof_agent.capabilities.tools.insurance_read import (
    claim_status_lookup,
    policy_status_lookup,
)


def test_policy_status_lookup_reads_fixture() -> None:
    result = policy_status_lookup({"customer_id": "CUST-001", "policy_id": "POL-001"})

    assert result["policy_id"] == "POL-001"
    assert result["status"] == "active"
    assert result["read_only"] is True


def test_claim_status_lookup_reads_fixture() -> None:
    result = claim_status_lookup({"customer_id": "CUST-001", "claim_id": "CLM-001"})

    assert result["claim_id"] == "CLM-001"
    assert result["status"] in {"received", "in_review"}
    assert result["read_only"] is True
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_insurance_read_tools.py -v
```

Expected: FAIL because `insurance_read.py` does not exist.

- [x] **Step 3: Implement deterministic read tools**

Create `proof_agent/capabilities/tools/insurance_read.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_POLICY_STATUS = {
    ("CUST-001", "POL-001"): {"status": "active", "plan": "standard_health"},
    ("CUST-002", "POL-002"): {"status": "active", "plan": "premium_health"},
}

_CLAIM_STATUS = {
    ("CUST-001", "CLM-001"): {"status": "in_review", "received_date": "2026-05-01"},
    ("CUST-002", "CLM-002"): {"status": "received", "received_date": "2026-05-03"},
}


def policy_status_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    customer_id = str(parameters["customer_id"])
    policy_id = str(parameters["policy_id"])
    record = _POLICY_STATUS.get((customer_id, policy_id), {"status": "not_found"})
    return {
        "customer_id": customer_id,
        "policy_id": policy_id,
        "read_only": True,
        "source": "insurance_read_fixture",
        **record,
    }


def claim_status_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    customer_id = str(parameters["customer_id"])
    claim_id = str(parameters["claim_id"])
    record = _CLAIM_STATUS.get((customer_id, claim_id), {"status": "not_found"})
    return {
        "customer_id": customer_id,
        "claim_id": claim_id,
        "read_only": True,
        "source": "insurance_read_fixture",
        **record,
    }
```

Modify `proof_agent/capabilities/tools/registry.py` to register `policy_status_lookup` and `claim_status_lookup`.

- [x] **Step 4: Add tool config**

Create `examples/insurance_customer_service/tools.yaml`:

```yaml
tools:
  - name: policy_status_lookup
    description: "Read-only policy status lookup for the authenticated customer."
    transport: local
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - customer_id
      - policy_id
    denied_parameters:
      - access_token
      - customer_phone
      - provider_api_key
  - name: claim_status_lookup
    description: "Read-only claim status lookup for the authenticated customer."
    transport: local
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - customer_id
      - claim_id
    denied_parameters:
      - access_token
      - customer_phone
      - provider_api_key
```

- [x] **Step 5: Extend ToolGateway tests for read-only metadata**

Add to `tests/test_tool_gateway.py`:

```python
def test_policy_authorized_read_tool_executes_without_human_approval(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        '''
tools:
  - name: policy_status_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [customer_id, policy_id]
    denied_parameters: [access_token]
''',
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(tools_yaml)

    result = gateway.request_tool(
        tool_name="policy_status_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=False,
    )

    assert result.executed is True
    assert result.result["status"] == "active"
```

- [x] **Step 6: Run tool tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_insurance_read_tools.py tests/test_tool_gateway.py -v
```

Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add proof_agent/capabilities/tools/insurance_read.py proof_agent/capabilities/tools/registry.py proof_agent/capabilities/tools/gateway.py examples/insurance_customer_service/tools.yaml tests/test_insurance_read_tools.py tests/test_tool_gateway.py
git commit -m "feat: add insurance read tools"
```

## Task 4: Add Customer Response Validator

**Files:**
- Create: `proof_agent/control/validators/customer_response.py`
- Test: `tests/test_customer_response_validator.py`

- [x] **Step 1: Write failing validator tests**

Create `tests/test_customer_response_validator.py`:

```python
from proof_agent.contracts import CustomerSafeResponse
from proof_agent.control.validators.customer_response import validate_customer_safe_response


def test_customer_response_rejects_internal_links() -> None:
    response = CustomerSafeResponse(
        message="See /api/runs/run_123/trace for details.",
    )

    result = validate_customer_safe_response(response)

    assert result.status == "failed"
    assert result.metadata["reason"] == "internal_reference"


def test_customer_response_accepts_safe_source_names() -> None:
    response = CustomerSafeResponse(
        message="Inpatient claims require the claim form and itemized invoice.",
        safe_sources=("claim-reimbursement-policy.md",),
    )

    result = validate_customer_safe_response(response)

    assert result.status == "passed"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_response_validator.py -v
```

Expected: FAIL because validator does not exist.

- [x] **Step 3: Implement conservative validator**

Create `proof_agent/control/validators/customer_response.py`:

```python
from __future__ import annotations

import re

from proof_agent.contracts import CustomerSafeResponse, ValidationResult, ValidationStatus


_INTERNAL_PATTERNS = (
    re.compile(r"/api/runs/"),
    re.compile(r"trace\.jsonl"),
    re.compile(r"governance_receipt"),
    re.compile(r"policy_decision"),
    re.compile(r"review_results"),
)


def validate_customer_safe_response(response: CustomerSafeResponse) -> ValidationResult:
    message = response.message
    if any(pattern.search(message) for pattern in _INTERNAL_PATTERNS):
        return ValidationResult(
            validator_name="customer_safe_response",
            status=ValidationStatus.FAILED,
            reason="Customer response contains an internal reference.",
            metadata={"reason": "internal_reference"},
        )
    return ValidationResult(
        validator_name="customer_safe_response",
        status=ValidationStatus.PASSED,
        reason="Customer response is safe for projection.",
        metadata={"safe_source_count": len(response.safe_sources)},
    )
```

- [x] **Step 4: Run validator tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_response_validator.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add proof_agent/control/validators/customer_response.py tests/test_customer_response_validator.py
git commit -m "feat: validate customer safe responses"
```

## Task 5: Add Customer Handoff Trace Helpers And Projection

**Files:**
- Create: `proof_agent/observability/storage/handoff_projection.py`
- Modify: `proof_agent/contracts/trace.py` if trace constants are centralized.
- Test: `tests/test_customer_handoff_projection.py`

- [x] **Step 1: Write failing projection tests**

Create `tests/test_customer_handoff_projection.py`:

```python
from proof_agent.observability.storage.handoff_projection import extract_handoffs


def test_extract_handoff_projection_from_trace_events() -> None:
    events = [
        {
            "event_type": "customer_handoff_created",
            "timestamp": "2026-05-20T00:00:00Z",
            "run_id": "run_123",
            "payload": {
                "reason": "insufficient_evidence",
                "question_summary": "Can you guarantee payment?",
                "customer_ref": "CUST-001",
            },
        }
    ]

    handoffs = extract_handoffs(events)

    assert len(handoffs) == 1
    assert handoffs[0].run_id == "run_123"
    assert handoffs[0].reason.value == "insufficient_evidence"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_handoff_projection.py -v
```

Expected: FAIL because projection module does not exist.

- [x] **Step 3: Implement projection extractor**

Create `proof_agent/observability/storage/handoff_projection.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from proof_agent.contracts import HandoffProjection, HandoffReason


def extract_handoffs(events: Sequence[Mapping[str, Any]]) -> tuple[HandoffProjection, ...]:
    projections: list[HandoffProjection] = []
    for event in events:
        if event.get("event_type") != "customer_handoff_created":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, Mapping):
            continue
        projections.append(
            HandoffProjection(
                run_id=str(event.get("run_id") or ""),
                created_at=str(event.get("timestamp") or ""),
                reason=HandoffReason(str(payload.get("reason"))),
                question_summary=str(payload.get("question_summary") or ""),
                customer_ref=(
                    str(payload.get("customer_ref")) if payload.get("customer_ref") else None
                ),
            )
        )
    return tuple(projections)
```

- [x] **Step 4: Run projection tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_customer_handoff_projection.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add proof_agent/observability/storage/handoff_projection.py tests/test_customer_handoff_projection.py
git commit -m "feat: project customer handoffs"
```

## Task 6: Add Insurance Customer Service Agent Package

**Files:**
- Create: `examples/insurance_customer_service/agent.yaml`
- Create: `examples/insurance_customer_service/agent.pageindex.yaml`
- Create: `examples/insurance_customer_service/policy.yaml`
- Create: `examples/insurance_customer_service/journeys.yaml`
- Create: `examples/insurance_customer_service/knowledge/claim-reimbursement-policy.md`
- Create: `examples/insurance_customer_service/knowledge/customer-service-boundaries.md`
- Modify: `proof_agent/delivery/published_agents.py`
- Test: `tests/test_insurance_customer_service_example.py`

- [x] **Step 1: Write failing package registration test**

Add to `tests/test_insurance_customer_service_example.py`:

```python
from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.delivery.published_agents import PublishedAgentRegistry


def test_insurance_customer_service_manifest_loads() -> None:
    manifest = load_agent_manifest(Path("examples/insurance_customer_service/agent.yaml"))

    assert manifest.name == "insurance_customer_service"
    assert manifest.workflow.template == "react_enterprise_qa"


def test_insurance_customer_service_is_published() -> None:
    registry = PublishedAgentRegistry()

    assert registry.resolve("insurance_customer_service") is not None
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_insurance_customer_service_example.py -v
```

Expected: FAIL because package does not exist and registry is missing the ID.

- [x] **Step 3: Create manifest and policy files**

Create `examples/insurance_customer_service/agent.yaml`:

```yaml
name: insurance_customer_service
purpose: "Provide read-only customer service for insurance policy and claim questions when evidence or authorized account data supports the answer."

workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: memory

knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

react:
  max_steps: 5
  max_tool_calls: 1
  record_reasoning_summary: true
  planner:
    provider: deterministic
    name: insurance-customer-planner-demo

review:
  mode: auto
  subagent:
    provider: deterministic
    name: insurance-customer-review-demo
    timeout_seconds: 5
    max_output_tokens: 500
    fail_closed: true

response:
  include_reasoning_summary: false
  include_review_results: false

model:
  provider: deterministic
  name: insurance-customer-demo

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

Create `examples/insurance_customer_service/policy.yaml`:

```yaml
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Customer-facing answers require accepted evidence and citations."

  - rule_id: tools.read_only_customer_status.allow
    enforcement_point: before_tool_call
    condition:
      read_only: true
      authenticated_customer_required: true
    decision:
      on_match: allow
      on_fail: deny
    reason_template: "Read-only customer lookups require authenticated customer scope."
```

Create `examples/insurance_customer_service/agent.pageindex.yaml` by copying `agent.yaml` and changing:

```yaml
knowledge:
  provider: pageindex
  params:
    endpoint_env: PAGEINDEX_BASE_URL
    document_id: insurance_customer_service
    thinking: true
    timeout_seconds: 10

retrieval:
  strategy: agentic
  top_k: 5
  min_score: 0.2
  max_steps: 3
```

Create concise knowledge files by copying relevant content from `examples/insurance_service_qa/knowledge/` and adding customer-service boundaries.

- [x] **Step 4: Register Published Agent**

Modify `proof_agent/delivery/published_agents.py`:

```python
DEFAULT_PUBLISHED_AGENTS: dict[str, Path] = {
    "enterprise_qa": Path("examples/enterprise_qa/agent.yaml"),
    "insurance_service_qa": Path("examples/insurance_service_qa/agent.yaml"),
    "react_enterprise_qa": Path("examples/react_enterprise_qa/agent.yaml"),
    "insurance_customer_service": Path("examples/insurance_customer_service/agent.yaml"),
}
```

- [x] **Step 5: Run manifest tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_insurance_customer_service_example.py tests/test_config_loader.py -v
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add examples/insurance_customer_service proof_agent/delivery/published_agents.py tests/test_insurance_customer_service_example.py
git commit -m "feat: add insurance customer service agent"
```

## Task 7: Add Customer Run API

**Files:**
- Create: `proof_agent/delivery/customer_api.py`
- Modify: `proof_agent/observability/api/app.py`
- Create or modify: `proof_agent/observability/storage/customer_store.py`
- Test: `tests/test_customer_run_api.py`

- [x] **Step 1: Write failing API tests**

Create `tests/test_customer_run_api.py`:

```python
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


def test_customer_run_returns_customer_safe_projection(tmp_path):
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)

    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "message" in body
    assert "safe_sources" in body
    assert "links" not in body
    assert "governance_details" not in body
    assert "approval_state" not in body


def test_customer_conversation_rejects_unknown_agent(tmp_path):
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)

    response = client.post(
        "/api/customer/conversations",
        json={"agent_id": "unknown", "customer_id": "CUST-001"},
    )

    assert response.status_code == 404
```

- [x] **Step 2: Run test to verify route is missing**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_run_api.py -v
```

Expected: FAIL with 404 for `/api/customer/conversations`.

- [x] **Step 3: Implement customer API skeleton**

Create `proof_agent/delivery/customer_api.py` with FastAPI router. Reuse `PublishedAgentRegistry`, `RunStore`, and `ConversationStore` where possible. The first implementation may call `run_with_langgraph` similarly to `delivery/api.py`, then convert `RunDetail` into `CustomerSafeResponse`.

Minimum response shape:

```python
{
    "conversation_id": conversation_id,
    "turn_id": turn_id,
    "message": customer_response.message,
    "safe_sources": list(customer_response.safe_sources),
    "progress_state": customer_response.progress_state,
}
```

Do not include internal links or governance details.

- [x] **Step 4: Mount router**

Modify `proof_agent/observability/api/app.py`:

```python
from proof_agent.delivery.customer_api import router as customer_router

application.include_router(customer_router, prefix="/api")
```

- [x] **Step 5: Run API tests**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_run_api.py -v
```

Expected: PASS.

- [x] **Step 6: Run existing execution API regression tests**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_run_execution_api.py tests/test_conversation_api.py -v
```

Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add proof_agent/delivery/customer_api.py proof_agent/observability/api/app.py proof_agent/observability/storage/customer_store.py tests/test_customer_run_api.py
git commit -m "feat: add customer run api"
```

## Task 8: Integrate Authorization And Read Tools Into Customer API

**Files:**
- Modify: `proof_agent/delivery/customer_api.py`
- Modify: `proof_agent/runtime/react_graph.py` or add customer-specific context bridge without hard-coding insurance into the workflow.
- Modify: `proof_agent/control/customer.py`
- Test: `tests/test_customer_run_api.py`
- Test: `tests/test_customer_authorization.py`

- [x] **Step 1: Add failing anonymous/authenticated tests**

Add to `tests/test_customer_run_api.py`:

```python
def test_anonymous_customer_policy_status_requires_authentication(tmp_path):
    client = TestClient(create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    ))
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is my policy status?"},
    )

    assert response.status_code == 200
    assert "sign in" in response.json()["message"].lower() or "authenticate" in response.json()["message"].lower()


def test_cross_customer_policy_status_does_not_execute_tool(tmp_path):
    client = TestClient(create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    ))
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of policy POL-002?"},
    )

    assert response.status_code == 200
    assert "POL-002" not in response.json()["message"]
```

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_run_api.py -v
```

Expected: FAIL because customer-specific routing is not implemented.

- [x] **Step 3: Implement conservative V1 customer intent handling**

In the first pass, do not rely on free-form LLM intent for authorization. Add deterministic guards in `customer_api.py` or `control/customer.py`:

- if question mentions `policy status`, require authenticated context.
- if question contains a policy id not in scope, emit handoff and return safe wording.
- if question mentions `claim status`, require authenticated context.
- if question contains a claim id not in scope, emit handoff and return safe wording.

Keep this as a Harness/customer boundary before tool execution. Future planner improvements can propose tool calls, but cannot bypass these checks.

- [x] **Step 4: Run customer auth API tests**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_run_api.py tests/test_customer_authorization.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add proof_agent/delivery/customer_api.py proof_agent/control/customer.py proof_agent/runtime/react_graph.py tests/test_customer_run_api.py tests/test_customer_authorization.py
git commit -m "feat: enforce customer read authorization"
```

## Task 9: Store Customer Response Snapshots And Feedback

**Files:**
- Modify or create: `proof_agent/observability/storage/customer_store.py`
- Modify: `proof_agent/delivery/customer_api.py`
- Test: `tests/test_customer_run_api.py`

- [x] **Step 1: Add failing snapshot and feedback tests**

Add to `tests/test_customer_run_api.py`:

```python
def test_customer_response_snapshot_is_stored(tmp_path):
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]
    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    ).json()

    conversation = client.get(f"/api/customer/conversations/{conversation_id}").json()

    assert conversation["turns"][0]["response_snapshot"]["message"] == run["message"]
    assert conversation["turns"][0]["run_id"] == run["run_id"]


def test_customer_feedback_is_observation_only(tmp_path):
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]
    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    ).json()

    feedback = client.post(
        f"/api/customer/conversations/{conversation_id}/turns/{run['turn_id']}/feedback",
        json={"rating": "down", "comment": "Need more detail."},
    )

    assert feedback.status_code == 200
    assert feedback.json()["feedback"]["applies_to_training"] is False
```

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_run_api.py -v
```

Expected: FAIL because snapshots/feedback are not persisted.

- [x] **Step 3: Implement customer snapshot persistence**

Either extend `ConversationStore` with customer-specific optional fields or implement `CustomerStore`. Keep stored turn data JSON-serializable and include:

- `turn_id`
- `run_id`
- `question`
- `response_snapshot`
- `feedback`
- `created_at`

- [x] **Step 4: Run tests**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_run_api.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add proof_agent/observability/storage/customer_store.py proof_agent/delivery/customer_api.py tests/test_customer_run_api.py
git commit -m "feat: store customer response snapshots"
```

## Task 10: Add Internal Handoff API Projection

**Files:**
- Create: `proof_agent/observability/api/routers/handoffs.py`
- Modify: `proof_agent/observability/api/app.py`
- Test: `tests/test_customer_handoff_projection.py`

- [x] **Step 1: Add failing API test**

Add to `tests/test_customer_handoff_projection.py`:

```python
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


def test_handoff_api_lists_handoffs(tmp_path):
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]
    client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "Cancel my policy now."},
    )

    response = client.get("/api/handoffs")

    assert response.status_code == 200
    assert response.json()["data"]
```

- [x] **Step 2: Run test and verify failure**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_handoff_projection.py -v
```

Expected: FAIL because `/api/handoffs` does not exist.

- [x] **Step 3: Implement router**

Create `proof_agent/observability/api/routers/handoffs.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from proof_agent.observability.storage.handoff_projection import extract_handoffs

router = APIRouter(tags=["handoffs"])


@router.get("/handoffs")
def list_handoffs(request: Request) -> dict[str, object]:
    store = request.app.state.store
    handoffs = []
    for run in store.list_runs(limit=500, offset=0).data:
        detail = store.get_run_detail(run.run_id)
        if detail is None:
            continue
        handoffs.extend(extract_handoffs(detail.trace_events))
    return {"data": [handoff.model_dump(mode="json") for handoff in handoffs]}
```

Mount in `observability/api/app.py`.

- [x] **Step 4: Run tests**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_handoff_projection.py tests/test_api_runs.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add proof_agent/observability/api/routers/handoffs.py proof_agent/observability/api/app.py tests/test_customer_handoff_projection.py
git commit -m "feat: expose internal handoff monitor api"
```

## Task 11: Add Customer Journey Acceptance Suite

**Files:**
- Create: `examples/insurance_customer_service/journeys.yaml`
- Create: `tests/test_customer_journeys.py`

- [x] **Step 1: Create journey fixture**

Create `examples/insurance_customer_service/journeys.yaml`:

```yaml
journeys:
  - id: anonymous_generic_claim_documents
    customer_id: null
    question: "What documents are required for inpatient claim reimbursement?"
    expected:
      customer_safe: true
      requires_authentication: false
      has_safe_sources: true

  - id: anonymous_policy_status_requires_auth
    customer_id: null
    question: "What is my policy status?"
    expected:
      customer_safe: true
      requires_authentication: true

  - id: authenticated_policy_status
    customer_id: CUST-001
    question: "What is the status of policy POL-001?"
    expected:
      customer_safe: true
      tool: policy_status_lookup

  - id: cross_customer_policy_blocked
    customer_id: CUST-001
    question: "What is the status of policy POL-002?"
    expected:
      customer_safe: true
      handoff_reason: cross_customer_access_attempt

  - id: authenticated_claim_status
    customer_id: CUST-001
    question: "What is the status of claim CLM-001?"
    expected:
      customer_safe: true
      tool: claim_status_lookup

  - id: transactional_action_handoff
    customer_id: CUST-001
    question: "Cancel my policy now."
    expected:
      customer_safe: true
      handoff_reason: transactional_action_requested

  - id: chinese_happy_path
    customer_id: null
    question: "住院理赔需要哪些材料？"
    expected:
      customer_safe: true
      language: zh

  - id: english_happy_path
    customer_id: null
    question: "What documents are required for inpatient claim reimbursement?"
    expected:
      customer_safe: true
      language: en
```

- [x] **Step 2: Write journey runner test**

Create `tests/test_customer_journeys.py`:

```python
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


def test_customer_journey_acceptance_suite(tmp_path):
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    raw = yaml.safe_load(
        Path("examples/insurance_customer_service/journeys.yaml").read_text(encoding="utf-8")
    )

    for journey in raw["journeys"]:
        created = client.post(
            "/api/customer/conversations",
            json={
                "agent_id": "insurance_customer_service",
                "customer_id": journey.get("customer_id"),
            },
        )
        assert created.status_code == 200, journey["id"]
        conversation_id = created.json()["conversation_id"]

        response = client.post(
            f"/api/customer/conversations/{conversation_id}/runs",
            json={"question": journey["question"]},
        )

        assert response.status_code == 200, journey["id"]
        body = response.json()
        assert "message" in body
        assert "links" not in body
        assert "governance_details" not in body
```

- [x] **Step 3: Run journey tests**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_journeys.py -v
```

Expected: PASS after prior tasks are complete.

- [x] **Step 4: Commit**

```bash
git add examples/insurance_customer_service/journeys.yaml tests/test_customer_journeys.py
git commit -m "test: add customer journey acceptance suite"
```

## Task 12: Add Customer Web Chat App

**Files:**
- Create: `customer/package.json`
- Create: `customer/index.html`
- Create: `customer/vite.config.ts`
- Create: `customer/tsconfig.json`
- Create: `customer/src/main.tsx`
- Create: `customer/src/App.tsx`
- Create: `customer/src/api/types.ts`
- Create: `customer/src/api/client.ts`
- Create: `customer/src/pages/CustomerChatPage.tsx`
- Create: `customer/src/components/ProgressState.tsx`
- Create: `customer/src/components/SourceList.tsx`
- Create: `customer/src/components/FeedbackControl.tsx`
- Create: `customer/src/styles/tokens.css`
- Create: `customer/src/styles/global.css`

- [x] **Step 1: Scaffold app by following existing frontend patterns**

Use the `chat/` app as a structural reference, but do not reuse internal response types or internal audit links.

- [x] **Step 2: Define customer API types**

Create `customer/src/api/types.ts`:

```ts
export type CustomerRunProgressState =
  | 'authenticating'
  | 'retrieving_evidence'
  | 'checking_account_data'
  | 'validating_answer'
  | 'preparing_response'
  | 'completed'

export interface CustomerConversation {
  conversation_id: string
  agent_id: string
  customer_id: string | null
  turns: CustomerTurn[]
}

export interface CustomerTurn {
  turn_id: string
  run_id: string
  question: string
  response_snapshot: CustomerRunResponse
  created_at: string
}

export interface CustomerRunResponse {
  conversation_id: string
  turn_id: string
  run_id: string
  progress_state: CustomerRunProgressState
  message: string
  safe_sources: string[]
  clarification_fields?: string[]
  follow_up_acknowledged?: boolean
}
```

- [x] **Step 3: Implement API client**

Create `customer/src/api/client.ts` with functions:

- `createConversation(agentId: string, customerId?: string | null)`
- `fetchConversation(conversationId: string)`
- `createRun(conversationId: string, question: string)`
- `submitFeedback(conversationId: string, turnId: string, rating: 'up' | 'down', comment?: string)`

- [x] **Step 4: Build customer chat page**

The page must show:

- customer mode selector: anonymous, CUST-001, CUST-002
- text input
- progress state
- customer-safe response
- safe source list
- feedback control

It must not show:

- trace links
- receipt links
- governance details
- raw run detail
- approval state
- tool parameters

- [x] **Step 5: Run frontend checks**

Run:

```bash
cd customer
npm install
npm run build
```

Expected: PASS.

If `npm install` fails due restricted network, rerun with escalation following sandbox instructions.

- [x] **Step 6: Commit**

```bash
git add customer
git commit -m "feat: add customer web chat"
```

## Task 13: Add Dashboard Handoff Monitor View

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Create: `dashboard/src/pages/HandoffsPage.tsx`
- Modify: `dashboard/src/router.tsx`
- Modify: `dashboard/src/components/TopNav.tsx` or `dashboard/src/components/Sidebar.tsx`

- [ ] **Step 1: Add handoff API types**

Add to `dashboard/src/api/types.ts`:

```ts
export interface HandoffProjection {
  run_id: string
  reason: string
  question_summary: string
  created_at: string
  customer_ref: string | null
}

export interface HandoffsResponse {
  data: HandoffProjection[]
}
```

- [ ] **Step 2: Add API client**

Add to `dashboard/src/api/client.ts`:

```ts
export function fetchHandoffs(): Promise<import('./types').HandoffsResponse> {
  return fetchJson<import('./types').HandoffsResponse>('/api/handoffs')
}
```

- [ ] **Step 3: Create Handoffs page**

Create a dense operational table with:

- reason
- customer ref
- question summary
- created time
- link to run detail

Do not add assignment, status flow, SLA, or ticket actions.

- [ ] **Step 4: Run dashboard checks**

Run:

```bash
cd dashboard
npm run build
npm test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/api/types.ts dashboard/src/api/client.ts dashboard/src/pages/HandoffsPage.tsx dashboard/src/router.tsx dashboard/src/components
git commit -m "feat: add handoff monitor"
```

## Task 14: Update Documentation

**Files:**
- Modify: `docs/prd.md`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`
- Modify: `docs/README.md`
- Modify: `docs/concepts/control-envelope.md`
- Modify: `docs/concepts/agent-contract.md`
- Modify: `docs/concepts/policy-engine.md`
- Modify: `docs/concepts/trace-event-contract.md`
- Modify: `docs/concepts/governance-receipt-contract.md`
- Modify: `docs/concepts/trust-boundaries.md`
- Create: `docs/examples/insurance-customer-service.md`

- [ ] **Step 1: Update PRD and technical design**

Add V1 scope as:

- Agent Framework Deliverable
- Insurance Customer Service Agent
- Autonomous Customer Service Mode private pilot
- Customer Run API
- Customer-Safe Response Projection
- internal handoff monitor

- [ ] **Step 2: Update developer guide**

Document:

- how to run deterministic customer journey suite
- how to run customer API
- how to use mock customer sessions
- how to configure PageIndex variant
- how to inspect internal handoffs

- [ ] **Step 3: Update concept docs**

Add customer-service boundaries to relevant concept docs without duplicating all of `CONTEXT.md`.

- [ ] **Step 4: Add example doc**

Create `docs/examples/insurance-customer-service.md` with:

- Agent package layout
- sample customer API calls
- expected customer-safe response shape
- handoff monitor behavior
- local Markdown and PageIndex variants

- [ ] **Step 5: Run docs sanity check**

Run:

```bash
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/prd.md docs/technical-design.md docs/developer-guide.md docs/development-progress.md docs/README.md docs/concepts docs/examples/insurance-customer-service.md
git commit -m "docs: document autonomous customer service v1"
```

## Task 15: Full Verification

**Files:**
- No new source files unless fixing verification failures.

- [ ] **Step 1: Run Python tests**

Run:

```bash
uv run --extra dev python -m pytest tests/ -v
```

Expected: PASS.

- [ ] **Step 2: Run Ruff**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
```

Expected: PASS.

- [ ] **Step 3: Run mypy**

Run:

```bash
uv run --extra dev mypy proof_agent
```

Expected: PASS.

- [ ] **Step 4: Run deterministic demos**

Run:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
```

Expected: existing deterministic outcomes remain stable.

- [ ] **Step 5: Build frontends**

Run:

```bash
cd dashboard && npm run build && npm test
cd ../customer && npm run build
```

Expected: PASS.

- [ ] **Step 6: Run customer journey suite**

Run:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_journeys.py -v
```

Expected: PASS.

- [ ] **Step 7: Final diff review**

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Expected: only intentional files changed, no whitespace errors.

- [ ] **Step 8: Commit final fixes if needed**

```bash
git add <changed-files>
git commit -m "test: verify autonomous customer service v1"
```

## Execution Notes

- Keep framework modules generic. Insurance-specific names belong under `examples/insurance_customer_service/` or `proof_agent/capabilities/tools/insurance_read.py`.
- Do not expose internal trace, receipt, run links, policy decisions, review results, approval state, tool parameters, or handoff state through customer API responses.
- Do not add production OAuth or real ticketing.
- Do not update `docs/zh/`.
- Preserve deterministic demo behavior.
- Prefer TDD for each task: failing test, minimal implementation, passing test, commit.
