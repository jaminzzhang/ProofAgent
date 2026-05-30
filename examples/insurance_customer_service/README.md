# Insurance Customer Service Agent

This is Proof Agent's canonical public Agent package. It demonstrates governed,
read-only insurance customer service with local Markdown knowledge, account-scoped
status tools, bounded memory, internal handoff events, and customer-safe response
projection.

Run a deterministic knowledge question:

```bash
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml \
  --question "What documents are required for inpatient claim reimbursement?"
```

Run the customer journey acceptance suite:

```bash
uv run --extra dashboard --extra dev python -m pytest tests/test_customer_journeys.py -v
```

See `docs/examples/insurance-customer-service.md` for the package layout, Customer
Run API examples, and the PageIndex-ready variant.
