# Institution Insurance Specialist Agent

`examples/institution_insurance_specialist/` is the staff-facing insurance
specialist reference Agent. It demonstrates Assisted Service Mode for internal
institution staff while staying decoupled from the customer-facing
`examples/insurance_customer_service/` package.

## Package Layout

```text
examples/institution_insurance_specialist/
  agent.yaml              # ReAct specialist Agent with node Prompt configuration
  policy.yaml             # evidence, read-only tool, transaction-deny, memory rules
  tools.yaml              # declares institution_* read-only lookup tools
  tools.py                # deterministic institution read handlers
  knowledge/              # specialist-facing insurance knowledge
```

The package intentionally does not include:

- `customer_adapter.py`
- `customers.yaml`
- `journeys.yaml`

Those files belong to customer-facing service packages. Institution specialist
runs use the ordinary governed Harness entry points and produce staff-facing
answers.

## Scope

The Workflow is generic for insurance institution specialists. Short-term
accident insurance is represented by package-level knowledge routing metadata
and read-only institution tool fixtures, not by a dedicated Harness topology.

The Agent can answer public insurance knowledge questions without institution
scope. Scoped report, policy, claim, customer, and agent lookups require
institution staff scope and Tool Gateway authorization.

## Tools

The package declares read-only institution tools:

- `institution_report_lookup`
- `institution_policy_lookup`
- `institution_claim_lookup`
- `institution_customer_profile_lookup`
- `institution_agent_profile_lookup`

These tools are deterministic fixtures for local development. They do not change
business state.

## Workflow Configuration

The package uses `workflow.template: react_enterprise_qa` with `workflow.nodes[]`
Prompt addenda for:

- Dynamic Insurance Business Subplan planning.
- public knowledge versus scoped business-record distinction.
- Insurance Source Authority Order.
- read-only institution tool review.
- Institution Specialist Case Memory.
- Institution Specialist Response Projection with optional External Wording
  Draft.

Node Prompt configuration supplies business context only. It does not replace
Harness-owned control prompts, topology, PolicyEngine, Tool Gateway, validators,
trace, or receipt behavior.

## Verification

Load and verify the package:

```bash
uv run --extra dev python -m pytest tests/test_institution_insurance_specialist_example.py -v
```

Run a local question:

```bash
uv run --extra dev proof-agent run examples/institution_insurance_specialist/agent.yaml \
  --question "For short-term accident claims, what should a branch specialist explain to an agent when the claim is still pending?"
```
