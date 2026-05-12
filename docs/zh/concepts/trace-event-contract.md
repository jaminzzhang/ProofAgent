# Trace Event Contract (追踪事件合约)

`trace.jsonl` 是审计事实的本源。每一份 Governance Receipt 都是从该事件流中生成的。

Trace 合约使用可移植的 JSONL 格式。其事件名称和字段应与 OpenTelemetry GenAI 的语义保持接近，以便未来的 adapter 能够清晰地映射检索、Agent 工作流、模型生成和工具执行。

## 必需的 Envelope

每一行 trace 都是一个 JSON 对象：

```json
{
  "schema_version": "trace.v1",
  "run_id": "run_20260509_103000",
  "event_id": "evt_0004",
  "sequence": 4,
  "timestamp": "2026-05-09T10:30:04Z",
  "event_type": "policy_decision",
  "span_id": "span_policy_before_answer",
  "parent_span_id": "span_workflow_enterprise_qa",
  "status": "ok",
  "payload": {},
  "redaction": {
    "applied": false,
    "fields": []
  }
}
```

## 必需的字段

| 字段 | 要求 | 备注 |
| --- | --- | --- |
| `schema_version` | 必需 | v1 使用 `trace.v1` |
| `run_id` | 必需 | 同一次 run 中的所有事件共享稳定的 id |
| `event_id` | 必需 | 在一次 run 中唯一 |
| `sequence` | 必需 | 单调递增的整数 |
| `timestamp` | 必需 | ISO 8601 UTC 格式 |
| `event_type` | 必需 | 下文 v1 事件类型之一 |
| `span_id` | 必需 | 用于分组的本地 span id |
| `parent_span_id` | 可选 | 只有 root 事件可缺省 |
| `status` | 必需 | `ok`, `blocked`, `waiting`, 或 `error` |
| `payload` | 必需 | 特定于事件的数据 |
| `redaction` | 必需 | 记录脱敏状态而不泄漏具体值 |

## v1 事件类型

| 事件类型 | 目的 |
| --- | --- |
| `run_started` | run 元数据和 manifest 路径 |
| `manifest_loaded` | 已解析的 `agent.yaml` 配置 |
| `policy_decision` | 在执行点的类型化策略决策 |
| `retrieval_started` | 本地知识检索开始 |
| `retrieval_result` | 检索到的块和 source id |
| `evidence_evaluation` | 被接受/被拒绝的证据及阈值 |
| `model_request` | 生成前的已脱敏模型调用元数据 |
| `model_response` | 已脱敏模型响应元数据和 token 消耗 |
| `model_error` | 在 trace 初始化之后发生的 provider 解析、SDK、认证、超时或 API 失败 |
| `approval_requested` | 工具审批进入等待状态 |
| `approval_granted` | 审批通过 |
| `approval_denied` | 审批被拒绝 |
| `approval_timeout` | 审批超时 |
| `tool_request` | 被请求的受控工具调用 |
| `tool_result` | 工具结果或安全的被跳过结果 |
| `memory_read` | 读取会话记忆 |
| `memory_write_requested` | 请求写入会话记忆 |
| `memory_write_decision` | 记忆策略决策 |
| `final_output` | 最终答案、拒答、升级或等待状态 |
| `redaction_applied` | 敏感字段已被移除或掩码 |
| `artifact_written` | trace 或 receipt 的工件路径 |
| `run_failed` | 带有错误码的终态失败 |

## 语义映射

| Harness 事件 | OpenTelemetry GenAI 概念 |
| --- | --- |
| `retrieval_started`, `retrieval_result` | retrieval span |
| `model_request`, `model_response` | model generation span |
| `model_error` | model span/log error 附带低基数的 `error.type` |
| `tool_request`, `tool_result` | execute tool span |
| `policy_decision` | custom agent/framework event |
| `final_output` | agent or workflow invocation output |
| `run_failed` | span/log error 附带低基数的 `error.type` |

v1 不需要发射 (emit) OpenTelemetry。它只需保持足够的结构，以便日后在不重写 trace 语义的情况下构建 adapter。

## 失败规则

- 如果 trace 写入在模型或工具执行前失败，则 run 必须 fail closed (阻断执行)。
- 配置格式错误可以在 trace 存在前失败。Provider 解析、缺少 SDK、缺少 API key、认证、超时以及 API 错误应当在 trace 初始化之后发出 `model_error`。
- 如果在最终响应存在后 trace 写入失败，CLI 必须打印 `PA_AUDIT_001`，且不得宣称该 run 是可审计的。
- 如果 receipt 生成失败，仍需向用户展示保留的 trace 路径，且 receipt outcome 变为 `FAILED_RECEIPT_UNAVAILABLE`。
- 被脱敏的值绝不能出现在 `payload` 中；`redaction.fields` 只记录字段的类别名称。

## 模型 Payload 规则

`model_request` payload 仅存储审计元数据：provider、模型、消息数量、prompt 长度、预估 tokens、流式意图和成本类别。它们不得存储原始消息内容。

`model_response` payload 存储 provider、模型、结束原因、内容长度、拒答原因和 token 消耗。它们不得存储原始的生成文本。

`model_error` payload 存储 provider、模型、错误代码、错误类别、是否可重试以及简短的非保密消息。