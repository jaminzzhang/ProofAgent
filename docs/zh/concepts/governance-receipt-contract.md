# Governance Receipt Contract (治理凭证合约)

Governance Receipt 是一个微型的、人类可读的审计工件，它由 JSONL trace 事件生成。

该 receipt 并非事实的本源。`trace.jsonl` 才是事实的本源，且必须遵循 [Trace Event Contract](trace-event-contract.md)。Receipt 是一个便于领导者阅读的摘要，可让 Agent 负责人、架构师、安全审核员或业务赞助者审查为什么一次执行会给出回答、拒绝、升级或暂停等待审批。

## 必需的结果 (Required Outcomes)

v1 支持以下最终结果：

```text
ANSWERED_WITH_CITATIONS
REFUSED_NO_EVIDENCE
ESCALATED_WEAK_EVIDENCE
WAITING_FOR_APPROVAL
TOOL_APPROVAL_DENIED
FAILED_WITH_TRACE
FAILED_RECEIPT_UNAVAILABLE
```

## 必需的章节 (Required Sections)

每个 receipt 必须包含：

- run id 和时间戳
- agent 名称和 `agent.yaml` 路径
- 用户提问
- 最终结果 (final outcome)
- 策略决策及其原因
- 接受和拒绝的证据
- 工具审批状态
- 记忆读写状态
- 当发生模型调用时，包含模型提供商、模型名称、token 消耗或模型错误摘要
- 审计工件路径
- 脱敏 (redaction) 摘要

## Trace 事件映射

| Receipt 章节 | Trace 事件来源 |
| --- | --- |
| 策略决策 (Policy Decisions) | `policy_decision` 事件 |
| 证据 (Evidence) | `retrieval_result` 和 `evidence_evaluation` 事件 |
| 工具 (Tools) | `tool_request`, `approval_requested`, `approval_granted`, `approval_denied`, `approval_timeout`, `tool_result` 事件 |
| 记忆 (Memory) | `memory_read`, `memory_write_requested`, `memory_write_decision` 事件 |
| 模型使用 (Model Usage) | `model_request`, `model_response`, `model_error` 事件 |
| 审计工件 (Audit Artifacts) | run metadata 和 artifact writer 事件 |
| 脱敏摘要 (Redaction Summary) | `redaction_applied` 事件和 trace writer metadata |

如果缺失了必需的 trace 事件，receipt 生成器必须 fail closed (静默/拒绝生成)。仅当 JSONL trace 已被保留，且向用户显示的错误指向该 trace 时，才可以产生 `FAILED_RECEIPT_UNAVAILABLE`。

工具审批部分必须遵循 [Approval State Contract](approval-state-contract.md)。

## 脱敏规则 (Redaction Rules)

Receipt 必须不能包含：

- API key 或模型提供商凭据
- 原始的 bearer tokens 或 OAuth tokens
- 生产环境的连接字符串
- 不必要的个人数据
- 策略标记为敏感的原始工具 payload 字段
- 原始 prompts、原始模型响应、provider headers 或 provider error bodies

当脱敏发生时，receipt 应展示字段分类的名称，而不是秘密值：

```text
Redacted: provider_api_key, customer_phone, access_token
```

## 测试要求

Receipt 的测试必须覆盖：

- allow, deny, require_approval, 和 escalate 策略决策
- 被接受和被拒绝的证据
- 已授权、被拒绝和已超时的工具审批
- 已回答、已拒绝、已升级、等待审批和已失败的 runs
- trace 路径的存在性
- 模型使用情况或模型错误的渲染
- 确保 receipt 输出中没有原始 secrets