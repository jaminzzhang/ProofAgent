# Agent Configuration Workspace Scope、准入与 TDD 计划

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | Slice 3 `LOCAL_VERIFIED`；独立子 Agent `PASS` |
| 最高风险等级 | P1 |
| 一句话依据 | 架构评审已固定目标 seam；现有 Local/PostgreSQL lifecycle adapters、Configuration UoW、sole-Agent policy 和 API 行为提供了完整证据 |
| 下一步建议 | Slice 3 收口；下一切片重新 Scope rollback authority，不复用本切片生产结论 |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| 用户请求 | 当前对话 | 是 | 同意继续 publication authority 切片；每个切片完成后由子 Agent 按明确流程验证 | Slice 1、2 已完成；当前为 Slice 3 |
| 架构评审 | `architecture-review-20260818-220308.html` | 是 | Delivery 与 concrete store 耦合；推荐 deep application module 与 focused ports | Graphify 图较旧，只作导航 |
| 项目规则 | `AGENTS-COMMON.md`、hicode coding rules | 是 | production PostgreSQL 权威、原子审计、TDD、无兼容 facade | 无 |
| 领域与 ADR | Agent Configuration context、ADR-0009、ADR-0011 | 是 | Workspace、Draft、Published Version、模块/lifecycle 分离 | context 含已退役知识术语，后续单独清理 |
| 当前实现 | configuration routers、Workspace、production application、Local/PostgreSQL adapters | 是 | development publish route 已改走 Workspace；rollback、编辑与 canonical seed bootstrap 仍是后续切片 | 无 |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | `NO_BLOCKING_GAPS` |
| 需求分析输入 | 用户请求、架构报告、现有稳定 API、两个真实 persistence adapters、生命周期规则 |
| 证据缺口 | 正式生产 Phase F publisher 与 development Draft publisher 的 Gate 不同；本切片只迁移后者 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | 用一个 Control-owned deep module 隐藏 Draft lifecycle、validation 和 development publication 的 persistence、evidence 与 policy 细节 |
| 范围内 | Slice 1/2 已有能力；Slice 3 development publish interface、validation outcome/freshness/blocker Gate、immutable version、Draft/pointer CAS、activation/audit、Local transaction baseline CAS、Local publication validator、API 回归、文档 |
| 范围外 | production validation/publish endpoint、正式 Phase F publisher、rollback、Contract/Workflow/Skill 编辑、schema、部署 |
| 非目标 | 新增 facade 后保留旧调用；统一 development 与 production 能力；把本地验证描述为生产批准 |
| 验收标准 | Workspace 行为与负向契约测试、API 回归、Local/PostgreSQL persistence 回归、Ruff/Mypy/Dashboard 与全量后端通过；publish route 不直接组合 compiler 或具体 store；独立子 Agent 复验 |
| `feature_context.md` 更新 | 已创建 |
| ADR 处理 | 不需要；ADR-0009、ADR-0011 与架构评审已固定 seam，当前切片可逆且不改变权威 |

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
| 建议结论 | `TDD_INPUT_READY` |
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
