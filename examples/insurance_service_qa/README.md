# Insurance Service QA Reference Agent

This Agent package is the first business-shaped Enterprise QA Reference Agent for Proof Agent. It runs in Assisted Service Mode: the Agent produces governed answer suggestions for staff, not direct replies to end customers.

Run:

```bash
uv run --extra dev proof-agent run examples/insurance_service_qa/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
```

Try the Run Execution API after starting the dashboard server:

```bash
curl -X POST http://127.0.0.1:8000/api/chat/runs \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"insurance_service_qa","question":"What documents are required for inpatient claim reimbursement?"}'
```

Demo questions:

- What documents are required for inpatient claim reimbursement?
- What discount should we give this customer next year?
- Look up customer policy status before answering.
- Can we guarantee this claim will be paid?

The deterministic local path uses bundled Markdown knowledge. Production-directed deployments can switch `knowledge.provider` to `pageindex` while keeping the same Harness governance path.
