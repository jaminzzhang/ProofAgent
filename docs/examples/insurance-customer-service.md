# Insurance Customer Service Agent

`examples/insurance_customer_service/` is the customer-facing public reference Agent. It uses React Enterprise QA Template V2 with Intent Resolution to demonstrate direct automatic replies for insurance customers while preserving Proof Agent as a reusable Controlled Agent Harness Framework.

## Package Layout

```text
examples/insurance_customer_service/
  agent.yaml              # React Enterprise QA V2 customer-service Agent
  policy.yaml             # answer, read-only tool, and memory rules
  tools.yaml              # declares policy_status_lookup and claim_status_lookup
  tools.py                # deterministic insurance read handlers
  customer_adapter.py     # insurance-specific Customer Run Adapter
  customers.yaml          # mock authenticated customer sessions
  journeys.yaml           # customer journey acceptance suite
  knowledge/              # customer-safe policy knowledge
  expected/               # acceptance fixture notes
```

This is a customer-facing public Agent package. The institution-facing specialist
example lives separately under `examples/institution_insurance_specialist/`.
Framework regression fixtures remain internal under
`proof_agent/evaluation/demo/fixtures/`.

The framework-owned Customer Run API stays generic. This package owns the insurance-specific adapter that detects policy/claim status requests, loads mock customer resources, performs resource disambiguation, calls the read-only local tool handlers, and returns a Customer-Safe Response Projection.

## Customer API

Create a conversation:

```bash
curl -X POST http://127.0.0.1:8000/api/customer/conversations \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"insurance_customer_service","customer_id":"CUST-001"}'
```

Run a customer question:

```bash
curl -X POST http://127.0.0.1:8000/api/customer/conversations/{conversation_id}/runs \
  -H 'Content-Type: application/json' \
  -d '{"question":"What documents are required for inpatient claim reimbursement?"}'
```

Expected customer-safe shape:

```json
{
  "conversation_id": "cust_conv_1234",
  "turn_id": "cust_turn_1234",
  "run_id": "run_1234",
  "progress_state": "completed",
  "message": "Inpatient claim reimbursement requires ...",
  "safe_sources": ["claim-reimbursement-policy.md"]
}
```

The customer response must not include trace links, receipt links, policy decisions, review results, approval state, tool parameters, or internal handoff state.

## Mock Customer Sessions

`customers.yaml` defines mock identities:

- `CUST-001` can read `POL-001` and `CLM-001`
- `CUST-002` can read `POL-002` and `CLM-002`
- anonymous sessions can ask generic knowledge questions but cannot read customer-specific policy or claim status

Cross-customer access attempts are blocked before read-only tool execution.

## Internal Handoffs

Customer handoff is internal only. Account-changing requests, such as cancellation requests, and cross-customer access attempts write `customer_handoff_created` trace events. Operators inspect them through:

```bash
curl http://127.0.0.1:8000/api/handoffs
```

Customers receive safe wording, not an `ESCALATED_TO_HUMAN` state.

## Verification

Run the customer journeys:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_journeys.py -v
```

Build the unified Chat app:

```bash
cd chat
npm install
npm run build
```
