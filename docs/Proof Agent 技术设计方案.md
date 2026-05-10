# Proof Agent 技术设计方案

> 基于 PRD、Controlled Agent Harness Framework、可行性分析、Engineering Review、当前代码实现，以及 `docs/superpowers/specs/2026-05-10-model-provider-design.md` 的综合技术设计方案。

## 0. 本次检视结论

旧版《Proof Agent 技术选型》整体方向正确，但有几处会误导后续实现的表述。本次更名并修正为《Proof Agent 技术设计方案》，把“选型理由”升级为“可执行架构设计”。

| 原表述 / 隐含假设 | 问题 | 修正 |
| --- | --- | --- |
| v1 `LocalKnowledgeProvider` 等同于本地向量检索 | 当前默认实现是 Markdown chunk + token overlap；Chroma/vector adapter 只应是可选路径 | 明确 local deterministic retrieval 是基线，Chroma/vector 放到 adapter/后续增强 |
| MCP SDK + stdio + LangGraph interrupt 像已完整落地 | 当前实现是 mock tool registry + ToolGateway + approval state；真实 MCP stdio 和 LangGraph interrupt 仍是 adapter 目标 | 区分已实现 mock gateway 与后续 MCP adapter |
| LangGraph 负责完整工作流执行 | 当前 `runtime/langgraph_runner.py` 只是隔离 adapter，主流程仍是 plain Python orchestrator | 保留 LangGraph 为目标 runtime，但公共边界仍是 Workflow + Policy + Audit |
| 模型只支持 deterministic | 下一步设计需要远程模型 provider | 增加 `ModelProvider` 层：`deterministic`、`openai_compatible`、`azure_openai`、`anthropic` |
| 远程模型失败可直接 fail fast | Proof Agent 的价值是可审计失败 | 增加 `model_error` trace，尽量在 trace 初始化后 fail closed |
| 模型输出可直接作为最终答案 | 这会削弱 Harness 控制力 | 明确远程输出必须经过 schema、safety、citation/evidence validators |
| 依赖列表把所有能力都当核心依赖 | 远程模型 SDK 不应影响无 key demo | `openai` 作为 optional dependency；Azure/Anthropic SDK 暂不加入一期 |

---

## 1. 设计原则

1. **Harness 控制流程，模型只生成内容**  
   LLM 不能决定检索、工具调用、审批、记忆写入、策略分支或最终接收。

2. **Local-first 基线必须稳定**  
   `proof-agent demo` 必须继续无网络、无 API key、无远程 SDK 可运行。

3. **第三方 SDK 不泄漏**  
   LangGraph、Chroma、MCP、OpenAI、Azure、Anthropic 等 SDK 类型只能存在于 adapter 层，不能进入 contracts、policy、trace、receipt、workflow 公共模型。

4. **失败也要尽量可审计**  
   config shape 错误可以在 trace 前失败；远程模型缺 key、缺 SDK、超时、限流、服务错误应尽量产生 `model_error` trace。

5. **远程输出默认不可信**  
   ModelProvider 返回内容后，必须再通过 schema、safety、citation/evidence validators，才能进入 final output。

6. **配置显式，但不携带 secret**  
   `agent.yaml` 可以声明 env var 名称、endpoint、timeout、temperature、token limit；不能写入 raw API key、bearer token、connection string 或 secret。

---

## 2. 总体架构

Proof Agent 是一个 local-first、CLI-first 的 Controlled Agent Harness Framework。核心架构是 Control Envelope：

```text
agent.yaml
  -> config loader / contracts
  -> workflow orchestrator
  -> policy engine
  -> knowledge provider
  -> evidence validators
  -> model provider
  -> output validators
  -> memory boundary
  -> trace writer
  -> governance receipt
```

模型能力被放在 Harness 内部的一个受控节点里：

```text
workflow/orchestrator
  -> providers.resolve_provider(ModelConfig)
  -> ModelProvider.generate(ModelRequest)
  -> ModelResponse
  -> validators
  -> final_output
```

关键边界：

- `contracts/` 定义稳定数据模型。
- `policy/` 只消费上下文和合约，不知道 SDK。
- `knowledge/` 只返回标准 `EvidenceChunk`。
- `providers/` 隔离远程模型 SDK。
- `audit/` 只从 trace 聚合 receipt，不读 workflow 私有状态。
- `workflow/` 负责 Control Envelope 顺序，不把控制权交给模型。

---

## 3. 当前实现基线

当前代码已经具备以下基线：

| 模块 | 当前状态 |
| --- | --- |
| CLI | Typer 命令：`demo`、`run`、`doctor`、`inspect`、`compare` |
| Config | `agent.yaml` 通过 Pydantic contracts 加载和校验 |
| Policy | 支持 `before_retrieval`、`before_answer`、`before_tool_call`、`before_memory_write` |
| Knowledge | Markdown chunk + deterministic token overlap retrieval |
| Model | `DeterministicProvider` hard-coded 于 orchestrator 标准回答路径 |
| Tool | ToolGateway + mock `customer_lookup` + approval state |
| Memory | session memory + denylist |
| Audit | JSONL trace + Jinja2 Governance Receipt + redaction |
| Tests | pytest + Ruff + mypy，当前测试覆盖 contracts、policy、knowledge、tools、memory、trace、receipt、workflow、CLI |
| Docker/CI | Dockerfile、docker-compose、GitHub Actions 已存在 |

当前 demo 输出：

```text
Proof Agent demo
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

---

## 4. 语言、包管理与开发工具

| 项 | 决策 | 理由 |
| --- | --- | --- |
| 语言 | Python 3.12+ | Agent 生态、LangGraph、MCP、Pydantic、Typer、OpenAI SDK 都有成熟 Python 支持 |
| 包管理 | `uv` + `pyproject.toml` + `uv.lock` | 快速、可复现、适合 CLI/package 项目 |
| CLI | Typer | 类型注解驱动，易测试，和当前代码一致 |
| 数据合约 | Pydantic v2 | frozen model、validator、JSON serialization 能支撑 contract-first 设计 |
| 测试 | pytest | 当前测试框架 |
| Lint | Ruff | 快速、统一 |
| 类型检查 | mypy strict | 保持合约边界清晰 |

核心命令：

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
uv run --extra dev proof-agent demo
```

---

## 5. Workflow Runtime

### 决策

公共心智模型是 **Workflow + Policy + Validator + Gateway + Audit**，不是 LangGraph。

LangGraph 保留为 runtime adapter 方向，但当前实现应继续把 LangGraph 细节隔离在 `proof_agent/runtime/langgraph_runner.py`，并允许 plain Python orchestrator 作为可测试基线。

### 设计约束

- `workflow/` 表达 Proof Agent 自己的流程语义。
- `runtime/` 负责把 workflow 接到 LangGraph 或未来 runtime。
- LangGraph 类型不得进入 config、contracts、policy、trace、receipt。
- tool approval 可以未来映射到 LangGraph `interrupt()`，但 ToolGateway/ApprovalState 仍是 Harness 自己的公共合约。

### 为什么这样设计

LangGraph 的 conditional edges、interrupt、checkpoint 对企业 Agent 很有价值，但 Proof Agent 的差异化不是“用了 LangGraph”，而是“外部控制系统”。因此 runtime 必须可替换。

---

## 6. Knowledge Provider

### 决策

一期基线使用 deterministic local retrieval：

- Markdown heading-aware chunking
- source + line range citation
- token overlap score
- `EvidenceChunk` 标准输出
- evidence threshold validator

ChromaDB + sentence-transformers 可以作为 `LocalKnowledgeIndex` / vector adapter 保留或增强，但不应被描述为 demo 必需路径。

### Provider 边界

```python
class KnowledgeProvider(Protocol):
    def retrieve(self, query: str, *, top_k: int = 3) -> tuple[EvidenceChunk, ...]: ...
```

任何未来 provider 必须遵守：

- 返回 `EvidenceChunk`。
- 来源信息能映射到 Governance Receipt。
- 不绕过 `before_retrieval` 和 `before_answer`。
- 请求、响应、错误、redaction 进入 trace。

### 后续扩展

- Chroma/vector local provider
- Agentic RAG provider
- Remote enterprise knowledge API provider
- PageIndex 类 provider

---

## 7. Model Provider

### 决策

新增 `ModelProvider` 抽象，替换 orchestrator 中 hard-coded `DeterministicProvider().answer()`。

支持的 provider 名称：

- `deterministic`
- `openai_compatible`
- `azure_openai`
- `anthropic`

一期实现：

- 实现 `deterministic`
- 实现 `openai_compatible`
- `azure_openai` 只落配置契约、校验提示、测试占位，不接真实 SDK
- `anthropic` 只落配置契约、校验提示、测试占位，不接真实 SDK

### OpenAI-compatible 的取舍

OpenAI 官方文档建议新 OpenAI-native 项目优先使用 Responses API，同时 Chat Completions 仍然被支持。Proof Agent 一期选择 Chat Completions-compatible surface，是为了接入 OpenAI-compatible 生态，包括 OpenAI、DeepSeek、Qwen-compatible gateways、OpenRouter、local OpenAI-compatible servers。

未来如果需要 OpenAI-native Responses 能力，可以新增独立 provider：

```text
openai_responses
```

而不是污染 `openai_compatible`。

参考：

- OpenAI Chat Completions API Reference: https://platform.openai.com/docs/api-reference/chat/create
- OpenAI Responses vs Chat Completions: https://platform.openai.com/docs/guides/responses-vs-chat-completions
- Anthropic Messages API: https://docs.anthropic.com/en/api/messages

### Provider 目录

```text
proof_agent/providers/
├── __init__.py
├── protocol.py
├── registry.py
├── deterministic.py
├── openai_compatible.py
├── azure_openai.py
└── anthropic.py
```

### Model contracts

新增 `proof_agent/contracts/model.py`：

```python
class ModelRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelMessage(FrozenModel):
    role: ModelRole
    content: str
    name: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)


class TokenUsage(FrozenModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int | None = None


class ModelRequest(FrozenModel):
    messages: tuple[ModelMessage, ...]
    provider: str
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int | None = None
    stream: bool = False
    response_format: Literal["text", "json"] = "text"
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    evidence_sources: tuple[str, ...] = Field(default_factory=tuple)


class ModelResponse(FrozenModel):
    content: str
    provider_name: str
    model_name: str
    refusal_reason: str | None = None
    token_usage: TokenUsage | None = None
    finish_reason: str | None = None
    raw_response_id: str | None = None
```

### Provider protocol

```python
class ModelProvider(Protocol):
    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def estimate_tokens(self, request: ModelRequest) -> int | None: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...
```

一期不实现 streaming。`ModelRequest.stream` 只是为 policy context 和 trace 留形状；provider 可以明确拒绝 `stream=True`。

### Config contract

`agent.yaml`:

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

`ModelConfig`:

```python
class ModelConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)
```

`params` 对 contracts 层是 opaque，但 provider 层必须校验允许字段。以下字段名禁止出现在 YAML：

- `api_key`
- `authorization`
- `bearer`
- `password`
- `secret`
- `access_token`
- `provider_api_key`

### Azure placeholder

```yaml
model:
  provider: azure_openai
  name: gpt-4o-mini
  params:
    endpoint_env: AZURE_OPENAI_ENDPOINT
    api_key_env: AZURE_OPENAI_API_KEY
    api_version: "2025-01-01-preview"
    deployment: proof-agent-demo
```

一期 `resolve_provider()` 对 `azure_openai` 返回清晰错误：

```text
azure_openai provider is defined but not implemented yet.
```

### Anthropic placeholder

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
  params:
    api_key_env: ANTHROPIC_API_KEY
    max_output_tokens: 800
```

一期 `resolve_provider()` 对 `anthropic` 返回清晰错误：

```text
anthropic provider is defined but not implemented yet.
```

---

## 8. Policy Engine

### 当前 enforcement points

- `before_retrieval`
- `before_answer`
- `before_tool_call`
- `before_memory_write`

### 新增 enforcement point

- `before_model_call`

区别：

- `before_answer` 判断证据是否足够回答。
- `before_model_call` 判断是否允许调用指定模型。

`before_model_call` context:

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "estimated_tokens": 612,
    "stream": False,
    "cost_class": "remote",
    "question": question,
    "accepted_evidence_count": 2,
    "citations_present": True,
}
```

Cost classes:

- `local`: deterministic/local model
- `remote`: network model provider
- `enterprise`: Azure or managed enterprise provider

一期规则条件至少支持：

- provider equals
- model equals
- cost_class equals
- estimated_tokens <= threshold
- stream equals

无规则命中时沿用当前 default allow。

---

## 9. Tool Gateway / MCP

### 当前基线

当前实现的稳定基线是：

- `tools.yaml`
- ToolGateway
- allowed/denied parameters
- risk level
- approval state
- local mock `customer_lookup`

### 后续 MCP adapter

真实 MCP stdio transport、`mcp[cli]`、`langchain-mcp-adapters` 仍是后续 adapter 方向，不是当前 demo 必需路径。

工具调用原则不变：

- workflow 不能直接调用 tool 实现。
- 所有工具必须经过 ToolGateway。
- `before_tool_call` 决定 allow / require approval / deny。
- 工具请求、审批、结果、错误必须进入 trace。

---

## 10. Validators

### 当前 validators

- schema
- evidence
- safety
- tool result

### 远程模型输出后的必经验证链

远程模型输出不能直接进入 final output。标准回答路径应为：

```text
model_response
  -> validate_final_output_schema
  -> validate_no_secret_strings
  -> validate_citations_supported_by_evidence
  -> final_output
```

新增：

```text
proof_agent/validators/citations.py
```

最小行为：

- final answer 如果包含 citation，citation 必须匹配 accepted evidence source。
- 如果当前回答路径要求 citations，但没有 accepted evidence，则 fail。
- 不使用 LLM-as-judge。

失败行为：

- emit validator trace event with `status="blocked"`
- 不把 unsafe model output 写成 final answer
- final outcome 走 controlled refusal 或 escalation
- receipt 显示 blocked validator result

---

## 11. Trace、Receipt、Redaction

### Trace

JSONL trace 是审计事实源。每一行是一个 `TraceEvent`。

新增 model events：

- `model_request`
- `model_response`
- `model_error`

`model_request` 只记录安全元数据：

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "message_count": 2,
    "prompt_length": 1420,
    "system_prompt_length": 220,
    "estimated_tokens": 612,
    "stream": False,
    "cost_class": "remote",
}
```

`model_response`：

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "finish_reason": "stop",
    "content_length": 420,
    "refusal_reason": None,
    "token_usage": {
        "input_tokens": 550,
        "output_tokens": 90,
        "total_tokens": 640,
    },
}
```

`model_error`：

```python
{
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "error_code": "PA_MODEL_004",
    "error_class": "timeout",
    "retryable": True,
    "message": "Provider request timed out.",
    "duration_ms": 30000,
}
```

安全规则：

- 不记录 raw prompt。
- 不记录 raw response。
- 不记录 raw headers。
- 不记录 provider error body。
- redaction 仍对所有 model event payload 生效。

### Governance Receipt

新增 `Model Usage` section：

```markdown
## Model Usage

| Field | Value |
|-------|-------|
| Provider | openai_compatible |
| Model | gpt-4o-mini |
| Cost Class | remote |
| Estimated Tokens | 612 |
| Input Tokens | 550 |
| Output Tokens | 90 |
| Finish Reason | stop |
```

如果 model resolution 或 generation 失败：

- receipt 显示 provider/model if known
- receipt 显示 error code 和 normalized error class
- 不显示 raw provider error body

---

## 12. Agent Contract

`agent.yaml` 是公开入口，声明 workflow、knowledge、model、policy、tools、memory、audit。

当前 deterministic 示例：

```yaml
name: enterprise_qa
purpose: Answer enterprise policy questions with evidence and governance controls.
workflow:
  runtime: langgraph
  template: enterprise_qa
knowledge:
  provider: local
  path: knowledge
model:
  provider: deterministic
  name: demo
policy:
  file: policy.yaml
tools:
  file: tools.yaml
memory:
  provider: session
audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

下一阶段 openai-compatible 示例：

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

---

## 13. 目录结构

推荐结构：

```text
proof_agent/
├── audit/
│   ├── receipt.py
│   ├── redaction.py
│   ├── trace.py
│   └── templates/
├── compare/
├── config/
├── contracts/
│   ├── approval.py
│   ├── evidence.py
│   ├── manifest.py
│   ├── model.py
│   ├── policy.py
│   ├── receipt.py
│   ├── run.py
│   ├── tool.py
│   └── trace.py
├── demo/
├── knowledge/
├── memory/
├── policy/
├── providers/
│   ├── __init__.py
│   ├── protocol.py
│   ├── registry.py
│   ├── deterministic.py
│   ├── openai_compatible.py
│   ├── azure_openai.py
│   └── anthropic.py
├── runtime/
├── tools/
├── validators/
│   ├── citations.py
│   ├── evidence.py
│   ├── safety.py
│   ├── schema.py
│   └── tool_result.py
└── workflow/
```

目录原则：

- `providers/` 只处理模型调用和 SDK 适配。
- `workflow/` 调用 provider protocol，不 import OpenAI/Azure/Anthropic SDK。
- `contracts/model.py` 是 provider-neutral。
- `validators/` 对远程模型输出进行二次验证。
- `audit/receipt.py` 只从 trace 聚合 model usage。

---

## 14. 依赖设计

核心依赖维持 local-first：

```toml
dependencies = [
  "typer>=0.12.0",
  "pydantic>=2.7.0",
  "pyyaml>=6.0.1",
  "jinja2>=3.1.0",
  "langgraph>=1.1.0",
  "langchain-mcp-adapters>=0.1.0",
  "mcp[cli]>=1.27.0",
  "sentence-transformers>=3.0.0",
  "chromadb>=1.5.0",
]
```

远程模型 SDK 使用 optional dependencies：

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.5.0", "mypy>=1.10.0"]
openai = ["openai>=1.30.0"]
all = ["proof-agent[openai]"]
```

一期不加入 Azure SDK 或 Anthropic SDK。

---

## 15. 错误码

已有：

- `PA_MODEL_001`: unsupported provider / provider not implemented / missing optional SDK

新增：

- `PA_MODEL_002`: provider API error
- `PA_MODEL_003`: authentication failure or missing API key
- `PA_MODEL_004`: provider timeout

错误映射：

| 场景 | Code | Trace |
| --- | --- | --- |
| unsupported provider | `PA_MODEL_001` | config 阶段可 fail before trace |
| placeholder provider | `PA_MODEL_001` | `model_error` if trace initialized |
| missing OpenAI SDK | `PA_MODEL_001` | `model_error` |
| missing API key env | `PA_MODEL_003` | `model_error` |
| auth invalid | `PA_MODEL_003` | `model_error` |
| timeout | `PA_MODEL_004` | `model_error` |
| rate limit/server error | `PA_MODEL_002` | `model_error` |

---

## 16. 测试策略

新增测试：

| Test | 目标 |
| --- | --- |
| `tests/test_model_contracts.py` | `ModelRequest`、`ModelMessage`、`ModelResponse`、`TokenUsage` immutability |
| `tests/test_model_provider_registry.py` | provider registry、placeholder provider、unsupported provider |
| `tests/test_deterministic_model_provider.py` | deterministic wrapper 行为不变 |
| `tests/test_openai_compatible_provider.py` | mocked OpenAI-compatible client、usage mapping、error wrapping |
| `tests/test_model_config_validation.py` | secret-looking params 被拒绝 |
| `tests/test_policy_before_model_call.py` | provider/model/token/stream/cost_class policy context |
| `tests/test_trace_model_events.py` | `model_request`、`model_response`、`model_error` 安全落 trace |
| `tests/test_receipt_model_usage.py` | receipt 渲染 Model Usage 和 model error |
| `tests/test_model_output_validators.py` | schema、safety、citation validation 链路 |

所有远程 provider 测试必须 mock SDK client，不依赖真实网络或真实 API key。

回归测试必须继续覆盖：

- `proof-agent demo`
- supported answer with citations
- unsupported refusal
- tool approval wait/deny
- trace redaction
- receipt sections

---

## 17. 下一步实施顺序

1. 增加 model contracts。
2. 增加 providers protocol/registry/factory。
3. 包装 deterministic provider。
4. 实现 openai-compatible provider，使用 optional `openai` dependency。
5. 增加 Azure/Anthropic placeholder provider。
6. 扩展 policy enforcement point：`before_model_call`。
7. 扩展 trace event：`model_request`、`model_response`、`model_error`。
8. 构建 `ModelRequest`，接入 orchestrator 标准回答路径。
9. 增加模型输出 validators，尤其 citation/evidence validator。
10. 更新 Governance Receipt 的 Model Usage section。
11. 更新 CLI doctor，显示远程模型配置就绪状态。
12. 更新 docs/concepts/agent-contract.md 和 trace-event-contract.md。
13. 运行 full verification。

---

## 18. Deferred Work

- Real Azure OpenAI adapter
- Real Anthropic adapter
- Streaming responses
- OpenAI Responses API-native provider
- Provider-native structured output / JSON schema mode
- LLM-as-judge quality evaluation
- 成本金额估算和预算策略
- 多轮 conversation state
- post-tool remote generation
