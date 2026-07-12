# Governance Receipt

Governance Receipt is the human-readable proof that an Agent run was controlled.

JSONL trace is the audit source of truth. Governance Receipt is the summary an AI Agent owner, architect, security reviewer, or business sponsor can read without inspecting raw events.

The normative v1 requirements live in [Governance Receipt Contract](../concepts/governance-receipt-contract.md). This page shows an example rendering.

## Example

```markdown
# Governance Receipt

Run: 2026-05-09T10:30:00Z
Agent: enterprise_qa
Question: What is the reimbursement rule for travel meals?
Final outcome: ANSWERED_WITH_CITATIONS

## Policy Decisions

| Point | Decision | Reason |
| --- | --- | --- |
| before_retrieval | allow | Enterprise QA requires retrieval before answering. |
| before_answer | allow | Evidence threshold met with 2 cited chunks. |
| before_tool_call | not_applicable | No tool was needed. |
| before_memory_write | allow | Session summary contains no sensitive fields. |
| before_model_call | allow | Deterministic demo provider is allowed for this run. |

## Evidence

| Source | Status |
| --- | --- |
| travel_policy.md#meals | accepted |
| reimbursement_faq.md#limits | accepted |

## Tools

No MCP tool was called.

## Model Usage

| Field | Value |
| --- | --- |
| Provider | deterministic |
| Model | demo |
| Cost Class | local |
| Estimated Tokens | 0 |

## Audit Artifacts

- Trace: `runs/2026-05-09-103000/trace.jsonl`
- Receipt: `runs/2026-05-09-103000/governance_receipt.md`
```

## Required Properties

- It must be generated for answered, refused, escalated, and failed runs.
- It must include policy decisions and reasons.
- It must include evidence status.
- It must include governed read-only tool authorization and result status when tools are involved. Historical receipts may preserve inert approval facts, but the initial release exposes no approval workflow.
- It must include model usage or model error summary when model calls occur.
- It must include trace artifact path.
- It must not print secrets, API keys, raw credentials, or unnecessary personal data.
- It must follow the required outcome and section contract.

## Why It Matters

Agent leaders do not only need a working demo. They need proof that the system can be explained after it runs. The receipt turns the Harness from invisible architecture into visible enterprise trust.
