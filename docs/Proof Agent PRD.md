# Proof Agent PRD

## 1. 产品定位

Proof Agent 是 **Controlled Agent Harness Framework**：用 Harness Engineering 管理 Agent 生命周期，把 LLM、工具、知识、记忆和运行时放入可编排、可审批、可验证、可审计的 Control Envelope。

核心产品判断：

- **Harness 是主产品**：Workflow、PolicyEngine、Tool Gateway、Validators、Memory Boundary、Trace 和 Governance Receipt 是一等能力。
- **模型和运行时是 adapter**：远程模型、LangChain/LangGraph、向量库、真实 MCP、Dashboard 都接入 Harness，而不是替代 Harness。
- **确定性 demo 是回归基线，不是产品边界**：项目不再定义为 local-first；本地 deterministic path 用于证明治理链路和保障测试。
- **CLI 与 Docker 是当前发布入口**：项目不再定义为 CLI-first；CLI、Docker、Dashboard API 都是受控 Harness 的入口或观察面。

长期愿景是企业级 **Agent Control Platform**。当前阶段先把框架的控制语义、合约、adapter 边界和可运行 Enterprise QA Template 做扎实。

## 2. 目标用户

- 企业 AI 平台团队：需要把远程模型、工具、知识库和审批纳入统一治理。
- Agent 应用负责人：需要证明 Agent 为什么回答、拒答、调用工具或等待审批。
- 安全、合规和架构评审人员：需要可读 receipt 和可机器处理 trace。
- AI 咨询与交付团队：需要可复用的受控 Agent 交付骨架。

## 3. 核心能力

| 能力 | 产品要求 |
| --- | --- |
| Agent Contract | 用 `agent.yaml` 声明 workflow、knowledge、model、policy、tools、memory、audit |
| Workflow | Harness 控制流程状态迁移，模型只在受控节点内生成内容 |
| PolicyEngine | 在 retrieval、answer、tool、memory、model call 等 enforcement point 输出类型化决策 |
| Model Provider | 支持 deterministic baseline 和远程 provider；远程输出必须经过 validators |
| Knowledge Provider | 支持本地文档、向量库和远程企业知识源 adapter；统一返回 `EvidenceChunk` |
| Tool Gateway / MCP | 所有工具调用经过 allowlist、参数校验、风险分级、审批和 trace |
| Memory Boundary | memory read/write 有 policy、redaction、retention 和 tenant boundary 设计 |
| Validators | schema、evidence、citation、safety、tool result 等准入控制 |
| Trace & Receipt | JSONL Trace 是事实源；Governance Receipt 是人类可读证明 |
| Dashboard | Dashboard API 查询 runs、trace、receipt、stats；UI/Approval Console 作为平台化演进 |
| Deployment | CLI 与 Docker 都能运行 deterministic demo；远程能力通过环境变量和 optional extras 启用 |

## 4. 当前 MVP 范围

当前可运行 MVP 聚焦 Enterprise QA Template，证明完整 Harness lifecycle：

1. 加载 `agent.yaml`。
2. 执行 policy gate。
3. 检索知识并评估 evidence。
4. 调用 deterministic 或 remote model provider。
5. 处理 tool approval。
6. 控制 memory write。
7. 运行 validators。
8. 写入 trace、receipt 和 run history。
9. 通过 CLI、Docker 或 Dashboard API 观察结果。

当前 deterministic demo 的验收结果：

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

> 注意：代码中的枚举值应以实现为准；文档中的示例必须在验证时同步检查。

## 5. 非目标

当前阶段不承诺：

- 完整托管多租户控制台。
- 生产级 RBAC / IAM / OAuth / DLP。
- 所有 MCP server 的兼容性。
- 对任意 prompt injection 的完全免疫。
- LLM-as-judge 替代 deterministic validators。
- 多 Agent 平台、模板市场或 hosted control plane。

这些是平台化方向，但必须在 Control Envelope 语义稳定后逐步加入。

## 6. 成功标准

- 企业评审者能在 30 分钟内跑通 CLI 或 Docker demo。
- deterministic demo 不需要 API key，且覆盖 answer、refusal、approval-wait 三类结果。
- 远程模型 path 不能绕过 policy、evidence、validator、trace 和 receipt。
- Tool Gateway 能证明真实 MCP 接入前后的工具治理语义一致。
- Dashboard API 能基于 run artifacts 查询执行历史，而不是另起一套执行语义。
- 文档体系清晰：AI 先读 `docs/README.md`，架构先读 `docs/Proof Agent 技术设计方案.md`。

## 7. 演进路线

| Phase | 目标 | 关键输出 |
| --- | --- | --- |
| 0 | 合约与定位 | PRD、技术设计、concept docs、Agent Contract |
| 1 | Deterministic Harness MVP | CLI、Docker、Enterprise QA Template、Trace、Receipt |
| 2 | Model Provider Governance | remote model provider、model trace、model validators |
| 3 | Observability & Dashboard API | RunStore、runs/history、health/runs/stats API |
| 4 | Production Adapters | LangChain/LangGraph、真实 MCP、vector store、Azure/Anthropic、streaming |
| 5 | Agent Control Platform | Dashboard UI、Approval Console、RBAC、多模板、多 Agent、外部观测导出 |
