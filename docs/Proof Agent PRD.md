
## 1. 产品目标

Proof Agent 的新定位是 **Controlled Agent Harness Framework**：一个面向企业场景的受控 Agent 框架，用 Workflow、Policy、Tool Gateway、Validator、Memory Boundary、Trace 和 Governance Receipt，把 LLM Agent 封装进可编排、可验证、可审批、可审计的执行系统。

长期愿景是企业级 **Agent Control Platform**。v1 不直接做完整平台，而是交付一个 local-first、CLI-first 的最小 Harness Framework MVP，并用一个企业知识问答 reference template 验证框架价值。

Control Envelope 是 Proof Agent 的核心机制：用确定性流程、策略决策、证据评估、工具审批、记忆边界、验证器、JSONL Trace 和 Governance Receipt 包裹 Agent 执行过程。v1 不做 GUI、完整 RBAC、多租户、生产 MCP Gateway 或多模板平台。

**MVP 核心能力：**

1. **Agent Contract**：用 `agent.yaml` 声明 workflow、policy、tools、memory、knowledge、model 和 audit
2. **受控 Agent 流程**：使用状态机 / workflow 定义可执行流程，流程控制权在 Harness，不在 LLM
3. **Policy Engine**：在关键 enforcement points 输出 `allow / deny / require_approval / escalate`
4. **Tool Gateway**：统一工具白名单、风险分级、参数校验、审批状态和审计；v1 用 1 个 MCP mock tool 证明链路
5. **Validator / Evaluator**：提供最小 schema、evidence、tool result、safety、quality 校验
6. **Memory Boundary**：v1 支持 Session Memory，可审计读写；Task / User / Long-term Memory 放入后续迭代
7. **Knowledge Provider**：v1 支持本地知识检索和 Harness RAG；外部 provider 后续扩展
8. **Trace & Governance Receipt**：JSONL Trace 是审计事实源，Governance Receipt 是可读证明
9. **Reference Template**：v1 只交付企业知识问答 reference template；其他行业模板后续基于真实需求扩展


---

## 2. MVP 功能列表

| 功能模块 | 描述 | MVP 要点 |
| --- | --- | --- |
| Agent Contract | 受控 Agent 的公开配置入口 | `agent.yaml` 声明 workflow、knowledge、model、policy、tools、memory、audit |
| Workflow Orchestrator | 定义和执行显式状态机 | v1 使用 LangGraph 实现，但公共心智是 Workflow，不是 LangGraph |
| Policy Engine | 企业规则决策中心 | v1 支持 `before_retrieval`、`before_answer`、`before_tool_call`、`before_memory_write` |
| Tool Gateway | 工具调用统一入口 | v1 支持 MCP mock tool、风险分级、审批状态、拒绝、超时与 Trace |
| Validator / Evaluator | 控制结构、证据、工具结果、安全和质量 | v1 先做确定性校验，不依赖 LLM-as-judge |
| Memory Boundary | 提供受控 Memory API | v1 支持 Session Memory；Task/User/Long-term Memory 后续扩展 |
| Knowledge Provider | 文档检索 + Harness RAG | v1 支持本地文档 + 本地检索；回答必须经过 evidence policy |
| Enterprise QA Template | 第一个 reference template | 验证受控问答、引用、拒答、审批、记忆边界、Trace 和 Receipt |
| Trace & Audit | 日志、执行追踪、状态记录 | v1 以 JSONL Trace 为审计事实源，并生成 Governance Receipt |
| Demo Comparison | 对比 Plain RAG 与 Harness RAG | 展示普通 RAG 可能直接回答，Harness RAG 必须按证据、引用、审批和策略回答或拒答 |
| Deployment | 一键启动 | Docker Compose 或 Python 环境即可运行 |

---

## 3. MVP 架构图（概念示意）

```text
+----------------------+
| User Interface / API |
+----------------------+
          |
          v
+----------------------+
| Workflow Orchestrator|
+----------------------+
          |
          v
+----------------------+
| Policy + Validators  | <- 控制流程、输出、工具、记忆
+----------------------+
          |
   +------+--------+
   |               |
   v               v
+---------+     +-----------+
| Memory  |     | Knowledge |
+---------+     +-----------+
   |               |
   +-------+-------+
           |
           v
    +--------------+
    | Tool Gateway |
    +--------------+
           |
           v
      MCP Mock Tool
           |
           v
      External Tools
```

---

## 4. MVP 非功能需求

- **开箱即用**：提供 Docker Compose，一键启动流程
- **可扩展**：v1 先提供清晰的本地接口与模板约定；外部 Memory/Knowledge/MCP Provider 后续按真实需求扩展
- **可审计**：每个节点执行结果、Memory/Knowledge 读写、MCP 调用记录
- **跨平台**：Python CLI + Docker 本地路径，优先兼容 Linux / Mac；Windows 作为后续验证项
- **开源许可**：MIT / Apache 2.0（方便企业使用）

---

## 5. MVP 交付计划（示例）

| 阶段      | 内容                                                      | 时间  |
| ------- | ------------------------------------------------------- | --- |
| Phase 0 | 文档重构与合约冻结：Controlled Agent Harness Framework 定位、v1 PRD、架构、核心合约 | 1 周 |
| Phase 1 | Framework Skeleton：CLI、Agent Contract、workflow skeleton、PolicyDecision、Trace、Receipt shell、deterministic provider | 2 周 |
| Phase 2 | Harness RAG Reference Template：本地知识检索、evidence evaluator、citation、Plain RAG vs Harness RAG | 2 周 |
| Phase 3 | Tool Gateway + Approval State：MCP mock tool、风险分级、allowlist、审批 granted/denied/timeout | 2 周 |
| Phase 4 | Memory Boundary + Validators：session memory、memory policy、redaction、schema/evidence/tool/safety validators | 2 周 |
| Phase 5 | Release Readiness：Docker Compose、doctor、inspect、README 3-minute launch、CI、Trust Boundaries | 1 周 |

---

## 6. MVP 成功标准

1. 开源项目可以在 30 分钟内完成本地评估
2. `proof-agent demo` 可以在无 API key 情况下运行，证明 Harness lifecycle
3. 用户可以使用企业知识问答 reference template 完成强受控问答：强制检索、证据不足拒答、引用来源、工具审批、记忆边界、Trace 可追踪、Receipt 可阅读
4. Tool Gateway 能证明工具调用必须经过策略、审批、拒绝或超时状态
5. Validator / Evaluator 能证明输出格式、证据、工具结果、安全和基本质量受控
6. 流程完全受控，节点执行顺序、人工确认、工具调用、记忆写入均可追踪
7. GitHub 上至少有 1 个企业知识问答 reference template 可运行，并包含 Plain RAG vs Harness RAG 对比、3-minute launch path 和 Governance Receipt Contract


---

## 7. 后续迭代方向

- Agent Control Platform：Workflow 管理、Prompt 管理、工具管理、策略管理、审批管理、执行日志、质量评估、成本分析
- Plan Controller：支持需求分析、运营分析、代码执行等长任务计划生成、校验、执行和恢复
- 支持多 Agent 协作（Crew / Flows）
- 丰富企业模板库（保险、金融、制造、政企场景）
- 增加 GUI / Admin Console
- 多 runtime、多 provider 与生产 MCP Gateway
- 多模态 Memory / Knowledge 支持（文档、图像、视频）
- 企业权限管理 / 多租户支持
