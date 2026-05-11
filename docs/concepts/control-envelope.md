# Control Envelope

Proof Agent 的核心抽象是 **Control Envelope**：一个包裹 Agent 执行过程的企业控制外壳。

Control Envelope 通过 **Harness Engineering** 实现。Harness 的设计理念是在 Agent 执行流程的关键节点插入显式的策略决策点（Policy Enforcement Points），使 Agent 的每一步行为都受到策略、证据、审批和审计的约束。普通 Agent 框架关注”怎么编排”和”怎么调用工具”，而 Harness 关注企业负责人真正关心的问题：

- 这个 Agent 是否必须先查知识库？
- 证据不足时是否会拒答？
- 调用工具前是否需要审批？
- Memory 写入是否有边界？
- 出问题后能不能复盘完整链路？
- 业务负责人能否看懂本次执行为什么被允许？

## Harness Engineering

Harness Engineering 是一种将企业控制要求注入 Agent 流程的工程设计方法。它的核心做法是：

1. **在流程节点之间插入策略决策点**：`before_retrieval`、`before_answer`、`before_tool_call`、`before_memory_write`、`before_model_call`
2. **每个决策产生类型化的结果**：`allow`、`deny`、`require_approval`、`escalate`
3. **每个决策被写入 Trace 并汇总到 Governance Receipt**

Harness 不替代底层的编排引擎（LangGraph）、知识库（RAG）或工具协议（MCP）。它在这些组件之上建立统一的控制合约。

### Harness RAG

**Harness RAG** 是基于 **Agentic RAG** 的受控知识检索与生成实现。与 Plain RAG（检索 → 生成）不同，Harness RAG 在检索和生成之间加入了策略门控：

```text
Plain RAG:    User Question → Retrieve → Generate Answer
Harness RAG:  User Question → Policy(before_retrieval) → Retrieve → Evidence Evaluation → Policy(before_answer) → Answer with Citations / Refuse / Escalate
```

Harness RAG 的受控特性：
- **强制检索**：回答前必须检索知识库，不允许 LLM 直接生成
- **证据评估**：检索结果必须通过证据质量检查，弱证据触发拒答或升级
- **引用要求**：支持回答必须附带引用来源
- **工具审批**：需要调用工具时必须经过显式审批状态
- **审计追踪**：每个步骤产生 JSONL Trace，最终生成 Governance Receipt

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
