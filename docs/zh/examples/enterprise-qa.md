# Enterprise Q&A Demo (企业问答演示)

Enterprise QA Template 是首个受到严格控制的企业知识问答 Agent。

之所以存在这个演示，是因为知识问答的应用范围足以覆盖许多企业，但又足够严格，能够证明 Harness 的价值：检索、证据、引用、模型治理、拒答、工具审批、记忆边界和审计。

公共启动合约位于 [Launch Script](launch-script.md) 中。Receipt 的输出必须遵循 [Governance Receipt Contract](../concepts/governance-receipt-contract.md)、[Trace Event Contract](../concepts/trace-event-contract.md) 以及 [Approval State Contract](../concepts/approval-state-contract.md)。

## 演示流程 (Demo Flow)

```text
Question (提问)
  |
  v
加载 agent.yaml
  |
  v
PolicyEngine.before_retrieval
  |
  v
检索本地知识
  |
  v
评估证据 (Evaluate evidence)
  |
  v
PolicyEngine.before_answer
  | allow                  | deny/escalate
  v                        v
ModelProvider.generate     拒答 / 升级 (Refusal / escalation)
  |
  v
验证器 (Validators)
  |
  v
带引用的回答 (Answer with citations)
  |
  v
可选的工具请求 (Optional tool request)
  |
  v
PolicyEngine.before_tool_call
  |
  v
如果需要则进入审批状态 (Approval state)
  |
  v
JSONL trace + Governance Receipt
```

## 普通 RAG 对比 Harness RAG

该演示必须至少包含一个并排对比的场景：

| 场景 | Plain RAG | Harness RAG |
| --- | --- | --- |
| 支持的问题 | 使用检索到的文本回答 | 带有引用和 trace 的回答 |
| 不支持的问题 | 可能会随意回答 | 拒答或升级 |
| 需调用工具的问题 | 可能会直接调用工具 | 要求进入审批状态 |
| 远程模型问题 | 信任 provider 的输出 | 将 provider 输出通过策略、trace 和验证器处理 |

这种比较是最快说明为什么这个项目不仅仅是另一个 RAG 模板的方法。

## 示例问题

- 支持的: "What is the reimbursement rule for this internal policy?"
- 不支持的: "What discount should we give this customer next year?"
- 需要调用工具的: "Look up customer policy status before answering."

## 验收标准

- 可以通过 `proof-agent run examples/enterprise_qa/agent.yaml` 运行演示。
- deterministic 演示无需 API key；远程 provider 路径是可选的。
- 得到支持的答案包含 citations (引用)。
- 不受支持的答案会引发拒答或升级。
- 需要审批的工具调用在执行前会暂停。
- 每次运行都会写入 `trace.jsonl`。
- 每次运行都会写入满足 receipt 合约的 Governance Receipt。
- README 和 launch script 可以在三分钟内解释清楚演示流程。
- Plain RAG 与 Harness RAG 在不支持的问题上有明显的分歧。