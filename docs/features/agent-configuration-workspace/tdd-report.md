# Agent Configuration Workspace TDD 报告

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `PARTIAL_VERIFICATION` |
| 最高风险等级 | P1 |
| 模式 | 行为保护重构；Slice 1、2、3 已完成本地验证与独立复验 |

## 2. 测试目标与范围

| 项 | 内容 |
| --- | --- |
| 测试目标 | 证明 Delivery 可通过 Workspace interface 完成 Draft lifecycle、development validation 与 development publication |
| 测试范围 | Control module、focused persistence ports、Local/PostgreSQL adapters、Delivery routes、本地 validation/publication adapters |
| 不覆盖范围 | production validation/publish endpoint、正式 Phase F publisher、rollback、Contract/Workflow/Skill 编辑、生产部署 |

## 3. 测试场景

| 编号 | 场景 | 类型 | 优先级 | 风险等级 |
| --- | --- | --- | --- | --- |
| ACW-T01 | 多 Agent inventory 在 Workspace 内聚合 | contract | P1 | P1 |
| ACW-T02 | production sole-Agent scope 失败关闭 | security/contract | P1 | P1 |
| ACW-T03 | 元数据更新 revision CAS 与 audit 原子提交 | consistency | P1 | P1 |
| ACW-T04 | 版本列表返回 Published history 与 active pointer | contract | P1 | P1 |
| ACW-T05 | Delivery 不读取具体 Local store | architecture | P1 | P1 |
| ACW-T06 | validation execution、Capture 与 Draft 身份一致 | contract/security | P1 | P1 |
| ACW-T07 | validation CAS、audit 与事务失败关闭 | consistency | P1 | P1 |
| ACW-T08 | validation route 返回稳定 404/409/500 | API/security | P1 | P1 |
| ACW-T09 | publication 只接受当前 Draft revision 的成功且无 blocker validation | authority/consistency | P1 | P1 |
| ACW-T10 | version、activation 与 audit 原子提交并受 Draft/pointer CAS 保护 | consistency/concurrency | P1 | P1 |
| ACW-T11 | publish route 只依赖 Workspace | architecture | P1 | P1 |

## 4. Given-When-Then 用例

| 编号 | Given | When | Then |
| --- | --- | --- | --- |
| ACW-T01 | repository 含多个 Agent Draft | 调用 `list_agents` | 返回每个 Agent 的 Draft/version/active 汇总 |
| ACW-T02 | Workspace 配置 sole-Agent scope | 读取其他 Agent | 返回稳定 not-found，不查询 fallback |
| ACW-T03 | 当前 revision 与虚构 operator actor | 调用 metadata update | Draft revision 增加，audit 与 Draft 同事务提交 |
| ACW-T04 | 一个 Published Version 和 active pointer | 调用 `list_versions` | 返回不可变 history 与 active ID |
| ACW-T05 | Delivery 注入 recording Workspace | 调用 HTTP route | route 只映射 request/response，不组合 storage 规则 |
| ACW-T06 | adapter 返回不一致 execution/capture identity 或双重 capture 状态 | 调用 `validate_draft` | 拒绝绑定，不写 Draft/audit |
| ACW-T07 | 并发 revision、audit append 或 commit 失败 | 持久化 Validation Record | 保留原 Draft，不产生部分审计写入 |
| ACW-T08 | Workspace 返回 not-found、conflict 或含内部路径的非预期异常 | 调用 validation route | 返回稳定 404/409/500 detail，不泄漏内部路径 |
| ACW-T09 | Draft 有失败 outcome、缺失、旧 revision 或带 blocker 的 Validation Record | 调用 `publish_draft` | 返回稳定 precondition error，不创建 version 或 activation |
| ACW-T10 | Draft 与 active pointer expectation 均匹配 | 发布 | immutable version、activation 与 audit 同事务提交；冲突不覆盖赢家 |
| ACW-T11 | 应用只注入 recording Workspace | 调用 publish route | route 不需要 Local store、compiler 或 RunStore |

## 5. Mock、数据与断言

| 项 | 规则 | 风险 |
| --- | --- | --- |
| In-memory UoW | 仅替代 persistence seam，不 mock Workspace 内部实现 | P1 |
| Agent 数据 | 使用虚构 ID、时间和 actor，不读取生产数据 | P1 |
| 断言 | 面向 Workspace 返回值、revision、audit 和稳定错误 | P1 |

## 6. RED-GREEN-REFACTOR 记录

| 步骤 | 行为 | 文件 | 结果 |
| --- | --- | --- | --- |
| RED-1 | 先写多 Agent inventory/read/update 行为测试 | `tests/test_agent_configuration_workspace.py` | 因 `proof_agent.control.agent_configuration_workspace` 不存在而失败 |
| GREEN-1 | 建立 Workspace interface，把 scope、summary、CAS 与 audit 收入 Control | `proof_agent/control/agent_configuration_workspace.py` | 新模块行为测试通过 |
| RED-2 | 要求 Local Configuration UoW 适配既有配置根目录 | `tests/test_local_persistence_bundle.py` | `LocalPersistenceBundle.create` 不接受 `configuration_root` 而失败 |
| GREEN-2 | 让 Local UoW 对显式配置根和 audit 根执行同一 staged commit | `proof_agent/capabilities/persistence/local/bundle.py` | 新旧 Local UoW 行为测试通过 |
| REFACTOR | development/production composition 与首批 route 统一注入 Workspace；删除旧 production-only module 名称与 app state | Delivery、composition、production tests | 76 个聚焦测试通过，4 个依赖外部环境的测试跳过 |

## 7. 修改文件清单

| 文件 | 修改类型 | 说明 |
| --- | --- | --- |
| `proof_agent/control/agent_configuration_workspace.py` | 新增/替换 | deep application module 与稳定结果类型 |
| `proof_agent/capabilities/persistence/local/bundle.py` | 修改 | 既有 Local 配置根的 focused UoW adapter |
| `proof_agent/observability/api/app.py` | 修改 | development/production 统一 Workspace composition |
| `proof_agent/delivery/configuration_api.py` | 修改 | inventory/read/update/version list 改走 Workspace |
| `proof_agent/delivery/production_agent_configuration.py` | 修改 | production Delivery 改用通用 Workspace 错误与 app state |
| `tests/test_agent_configuration_workspace.py` | 新增 | 多 Agent、CAS、audit、无 publication 行为测试 |
| production/API/persistence tests | 修改 | 删除旧命名并保护现有接口行为 |
| 本报告与领域上下文 | 新增/修改 | 记录范围、术语和验证证据 |

## 8. 受限命令执行记录

| 命令 | 范围 | 是否执行 | 结果 | 未执行原因 |
| --- | --- | --- | --- | --- |
| `.venv/bin/python -m pytest ...` | Workspace、development/production API、Local adapter、composition | 是 | 76 passed，4 skipped | 无 |
| PostgreSQL/port 聚焦 Pytest | PostgreSQL adapter 与 persistence contracts | 是 | 13 passed，9 skipped | PostgreSQL 集成环境未配置 |
| 聚焦 Ruff | 本切片 Python 文件 | 是 | 通过 | 无 |
| 聚焦 Mypy | 本切片 6 个 source 文件 | 是 | 通过 | 无 |
| `.venv/bin/python -m pytest tests -q` | backend 全量 | 是 | 1839 passed，120 skipped，2 deselected，1 个既有 Authlib warning | 首轮 8 个回环端口测试受沙箱限制；允许本机回环后同命令通过 |
| Ruff、Mypy、domain-context、diff | repository 静态检查 | 是 | 全部通过；Mypy 覆盖 346 个 source 文件 | 无 |
| `npm test` | Dashboard 全量 | 是 | 32 个文件、195 个测试通过 | 无 |
| `npm run build` | Dashboard production build | 是 | 通过 | 无 |

## 9. Slice 2 TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 受控实现与行为保护重构 |
| 公开 interface | `AgentConfigurationWorkspace.validate_draft(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent 修正后复验 `PASS` |
| 不测试的实现细节 | 私有 helper、adapter 内部编译目录、内部调用次数 |
| 范围外 | production endpoint、publication、rollback、Contract/Workflow/Skill 编辑、schema、部署 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-3 | Workspace validation interface 行为 | `tests/test_agent_configuration_workspace.py` | 因 `AgentConfigurationValidationExecution` 尚不存在而失败 |
| GREEN-3 | Workspace 保存 revisioned Validation Record、Draft operation audit 与全局 audit | `proof_agent/control/agent_configuration_workspace.py` | module 行为测试通过 |
| RED-4 | validation route 只依赖 Workspace，不配置 concrete store | `tests/test_agent_configuration_api.py` | 旧 route 返回 HTTP 500 |
| GREEN-4 | route 委托 Workspace；Local adapter 承担 compile、Harness、Run artifact 与 Full Capture | `proof_agent/delivery/agent_configuration_validation.py`、`configuration_api.py` | validation API 行为通过 |
| REFACTOR-2 | 删除 Delivery capture/warning helpers 和零调用的 `LocalAgentConfigurationStore.record_validation` | Delivery 与 Local store | 聚焦回归 79 passed、4 skipped |
| VERIFY-MAIN-2 | 主代理全量验证 | backend、Dashboard、静态检查 | backend 1842 passed、120 skipped、2 deselected；Dashboard 195 passed；build、Ruff、Mypy、domain-context、diff 全部通过 |
| VERIFY-AGENT-1 | 独立子 Agent 按明确清单复核 Slice 2 | 45 passed、4 skipped；Ruff、Mypy、domain-context、diff、AST 删除检查通过 | `PASS_WITH_FINDINGS`：无 P0/P1；提出 Capture 身份、稳定 500、负向测试、UoW 类型和文档漂移问题，均已进入修正 |
| REFACTOR-3 | 收口独立复核发现项 | 强类型 Capture、证据身份/互斥、稳定 500、失败关闭测试、focused UoW 类型、文档一致性 | 聚焦验证 56 passed、4 skipped |
| VERIFY-MAIN-3 | 发现项修正后重跑主代理全量门禁 | backend、Dashboard、静态检查 | backend 1853 passed、120 skipped、2 deselected；Dashboard 195 passed；build、Ruff、Mypy（347 source files）、domain-context、diff 全部通过 |
| VERIFY-AGENT-2 | 同一独立子 Agent 复验首轮发现项与完整切片 | 56 passed、4 skipped；Ruff、Mypy、domain-context、diff、AST 删除与生命周期检查全部通过 | `PASS`；未发现 P0–P3 未关闭问题 |

## 10. Slice 3 TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 受控实现与行为保护重构 |
| 公开 interface | `AgentConfigurationWorkspace.publish_draft(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；首轮发现修正后，同一独立子 Agent 复验 `PASS` |
| 不测试的实现细节 | 私有 helper、UUID 具体值、adapter 内部编译目录、内部调用次数 |
| 范围外 | rollback、production publish endpoint、正式 Phase F publisher、Contract/Workflow/Skill 编辑、schema、部署 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-5 | Workspace publication authority 行为 | `tests/test_agent_configuration_workspace.py` | 因 `AgentConfigurationPublicationValidator` 尚不存在而导入失败 |
| GREEN-5 | Workspace 校验当前 Validation Record，冻结 version facts，并以 Draft/pointer CAS 原子提交 version、activation 与 audit | `proof_agent/control/agent_configuration_workspace.py` | 首个 publication 行为测试通过 |
| RED-6 | publish route 只依赖 Workspace，不配置 concrete store | `tests/test_agent_configuration_api.py` | 旧 route 返回 HTTP 500 |
| GREEN-6 | route 委托 Workspace；Local adapter 只做 package/live-asset publication validation | `proof_agent/delivery/agent_configuration_publication.py`、`configuration_api.py` | route 删除测试与真实 API publication 回归通过 |
| REFACTOR-4 | 增加 stale/missing/blocked、Draft conflict、pointer conflict、事务回滚、稳定错误码和 AST 删除保护 | Workspace、API 与 Local publication validation | 聚焦 136 passed、11 skipped；Ruff、Mypy 通过 |
| VERIFY-MAIN-4 | 主代理执行首轮仓库级门禁 | backend、前端、静态与领域检查 | backend 1867 passed、120 skipped、2 deselected；Dashboard 195、Chat 35；typecheck、两端 build、Ruff、Mypy（348 source files）、domain-context、diff、`uv lock --check` 全部通过 |
| VERIFY-AGENT-3 | 独立子 Agent 按明确清单首轮复核 | Scope→diff、AST、authority/CAS/error mapping、聚焦门禁 | `FAIL`：发现失败 outcome 可发布、真实 Local UoW lost update 两个 P1，以及原始 ValueError 400 泄漏一个 P2 |
| RED-7 | 锁定首轮发现项 | failed outcomes、两个真实 Local UoW 交错提交、ValueError 内部路径 | 5 个新增场景均在旧实现失败 |
| GREEN-7 | 实施失败 outcome Gate、外置共享锁下的事务基线摘要 CAS、稳定 400 映射 | Workspace、Local store/UoW、Delivery | 新增场景通过；交错 publication 只保留赢家的 version、pointer 与 audit |
| VERIFY-MAIN-5 | 发现项修正后重跑仓库级门禁 | backend、前端、静态与领域检查 | backend 1872 passed、120 skipped、2 deselected；聚焦 141 passed、11 skipped；Dashboard 195、Chat 35；typecheck、两端 build、Ruff、Mypy（348 source files）、domain-context、diff、`uv lock --check` 全部通过 |
| VERIFY-AGENT-4 | 同一独立子 Agent 复验首轮发现项与完整 Slice 3 | failed outcome、Local writer interleaving/restore、HTTP probes、AST、production isolation、聚焦门禁 | `PASS`；141 passed、11 skipped；Ruff、Mypy（11 files）、domain-context、diff 通过；未发现 P0–P3 未关闭问题 |

## 11. 风险与待确认问题

| 问题 | 等级 | 影响 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| rollback、Contract/Workflow/Skill 编辑和 canonical seed bootstrap 仍直接依赖 Local store | P1 | Workspace 尚未完全深化 | 按独立 Scope 继续迁移；不在 Slice 3 中扩张范围 | 研发负责人未指定 |
| 本地 adapter 在 publication CAS 前可能留下 derived compiled package | P2 | 不形成 authoritative Published Version 或 active pointer，但需要后续清理策略 | 在 artifact lifecycle 切片中定义清理与重试；当前以 CAS 失败关闭权威写入 | 研发负责人未指定 |
| Local UoW 未证明双目录替换中进程崩溃的 durable crash-atomic recovery | P2 | development-only 无锁 reader 可能短暂观察切换；不能作为生产事务证据 | 保持 S0 development-only；生产继续使用 PostgreSQL，若提升本地耐久等级需独立设计 generation/recovery protocol | 研发负责人未指定 |
| 本地验证不等于生产批准 | P1 | 不能证明真实 PostgreSQL/部署状态 | 维持 `PARTIAL_VERIFICATION` | 发布负责人未指定 |

## 12. 上下文更新建议

| 建议位置 | 类型 | 内容摘要 | 原因 |
| --- | --- | --- | --- |
| Agent Configuration context | 术语 | Workspace interface 与 focused persistence seam | 保持架构语言一致 |
| `docs/PROJ_CONTEXT.md` | Feature 状态 | 记录本切片状态和证据路径 | 供后续切片定位 |
