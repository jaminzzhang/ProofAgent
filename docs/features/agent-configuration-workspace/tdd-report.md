# Agent Configuration Workspace TDD 报告

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | Slice 8D KSS Knowledge binding 主代理 `LOCAL_VERIFIED`；独立复验 `PASS_WITH_ENV_LIMITATION` |
| 最高风险等级 | P1 |
| 模式 | 行为保护重构；Slice 1—7 已完成本地验证与独立复验；Slice 8A/8B/8C 依次恢复 Production Contract、Workflow 与 Skill Pack 交互；Slice 8D 恢复 KSS exact Release Draft candidate 交互 |

## 2. 测试目标与范围

| 项 | 内容 |
| --- | --- |
| 测试目标 | 证明 Delivery 可通过 Workspace interface 完成 Draft lifecycle、development validation/publication、Agent Version pointer rollback、Workflow Stage Configuration、raw Contract、Skill Pack 专用编辑，以及 Production Contract、Workflow、Skill Pack 与 KSS Knowledge Draft candidate 保存/预览 |
| 测试范围 | Control module、focused persistence ports、Local/PostgreSQL adapters、Development/Production Delivery routes、本地 inspectors、KSS management catalog seam 与 Dashboard capability 驱动流程 |
| 不覆盖范围 | production validation/publish、正式 Phase F publisher、executable KSS binding/profile、Source rollback-Draft、Blue/Green deployment rollback、canonical seed bootstrap |

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
| ACW-T12 | rollback target 必须是同一 Agent 的 immutable Published Version | authority | P1 | P1 |
| ACW-T13 | rollback activation 与 audit 原子提交并受 exact pointer CAS 保护 | consistency/concurrency | P1 | P1 |
| ACW-T14 | rollback route 只依赖 Workspace，错误 detail 稳定 | architecture/security | P1 | P1 |
| ACW-T15 | rollback 不修改 version history，不重算 target KSS binding | authority/negative | P1 | P1 |
| ACW-T16 | Stage 保存一次原子替换 template、descriptor version 与 stages | authority/contract | P1 | P1 |
| ACW-T17 | Stage 保存以调用方 revision CAS，并覆盖编译期间并发写入 | consistency/concurrency | P1 | P1 |
| ACW-T18 | Stage audit 与 Draft 同事务提交且不含 Prompt 文本 | security/consistency | P1 | P1 |
| ACW-T19 | Stage preview 脱敏且不执行模型、工具、Run 或状态写入 | security/negative | P1 | P1 |
| ACW-T20 | Stage route 只依赖 Workspace；Dashboard 只发送一次保存命令 | architecture | P1 | P1 |
| ACW-T21 | raw Contract 整包候选先校验，再以 revision CAS 保存并原子追加双层 audit | authority/consistency | P1 | P1 |
| ACW-T22 | stale revision、adapter、audit 或 commit 失败时不覆盖 Draft 且不产生部分 audit | concurrency/fault | P1 | P1 |
| ACW-T23 | Contract GET/PATCH route 只依赖 Workspace，并返回稳定 400/404/409/500 | architecture/security | P1 | P1 |
| ACW-T24 | Dashboard Contract 保存携带当前 Draft revision，未知请求字段被拒绝 | contract | P1 | P1 |
| ACW-T25 | Skill Pack GET/POST/PATCH/DELETE route 只依赖 Workspace | architecture | P1 | P1 |
| ACW-T26 | 完整 Skill Pack create 一次原子更新 binding 与 definition | authority/consistency | P1 | P1 |
| ACW-T27 | Skill Pack mutation 使用调用方 revision CAS，并覆盖 inspection 期间并发写入 | concurrency | P1 | P1 |
| ACW-T28 | Skill Pack audit 与 Draft 同事务提交且不含 Prompt、intent 或 raw YAML | security/consistency | P1 | P1 |
| ACW-T29 | Local inspector 自动清理派生包并只返回逻辑路径；Dashboard create 只发一次命令 | architecture/security | P1 | P1 |
| ACW-T30 | Draft KSS candidate 只包含 exact Space/Base/Base Version/Release identity | authority/contract | P1 | P1 |
| ACW-T31 | KSS catalog unavailable、retired、missing 或 parent mismatch 失败关闭且无 fallback | authority/security | P1 | P1 |
| ACW-T32 | KSS candidate 使用 Draft revision CAS，并与 Draft/global audit 原子提交 | consistency/concurrency | P1 | P1 |
| ACW-T33 | Production Knowledge route 强制 Agent 与 KSS 权限，返回稳定 400/404/409/500/503 | API/security | P1 | P1 |
| ACW-T34 | Dashboard 409 保留 exact Release 选择、冻结重放并要求显式 Reload Latest | concurrency/UX | P1 | P1 |

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
| ACW-T12 | target 缺失或属于其他 Agent | 调用 `rollback_version` | 返回稳定 not-found，pointer/audit 不变 |
| ACW-T13 | target 存在且 current pointer 已读取 | 回滚 | exact CAS、activation 与 audit 同一 UoW；并发冲突不覆盖赢家 |
| ACW-T14 | 应用只注入 recording Workspace，或 Workspace 抛内部异常 | 调用 rollback route | route 不需要 Local store；返回稳定 404/409/400/500 detail |
| ACW-T15 | target Published Version 包含 immutable runtime facts | 回滚 | 返回同一 target version 投影；不改任何 Published Version，不调用 Phase F 或部署 rollback |
| ACW-T16 | 当前 Draft 与合法 Stage command | 调用 `update_workflow_stages` | 一个新 revision 同时包含 template、descriptor version 与 stages |
| ACW-T17 | stale client revision，或 inspection 后发生并发写入 | 保存 Stage command | 返回稳定 conflict，不覆盖并发赢家 |
| ACW-T18 | Stage Prompt 含敏感业务文本，或 audit commit 失败 | 保存 Stage command | audit 只含 trace-safe metadata；失败时 Draft 与 audit 均不变 |
| ACW-T19 | 当前 Draft 可解析，且 Stage/context 合法 | 调用 `preview_workflow_stage` | 返回限长脱敏投影，不新增 Draft、audit、trace 或 Run |
| ACW-T20 | API 注入 recording Workspace，Dashboard 编辑 Stage | 保存或预览 | route 不组合 store/compiler/YAML；Dashboard 不先保存 raw Contract |
| ACW-T21 | 当前 revisioned Draft 与三个可选 YAML 文件 | 调用 `update_contract` | 整包候选先校验，再以 revision CAS 保存 Contract 与双层 audit |
| ACW-T22 | stale revision、校验期间并发写入、audit 或 commit 失败 | 保存 raw Contract | 不覆盖赢家；Draft 与 audit 不产生部分写入 |
| ACW-T23 | 应用只注入 recording Workspace，或 Workspace/adapter 抛错 | 调用 Contract GET/PATCH | route 不需要 Local store/compiler；返回稳定 400/404/409/500 且不泄漏路径 |
| ACW-T24 | Dashboard 有当前 Draft revision，或请求含未知字段 | 保存 raw Contract | client 发送 revision；未知字段在 Workspace 前返回 422 |
| ACW-T25 | API 只注入 recording Workspace | 调用四个 Skill Pack route | route 不需要 Local store、compiler、manifest 或 YAML |
| ACW-T26 | revisioned Draft 与完整 create command | 创建 Skill Pack | 一个新 revision 同时包含 binding、definition 和所有编辑字段 |
| ACW-T27 | stale revision，或 inspection 后发生并发写入 | 创建、更新或删除 Skill Pack | 返回稳定 conflict，不覆盖并发赢家 |
| ACW-T28 | Prompt/intent 含敏感业务文本，或 audit/commit 失败 | 保存 Skill Pack | audit 只含 trace-safe identity metadata；Draft 与 audit 原子回滚 |
| ACW-T29 | 当前 Draft 可解析，Dashboard 完成 create drawer | 读取/保存 Skill Pack | 临时目录返回前清理，只返回包内逻辑引用；浏览器只发送一次 create command |
| ACW-T30 | live KSS catalog 含一个 queryable Release | 保存 Draft candidate | 只持久化四个 exact identity，不包含 credential、scorer 或内容 |
| ACW-T31 | KSS unavailable、Release retired/missing 或父级 identity 不匹配 | 保存 Draft candidate | 返回稳定错误；Draft、audit 与当前 Active Version 不变；不查询本地 fallback |
| ACW-T32 | 当前 Draft revision 与 actor | 保存合法 candidate | revision +1，Draft operation audit 与 global audit 同一 UoW 提交；stale 或 fault 不产生部分写入 |
| ACW-T33 | Production route 收到合法、未知字段或依赖异常 | GET/PATCH Knowledge binding | 双权限与 strict body 生效；错误 detail 稳定且不泄漏内部路径 |
| ACW-T34 | Operator 选择 Release 后发生 409 | 再次保存 | 保留本地选择但禁用保存；只有显式 Reload Latest 后才采用新 revision |

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

## 11. Slice 4 TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 受控实现与行为保护重构 |
| 公开 interface | `AgentConfigurationWorkspace.rollback_version(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 不测试的实现细节 | 私有 helper、具体 UUID、SQL 语句形状、Local staging 目录名 |
| 范围外 | 正式 Phase F publisher、production publication endpoint、Source rollback-Draft、Blue/Green deployment rollback、Contract/Workflow/Skill 编辑、schema、部署 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-8 | Workspace rollback result、activation command 与 route delegation | Workspace/API tests | 因 `AgentActivationRecord` 与 `AgentConfigurationRollback` 不存在而在 collection 阶段失败 |
| GREEN-8 | Workspace 校验 target，构建 exact pointer expectation，并以同一 UoW 提交 activation 与 `agent.version.rolled_back` audit | Control、contracts、persistence ports | Workspace/API 聚焦 83 passed、4 skipped |
| REFACTOR-5 | Local/PostgreSQL adapter 实现同一 activation port；删除 `LocalAgentConfigurationStore.rollback_active_version` 和 route direct-store 调用；补稳定错误映射 | adapters、Delivery、store/API/CLI tests | 162 passed、26 skipped；Ruff、聚焦 Mypy、diff 通过 |
| RED-9 | 独立复验前自审与首轮 finding 锁定兼容、KSS binding、command invariant、非 RuntimeError 500、专属权限和 strict body | Workspace/API/port tests | 各场景在缺少对应保护或测试时失败；`OSError` 旧路径返回 plain 500 |
| GREEN-9 | 补 exact KSS binding、empty/already-active pointer、record invariant、任意非预期 Exception 稳定 500、rollback 专属 403/Workspace-not-called 与 unknown field 422 | Workspace、Delivery、tests | 新增场景通过；独立子 Agent 首轮 P2 权限证据缺口已关闭 |
| VERIFY-MAIN-6 | 主代理执行切片聚焦与仓库级门禁 | backend、前端、静态与领域检查 | 聚焦 205 passed、28 skipped；backend 1891 passed、122 skipped、2 deselected；Dashboard 195、Chat 35；两端 `tsc -b` build、Ruff、Mypy（348 source files）、domain-context、diff、`uv lock --check` 全部通过；1 个既有 Authlib warning |
| ENV-1 | 首轮 backend 与 lock 检查受沙箱限制 | 8 个 loopback tests、uv cache | 允许本机回环和 uv cache 后按原命令重跑通过，不计为产品缺陷 |
| VERIFY-AGENT-5 | 独立子 Agent 按 Slice 4 清单复验 | scope→diff、权限、target identity、CAS、事务/audit、KSS binding、旧实现删除、错误映射、范围隔离 | `PASS / NO_BLOCKING_FINDINGS`；200 passed、27 skipped；Ruff、Mypy（7 source files）、domain-context、diff 与 deletion grep 通过；首轮 P2 权限证据缺口已关闭 |

## 12. Slice 5 TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 受控实现与行为保护重构 |
| 公开 interface | `AgentConfigurationWorkspace.update_workflow_stages(...)`、`AgentConfigurationWorkspace.preview_workflow_stage(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS / NO_BLOCKING_FINDINGS` |
| 不测试的实现细节 | 私有 helper、临时编译目录、YAML 序列化的非语义格式 |
| 范围外 | raw Contract、Skill Pack、production Stage endpoint、validation/publication/rollback、schema、部署 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-10 | Workspace Stage typed command 与保存行为 | `tests/test_agent_configuration_workspace.py` | 因 Stage facts/inspector interface 不存在而在 collection 阶段失败 |
| GREEN-10 | Workspace 受控替换 Workflow 字段，执行 Prompt/context/template Gate，并以 revision CAS 原子保存 Draft 与双层 audit | Control module 与 Stage validation rules | Workspace 测试通过 |
| RED-11 | Workspace preview interface | Workspace tests | 因 `preview_workflow_stage(...)` 不存在而失败 |
| GREEN-11 | Workspace 从 revisioned Draft 组合受控、脱敏 preview，不执行或写入状态 | Workspace 与 local inspector | preview 行为测试通过 |
| RED-12 | Stage route 只依赖 Workspace；Dashboard 保存只发一个 Stage command | API 与 Dashboard tests | 旧 route 缺少新字段并继续先保存 raw Contract |
| GREEN-12 | Delivery 只保留权限、请求/响应与稳定错误映射；Dashboard 发送 `expected_revision` 和 template 的单命令 | Delivery、composition、Dashboard | API 与 Dashboard 回归通过 |
| REFACTOR-6 | 把 Prompt Gate 从 bootstrap 移入 Control；删除 route 内 YAML mutation、compiler/manifest/store 与 preview helpers | Control、bootstrap、Delivery | 聚焦 177 passed、4 skipped；Ruff、Mypy 通过 |
| RED-13 | inspector 不得在配置根残留 preview/update 编译包 | API integration test | 旧 adapter 创建并保留 `compiled_workflow_stages` 目录，测试失败 |
| GREEN-13 | inspector 去除 concrete store 依赖，在受控临时目录编译并于返回前清理 | Local Stage inspector | update/preview 定向 3 passed；配置根无 derived package |
| RED-14 | 临时编译 facts 不得把已清理目录的绝对路径暴露到 preview | 独立子 Agent HTTP 探针与 API regression | `include_policy_outline` 返回含临时目录前缀的绝对路径 |
| GREEN-14 | adapter 只返回包内、相对的逻辑 Contract 引用，并拒绝越界路径 | Local Stage inspector 与 API tests | preview 返回 `policy.yaml`，不含临时前缀或失效绝对路径；定向 3 passed |
| RED-15 | preview 必须限制超长 purpose 与嵌套 response/memory 投影 | 独立子 Agent HTTP 探针与 Control tests | 50,000 字符 purpose 原样返回；3 个新增输出预算场景失败 |
| GREEN-15 | Control preview 对 Prompt、结构化上下文、单值、键、集合项数和递归深度设置预算，并标记 `truncation_applied` | Stage context Control tests | 113 passed、4 skipped；超长与嵌套场景均受限 |
| RED-16 | 非字符串 JSON scalar 也必须计入 preview 总文本预算 | 独立子 Agent probe 与 Control test | 64 个 4,000 位整数产生约 257 KB 响应，新增场景失败 |
| GREEN-16 | scalar 按真实 JSON 序列化长度扣减预算；超限或不可安全序列化时返回截断标记 | Stage context Control tests | 114 passed、4 skipped；整数绕过场景受限 |
| RED-17 | `NaN` 与 `±Infinity` 不得绕过严格 JSON preview 语义 | 独立子 Agent API probe 与 Control tests | 宽松序列化保留非有限数，API 静默转为 `null` 且无截断标记；3 个场景失败 |
| GREEN-17 | scalar 使用 `allow_nan=False` 严格序列化，非有限数进入安全截断分支 | Stage context Control tests | 117 passed、4 skipped；严格 JSON 可重新序列化且标记截断 |
| VERIFY-MAIN-7 | 主代理执行仓库级门禁 | backend、前端、静态与领域检查 | backend 1917 passed、122 skipped、2 deselected；Dashboard 195、Chat 35；两端 build、Ruff、Mypy（350 source files）、domain-context、diff、`uv lock --check` 全部通过；1 个既有 Authlib warning |
| ENV-2 | 首轮 backend 与 lock 检查受沙箱限制 | 8 个 loopback tests、uv cache | 允许本机回环和 uv cache 后按原命令重跑通过，不计为产品缺陷 |
| VERIFY-AGENT-6 | 独立子 Agent 按 Slice 5 明确清单复验并攻击输出边界 | scope→diff、authority、CAS/audit、权限、删除检查、真实 API preview、前后端与静态门禁 | `PASS / NO_BLOCKING_FINDINGS`；聚焦 188 passed、4 skipped；发现的临时路径泄漏、输出预算与严格 JSON 三组 P2 均经 RED 修正后关闭 |

## 13. Slice 6 TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 受控实现与行为保护重构 |
| 公开 interface | `AgentConfigurationWorkspace.update_contract(...)`；读取复用 `get_draft(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS / NO_BLOCKING_FINDINGS` |
| 不测试的实现细节 | 临时目录随机名称、YAML 非语义格式、私有 helper |
| 范围外 | Skill Pack 专用编辑、canonical seed bootstrap、production Contract endpoint、validation/publication/activation/rollback、schema、部署 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-18 | Workspace Contract seam、整包候选校验、revision CAS、双层 audit 与事务失败关闭 | Workspace tests | 旧 Workspace 不接受 `contract_validator` 且无 `update_contract(...)`；6 个场景失败 |
| GREEN-18 | Workspace 合并三个可选文件，保留 extra/advanced fields，经 injected validator 后以 Configuration UoW 原子提交 | Control module 与 Workspace tests | 成功、stale、校验期间并发、validator/audit/commit failure 场景通过 |
| RED-19 | Contract GET/PATCH 只依赖 Workspace；Dashboard 发送当前 revision；未知字段先拒绝 | API、AST 与 Dashboard tests | 旧 route 直接读取 Local store/compiler/manifest，请求不接受 revision；8 个场景失败 |
| GREEN-19 | Delivery 只保留权限、请求/响应与稳定错误映射；Dashboard 显式发送 revision；composition 注入临时编译 validator | Delivery、composition、Dashboard | focused 后端与前端回归通过；旧 Contract 专用 route 组合逻辑删除 |
| RED-20 | 无效 YAML/manifest 的 400 响应不得泄漏已清理的临时绝对路径 | 真实 TestClient 两组无效候选 | 响应包含 `proof-agent-contract-*` 与 `/private/.../agent.yaml`；2 个场景失败 |
| GREEN-20 | Local validator 在 adapter 边界把校验细节收敛为稳定 ValueError，保留内部异常链；Route 返回 `agent_contract_invalid` | Local adapter 与真实 API tests | 两组无效候选均返回无路径 400；失败候选不写 Draft/audit，临时目录自动清理 |
| VERIFY-MAIN-8 | 主代理执行聚焦与仓库级门禁 | backend、前端、静态、构建与领域检查 | focused 189 passed、4 skipped；全量 backend 1936 passed、122 skipped、2 deselected；Dashboard 195、Chat 35；两端 `tsc -b` build、Ruff、Mypy（351 source files）、domain-context、diff、`uv lock --check` 全部通过；1 个既有 Authlib warning，Chat 保留既有 chunk-size warning |
| ENV-3 | `uv lock --check` 首轮受沙箱外部 cache 权限限制 | uv cache | 沙箱外按原命令重跑通过，不计为产品缺陷；两个前端 package 未定义独立 `typecheck` script，build 已执行 `tsc -b` |
| VERIFY-AGENT-7 | 独立子 Agent 按 Slice 6 明确清单复验 | scope→diff、authority、CAS/audit、权限、整包校验、路径安全、无残留、删除检查、范围隔离与完整门禁 | `PASS / NO_BLOCKING_FINDINGS`；focused 155 passed、6 skipped；全量 backend 1936 passed、122 skipped、2 deselected；Dashboard 195、Chat 35；Ruff、Mypy（351 source files）、两端与共享 UI build、domain-context、diff、lock 全部通过。invalid YAML、缺字段 manifest、缺失 Skill Pack definition 与 OSError 均失败关闭，无 raw/path 泄漏或部分写入；3 个跟踪临时目录全部清理 |

## 14. Slice 7 TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 受控实现与行为保护重构 |
| 公开 interface | `get_business_flow_skill_packs(...)`、`create_business_flow_skill_pack(...)`、`update_business_flow_skill_pack(...)`、`delete_business_flow_skill_pack(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS / NO_BLOCKING_FINDINGS` |
| 不测试的实现细节 | 临时目录随机名称、YAML 非语义格式、私有 helper |
| 范围外 | canonical seed bootstrap、production Skill Pack endpoint、KSS binding 编辑、validation/publication/activation/rollback、schema、部署 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-21 | Workspace Skill Pack typed seam、完整 create、update/delete、revision CAS、双层 audit 与事务失败关闭 | Workspace tests | Control Skill Pack command module、inspector seam 与四个公开 interface 不存在；collection 失败 |
| GREEN-21 | Control 同时构建 manifest binding 与 package-local definition；Workspace 经 inspector 后以 CAS 原子保存 Draft 与双层 audit | Control module 与 Workspace tests | read、完整 create、update/delete、stale、inspection 并发、audit/commit failure 场景通过 |
| RED-22 | Local inspector 自动清理、只返回逻辑路径、拒绝越界 extra file 且不泄漏临时路径 | adapter tests | Local Skill Pack adapter 不存在；collection 失败 |
| GREEN-22 | adapter 在受控临时目录编译、严格校验 mutation、允许 read-only 可修复问题投影，并在边界收敛错误与路径 | Local inspector tests | success/failure cleanup、unsafe path、configuration issue 路径安全场景通过 |
| RED-23 | 四个 route 只依赖 Workspace；权限、unknown field、稳定 400/404/409/500；Dashboard 完整 create 单命令与 revision | API、AST 与 Dashboard tests | 旧 route 返回 500 或缺少新字段；Dashboard 仍 POST 后 PATCH；3 个前端场景失败 |
| GREEN-23 | Delivery 只保留权限、request/response 与稳定错误；Dashboard create/update/delete 发送 projection revision，create 一次携带全部字段 | Delivery、composition、Dashboard | 旧 YAML/compiler/store/projection helpers 删除；API 与前端回归通过 |
| RED-24 | absolute/`..` Skill definition 必须在任何 definition loader 前失败关闭，raw Contract 与 Skill Pack command 使用同一包边界 | adapter、loader 与真实 Contract API tests | 外部 definition 会被 raw Contract validator/Skill inspector 读取；Contract PATCH 可持久化后续专用 GET 无法读取的 Draft |
| GREEN-24 | 把 package-local definition 约束提升为共享 package security rule；raw mapping Gate 在路径归一化前拒绝 absolute、Windows/反斜杠与任意 `..`，resolved Gate 再防 symlink/越界 | bootstrap security helper、manifest loader、两个 adapter、真实 TestClient | unsafe definition 返回稳定 400；loader 未调用；Draft、Contract 与全局 audit 不变；既有包内 `skill_packs/` 引用兼容 |
| RED-25 | 409 后不得关闭 Drawer、盲目抬升 revision 或把已删除 target 回退到其他 Pack | Dashboard concurrent-change/concurrent-delete tests | 旧 handler 吞错并关闭 Drawer；首轮修正会以最新 revision 重放旧完整 payload，可能覆盖并发赢家或误改其他 Pack |
| GREEN-25 | mutation 返回显式 outcome；冲突刷新 projection 但冻结 Save/Delete，编辑 target ID 固定；只有显式 Reload Latest 才建立新编辑基线 | Dashboard page/editor tests | 输入保留；并发删除不 retarget；并发改动不会被 silent rebase；重载后才使用新 revision |
| RED-26 | create/update `description` 保持既有非空公共契约 | API 与 Dashboard tests | 首轮 request model 放宽为空，形成未记录的 HTTP 语义漂移 |
| GREEN-26 | 恢复 `min_length=1`；Create Drawer 把 description 设为必填 | Delivery request model 与 Dashboard | 空值继续 422 且 Workspace 不被调用；完整 create 仍只发送一次命令 |
| RED-27 | recoverable capability-ref issue 不得把 path-like raw ref 复制到 message 或 Pack projection | adapter 与真实 GET tests | `/private/operator-secret.yaml` 同时出现在 issue message 与 `validator_refs` response |
| GREEN-27 | issue 使用固定 trace-safe 文案；仅在 recoverable issue projection 中过滤不符合受限逻辑 ID 的 refs | Local Skill inspector 与 API | direct adapter/完整 HTTP response 均不含 raw ref、临时目录或 artifact path；正常合法 projection 保持原值 |
| REFACTOR-8 | 删除旧 Skill route 编译残留与执行路径 | ignored runtime directories、deletion grep、API regression | 精确删除 `runs/config/compiled_projection` 与 `runs/config/compiled_validation`；新流程执行 28 passed、1 skipped 后目录仍不存在 |
| VERIFY-MAIN-9 | 主代理执行聚焦与仓库级门禁 | backend、前端、静态、构建与领域检查 | focused 196 passed、4 skipped；全量 backend 1964 passed、122 skipped、2 deselected；Dashboard 197、Chat 35；两端 `tsc -b` build、Ruff、Mypy（354 source files）、domain-context、diff、lock 全部通过；1 个既有 Authlib warning，Chat 保留既有 chunk-size warning |
| ENV-4 | 首轮真实 PostgreSQL Configuration UoW 环境未配置 | `PROOF_AGENT_TEST_POSTGRES_DSN` | 当时定向 2 skipped；后续由 `VERIFY-PG-1` 关闭 |
| VERIFY-AGENT-8 | 独立子 Agent 按 Slice 7 明确清单复验 | scope→diff、权限、typed authority、CAS/audit、路径安全、单命令、删除与范围隔离 | `PASS / NO_BLOCKING_FINDINGS`；focused 216 passed、4 skipped；全量 backend 1964 passed、122 skipped、2 deselected；Dashboard 197、Chat 35；两端与共享 UI build、Ruff、Mypy（354 source files）、TypeScript、domain-context、diff、lock、AST/deletion、production isolation 全部通过。首轮 definition 预读取/词法路径、Contract 包边界、stale blind-rebase、issue 泄漏、description 漂移与旧派生目录均经 RED 修正后关闭 |
| RED-28 | 强制启用真实 PostgreSQL 测试后，worker-role expired-owner fencing 场景仍引用已删除的 ProofAgent `KNOWLEDGE_WORKER` | `tests/test_worker_role_leases.py` | 最小用例稳定失败：`AttributeError: ProductionWorkerRole has no attribute KNOWLEDGE_WORKER` |
| GREEN-28 | 保持 ADR-0210 的 KSS 独立权威与历史迁移不变，把 fencing 场景改为当前唯一可执行角色 `RUN_EXECUTOR` | PostgreSQL worker-role integration test | 最小用例 1 passed；未恢复旧枚举、advisory lock 或 ProofAgent Knowledge Worker 入口 |
| VERIFY-PG-1 | disposable PostgreSQL 17.5、显式 DSN 与 fail-on-missing Gate | Configuration UoW、worker-role leases、全部 PostgreSQL 标记与 backend 全量 | Configuration UoW 2 passed；PostgreSQL 标记集 84 passed、11 skipped、1993 deselected，其中 11 个 skip 均因 S3 endpoint 未配置；backend 2050 passed、36 skipped、2 deselected；1 个既有 Authlib warning。DSN 凭据未写入文档或 Git |
| VERIFY-AGENT-9 | 独立子 Agent 复验 PostgreSQL 补充验证与 stale role-test 清理 | ADR-0210、角色枚举、advisory lock、历史迁移、fencing/CAS、状态文档与真实 PostgreSQL | `PASS / NO_BLOCKING_FINDINGS`，无未关闭 P0–P3；最小 fencing 与 Configuration UoW 3 passed；PostgreSQL 标记集 84 passed、11 个 S3 endpoint skip；Ruff、domain-context、diff-check 通过；未读取 `.env` 或记录凭据 |

## 15. 风险与待确认问题

| 问题 | 等级 | 影响 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| canonical seed bootstrap 仍直接依赖 Local store | P1 | Workspace 尚未完全深化 | 按独立 Scope 继续迁移；不在 Slice 7 中扩张范围 | 研发负责人未指定 |
| 本地 adapter 在 publication CAS 前可能留下 derived compiled package | P2 | 不形成 authoritative Published Version 或 active pointer，但需要后续清理策略 | 在 artifact lifecycle 切片中定义清理与重试；当前以 CAS 失败关闭权威写入 | 研发负责人未指定 |
| Local UoW 未证明双目录替换中进程崩溃的 durable crash-atomic recovery | P2 | development-only 无锁 reader 可能短暂观察切换；不能作为生产事务证据 | 保持 S0 development-only；生产继续使用 PostgreSQL，若提升本地耐久等级需独立设计 generation/recovery protocol | 研发负责人未指定 |
| 真实 PostgreSQL 证据仅来自 disposable 本地服务 | P1 | 已证明本地 PostgreSQL 17.5 上的事务、advisory lock 与 CAS 测试合同，但不能证明生产数据库、权限、网络或部署状态 | 生产候选仍需在受控发布环境执行 PostgreSQL 与部署 Gate | 测试或发布负责人未指定 |
| 本地验证不等于生产批准 | P1 | `VERIFIED_LOCAL` 不证明生产部署状态 | 保持正常 Product Release Authority 与发布审批 | 发布负责人未指定 |

## 16. 上下文更新建议

| 建议位置 | 类型 | 内容摘要 | 原因 |
| --- | --- | --- | --- |
| Agent Configuration context | 术语 | Workspace interface 与 focused persistence seam | 保持架构语言一致 |
| `docs/PROJ_CONTEXT.md` | Feature 状态 | 记录本切片状态和证据路径 | 供后续切片定位 |

## 17. Slice 8A TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 公开 HTTP 契约扩展与行为保护重构 |
| 公开 interface | Production `PATCH /api/config/agents/{agent_id}/drafts/{draft_id}/contract`；复用 `AgentConfigurationWorkspace.update_contract(...)` |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS_WITH_ENV_LIMITATION`；当前真实 PostgreSQL 证据为 `PARTIAL_VERIFICATION` |
| 不测试的实现细节 | 临时目录名称、YAML 非语义格式、私有 helper |
| 范围外 | Production Workflow Stage、Skill Pack、Knowledge/KSS binding、validation、publication、activation、rollback |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-29 | Production Contract PATCH、strict revision、权限与稳定错误映射 | `tests/test_production_agent_configuration_api.py` | 旧实现统一返回 405；6 个场景失败 |
| GREEN-29 | 新 route 只委托 Workspace；要求 `expected_revision` 与至少一个 Contract 文件；稳定映射 400/404/409/500 | Production Delivery 与 API tests | 12 个 Production API 场景通过 |
| GREEN-30 | Production composition 注入自动清理的整包 Contract validator；持久化继续使用 PostgreSQL Configuration UoW | `production_roles.py`、composition/service tests | Contract candidate 先校验，再以 revision CAS 保存并追加双层 audit |
| RED/GREEN-31 | Production capability 只开放 General 与五个 Contract 模块；Dashboard 每个模块保存发送当前 revision | Agent Detail tests | Tools、Policy、Response 参数化场景与 Model、Memory 专用场景通过；Workflow、Skills、Knowledge 保持只读 |
| VERIFY-MAIN-10 | 主代理执行聚焦与仓库级门禁 | backend、Dashboard、静态、构建与领域检查 | focused backend 79 passed；backend 1986 passed、122 skipped、2 deselected；Dashboard 201 passed；TypeScript、两端与共享 UI build、Ruff、聚焦 Mypy、domain-context、diff、lock 全部通过；1 个既有 Authlib warning |
| ENV-5 | 首轮 backend 与 lock 受沙箱限制；分发测试发现忽略的 `.pyc` 空目录骨架 | loopback、uv cache、KSS build cache | 精确清理纯 `.pyc` 与空目录；允许本机回环和 uv cache 后按原命令重跑通过，不计为产品缺陷 |
| VERIFY-AGENT-10 | 独立子 Agent 对抗复验 Slice 8A | scope→diff、权限、strict body、CAS/audit、错误映射、stale UX、composition、route isolation 与全门禁 | `PASS_WITH_ENV_LIMITATION / CONDITIONAL_RECOMMENDATION`；无未关闭 P0–P3；focused backend 79 passed、2 skipped，backend 1986 passed、122 skipped、2 deselected，Dashboard 201、Agent Detail 45；Ruff、Mypy（354 source files）、TypeScript、build、domain-context、diff、lock 全部通过 |
| ENV-6 | 当前 shell 未配置 `PROOF_AGENT_TEST_POSTGRES_DSN` | 真实 PostgreSQL Configuration UoW | 2 skipped，标记 `PARTIAL_VERIFICATION`；既往 disposable PostgreSQL 证据不冒充本次数据库连接证明，不影响 Slice 8A 代码 verdict |

## 18. Slice 8B TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 公开 HTTP 契约扩展与行为保护重构 |
| 公开 interface | Production Workflow Template catalog/detail；Production Workflow Stage update/preview；共享 Workflow HTTP DTO/serialization |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent 复验 `PASS / NO_BLOCKING_FINDINGS`；真实 PostgreSQL 证据为 `PARTIAL_VERIFICATION` |
| 不测试的实现细节 | 临时目录名称、YAML 非语义格式、私有 helper |
| 范围外 | Production Skill Pack、Knowledge/KSS binding、validation、publication、activation、rollback |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-32 | Production Template catalog/detail、Stage update/preview 与权限/strict revision | `tests/test_production_agent_configuration_api.py` | 旧实现统一返回 404；3 个场景失败 |
| GREEN-32 | Development/Production 共享严格 Prompt、Stage item、Preview DTO 与 Descriptor serialization；Production 新增 catalog/detail、update/preview route | shared Delivery HTTP contracts、Production API tests | 路由成功、权限、strict body、typed delegation 场景通过 |
| GREEN-33 | Production composition 注入自动清理的 Workflow Stage inspector；持久化继续使用 PostgreSQL UoW | `production_roles.py`、composition tests | inspector 不保留编译目录，不形成第二持久化权威 |
| RED/GREEN-34 | Production Workflow capability 显示完整编辑器；Core/Stage 保存携带 revision；409 保留未保存 Prompt 且不刷新或 blind rebase | Agent Detail tests | Production Workflow Core、Stage、Preview 与 stale-state 行为通过 |
| REFACTOR-9 | 抽取 Development/Production 共用的 Workflow HTTP contract/serialization | `agent_configuration_workflow_http.py`、Development API regression | 两个 router 不复制 DTO 与 Control translation；Development 成功响应保持兼容 |
| VERIFY-MAIN-11 | 主代理执行聚焦与仓库级门禁 | backend、Dashboard、静态、构建与领域检查 | focused backend 166 passed、4 skipped；backend 1995 passed、122 skipped、2 deselected；Dashboard 202 passed；Ruff、Mypy、TypeScript、两端与共享 UI build、domain-context、diff 全部通过；1 个既有 Authlib warning |
| VERIFY-AGENT-11 | 独立子 Agent 对抗复验 Slice 8B | scope→diff、共享 DTO、权限矩阵、CAS/audit、Prompt 与 preview 安全、stale UX、composition、route isolation 与全门禁 | `PASS / NO_BLOCKING_FINDINGS`；focused backend 188 passed、6 skipped，Agent Detail 46，Dashboard 202；Ruff、Mypy（355 source files）、TypeScript、build、domain-context、diff、lock、权限矩阵与 AST 禁止依赖检查全部通过 |
| ENV-7 | 当前 shell 未配置 `PROOF_AGENT_TEST_POSTGRES_DSN` | 真实 PostgreSQL Configuration UoW | 延续 `PARTIAL_VERIFICATION`；不把 fake UoW 或既往 PostgreSQL 证据冒充本次数据库证明 |

## 19. Slice 8C TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 公开 HTTP 契约扩展与行为保护重构 |
| 公开 interface | Production Skill Pack GET 与 Business Flow create/update/delete；共享 Skill Pack HTTP fields、command translation 与 projection serialization |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS / NO_BLOCKING_FINDINGS`；真实 PostgreSQL 证据为 `PARTIAL_VERIFICATION` |
| 不测试的实现细节 | 临时目录随机名称、YAML 非语义格式、私有 helper |
| 范围外 | Knowledge/KSS binding、production validation、publication、activation、rollback |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-35 | Production Skill Pack GET/POST/PATCH/DELETE、strict revision、权限、稳定错误与 capability | Production API/composition tests | 旧实现四条 route 均为 404，capability 无 `skills`，composition 无 inspector；10 个预期失败 |
| GREEN-35 | Production route 只委托 Workspace typed command；GET 使用 `agent.view`，mutation 使用 `agent.edit`；create/update/delete 强制调用方 revision | Production API tests | 成功路径、完整 typed command、权限矩阵、未知字段、400/409/500 与路径不泄漏通过 |
| REFACTOR-10 | 抽取 Development/Production 共用 Skill Pack HTTP fields、Control command translation 与 projection serialization | `agent_configuration_skill_pack_http.py`、Development API regression | Development 可选 revision 兼容语义保持；Production 使用独立 required-revision request；Delivery 不复制命令翻译 |
| GREEN-36 | Production composition 注入既有自动清理 Skill Pack inspector；PostgreSQL UoW 继续是唯一 Draft/audit 持久化权威 | composition、adapter/Workspace tests、canonical template probe | canonical Production 模板投影 6 packs、0 issues；无持久化临时目录或第二权威 |
| RED/GREEN-37 | Production capability 开放 `skills`；Dashboard 列表、完整 create、update、delete 使用 projection revision，409 冻结原 target 并要求显式 Reload Latest | Agent Detail tests | 50 passed；create/update/delete 发送 revision 4；create、edit 与列表 delete 在 409 后禁止 blind replay；并发删除不 retarget，目标消失后不残留无响应锁 |
| VERIFY-MAIN-12 | 主代理执行聚焦与仓库级门禁 | backend、Dashboard/Chat、静态、构建与领域检查 | focused backend 185 passed、4 skipped；backend 2006 passed、122 skipped、2 deselected；Dashboard 203、Chat 35；Ruff、Mypy（356 source files）、TypeScript、共享 UI/两端 build、domain-context、diff、lock 全部通过；1 个既有 Authlib warning，Chat 保留既有 chunk-size warning |
| VERIFY-AGENT-12 | 独立子 Agent 对抗复验 Slice 8C，并复验三项并发 UX 修正 | scope→diff、typed authority、权限、CAS/audit、路径与临时目录安全、错误映射、stale UX、composition、KSS/生命周期隔离与全门禁 | `PASS_WITH_ENV_LIMITATION / NO_BLOCKING_FINDINGS`；focused backend 144 passed、6 skipped，backend 2006 passed、122 skipped、2 deselected，Agent Detail 50，Dashboard 206，Chat 35；Ruff、Mypy（356 source files）、TypeScript、build、domain-context、diff、lock 全部通过；canonical 模板 6 packs、0 issues、0 残留目录 |
| ENV-8 | 当前 shell 未配置 `PROOF_AGENT_TEST_POSTGRES_DSN` | 真实 PostgreSQL Configuration UoW | 2 项真实 PostgreSQL UoW 用例继续 skip，标记 `PARTIAL_VERIFICATION`；不把 fake UoW 或既往 disposable PostgreSQL 证据冒充本次数据库证明 |

## 20. Slice 8D TDD 记录

| 项 | 内容 |
| --- | --- |
| 模式 | 领域 contract 扩展、公开 HTTP 契约扩展与行为保护重构 |
| 公开 interface | Workspace KSS candidate read/update；Production Knowledge binding GET/PATCH；Dashboard exact Release selector/save |
| 当前状态 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS_WITH_ENV_LIMITATION`；真实 PostgreSQL 证据为 `PARTIAL_VERIFICATION` |
| 不测试的实现细节 | Catalog client 内部传输、React 私有 state、JSONB 序列化 helper |
| 范围外 | KSS 管理写操作、credential/scorer、executable binding/profile、Phase F publication、activation、rollback、当前问答运行时切换 |

| 步骤 | 行为 | 证据 | 结果 |
| --- | --- | --- | --- |
| RED-38 | Draft first-class KSS candidate、Workspace read/update、exact catalog 校验与原子审计 | Workspace tests | constructor/interface 缺失，6 个场景失败 |
| GREEN-38 | 新增无密钥四元组 strict contract 与 catalog port；保存前验证 ready/queryable/完整父级身份，再以 revision CAS 提交 Draft 与双层 audit | Workspace/contract tests | 7 个 KSS 聚焦场景通过；credential、scorer、content、latest 与未知字段 fail closed；unavailable、retired、parent mismatch、stale、missing、audit/commit fault 均不写状态或提前调用 KSS |
| RED-39 | Production Knowledge GET/PATCH、双权限、strict body 与稳定错误映射 | Production API tests | 旧路由返回 404；8 个场景失败 |
| GREEN-39 | Delivery 只委托 Workspace，组合既有 KSS management client；返回 revision、candidate、readiness 与 Release catalog | Production API/composition tests | exact tuple delegation、权限、400/404/409/500/503、路径不泄漏与 production isolation 通过 |
| RED-40 | Production Knowledge 仍是旧 Contract 只读投影；无 selector/save/stale recovery | Agent Detail tests | 新增 5 个场景失败，其余 50 个回归通过 |
| GREEN-40 | Production capability 开放 `knowledge`；Dashboard 显示 authoring-only、live readiness/queryable catalog，保存 projection revision；409 保留选择并冻结重放；Development 保留 Knowledge Contract 投影但不声明 editable，也不调用 Production 专用 route | Dashboard client/page 与 Development API tests | client 20、Agent Detail 56；成功 exact save、409 explicit reload、500 输入保留、unavailable fail-closed、Development read-only/no-fetch 通过 |
| VERIFY-MAIN-13 | 主代理执行聚焦与仓库级门禁 | backend、Dashboard/Chat、静态、构建与领域检查 | focused backend 112 passed、4 skipped；backend 2026 passed、122 skipped、2 deselected；Dashboard 214、Agent Detail 56、Chat 35；Ruff、Mypy（356 source files）、TypeScript、共享 UI/两端 build、domain-context、diff、lock 全部通过；1 个既有 Authlib warning，Chat 保留既有 chunk-size warning |
| VERIFY-AGENT-13 | 独立子 Agent 对抗复验 Slice 8D，并复验 strict candidate 与 Development 只读兼容修正 | scope→diff、KSS 权威、权限、strict contract、CAS/audit、错误映射、stale UX、composition、lifecycle/runtime 隔离与全门禁 | `PASS_WITH_ENV_LIMITATION`；无未关闭 P0–P3；focused backend 37 passed、1 skipped，相关后端 222 passed、15 skipped，backend 2026 passed、122 skipped、2 deselected，Dashboard focused 76、全量 214，Chat 35；Ruff、Mypy（356 source files）、TypeScript、build、domain-context、diff、lock 全部通过 |
| ENV-9 | 当前 shell 未配置 `PROOF_AGENT_TEST_POSTGRES_DSN` | 真实 PostgreSQL Configuration UoW | 2 项真实 PostgreSQL UoW 用例 skip，标记 `PARTIAL_VERIFICATION`；既往 disposable PostgreSQL 证据不冒充本次连接证明 |
