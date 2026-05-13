# Insurance Service QA Reference Agent

The Insurance Service QA Reference Agent is the first business-shaped package built on the Enterprise QA template. It targets Assisted Service Mode for insurance and financial service staff: the Agent prepares governed answer suggestions, but staff remain responsible for review before sending anything to an end customer.

## Agent Package

```text
examples/insurance_service_qa/
  agent.yaml
  policy.yaml
  tools.yaml
  questions.yaml
  knowledge/
  expected/
```

The package uses the same Harness semantics as `examples/enterprise_qa/`: evidence retrieval is mandatory, unsupported questions refuse, and customer policy status lookup requires approval.

## Local Run

```bash
uv run --extra dev proof-agent run examples/insurance_service_qa/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
```

Expected governed outcomes:

| Scenario | Question | Expected behavior |
| --- | --- | --- |
| Supported | "What documents are required for inpatient claim reimbursement?" | Answer with accepted evidence and receipt |
| Unsupported | "What discount should we give this customer next year?" | Refuse because evidence is unavailable |
| Tool-required | "Look up customer policy status before answering." | Wait for approval before lookup |

## Execution API

The package is registered as a default Published Agent:

```bash
curl -X POST http://127.0.0.1:8000/api/chat/runs \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"insurance_service_qa","question":"What documents are required for inpatient claim reimbursement?"}'
```

Future production-directed versions can switch the knowledge provider to PageIndex while keeping the same Control Envelope, policy, validation, trace, and receipt behavior.
