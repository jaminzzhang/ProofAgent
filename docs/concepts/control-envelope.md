# Control Envelope

The core abstraction of Proof Agent is the **Control Envelope**: an enterprise control shell that wraps the Agent execution process.

The Control Envelope is implemented through **Harness Engineering**. The design philosophy of Harness is to insert explicit Policy Enforcement Points into key nodes of the Agent execution flow, ensuring every step of the Agent is constrained by policies, evidence, approvals, and audits. While normal Agent frameworks focus on "how to orchestrate" and "how to call tools," Harness focuses on the questions enterprise leaders actually care about:

- Must this Agent search the knowledge base first?
- Will it refuse to answer if evidence is insufficient?
- Is approval required before calling a tool?
- Are there boundaries on writing to Memory?
- If something goes wrong, can the entire chain be reviewed?
- Can business leaders understand why this execution was allowed?

## Harness Engineering

Harness Engineering is an engineering design method to inject enterprise control requirements into the Agent flow. Its core practices are:

1. **Inserting policy enforcement points between flow nodes**: `before_retrieval`, `before_retrieval_plan`, `before_retrieval_step`, `before_answer`, `before_tool_call`, `before_memory_write`, `before_model_call`
2. **Generating typed results from each decision**: `allow`, `deny`, `require_approval`, `escalate`
3. **Writing each decision to Trace and summarizing it in the Governance Receipt**

Harness does not replace underlying orchestration engines (LangGraph), knowledge bases (RAG), or tool protocols (MCP). It establishes a unified control contract over these components.

### Controlled ReAct

Controlled ReAct applies the same envelope to planner-driven action loops. The planner may propose only actions from the fixed ReAct Action Set:

```text
ASK_CLARIFICATION
PLAN_RETRIEVAL
RUN_RETRIEVAL_STEP
PROPOSE_TOOL_CALL
GENERATE_FINAL_ANSWER
ESCALATE
STOP
```

The planner does not execute those actions directly. The Harness records an audit-safe `reasoning_summary`, emits an `action_proposal`, runs any configured advisory review, evaluates policy, and then decides whether the action may proceed.

Auto Review Scope covers `before_retrieval_plan`, `before_retrieval_step`, `before_tool_call`, and `before_model_call`. `before_answer` remains deterministic evidence and citation governance, because answer admission must be explainable from accepted evidence and citations.

`ASK_CLARIFICATION` produces `WAITING_FOR_USER_CLARIFICATION`. That is a controlled conversation continuation state: the current run pauses with a trace event and final output asking for missing details, and any follow-up turn must re-enter the same Control Envelope.

### Harness RAG

**Harness RAG** is a governed knowledge retrieval and generation implementation that can use single-step retrieval now and Agentic RAG as a future Retrieval Strategy. Unlike Plain RAG (Retrieve → Generate), Harness RAG introduces policy gates between retrieval and generation:

```text
Plain RAG:    User Question → Retrieve → Generate Answer
Harness RAG:  User Question → Policy(before_retrieval) → Policy(before_retrieval_step) → Retrieval Step → Evidence Evaluation → Policy(before_answer) → Answer with Citations / Refuse / Escalate
```

Agentic RAG is not a Knowledge Provider and not a workflow template. It is a Retrieval Strategy that may add planning, query rewrite, reranking, or multiple governed retrieval steps while preserving the same Control Envelope.

Governed features of Harness RAG:
- **Mandatory Retrieval**: Must retrieve from the knowledge base before answering; LLMs are not allowed to generate directly.
- **Evidence Evaluation**: Retrieval results must pass evidence quality checks; weak evidence triggers a refusal or escalation.
- **Citation Requirement**: Answers must include source citations.
- **Tool Approvals**: Tool calls must go through an explicit approval state.
- **Audit Tracking**: Every step produces a JSONL Trace, ultimately generating a Governance Receipt.

## Boundary

```text
                 Control Envelope
  +------------------------------------------------+
  | PolicyEngine                                   |
  | Evidence contract                              |
  | Tool approval state                            |
  | Memory boundary                                |
  | JSONL trace                                    |
  | Governance Receipt                             |
  +------------------------------------------------+
         |              |              |              |
         v              v              v              v
     Workflow       Knowledge       Model          MCP Tools
  LangGraph/LC     Local/Vector    Remote/local    Mock/real
```

The envelope does not replace the underlying systems. LangGraph can own workflow execution, LangChain can connect ecosystem components, vector stores can own retrieval indexes, model providers can own generation, and MCP can own tool protocol. Proof Agent owns the enterprise control contract across them.

## v1 Principles

- **Agent Contract first:** users start from `agent.yaml`, not internal classes.
- **Policy before output:** important actions pass through explicit policy decisions.
- **Evidence over confidence:** missing or weak evidence causes refusal or escalation.
- **Approval is state:** tool approval is visible, resumable, and traced.
- **Audit has a portable fact stream:** JSONL trace is the source of truth; Dashboard and external observability are adapters.
- **Readable proof:** Governance Receipt turns trace events into a leader-readable summary.
- **No hidden reasoning logs:** ReAct stores only audit-safe Reasoning Summary fields. Raw chain-of-thought must not be recorded, stored, or exposed.

## What Architects Should Like

The envelope creates stable boundaries without over-abstracting v1:

- runtime and provider implementations stay behind adapters
- policy decisions are typed
- trace events are deterministic and portable
- deterministic demo remains the regression baseline
- production integrations must preserve the same Harness contract

## What Agent Owners Should Like

The envelope makes an Agent demo feel like a delivery artifact:

- clear safety behavior
- visible refusal paths
- explicit tool governance
- readable audit output
- one-command demo path
- a story they can explain to security, compliance, and business stakeholders

## Customer Service Envelope

Autonomous Customer Service Mode uses the same Control Envelope with an additional customer-safe projection boundary. Customer Run API may start governed runs and policy-authorized read-only tools, but the terminal customer receives only `CustomerSafeResponse` fields. Trace, receipt, policy decisions, approval state, tool parameters, review results, and internal handoff state remain internal.

Internal customer handoffs are trace events and Dashboard projections. They do not create a customer-visible escalation outcome.
