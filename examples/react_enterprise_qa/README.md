# Controlled ReAct Enterprise QA

This is the deterministic, no-key Controlled ReAct Enterprise QA package. It reuses the Enterprise QA knowledge, policy, and tool definitions while adding a ReAct planner, Harness Review Subagent, clarification outcome, response controls, and ReAct governance trace events.

Run the full deterministic scenario set:

```bash
uv run --extra dev --extra dashboard proof-agent react-demo
```

Expected outcomes:

- `supported`: `ANSWERED_WITH_CITATIONS`
- `unsupported`: `REFUSED_NO_EVIDENCE`
- `clarify`: `WAITING_FOR_USER_CLARIFICATION`
- `tool_required`: `WAITING_FOR_APPROVAL`

Single-run execution is also supported:

```bash
uv run --extra dev --extra dashboard proof-agent run examples/react_enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
```

The workflow records audit-safe ReAct Reasoning Summary and Auto Review events in `trace.jsonl` and renders ReAct sections in the Governance Receipt. It must not record raw chain-of-thought.
