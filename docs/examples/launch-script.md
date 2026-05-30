# Launch Script

This page is the public demo and evaluation contract for Proof Agent. If these paths do not work, the Harness framework is not ready.

## Goal

In two minutes, an enterprise AI Agent owner should see the deterministic Harness regression demo:

- a runnable enterprise Q&A Agent
- a supported answer with citations
- an unsupported question refused or escalated
- a tool-required question paused for approval
- a JSONL trace path
- a human-readable Governance Receipt path
- a Plain RAG vs Harness RAG comparison

## 2-Minute Demo Command

```bash
proof-agent demo
```

The demo must not require an LLM API key. It uses internal bundled fixtures and deterministic model output while still exercising the same policy, evidence, approval, trace, and receipt code paths as the full enterprise evaluation.

## 30-Minute Enterprise Evaluation

```bash
docker compose up
proof-agent run examples/insurance_customer_service/agent.yaml \
  --question "What documents are required for inpatient claim reimbursement?"
proof-agent inspect runs/latest/governance_receipt.md
```

The CLI or Docker path must load `examples/insurance_customer_service/agent.yaml` and write artifacts under `runs/latest/`.

Optional Dashboard API path:

```bash
uv run --extra dashboard proof-agent server --host 127.0.0.1 --port 8000
```

The Dashboard API reads run artifacts. It must not bypass workflow, policy, validators, trace, or receipt generation.

Optional remote model evaluation after configuring `model.provider: openai_compatible` in `agent.yaml`:

```bash
OPENAI_API_KEY=... proof-agent run examples/insurance_customer_service/agent.yaml \
  --question "What documents are required for inpatient claim reimbursement?"
```

Remote provider configuration must use environment variable names in `agent.yaml`; raw secrets must not be committed.

## Demo Questions

These internal regression questions are exercised by `proof-agent demo`:

| Step | Question | Expected result |
| --- | --- | --- |
| 1 | "What is the reimbursement rule for travel meals?" | Harness RAG answers with citations |
| 2 | "What discount should we give this customer next year?" | Harness RAG refuses or escalates because evidence is missing |
| 3 | "Look up customer policy status before answering." | Harness RAG requests approval before running the MCP mock tool |

## Side-by-Side Comparison

The demo must include a Plain RAG vs Harness RAG view for the unsupported question:

| Path | Expected behavior |
| --- | --- |
| Plain RAG | May answer loosely from partial or irrelevant context |
| Harness RAG | Refuses or escalates because required evidence is missing |

The comparison exists to prove this project is not just a RAG template.

## Required Artifacts

Every run must print these paths:

```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

The receipt must summarize policy decisions, evidence status, tool approval status, memory write status, final outcome, and the trace path.

## Recording Script

1. Show the README title and v1 scope.
2. Run `proof-agent demo`.
3. Ask the supported question and show cited output.
4. Ask the unsupported question and show refusal or escalation.
5. Ask the tool-required question and show approval state.
6. Open `runs/latest/governance_receipt.md`.
7. Show the Plain RAG vs Harness RAG comparison.
8. Optionally run the full Docker + canonical package evaluation command shown above.
9. Optionally start `proof-agent server` and inspect `/api/health`, `/api/runs`, and `/api/stats`.

## Smoke Test

The README demo path is accepted only if:

- `proof-agent demo` requires no LLM API key
- the demo exercises policy, evidence, approval, trace, and receipt code paths
- the demo produces an answer or refusal
- the demo writes `runs/latest/trace.jsonl`
- the demo writes `runs/latest/governance_receipt.md`
- the unsupported comparison shows Plain RAG and Harness RAG diverging

The enterprise evaluation path is accepted only if:

- the command uses `examples/insurance_customer_service/agent.yaml`
- Docker Compose starts the required local services
- the run writes the same trace and receipt artifacts

The dashboard path is accepted only if:

- it reads existing run history
- it exposes health, run, trace, receipt, and stats data through `/api`
- it does not create an alternate execution path
