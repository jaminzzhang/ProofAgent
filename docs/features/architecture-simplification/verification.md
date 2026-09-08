# 架构简化分析与验证 — 2026-09-08

[COMPUTED | HIGH] 本次完成可验证的依赖方向修正和退役代码清理，声明范围为
`LOCAL_VERIFIED`。真实外部服务、PostgreSQL/S3 集成和生产发布仍为
`PARTIAL_VERIFICATION`，不因本次测试通过改变发布权限。

## 目标、范围与依据

用户授权分析当前项目、优化架构、删除无用代码。按行为保护重构执行，由当前
Agent 自检，不声称独立 Review。起点 `838ea63`，开始时工作区干净；最终改动
保留在工作区，未提交、推送或部署。

依据：`AGENTS-COMMON.md`、README、PRD、technical-design、development-progress、
ADR-0242/0249 的现行规则及外部知识库配置文档。历史记忆仅用于提醒先核查当前
边界；其中 KSS-only 描述已失效，不作为本次实现依据。

## 当前架构判断

[INFERRED | HIGH] 当前项目适合继续维持模块化单体：一个 Control Plane，配合
同一镜像的 API/Executor 进程角色。此次没有证据支持增加微服务、事件总线或通用
插件框架；优先减少反向依赖和孤立实现。

| 层/节点 | 当前责任与证据 | 本次判断 |
| --- | --- | --- |
| Delivery / Bootstrap | `delivery/api.py`、`bootstrap/composition.py`；入口、依赖装配 | 保留单一受控执行入口 |
| Control | `control/workflow/controlled_react/`；规划约束、工具权限、观察提交、答案验证 | 保留模型提议与执行授权分离 |
| Contracts / Ports | `contracts/`、`contracts/ports/`；共享数据和能力边界 | 修正 PublishedAgent 的归属 |
| Capabilities | `bootstrap/external_knowledge.py` 装配 Dify/Agentset，独立 guarded transport | 保留 provider-neutral port 和出站权限 |
| Persistence / Observability | PostgreSQL 可变状态、S3 工件、Trace/Receipt 投影 | 不改变事务、租约、fencing 或存储格式 |
| Dashboard / Operator | 现行产品面，Customer/handoff 已退出 | 清理未使用的交接类型和文案 |

[KNOWN | HIGH] 扫描 `control/` 和 `contracts/` 的 AST 时发现两个 Control 模块
从 `delivery.published_agents` 导入纯数据对象。这会连带导入 registry、本地配置
存储和加载器。当前已改为直接依赖 `contracts.published_agent`。

[KNOWN | HIGH] 原 `control/customer.py` 与 `control/memory/extractor.py` 的公开
符号在产品代码、测试和活动前端中没有调用方；全仓引用仅剩自身及历史计划。
FastAPI 装饰器函数、注册表、fixture 和测试专用适配器另行核实，未把零文本引用
直接视为无用代码。

## 任务树与验收

```text
G1 简化当前架构
├─ T1 / AC1 修正 Control → Delivery 反向依赖：已验证
├─ T2 / AC2 删除确认孤立的旧产品实现：已验证
└─ T3 / AC3 同步活动架构文档并验证行为：已验证
```

| 任务 | 实际改动 | 验收结果 |
| --- | --- | --- |
| T1 | PublishedAgent 数据类移入 `contracts/published_agent.py`；生产准入、发布、运行提交、执行与测试统一导入 | 字段、默认值、冻结语义保持；AST 门禁禁止 Control/Contracts 导入 Delivery |
| T2 | 删除 Customer 授权辅助模块 46 行、Memory 提取器 196 行、Dashboard 交接类型 17 行和文案 18 行 | 共 277 行确认孤立的代码/声明被移除；未删除测试或降低断言 |
| T3 | technical-design 正文以 Dify/Agentset 外部绑定替代现行 KSS-only 描述；文档索引改为活动配置指南 | 文档与当前规则一致；本地行为检查完成 |

## 验证记录

工作目录为仓库根目录，命令使用已有 `.venv`，未读取 `.env` 或连接生产。

| 证据 | 命令/场景 | 实际结果 |
| --- | --- | --- |
| E1 基线 | pytest：dependency_layout、production_agent_readiness、production_agent_configuration_service、published_agent_materializer、run_execution_service、run_submission_service、memory_admission、memory_boundary | 修改前 39 passed |
| E2 架构 RED | `pytest tests/test_dependency_layout.py::test_control_and_contracts_do_not_depend_on_delivery -q` | 原实现失败，定位两个反向导入；不是环境失败 |
| E3 回归 GREEN | 与 E1 相同的 8 个测试文件 | 40 passed，含新增架构门禁 |
| E4 全后端 | `.venv/bin/python -m pytest tests/ -q` | 2694 passed、109 skipped、2 deselected；8 个回环 socket PermissionError |
| E5 环境补验 | 沙箱外 pytest：test_mcp_discovery.py、test_remote_verify_gateway.py、test_remote_verify_gateway_regression_1.py、test_tool_gateway.py | 45 passed，覆盖 E4 的全部 8 个失败；其余 37 项与 E4 重叠，不重复计数 |
| E6 静态 | `.venv/bin/ruff check proof_agent tests`；`.venv/bin/mypy proof_agent` | 通过；Mypy 396 source files |
| E7 前端 | `npm run typecheck`；`npm test`；`npm run build` | 通过；Dashboard 241、Chat 35 tests；现有 chunk size 提示 |
| E8 文档 | `python3 scripts/check-domain-contexts.py`；`git diff --check` | 通过 |

[COMPUTED | HIGH] E4 与 E5 合计覆盖 2702 个通过的不同后端测试，不能表述为一次
完整无跳过的测试运行。109 个跳过及 2 个默认 deselected 仍未验证。
Authlib 弃用与 Pydantic serializer 提示不由本次改动引入。

## 自检与保留理由

- [KNOWN | HIGH] 保留 Customer/Handoff 历史数据契约、响应校验和 trace 展示：
  它们不等于当前客户产品，不能通过删字段破坏记录读取或严格校验。
- [KNOWN | HIGH] 保留 KSS 历史发布/拒绝代码：
  `test_production_agent_readiness.py` 明确验证历史版本可读取但不能 ready/queued。
  清理它们需要独立确定历史数据迁移和拒绝契约，本次没有改变这些语义。
- [KNOWN | HIGH] `llama_index_bridge.py` 没有主运行路径调用方，但仍有专门测试与
  `tree` 可选依赖安装契约。没有将测试支撑的能力直接归类为可无条件删除。
- [INFERRED | MED] `configuration/local_store.py`、AgentConfigurationWorkspace、
  ReAct orchestrator 仍较大；文件行数不能证明它们的职责可安全拆分。
  后续应随具体行为变更提取稳定边界，避免单纯拆文件产生更多跳转。

本次未发现需要撤销改动的行为回归。结论限于上述扫描和测试；不保证全仓再无死代码，
也不宣称所有架构耦合都已消除。Control 对 Bootstrap/具体能力仍有依赖，未扩张本次
Delivery 边界门禁为不符合现状的“全量 Clean Architecture”声明。

## 被测差异标识

基准 `838ea63`；将本次 Git 变更/新增的 `.py`、`.ts`、`.tsx` 路径排序，
逐项拼接 `path + NUL + file bytes（删除项为 <deleted>）+ NUL`，计算 SHA-256：

`478b5d736ad2c629f6cc56839a872ac201585d56218115d3647d5b521a713fd7`
