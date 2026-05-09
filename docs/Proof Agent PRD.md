
## 1. 产品目标

快速验证开源 Proof Agent 作为 **Enterprise Agent Delivery Kit** 的可用性和价值。v1 交付一个开箱即用、强受控、可审计的企业知识问答 Agent，帮助企业 AI Agent 负责人快速评估、演示和复用。

Control Envelope 是 v1 的内部机制：用策略、证据、工具审批、记忆边界、JSONL Trace 和 Governance Receipt 包裹 Agent 执行过程。v1 不做通用 governance platform，不做完整 MCP Gateway，不做多模板平台。

**MVP 核心能力：**

1. **受控 Agent 流程**：使用状态机 / workflow 定义可执行流程
2. **Memory 接口**：v1 支持 Session Memory，可审计读写；Task / User Memory 放入后续迭代
3. **Knowledge 接口**：支持整合主流的RAG库，RAG 查询、向量库或简单文档存储
4. **MCP mock tool 审批**：用 1 个 mock tool 证明显式审批状态、拒绝、超时和 Trace
5. **Harness 工程**：整体Agent流程嵌入 Control Envelope，保证流程、输出、工具、记忆和审计可控
6. **交付模板/示例**：v1 只交付企业知识问答 delivery template；其他行业模板后续基于真实需求扩展


---

## 2. MVP 功能列表

| 功能模块                     | 描述               | MVP 要点                                           |
| ------------------------ | ---------------- | ------------------------------------------------ |
| Workflow/Harness Runtime | 定义 Agent 流程，节点可控 | v1 使用 LangGraph，支持条件节点、工具节点、LLM 节点、人工确认节点 |
| Memory Service           | 提供统一 Memory API  | v1 支持 Session Memory；Task/User Memory 后续扩展             |
| Knowledge Service        | 文档检索 + RAG 接口    | v1 支持本地文档 + 本地向量搜索                                    |
| MCP Mock Tool Approval   | 工具审批状态验证     | v1 支持 1 个 MCP mock tool，证明显式审批、拒绝、超时与 Trace                              |
| Enterprise QA Template   | 可运行的交付模板     | v1：企业知识问答 Agent；后续模板只作为 vNext deferred work  |
| Trace & Audit            | 日志、执行追踪、状态记录     | v1 以 JSONL Trace 为审计事实源，并生成 Governance Receipt |
| Demo Comparison          | 对比普通 RAG 与 Harness RAG | 展示普通 RAG 可能直接回答，Harness RAG 会按证据、引用、审批和策略回答或拒答 |
| Deployment               | 一键启动             | Docker Compose 或 Python 环境即可运行                   |

---

## 3. MVP 架构图（概念示意）

```text
+----------------------+
| User Interface / API |
+----------------------+
          |
          v
+----------------------+
| Workflow / Harness   | <- 控制 Agent 流程
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
    | MCP Mock Tool|
    +--------------+
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
| Phase 1 | 技术调研 + 选型（LangGraph + MCP Adapter + Memory + Knowledge） | 2 周 |
| Phase 2 | 最小框架搭建：PolicyEngine、JSONL Trace、LangGraph 流程、Knowledge/Session Memory 接口 | 3 周 |
| Phase 3 | MCP mock tool + 显式审批状态 + 企业知识问答模板 + Governance Receipt        | 2 周 |
| Phase 4 | Docker Compose、CLI、测试矩阵、Plain RAG vs Harness RAG 对比、3-minute launch script、文档、示例流程 | 1 周 |
| Phase 5 | 开源发布 + GitHub Demo                                      | 1 周 |

---

## 6. MVP 成功标准

1. 开源项目可以在 30 分钟内部署完成
2. 用户可以使用企业知识问答模板完成强受控问答：强制检索、证据不足拒答、引用来源、工具审批、Trace 可追踪、Receipt 可阅读
3. Memory / Knowledge / MCP mock tool 可在企业知识问答模板中正常调用
4. 流程完全受控，节点执行顺序、人工确认、工具调用均可追踪
5. GitHub 上至少有 1 个企业知识问答 Demo 流程可运行，并包含 Plain RAG vs Harness RAG 对比、3-minute launch path 和 Governance Receipt Contract


---

## 7. 后续迭代方向

- 支持多 Agent 协作（Crew / Flows）
- 丰富企业模板库（保险、金融、制造、政企场景）
- 增加 GUI 可视化编辑器
- 多 runtime、多 provider 与生产 MCP Gateway
- 多模态 Memory / Knowledge 支持（文档、图像、视频）
- 企业权限管理 / 多租户支持
