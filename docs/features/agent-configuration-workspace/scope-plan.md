# Agent Configuration Workspace Scope、准入与 TDD 计划

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | Slice 5 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 最高风险等级 | P1 |
| 一句话依据 | 领域上下文已固定 Workflow Stage Prompt/Context 的受限语义；现有 Configuration UoW、受控编译器和稳定 API 行为足以迁移保存与预览权威 |
| 下一步建议 | Slice 5 已完成；后续以独立 Scope 迁移 raw Contract 或 Skill Pack 编辑权威 |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| 用户请求 | 当前对话 | 是 | 用户同意实施 Workflow Stage Configuration 编辑权威；每个切片完成后由子 Agent 按明确流程验证 | 当前为 Slice 5 |
| 架构评审 | `architecture-review-20260818-220308.html` | 是 | Delivery 与 concrete store 耦合；推荐 deep application module 与 focused ports | Graphify 图较旧，只作导航 |
| 项目规则 | `AGENTS-COMMON.md`、hicode coding rules | 是 | production PostgreSQL 权威、原子审计、TDD、无兼容 facade | 无 |
| 领域与 ADR | Agent Configuration context、ADR-0009、ADR-0011 | 是 | Workspace、Draft、Published Version、模块/lifecycle 分离 | context 含已退役知识术语，后续单独清理 |
| 当前实现 | configuration router、Workspace、Local compiler/store、Dashboard Workflow editor | 是 | Stage 保存与预览仍在 route 内组合 YAML、compiler 与 concrete store；Dashboard Stage 保存先写 Contract、再写 stages | Contract/Skill 编辑与 canonical seed bootstrap 仍待后续切片 |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 需求分析输入 | 用户确认、领域规则、现有稳定 API、Configuration UoW、受控编译器、Dashboard 回归 |
| 证据缺口 | 真实 PostgreSQL Stage endpoint 不存在且不在本切片；本轮只提供 development local adapter 证据，不形成生产批准 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | 让 Control-owned Workspace 成为 Workflow Stage Configuration 保存与 Context Preview 的唯一应用权威 |
| 范围内 | Workspace update/preview interface、typed Stage command、受控本地 Draft inspection adapter、revision CAS、原子审计、development API、稳定错误映射、Dashboard 单次保存、旧 route 逻辑删除、文档 |
| 范围外 | raw Contract 编辑、Skill Pack 编辑、production Stage endpoint、validation/publication/rollback、schema、部署 |
| 非目标 | 新增 facade 后保留旧调用；把 Stage Prompt 变成 Harness control prompt；执行模型/工具/Run；把本地验证描述为生产批准 |
| 验收标准 | Workspace/API/Dashboard 行为测试、Ruff/Mypy/前端与全量后端通过；保存以 expected revision CAS 一次提交 template、descriptor version 与 stages；audit 无 Prompt 原文；预览无写入；独立子 Agent 复验 |
| `feature_context.md` 更新 | 已创建 |
| ADR 处理 | 不需要；ADR-0009、ADR-0210 与 Agent Configuration 领域上下文已固定 immutable-version pointer rollback 和精确 KSS binding 规则 |

## 5. 设计树方案

| 节点 | 类型 | 触发条件/输入 | 处理方案 | 输出/状态变化 | 范围边界 | 验证点 | 风险等级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | Delivery 读取或更新 Draft | 调用 Workspace interface | 领域结果 | 不暴露 adapter | interface test | P1 |
| MAIN-1 | inventory | Agent catalog 请求 | Workspace 汇总 Draft/version/active | inventory | 不做 observability projection | multi-agent test | P1 |
| MAIN-2 | read | Agent/Draft ID | 应用 scope 后读取 lifecycle port | revisioned Draft | 不读取文件布局 | not-found test | P1 |
| MAIN-3 | update | metadata、revision、actor | UoW 内保存与审计 | revision +1 | 不改 Contract | CAS/audit test | P1 |
| MAIN-4 | versions | Agent ID | lifecycle port 读取 Published 与 active | version collection | 不激活 | list test | P1 |
| BRANCH-1 | stale revision | expected revision 不匹配 | repository 拒绝并回滚 | stable conflict | 不做 last-write-wins | conflict test | P1 |
| BRANCH-2 | wrong production scope | 非 sole Agent | Workspace 拒绝 | stable not-found | development 可多 Agent | scope test | P1 |
| BRANCH-3 | dependency failure | adapter/UoW 失败 | 传播为 stable application error | 无 fallback | 不切本地权威 | fault test | P1 |
| BOUND-1 | lifecycle authority | Draft 已更新 | 不验证、不发布、不回滚 | active pointer 不变 | 后续切片 | negative test | P1 |

## 6. 澄清问题队列

| 问题 | 状态 | 推荐答案 | 推荐理由 | 影响 | 建议确认人 |
| --- | --- | --- | --- | --- | --- |
| 首个垂直切片 | 已关闭 | inventory/read/metadata update/version list | 已有稳定行为与两个 adapters；不触及 publication | 控制风险与改动宽度 | 用户已选择模块；切片为实现假设 |
| 是否一次迁移 validation/publication/rollback | 已关闭 | 否；validation 已作为 Slice 2 单独迁移 | 三者分别涉及运行证据、发布 Gate 与 active pointer | 保持各切片可独立验证 | 架构评审建议逐片替换 |
| 是否保留 production-only service facade | 已关闭 | 否 | 会形成新旧双 interface | deletion test 必须删除旧命名与调用 | codebase-design 原则 |

## 7. 关键规则与影响范围

| 对象 | 影响说明 | 证据来源 | 确认状态 | 风险等级 |
| --- | --- | --- | --- | --- |
| Workspace interface | 成为 Delivery 的唯一生命周期入口 | 架构评审 | 已确认 | P1 |
| Configuration UoW | 保持 Draft 与 audit 原子提交 | hicode rules | 已确认 | P1 |
| sole-Agent policy | 收入 Workspace implementation | ADR-0124、现有 production service | 已确认 | P1 |
| Local/PostgreSQL adapters | 只满足 focused ports，不拥有业务规则 | AGENTS-COMMON.md | 已确认 | P1 |
| development publication | Workspace 成为普通 Draft publication lifecycle authority；失败 validation outcome 不得晋升 | Agent Configuration context、架构评审 | 已确认 | P1 |
| formal production publisher | 保持 Phase F evidence 与 online smoke authority，不并入本切片 | ADR-0152、现有 production publisher | 已确认 | P1 |

## 8. 风险与阻断建议

| 风险 | 等级 | 证据 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| 新 Workspace 只是 pass-through facade | P1 | codebase-design deletion test | 把 scope、汇总、CAS 与审计规则移入 module，并删除 Delivery 规则 | 研发负责人未指定 |
| Local 与 PostgreSQL 行为漂移 | P1 | 两个 adapter 的事务实现不同 | 同一 module contract 测试，并保留 adapter 回归 | 测试负责人未指定 |
| 元数据更新误触发发布 | P1 | Draft/Published 生命周期必须分离 | 负向断言 active/version 不变 | 发布负责人未指定 |
| 一次迁移过宽 | P1 | router 与 store 仍包含其他复杂用例 | 严格限定本切片，后续重新 Scope | 研发负责人未指定 |

## 9. 推荐设计树方案与取舍

| 方案 | 是否推荐 | 主干逻辑 | 分支处理 | 范围边界 | 收益 | 代价或风险 | 不选原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Control-owned Workspace + focused ports | 是 | Delivery → Workspace → UoW/AgentLifecycleRepository；validation executor 作为独立 adapter | scope、CAS、audit、not-found、execution/capture identity | Slice 1 与 Slice 2 | interface 小、规则集中、两个 adapter 复用 | 需要迁移测试与 wiring | 推荐 |
| Delivery facade 包裹 Local store | 否 | route → facade → concrete store | 仍由 route 处理规则 | development only | 改动小 | 只是多一层，PostgreSQL 不复用 | deletion test 不通过 |
| 一次迁移全部生命周期 | 否 | 一个大 application 重写全部 route | 同时处理运行与发布失败 | 全 Workspace | 最终形态直接 | 风险和回归面过大 | 不能独立验证与回滚 |

## 10. 设计树到 TDD 任务计划

| 项 | 内容 |
| --- | --- |
| 任务计划结论 | Slice 3 `LOCAL_VERIFIED`；RED、GREEN、REFACTOR、主代理门禁与独立复验均已完成 |
| 下一步路由 | 后续 rollback authority 独立进入 `hicode:scope` |
| 未覆盖设计树节点 | production validation/publish endpoint、正式 Phase F publisher、rollback、Contract/Workflow/Skill 编辑明确延期 |

### Task ACW-1：建立 Workspace interface 行为测试

- 目标：通过公开 interface 覆盖 inventory、read、metadata update 与 versions。
- TDD 起点：多 Agent inventory 与 arbitrary development Draft 当前被 production-only service 拒绝。
- 停止条件：需要改变 publication、schema 或 production 配置。

### Task ACW-2：实现 deep application module

- 目标：把 scope、summary、revision CAS、audit 和 error 规则收进 Control module。
- TDD 起点：ACW-1 RED。
- 停止条件：focused lifecycle port 无法表达现有行为。

### Task ACW-3：迁移 Delivery 与 composition

- 目标：development/production route 使用同一 Workspace interface，删除 production-only application state 和具体 store 读取规则。
- TDD 起点：注入 recording Workspace 的 route contract tests。
- 停止条件：需要迁移 publication/rollback，或新增 production validation endpoint。

### Task ACW-4：验证与证据

- 目标：执行 module、API、adapter、静态与全量回归，并更新 TDD 报告。
- 停止条件：验证需要生产连接、生产数据或部署。

## 11. TDD 输入与测试重点

| 设计树节点 | 场景 | 类型 | 优先级 | 数据要求 | 对应任务 |
| --- | --- | --- | --- | --- | --- |
| MAIN-1 | 多 Agent inventory 汇总 | contract | P1 | 虚构 Agent/Draft | ACW-1、ACW-2 |
| MAIN-2 | development arbitrary Draft 与 production sole scope | contract/security | P1 | 虚构 ID | ACW-1、ACW-2 |
| MAIN-3 | CAS 更新与原子 audit | consistency | P1 | 虚构 actor | ACW-1、ACW-2 |
| MAIN-4 | versions 与 active pointer | contract | P1 | 虚构 Published Version | ACW-1、ACW-2 |
| BRANCH-1 | stale revision | concurrency | P1 | revision 1/2 | ACW-1、ACW-2 |
| BRANCH-2 | wrong sole Agent | security | P1 | 非 sole ID | ACW-1、ACW-2 |
| BOUND-1 | metadata update 不发布 | negative | P1 | empty version repo | ACW-1、ACW-4 |

## 12. ADR 判断

| 项 | 内容 |
| --- | --- |
| 是否需要 ADR | 否 |
| 判断理由 | ADR-0009、ADR-0011 已确定 Workspace 与 lifecycle 分层；本切片不改变公开权威或难逆数据模型 |
| 涉及决策点 | interface/DTO 命名和逐片迁移顺序可在既有决策内演进 |

## 13. 知识沉淀与上下文更新

| 目标文档 | 更新类型 | 内容摘要 | 处理方式 | 确认状态 |
| --- | --- | --- | --- | --- |
| `docs/PROJ_CONTEXT.md` | Feature 索引 | 增加 `agent-configuration-workspace` | 本次更新 | 实现追踪 |
| Agent Configuration context | 术语 | 增加 deep Workspace interface 与 focused persistence seam | 已更新 | 首个切片完成 |
| TDD report | 证据 | 记录 RED/GREEN/REFACTOR 与真实命令 | 已更新 | 本地全量验证完成 |

## 14. Slice 2 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 最高风险等级 | P1 |
| 公开 interface | `AgentConfigurationWorkspace.validate_draft(...)` |
| 可观察行为 | 返回 Validation Run 投影；把 Validation Record、Draft operation audit 和全局 audit 按 revision CAS 写入同一 Configuration UoW |
| 范围外 | production endpoint、publication、rollback、Contract/Workflow/Skill 编辑、schema、部署 |
| ADR 判断 | 不需要；仍执行 ADR-0009、ADR-0011 的 Workspace 与 lifecycle seam，不改变持久化权威 |

## 15. Slice 2 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-V-ROOT | Operator 请求验证一个 Draft | Delivery 调用 Workspace interface | 返回稳定 Validation 投影 | HTTP 与 module 行为测试 | P1 |
| ACW-V-MAIN-1 | Draft 存在且 question 合法 | Workspace 读取 revisioned Draft，调用 injected validation executor | 产生 Run artifact 与 trace-safe execution evidence | fake executor + Local adapter API 回归 | P1 |
| ACW-V-MAIN-2 | execution 完成 | Workspace 生成 Validation Record、Draft operation audit 和全局 audit | Draft revision 增加 1 | 同一 UoW commit 断言 | P1 |
| ACW-V-BRANCH-1 | full capture safety gate 拒绝 payload | executor 返回 trace-safe `capture_error`，Validation Record 仍保存 | summary-only 证据可用 | 既有 full-capture failure 回归 | P1 |
| ACW-V-BRANCH-2 | execution 后 Draft revision 已变化 | repository CAS 拒绝写入 | 返回稳定 conflict，不覆盖 Draft | conflict 行为测试 | P1 |
| ACW-V-BRANCH-3 | compiler、runtime 或 Run artifact 失败 | 不写 Validation Record；沿既有错误映射返回 | Draft 不变 | API 失败回归 | P1 |
| ACW-V-BOUND-1 | Validation Record 已保存 | 不发布、不激活、不回滚 | Published Version 不变 | negative assertion | P1 |

## 16. Slice 2 TDD 任务

### Task ACW-V1：Workspace validation 行为

- RED：从 Workspace interface 验证 execution evidence、Validation Record、revision CAS 和双层 audit。
- GREEN：加入最小 validation executor seam 与 `validate_draft` 实现。
- 停止条件：需要改变 Run artifact、Published Version 或数据库 schema。

### Task ACW-V2：Local validation adapter 与 Delivery 删除测试

- RED：现有 route 仍直接组合 compiler、RunStore 和 Local store。
- GREEN：把本地编译、执行和 Full Capture 投影移入 adapter；route 只做权限、请求和响应映射。
- 停止条件：需要新增 production validation endpoint 或远程执行协议。

### Task ACW-V3：验证与独立复核

- 主代理执行聚焦测试、全量测试、Ruff、Mypy、Dashboard test/build 和领域检查。
- 切片完成后启动独立子 Agent，按 Scope、diff、测试证据、旧依赖检索、权限/审计/并发清单复核。
- 子 Agent 发现问题时，主代理修正后重新执行相关验证。

## 17. Slice 3 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 最高风险等级 | P1 |
| 公开 interface | `AgentConfigurationWorkspace.publish_draft(...)` |
| 可观察行为 | 当前 Draft revision 的无 blocker Validation Record 被提升为 immutable Published Agent Version；Active Agent Version 与 audit 在同一 UoW 提交 |
| 范围外 | rollback、production publish endpoint、正式 Phase F publisher、Contract/Workflow/Skill 编辑、schema、部署 |
| ADR 判断 | 不需要；执行既有 Agent Publication、manual publish、validation-before-publication 和 immutable snapshot 决策 |

## 18. Slice 3 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-P-ROOT | Operator 显式发布一个 Draft | Delivery 调用 Workspace interface | 返回 Published Agent Version | HTTP 与 module 行为测试 | P1 |
| ACW-P-MAIN-1 | Draft 存在且有指定或最新 Validation Record | Workspace 要求 validation 属于当前 Draft revision、outcome 非失败态，且没有 errors/publish blockers | validation 被接受 | failed/stale/missing/blocked tests | P1 |
| ACW-P-MAIN-2 | package 与 publication policy 验证通过 | Workspace 解析并冻结 Workflow Stage Availability 与 Effective Configuration | immutable version facts | snapshot assertions | P1 |
| ACW-P-MAIN-3 | publication record 已构建 | AgentLifecycleRepository 以 Draft revision CAS 和 active pointer expectation 原子保存 version/activation；audit 同事务提交 | 新 active version | Local/PostgreSQL port tests、audit test | P1 |
| ACW-P-BRANCH-1 | Draft 在 validation 或 publish 前后变化 | freshness Gate 或 repository CAS 拒绝 | 不发布、不激活 | conflict test | P1 |
| ACW-P-BRANCH-2 | active pointer 被并发推进 | pointer CAS 拒绝 | 不覆盖并发赢家 | pointer conflict test | P1 |
| ACW-P-BRANCH-3 | compiler、manifest 或 live asset policy 失败 | adapter 失败关闭 | state 不变、稳定错误 | API failure test | P1 |
| ACW-P-BRANCH-4 | 两个 Local staging UoW 从同一基线交错提交 | 外置权威锁内重验真实 configuration/audit 摘要 | 只允许一个赢家 | real Local UoW interleaving tests | P1 |
| ACW-P-BOUND-1 | publication 成功 | 不执行 rollback，不调用正式 Phase F publisher | 历史 version 保持 immutable | negative AST/deletion test | P1 |

## 19. Slice 3 TDD 任务

### Task ACW-P1：Workspace publication authority

- RED：从 Workspace interface 证明 current validation、immutable snapshot、Draft/pointer CAS、activation 和 audit。
- GREEN：实现 `publish_draft(...)`，用现有 Configuration UoW 与 AgentLifecycleRepository 原子提交。
- 停止条件：需要改变数据库 schema、Phase F evidence 或 production endpoint。

### Task ACW-P2：Local publication validator 与 Delivery 删除测试

- RED：现有 publish route 仍直接组合 compiler 与 Local store。
- GREEN：本地 adapter 只负责 package/live asset publication validation；route 只做权限、请求和响应映射。
- 停止条件：需要迁移 rollback 或 canonical seed bootstrap。

### Task ACW-P3：验证与独立复核

- 主代理执行聚焦、全量、静态和 Dashboard 门禁。
- 切片完成后启动独立子 Agent，验证 scope→diff、freshness/blocker Gate、CAS、audit、删除目标、错误映射和无 rollback/Phase F 调用。

## 20. Slice 4 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 最高风险等级 | P1 |
| 公开 interface | `AgentConfigurationWorkspace.rollback_version(...)` |
| 可观察行为 | 选择一个既有 immutable Published Agent Version，精确比较并切换 Active Agent Version pointer，同时提交全局 configuration audit；返回恢复后的不可变 KSS binding 投影 |
| 兼容边界 | 保持既有 HTTP method、path、权限、空 request body 和成功响应字段；当前指针为空或目标已 active 的既有行为不在本切片改变 |
| 范围外 | 正式 Phase F publisher、production publication endpoint、Blue/Green deployment rollback、Source rollback-Draft、Contract/Workflow/Skill 编辑、schema、部署 |
| ADR 判断 | 不需要；执行 ADR-0009、ADR-0210 和既有 Agent Version Rollback 领域规则 |

## 21. Slice 4 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-RB-ROOT | Operator 以 `agent.publish` 请求回滚一个 Agent Version | Delivery 只调用 Workspace interface | 返回 rollback projection | HTTP interface 与 AST 删除测试 | P1 |
| ACW-RB-MAIN-1 | target Published Version 存在 | Workspace 在同一 UoW 读取 target 与当前 active pointer | 构建 activation command 与 exact pointer expectation | module contract test | P1 |
| ACW-RB-MAIN-2 | pointer expectation 匹配 | lifecycle repository 原子写入新的 Active Agent Version；Workspace 同事务追加 `agent.version.rolled_back` audit | activation 与 audit 同时可见 | UoW、Local、PostgreSQL adapter tests | P1 |
| ACW-RB-MAIN-3 | target version 含不可变 KSS binding | 不重算、不降级、不恢复已删除 Hybrid 运行时；响应投影来自 target Published Version | 精确恢复 target binding | KSS-bound response regression | P1 |
| ACW-RB-BRANCH-1 | target 不存在或不属于 Agent | Workspace 返回稳定 not-found | pointer/audit 不变 | not-found test | P1 |
| ACW-RB-BRANCH-2 | pointer 在读取后被并发推进 | repository exact CAS 拒绝第二个 writer | 并发赢家不被覆盖 | fake conflict、real Local interleaving、PostgreSQL concurrency test | P1 |
| ACW-RB-BRANCH-3 | audit append 或 UoW commit 失败 | 整个业务事件回滚 | pointer 与 audit 均不产生部分写入 | fault tests | P1 |
| ACW-RB-BOUND-1 | rollback 成功 | 不修改或删除任何 Published Agent Version，不创建 Draft，不调用 Phase F 或部署 rollback | history immutable | negative assertions 与 import/AST 检查 | P1 |

## 22. Slice 4 TDD 任务

### Task ACW-RB1：Workspace rollback authority

- RED：从 Workspace interface 证明 target 校验、active-pointer expectation、activation、KSS binding 恢复投影和 audit 原子性。
- GREEN：引入 adapter-neutral activation command，通过 Configuration UoW 与 `AgentLifecycleRepository` 提交。
- 停止条件：需要改变 public HTTP contract、数据库 schema 或正式生产 release evidence。

### Task ACW-RB2：双 adapter 与 Delivery 删除测试

- RED：当前 route 仍直接调用 `LocalAgentConfigurationStore.rollback_active_version(...)`，PostgreSQL lifecycle port 无等价能力。
- GREEN：Local/PostgreSQL adapter 实现同一 exact-pointer activation port；route 只做权限、请求和响应映射；删除旧 direct-store rollback 方法。
- 停止条件：需要迁移 canonical seed bootstrap 或其他 configuration edit routes。

### Task ACW-RB3：验证与独立复核

- 主代理执行聚焦测试、真实 Local 交错事务、可用 PostgreSQL 集成测试、全量后端、Ruff、Mypy、Dashboard/Chat 与领域检查。
- 切片完成后启动独立子 Agent，按 scope→diff、权限、target identity、CAS、事务/audit、KSS binding、旧实现删除、错误映射和范围隔离清单复验。
- 子 Agent 发现问题时，主代理先补 RED 再修正并重跑相关门禁。

## 23. Slice 5 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS / NO_BLOCKING_FINDINGS` |
| 最高风险等级 | P1 |
| 公开 interface | `AgentConfigurationWorkspace.update_workflow_stages(...)`、`AgentConfigurationWorkspace.preview_workflow_stage(...)` |
| 可观察行为 | 保存以一个 Draft revision CAS 更新 Workflow Template、Descriptor Version 与 Stage overrides，并原子追加 Draft operation audit 和全局 audit；预览返回脱敏投影且不写任何状态 |
| 兼容边界 | 保持 HTTP method/path、`agent.edit`/`agent.validate` 权限和现有成功响应；请求新增可选 `expected_revision` 与 `template`，旧调用可继续使用服务端当前 revision 与既有 template |
| 范围外 | raw Contract 编辑、Skill Pack 编辑、production Stage endpoint、validation/publication/rollback、schema、部署 |
| ADR 判断 | 不需要；执行既有 Workflow Stage Configuration、Harness Prompt Authority Boundary、Workspace ownership 与 Draft CAS 规则 |

## 24. Slice 5 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-WS-ROOT | Operator 保存或预览 Workflow Stage Configuration | Delivery 只调用 Workspace interface | Contract Bundle 或 preview projection | HTTP interface 与 AST 删除测试 | P1 |
| ACW-WS-MAIN-1 | 保存请求含 template、descriptor version、stages 与 expected revision | Workspace 解析当前 Agent YAML，只替换受控 Workflow 字段，构建 typed candidate | candidate Draft | YAML/Unicode/未知字段/legacy nodes tests | P1 |
| ACW-WS-MAIN-2 | candidate 构建完成 | injected local adapter 编译并加载 manifest；Control 复用既有 Stage validation | 可保存 candidate | invalid template/stage/prompt/context tests | P1 |
| ACW-WS-MAIN-3 | candidate 校验通过 | Configuration UoW 以 expected revision 保存 Draft，并原子追加 operation/global audit | revision +1 | CAS、audit、commit failure tests | P1 |
| ACW-WS-MAIN-4 | 请求 Context Preview | Workspace 检查 Draft、stage、Prompt 与 context，调用受控 inspector 并构建 redacted preview | 无执行 preview | no Run/no mutation、redaction tests | P1 |
| ACW-WS-BRANCH-1 | client revision 已过期或保存期间并发写入 | revision CAS 拒绝 | stable 409；不覆盖赢家 | stale/interleaving tests | P1 |
| ACW-WS-BRANCH-2 | compiler、manifest 或 adapter 失败 | 保存失败关闭；Delivery 返回稳定错误且不泄漏路径 | Draft/audit 不变 | fault/error mapping tests | P1 |
| ACW-WS-BRANCH-3 | Prompt 或 context 试图越过 descriptor/Harness 约束 | 既有 `PA_CONFIG_002` Gate 拒绝 | 不保存、不预览 | governance-bypass tests | P1 |
| ACW-WS-BOUND-1 | Stage 保存/预览完成 | 不验证、不发布、不激活，不迁移 Contract/Skill 路由 | 其他 lifecycle 权威不变 | negative assertions 与 scope diff | P1 |

## 25. Slice 5 TDD 任务

### Task ACW-WS1：Workspace Stage 保存与预览行为

- RED：从 Workspace interface 证明 typed mutation、revision CAS、双层 audit、Prompt 不进入 audit、preview 无状态写入。
- GREEN：实现 `update_workflow_stages(...)` 与 `preview_workflow_stage(...)`，复用现有 Configuration UoW 和 Control Stage rules。
- 停止条件：需要改变 Published Version、数据库 schema 或 production endpoint。

### Task ACW-WS2：Local inspector 与 Delivery 删除

- RED：现有 route 仍直接组合 YAML、compiler、manifest loader、Local store 与 preview helper。
- GREEN：引入只负责本地编译/manifest facts 的 adapter；route 只做权限、请求/响应和稳定错误映射；删除 Stage 专用 route helpers。
- 停止条件：需要迁移 raw Contract 或 Skill Pack 编辑。

### Task ACW-WS3：Dashboard 单次保存与独立复核

- RED：Dashboard 保存 Stage 先调用 Contract endpoint，再调用 Stage endpoint。
- GREEN：Stage command 携带当前 template 与 Draft revision，一次调用完成；保留显式 Save Core 行为。
- 验证：主代理执行聚焦、全量、静态与前端门禁；独立子 Agent 复验 scope→diff、权限、CAS、审计、Prompt 安全、preview 无执行、旧实现删除、错误映射和范围隔离。
