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

The envelope (控制外壳) 不取代底层系统。LangGraph 可以拥有工作流执行，LangChain 可以连接生态组件，向量库可以拥有检索索引，模型提供商可以拥有生成，而 MCP 可以拥有工具协议。Proof Agent 则拥有跨越这些组件的企业控制合约。

## v1 原则

- **Agent Contract 优先:** 用户从 `agent.yaml` 开始，而不是内部类。
- **策略先于输出:** 重要的动作必须通过明确的策略决策。
- **证据重于置信度:** 缺失或薄弱的证据会导致拒答或升级。
- **审批是一种状态:** 工具审批是可见的、可恢复的且被追踪的。
- **审计具有可移植的事实流:** JSONL trace 是真相的来源；Dashboard 和外部可观测性都是适配器 (adapters)。
- **可读的证明:** Governance Receipt 将 trace 事件转化为领导者可读的摘要。

## 为什么架构师应该喜欢它

The envelope 创造了稳定的边界，而没有过度抽象 v1：

- 运行时和提供商的实现隐藏在适配器之后
- 策略决策具有类型
- trace 事件是确定性且可移植的
- 确定性 demo 保留为回归基线
- 生产集成必须保留相同的 Harness 合约

## 为什么 Agent 负责人应该喜欢它

The envelope 使 Agent 演示感觉像是一个可交付的工件：

- 清晰的安全行为
- 可见的拒答路径
- 显式的工具治理
- 可读的审计输出
- 单命令演示路径
- 一个他们可以向安全、合规和业务利益相关者解释的故事