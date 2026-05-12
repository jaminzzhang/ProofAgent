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

1. **Inserting policy enforcement points between flow nodes**: `before_retrieval`, `before_answer`, `before_tool_call`, `before_memory_write`, `before_model_call`
2. **Generating typed results from each decision**: `allow`, `deny`, `require_approval`, `escalate`
3. **Writing each decision to Trace and summarizing it in the Governance Receipt**

Harness does not replace underlying orchestration engines (LangGraph), knowledge bases (RAG), or tool protocols (MCP). It establishes a unified control contract over these components.

### Harness RAG

**Harness RAG** is a governed knowledge retrieval and generation implementation based on **Agentic RAG**. Unlike Plain RAG (Retrieve → Generate), Harness RAG introduces policy gates between retrieval and generation:

```text
Plain RAG:    User Question → Retrieve → Generate Answer
Harness RAG:  User Question → Policy(before_retrieval) → Retrieve → Evidence Evaluation → Policy(before_answer) → Answer with Citations / Refuse / Escalate
```

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