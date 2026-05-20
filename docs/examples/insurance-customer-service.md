# Insurance Customer Service Agent

`examples/insurance_customer_service/` is the V1 customer-facing reference Agent. It demonstrates direct automatic replies for insurance customers while preserving Proof Agent as a reusable Controlled Agent Harness Framework.

## Package Layout

```text
examples/insurance_customer_service/
  agent.yaml              # local Markdown customer-service Agent
  agent.pageindex.yaml    # PageIndex-ready variant
  policy.yaml             # answer, read-only tool, and memory rules
  tools.yaml              # policy_status_lookup and claim_status_lookup
  customers.yaml          # mock authenticated customer sessions
  journeys.yaml           # customer journey acceptance suite
  knowledge/              # customer-safe policy knowledge
  expected/               # acceptance fixture notes
```

`insurance_service_qa` remains the staff-facing baseline package. `insurance_customer_service` is the terminal-customer package.

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

`customers.yaml` defines V1 mock identities:

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

## PageIndex Variant

Use `agent.pageindex.yaml` when the knowledge source is PageIndex:

```yaml
knowledge:
  provider: pageindex
  params:
    endpoint_env: PAGEINDEX_BASE_URL
    document_id: insurance_customer_service
    thinking: true
    timeout_seconds: 10
```

The same Control Envelope still applies: retrieval plan/step events, evidence evaluation, customer-safe projection, and trace persistence remain framework-owned.

## Verification

Run the customer journeys:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_journeys.py -v
```

Build the customer app:

```bash
cd customer
npm install
npm run build
```
