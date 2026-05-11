# Proof Agent 可行性分析报告

## 1. 结论

Proof Agent 作为 **Controlled Agent Harness Framework** 技术上可行，且方向清晰：不要再把项目限定为本地 RAG demo 或 CLI 工具，而是把 Harness 生命周期管理作为核心价值，用 adapter 接入远程模型、LangChain/LangGraph、向量库、真实 MCP 和 Dashboard。

短期可行性来自当前代码基线：已有 typed contracts、policy gates、deterministic Enterprise QA Template、remote model provider abstraction、tool approval、memory boundary、trace/receipt、RunStore、Dashboard API、CLI、Docker、tests 和 CI。

## 2. 市场与受众

目标受众：

- 企业 AI 平台团队：需要统一治理模型、知识、工具、审批和审计。
- Agent 应用负责人：需要把 demo 变成可评估、可复盘的交付物。
- 安全、合规、架构评审团队：需要结构化 trace 和可读 receipt。
- AI 咨询与交付团队：需要可复用的 Harness 模板，而不是每个项目从 prompt 拼装开始。

市场信号：

- LangGraph、LangChain、CrewAI、LlamaIndex 等框架说明 Agent 编排需求成立。
- MCP 生态说明工具协议正在标准化，但企业仍需要工具审批、权限和审计。
- 向量库和 RAG 已经普及，差异化不在“能检索”，而在“证据不足时能拒答且可证明”。
- 企业采用远程模型是常态，因此项目必须支持 OpenAI-compatible、Azure、Anthropic 等 provider adapter。

## 3. 技术可行性

| 方向 | 可行性 | 关键设计 |
| --- | --- | --- |
| Harness 生命周期 | 高 | Workflow、PolicyEngine、ToolGateway、Validators、Trace、Receipt 已形成清晰边界 |
| 远程模型 | 高 | `ModelProvider` protocol、`openai_compatible`、model trace、model validators 已落地 |
| LangChain/LangGraph | 高 | LangGraph 保持 runtime adapter；LangChain 可作为生态 adapter，不进入 contracts |
| 向量库 | 高 | `[vector]` extra 和 `EvidenceChunk` contract 让 Chroma/Milvus/pgvector 等实现可替换 |
| 真实 MCP | 中高 | 当前 mock 证明审批状态；真实 stdio/HTTP MCP 需作为 ToolGateway adapter 接入 |
| Dashboard | 中高 | 当前已有 FastAPI Dashboard API；完整 UI 和 Approval Console 是后续平台化工作 |
| Docker 部署 | 高 | Dockerfile、docker-compose 已存在；远程 provider 通过 env vars 启用 |

## 4. 关键风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 把 Harness 做成又一个 Agent framework | 高 | 文档和代码都强调 Harness owns control semantics，runtime/provider/tool 是 adapter |
| 远程模型绕过治理 | 高 | `before_model_call`、model trace、schema/safety/citation validators 必须强制执行 |
| MCP 工具面膨胀 | 中 | ToolGateway 做 allowlist、risk level、参数校验、审批和结果标准化 |
| Dashboard 变成第二套执行系统 | 中 | Dashboard API 只读 run artifacts；执行仍通过 Harness workflow |
| 文档互相冲突 | 中 | 保留少量权威文档，删除早期重复计划和评审稿 |
| 企业安全期望过高 | 中 | Trust Boundaries 明确当前控制范围和非目标 |

## 5. 推荐落地策略

1. **先稳定文档信息架构**：`docs/README.md`、PRD、技术设计、concept docs、examples docs。
2. **保留 deterministic baseline**：它是测试和演示底线，不再是产品定位边界。
3. **把生产能力统一纳入 adapter 策略**：remote model、LangChain/LangGraph、vector store、MCP、Dashboard 都遵循 contract-first。
4. **让 Docker 和 CLI 同等重要**：CLI 适合开发者，Docker 适合企业评估和部署路径。
5. **逐步平台化**：Dashboard UI、Approval Console、RBAC、多租户和 hosted control plane 必须建立在 trace/receipt/run store 之上。

## 6. 总结

Proof Agent 的机会不在“再做一个 RAG/Agent demo”，而在提供企业可以理解和治理的 Agent Harness：流程由 Harness 控制，模型只生成候选内容，工具必须审批，证据必须支撑，输出必须验证，所有结果都能审计。
