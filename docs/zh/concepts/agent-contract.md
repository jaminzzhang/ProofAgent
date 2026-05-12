# Agent Contract (Agent 合约)

`agent.yaml` 是 Proof Agent 的首要公共接口。

它描述了作为企业交付物的 Agent：用途、工作流、知识库、模型提供商、策略、工具、记忆以及审计输出。用户在阅读实现代码之前，应该就能从这里理解该 Agent 被允许做什么。

## v1 结构

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
  params: {}

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ./runs/latest/trace.jsonl
  receipt_path: ./runs/latest/governance_receipt.md
```

这种 schema 被有意设计得非常小巧。它足以运行首个企业问答模板，同时为通过特定 adapter 参数集成远程模型、向量库、MCP 以及 dashboard 留下了空间。

## 职责

`agent.yaml` 应该回答以下问题：

- 这个 Agent 的用途是什么
- 它使用哪个工作流模板
- 知识从哪里来
- 它使用哪种模型提供商模式
- 哪个策略在控制它
- 哪些工具是可用的
- 允许的记忆范围是什么
- 审计工件被写在什么地方

目前 v1 支持的模型提供商 (model providers) 包括：

- `deterministic`: 本地演示 provider，无需 SDK 或 API key。
- `openai_compatible`: 兼容 Chat Completions 的远程 provider。
- `azure_openai`: 仅供配置合约和验证的占位符。
- `anthropic`: 仅供配置合约和验证的占位符。

Provider 的设置位于 `model.params` 下。它们可以指定诸如 `api_key_env`, `base_url_env`, `organization_env` 或 `project_env` 等环境变量的名称，但绝不能包含原始的凭证 (secret) 值。

兼容 OpenAI 的配置示例：

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

只有当 Adapter 字段在合约边界保持对 provider 中立时才被允许存在。原始的 SDK 客户端、授权对象、LangChain 对象、LangGraph 对象、MCP 会话对象或向量库句柄不得出现在 `agent.yaml` 或合约模型中。

## 失败行为 (Failure Behavior)

无效的合约必须在执行开始前报错 (fail fast)。错误信息应指出缺失或无效的字段以及导致该错误的配置文件。

示例：

- 缺失 `policy.file` -> fail fast 并提供配置指南
- 缺失 knowledge path -> 在模型调用前 fail fast
- 不支持的模型 provider -> fail fast；v1 会默认回退至 deterministic demo 模式
- 缺少远程模型 SDK 或 API key -> 尽可能在 trace 初始化之后发出 `model_error`
- 不支持的 runtime -> fail fast；即使 LangGraph/LangChain 适配器发生演进，公共的工作流合约也要保持稳定
- audit path 不可写 -> 在回答前报错

合约是信任体系的一部分。如果配置不明确，Agent 就不能运行。