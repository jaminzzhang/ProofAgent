# Enterprise Q&A Demo

The first v1 template is a strongly controlled enterprise knowledge Q&A Agent.

This demo exists because knowledge Q&A is broad enough for many enterprises, but strict enough to prove the Harness value: retrieval, evidence, citation, refusal, tool approval, memory boundary, and audit.

The public launch contract lives in [Launch Script](launch-script.md). The receipt output must follow [Governance Receipt Contract](../concepts/governance-receipt-contract.md), [Trace Event Contract](../concepts/trace-event-contract.md), and [Approval State Contract](../concepts/approval-state-contract.md).

## Demo Flow

```text
Question
  |
  v
Load agent.yaml
  |
  v
PolicyEngine.before_retrieval
  |
  v
Retrieve local knowledge
  |
  v
Evaluate evidence
  |
  v
PolicyEngine.before_answer
  | allow                  | deny/escalate
  v                        v
Answer with citations      Refusal / escalation
  |
  v
Optional tool request
  |
  v
PolicyEngine.before_tool_call
  |
  v
Approval state if required
  |
  v
JSONL trace + Governance Receipt
```

## Plain RAG vs Harness RAG

The demo must include at least one side-by-side scenario:

| Scenario | Plain RAG | Harness RAG |
| --- | --- | --- |
| Supported question | Answers with retrieved text | Answers with citations and trace |
| Unsupported question | May answer loosely | Refuses or escalates |
| Tool-required question | May call tool directly | Requires approval state |

This comparison is the fastest way to show why this project is not just another RAG template.

## Example Questions

- Supported: "What is the reimbursement rule for this internal policy?"
- Unsupported: "What discount should we give this customer next year?"
- Tool-required: "Look up customer policy status before answering."

## Acceptance Criteria

- The demo runs from `proof-agent run examples/enterprise_qa/agent.yaml`.
- Supported answers include citations.
- Unsupported answers refuse or escalate.
- Tool calls requiring approval pause before execution.
- Every run writes `trace.jsonl`.
- Every run writes a Governance Receipt that satisfies the receipt contract.
- The README and launch script can explain the demo in under three minutes.
- Plain RAG and Harness RAG visibly diverge for the unsupported question.
