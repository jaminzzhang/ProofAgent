# Governance Receipt (治理凭证)

Governance Receipt 是一份人类可读的证明，它证明了一个 Agent 的运行是受控的。

JSONL trace 是审计的事实本源。Governance Receipt 是一个摘要，AI Agent 负责人、架构师、安全审查员或业务赞助者可以阅读它，而无需检查原始事件。

规范的 v1 要求位于 [Governance Receipt Contract](../concepts/governance-receipt-contract.md)。本页面展示了一个渲染示例。

## 示例

```markdown
# Governance Receipt

Run: 2026-05-09T10:30:00Z
Agent: enterprise_qa
Question: What is the reimbursement rule for travel meals?
Final outcome: ANSWERED_WITH_CITATIONS

## Policy Decisions

| Point | Decision | Reason |
| --- | --- | --- |
| before_retrieval | allow | Enterprise QA requires retrieval before answering. |
| before_answer | allow | Evidence threshold met with 2 cited chunks. |
| before_tool_call | not_applicable | No tool was needed. |
| before_memory_write | allow | Session summary contains no sensitive fields. |
| before_model_call | allow | Deterministic demo provider is allowed for this run. |

## Evidence

| Source | Status |
| --- | --- |
| travel_policy.md#meals | accepted |
| reimbursement_faq.md#limits | accepted |

## Tools

No MCP tool was called.

## Model Usage

| Field | Value |
| --- | --- |
| Provider | deterministic |
| Model | demo |
| Cost Class | local |
| Estimated Tokens | 0 |

## Audit Artifacts

- Trace: `runs/2026-05-09-103000/trace.jsonl`
- Receipt: `runs/2026-05-09-103000/governance_receipt.md`
```

## 必需属性

- 必须为已回答、拒答、升级和失败的运行生成它。
- 必须包含策略决策及原因。
- 必须包含证据状态。
- 如果涉及工具，必须包含工具审批状态。
- 如果发生模型调用，必须包含模型使用情况或模型错误摘要。
- 必须包含 trace 工件的路径。
- 不能打印 secrets、API keys、原始凭据或不必要的个人数据。
- 必须遵循必需的结果和章节合约。

## 为什么这很重要

Agent 领导者需要的不仅仅是一个可工作的演示。他们需要证明，该系统在运行后是可以解释的。Receipt 将 Harness 从无形的架构变成了可见的企业信任。