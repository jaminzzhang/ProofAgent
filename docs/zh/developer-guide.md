# Proof Agent 开发指南

> 受众：AI Agent 负责人、Agent 平台负责人、企业 AI 应用工程负责人。
>
> 目标：用 Proof Agent 快速开发、验证、部署一个可治理的 Agent，而不是从零实现策略门控、工具审批、证据校验、审计和可观测性。

## 1. 使用方式概览

Proof Agent 的开发入口是一个可治理的 Agent package，而不是一段裸 Agent 代码。

一个 Agent package 通常包含：

```text
agent.yaml          # Agent Contract：声明 workflow、runtime、model、knowledge、tools、memory、audit
policy.yaml         # Control Plane 策略：声明何时允许、拒绝、审批或升级
tools.yaml          # Tool / MCP 声明：工具白名单、风险等级、参数边界、审批要求
knowledge/          # 业务知识源；v1 默认支持本地 Markdown 知识库
questions.yaml      # 可选：评估问题集
expected/           # 可选：期望 trace / receipt 示例
```

当前可运行参考实现是 [Enterprise QA Template](examples/enterprise-qa.md)，对应目录是 `examples/enterprise_qa/`。

## 2. 快速开始 (Quick Start)

从仓库根目录运行本地 deterministic demo：

```bash
uv run --extra dev proof-agent demo
```

运行 Enterprise QA Template：

```bash
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml
```

对比普通 RAG 与受控 Harness RAG：

```bash
uv run --extra dev proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
```

查看最新 Governance Receipt：

```bash
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
```

查看最新 trace：

```bash
uv run --extra dev proof-agent inspect runs/latest/trace.jsonl
```

启动 Dashboard API：

```bash
uv run --extra dashboard proof-agent dashboard --host 127.0.0.1 --port 8000
```

Dashboard API 读取已有 run history。它不是第二条 Agent 执行路径。

## 3. 架构心智模型

使用 Proof Agent 时，应按以下层次思考：

```text
Delivery / Entry
  CLI | Docker | Template | future Execution API

Bootstrap / Composition
  agent.yaml loader | config validation | registry | dependency wiring

Control Plane
  Workflow | Orchestrator | Policy Gates | Approval State Machine
  Evidence Evaluation | Validators | Memory Policy | Outcome

Runtime Plane
  Plain Python Runner | LangGraph Adapter | LangChain Adapter
  state execution | checkpoint | interrupt/resume | streaming

Capability Layer
  Model | Knowledge/Retrieval | Memory | Tool/MCP | Skill Packs

Contracts & Ports
  Stable DTOs and provider protocols used across layers

Audit & Observability
  TraceWriter -> JSONL Trace -> RunStore -> Governance Receipt -> Dashboard API
```

核心边界：

- Control owns decisions.
- Runtime owns execution mechanics.
- Capability owns concrete abilities.
- Contracts define the language.
- Audit records facts.

## 4. 当前 v1 能力边界

| 区域 | v1 状态 |
| --- | --- |
| Entry | CLI、Docker demo、Dashboard API |
| Workflow template | `enterprise_qa` |
| Runtime config | `workflow.runtime: langgraph`；当前 adapter 边界已存在，MVP 主流程仍委托 plain Python orchestrator |
| Knowledge | `knowledge.provider: local`，本地 Markdown 检索 |
| Model | `deterministic` 和 `openai_compatible` 已实现；`azure_openai`、`anthropic` 是清晰失败的 placeholder |
| Policy | `before_retrieval`、`before_answer`、`before_tool_call`、`before_memory_write`、`before_model_call` |
| Tools / MCP | ToolGateway、mock `customer_lookup`、approval state；真实 MCP transport 是扩展方向 |
| Memory | `memory.provider: session`，带敏感字段 denylist |
| Validators | schema、evidence、safety、citations、tool result |
| Audit | JSONL trace、Governance Receipt、RunStore、Dashboard read API |

v1 的 deterministic path 必须始终不依赖 API key、网络模型或外部服务。

## 5. 配置 Agent Contract

`agent.yaml` 是 Proof Agent 的首要公共接口。最小参考：

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge:
  provider: local
  path: ./knowledge

model:
  provider: deterministic
  name: demo

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

当前 v1 配置约束：

- `workflow.runtime` 必须是 `langgraph`。
- `workflow.template` 必须是 `enterprise_qa`。
- `knowledge.provider` 必须是 `local`。
- `memory.provider` 必须是 `session`。
- `model.provider` 支持 `deterministic`、`openai_compatible`、`azure_openai`、`anthropic`，但 Azure 和 Anthropic 目前是 placeholder。
- `policy.file`、`tools.file`、`knowledge.path` 必须存在。
- `audit.trace_path` 和 `audit.receipt_path` 的父目录必须可写。

远程模型配置必须使用环境变量名，不要把 raw secret 写入 YAML：

```yaml
model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 30
```

运行示例：

```bash
OPENAI_API_KEY=... uv run --extra openai proof-agent run examples/enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
```

## 6. 配置 Control Plane

Control Plane 决定 Agent 是否可以继续行动。它不信任模型输出，也不让 Runtime 或 Tool 直接绕过治理。

常见策略文件：

```yaml
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require accepted evidence and citations."

  - rule_id: tools.customer_lookup.approval
    enforcement_point: before_tool_call
    condition:
      tool_name: customer_lookup
      risk_level: medium
    decision:
      on_match: require_approval
    reason_template: "Customer policy lookup requires explicit approval."
```

Control Plane 的开发步骤：

1. 明确 Agent 什么时候必须拒答。
2. 明确回答前需要多少证据。
3. 明确哪些工具需要审批。
4. 明确哪些字段不能写入 memory。
5. 明确模型调用前的 provider、token、成本或风险策略。
6. 用 trace 和 receipt 验证每个策略门是否被记录。

## 7. 配置 Runtime Plane

Runtime Plane 负责执行机制，不负责治理决策。

当前配置：

```yaml
workflow:
  runtime: langgraph
  template: enterprise_qa
```

当前 MVP 中，`runtime/langgraph_runner.py` 是 LangGraph adapter boundary，主流程仍由 Enterprise QA orchestrator 执行。后续真实 LangGraph runtime 应承担 StateGraph、checkpoint、interrupt/resume 和 streaming hooks，但不得改变 Control Plane 的治理语义。

开发原则：

- Runtime 可以推进状态，但不能跳过 PolicyEngine。
- Runtime 可以实现 human interrupt，但审批事实仍由 ApprovalState 和 trace 记录。
- Runtime 可以 stream token，但 trace 中不能记录 raw secret 或未脱敏 provider payload。
- LangChain/LangGraph SDK 类型不能泄漏到 contracts、policy、trace、receipt 或 dashboard contracts。

## 8. 配置 Capability Layer

Capability Layer 提供 Agent 可调用能力。

### Model

使用 deterministic provider 做本地回归：

```yaml
model:
  provider: deterministic
  name: demo
```

使用 OpenAI-compatible provider 做远程模型验证：

```yaml
model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
```

扩展新的模型 provider 时：

- 实现 `ModelProvider` protocol。
- 返回 provider-neutral `ModelResponse`。
- 在 provider registry 注册。
- provider SDK 错误要映射为 Proof Agent error code。
- trace 只能记录 provider、model、token usage、content length、finish reason 等安全摘要。

### Knowledge

当前 v1 使用本地 Markdown 知识库：

```yaml
knowledge:
  provider: local
  path: ./knowledge
```

扩展 vector 或 enterprise search 时：

- Provider 必须返回 `EvidenceChunk`。
- Retrieval 不能决定最终回答。
- Evidence 是否足够由 evaluators、PolicyEngine 和 validators 决定。
- 向量库 SDK 类型不能进入 contracts。

### Memory

当前 v1 使用 session memory：

```yaml
memory:
  provider: session
```

扩展持久 memory 前，必须先定义：

- retention policy
- deletion behavior
- redaction behavior
- tenant boundary
- `before_memory_write` policy

### Tools / MCP

工具通过 `tools.yaml` 注册：

```yaml
tools:
  - name: customer_lookup
    description: "Mock customer policy status lookup."
    transport: stdio
    command: python
    args:
      - -m
      - proof_agent.capabilities.tools.mcp_mock
    risk_level: medium
    requires_approval: true
    allowed_parameters:
      - customer_id
      - policy_id
    denied_parameters:
      - access_token
      - customer_phone
      - provider_api_key
```

工具开发原则：

- 所有工具调用必须经过 ToolGateway。
- 高风险工具必须进入 approval state。
- 参数必须有 allowlist / denylist。
- Tool result 必须经过 validator。
- 真实 MCP stdio/http transport 应作为 ToolGateway 后面的 adapter，而不是新的执行路径。

### Skills

Skill 是能力包，不是绕过 Control 的快捷入口。一个 Skill 可以包含：

- prompt pattern
- tool schema
- retrieval recipe
- policy rule
- validator
- workflow fragment

Skill 被引入后，应注册或编译进 Control、Runtime、Capability 的现有模型中。它不能直接调用模型、工具或 memory 来绕过 PolicyEngine、Approval 和 Trace。

## 9. 开发一个新 Agent

推荐流程：

1. 从 `examples/enterprise_qa/` 复制一个 Agent package。
2. 修改 `agent.yaml` 的 `name`、`purpose`、`knowledge.path`、`model`、`audit`。
3. 替换 `knowledge/` 下的业务知识 Markdown。
4. 修改 `policy.yaml`，定义回答、工具、memory、模型调用策略。
5. 修改 `tools.yaml`，只注册当前 Agent 需要的工具。
6. 保持 deterministic provider，先跑本地回归。
7. 切换到 `openai_compatible`，用真实模型验证候选输出是否仍被 validators 管住。
8. 运行 compare，确认 Plain RAG 与 Harness RAG 在 unsupported 问题上有明显差异。
9. 检查 `runs/latest/trace.jsonl` 和 `runs/latest/governance_receipt.md`。
10. 再进入 Docker 或 Dashboard API 路径。

建议验证命令：

```bash
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml --question "Look up customer policy status before answering."
uv run --extra dev proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
```

## 10. 部署

本地或 CI smoke path：

```bash
uv run --extra dev proof-agent demo
```

Docker path：

```bash
docker compose up
```

Dashboard API path：

```bash
uv run --extra dashboard proof-agent dashboard --host 127.0.0.1 --port 8000
```

部署时应交付：

```text
Agent package
Docker image or Python runtime
environment variable configuration
runs/ storage volume
Dashboard API if observability is required
```

不要提交：

- API keys
- bearer tokens
- passwords
- connection strings
- provider secrets
- generated files under `runs/latest/`

## 11. 运行管理

每次运行都应产生：

```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

启用 `RunStore` 后，每个 run 会保存到：

```text
runs/history/{run_id}/trace.jsonl
runs/history/{run_id}/governance_receipt.md
runs/history/{run_id}/run_meta.json
```

AI Agent 负责人应定期检查：

- final outcome 分布
- refusal 是否符合预期
- unsupported 问题是否被拒答
- tool approval 是否被正确触发
- memory write 是否被策略拦截
- model usage 是否正常
- trace 是否完整
- receipt 是否能解释最终结果

## 12. 何时需要扩展框架

需要新增能力时，优先判断它属于哪一层：

| Need | Extension point |
| --- | --- |
| 新模型供应商 | Capability Layer: ModelProvider adapter |
| 新知识库或向量库 | Capability Layer: KnowledgeProvider adapter |
| 新工具或 MCP server | Capability Layer: ToolGateway adapter |
| 新审批方式 | Control Plane: ApprovalState / approval provider |
| 新 Agent 状态机 | Runtime Plane: LangGraph/LangChain runtime adapter |
| 新审计展示 | Audit & Observability: RunStore / Dashboard read projection |
| 新 Agent 模板 | Control Plane + Runtime + Capability package |

默认规则：先定义 contract 或 port，再实现 adapter。不要让第三方 SDK 类型进入公共合约、策略、trace、receipt 或 dashboard contracts。

## 13. 负责人验收清单

上线前至少确认：

- Agent 能用 deterministic provider 跑通。
- `agent.yaml` 不包含 raw secret。
- unsupported 问题会拒答或升级。
- supported 问题有证据和 citations。
- 高风险工具会等待审批。
- memory 不写入敏感字段。
- 远程模型输出经过 validators。
- trace 记录关键 policy、retrieval、model、tool、memory、final output 事件。
- Governance Receipt 能解释最终 outcome。
- Dashboard API 只读 run history，不创建新执行路径。