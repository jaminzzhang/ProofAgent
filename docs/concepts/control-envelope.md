# Control Envelope

Proof Agent 的核心抽象是 **Control Envelope**：一个包裹 Agent 执行过程的企业控制外壳。

普通 Agent 框架通常关注“怎么编排”和“怎么调用工具”。Control Envelope 关注企业负责人真正关心的问题：

- 这个 Agent 是否必须先查知识库？
- 证据不足时是否会拒答？
- 调用工具前是否需要审批？
- Memory 写入是否有边界？
- 出问题后能不能复盘完整链路？
- 业务负责人能否看懂本次执行为什么被允许？

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
         |              |              |
         v              v              v
     Workflow       Knowledge        MCP Tools
    LangGraph       Local RAG        Mock first
```

The envelope does not replace the underlying systems. LangGraph still owns workflow execution. Knowledge libraries still own retrieval. MCP still owns tool protocol. Proof Agent owns the enterprise control contract across them.

## v1 Principles

- **Agent Contract first:** users start from `agent.yaml`, not internal classes.
- **Policy before output:** important actions pass through explicit policy decisions.
- **Evidence over confidence:** missing or weak evidence causes refusal or escalation.
- **Approval is state:** tool approval is visible, resumable, and traced.
- **Audit is local first:** JSONL trace is the source of truth; external observability is an adapter.
- **Readable proof:** Governance Receipt turns trace events into a leader-readable summary.

## What Architects Should Like

The envelope creates stable boundaries without over-abstracting v1:

- runtime is LangGraph-only publicly
- providers stay local-first
- policy decisions are typed
- trace events are deterministic
- extension points are introduced only after the enterprise Q&A template proves them

## What Agent Owners Should Like

The envelope makes an Agent demo feel like a delivery artifact:

- clear safety behavior
- visible refusal paths
- explicit tool governance
- readable audit output
- one-command demo path
- a story they can explain to security, compliance, and business stakeholders
