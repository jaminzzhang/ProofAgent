# Agent Configuration Workspace Scope、准入与 TDD 计划

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | Slice 8D KSS Knowledge binding 主代理 `LOCAL_VERIFIED`；独立复验 `PASS_WITH_ENV_LIMITATION` |
| 最高风险等级 | P1 |
| 一句话依据 | Knowledge 专用交互只保存无密钥 exact KSS Release Draft candidate；live catalog 校验、revision CAS、双层审计与稳定错误映射保持在 Workspace 权威链路 |
| 下一步建议 | 进入部署与端到端交互验证；真实 PostgreSQL DSN 证据仍保持 `PARTIAL_VERIFICATION` |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| 用户请求 | 当前对话 | 是 | 用户要求恢复 Agent Detail 的 Workflow、Knowledge、Model 等专用交互，并在每个切片完成后由子 Agent 按明确流程验证 | Slice 8D 已完成并独立复验通过 |
| 架构评审 | `architecture-review-20260818-220308.html` | 是 | Delivery 与 concrete store 耦合；推荐 deep application module 与 focused ports | Graphify 图较旧，只作导航 |
| 项目规则 | `AGENTS-COMMON.md`、hicode coding rules | 是 | production PostgreSQL 权威、原子审计、TDD、无兼容 facade | 无 |
| 领域与 ADR | Agent Configuration context、ADR-0009、ADR-0011 | 是 | Workspace、Draft、Published Version、模块/lifecycle 分离 | context 含已退役知识术语，后续单独清理 |
| 当前实现 | Production configuration router、Workspace、KSS management client 与 Dashboard module editors | 是 | Slice 8A 已恢复 Tools/Policy/Model/Memory/Response；Slice 8B Workflow、8C Skill Pack、8D KSS exact Release selector/save 已独立通过 | 真实 PostgreSQL DSN 证据待环境提供 |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | Slice 8A/8B/8C/8D 均已完成主代理验证与独立复验；部署和端到端验证可继续 |
| 需求分析输入 | 用户明确的交互恢复目标、领域规则、现有稳定 API、Configuration UoW、Contract/Workflow/Skill Pack Workspace command 与 Dashboard editor 回归 |
| 证据缺口 | 当前环境未配置 `PROOF_AGENT_TEST_POSTGRES_DSN`，真实 PostgreSQL UoW 证据为 2 项 skip；本轮不形成生产发布批准 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | 让 Production Agent Detail 通过 Control-owned Workspace 恢复 Contract、Workflow、Skill Pack 与 KSS Knowledge Draft candidate 专用交互，同时保持 Development/Production 共用一套业务权威 |
| 范围内 | Slice 8A 的 Tools/Policy/Model/Memory/Response Contract 保存；Slice 8B 的 Workflow catalog、Core、Stage 与 Preview；Slice 8C 的 Skill Pack 列表与 create/update/delete；Slice 8D 的 exact KSS Release Draft candidate 读取/保存；权限、revision CAS、双层 audit、稳定错误映射与 Dashboard stale-state 保护 |
| 范围外 | KSS 管理写操作、credential/scorer、executable binding/profile、production validation/publication/activation/rollback；不修改 schema，不执行正式生产发布 |
| 非目标 | 复制 Workspace 业务规则到 Production route；用通用 YAML 表单代替专用交互；恢复旧 Knowledge Source/Hybrid 权威；把本地验证描述为生产批准 |
| 验收标准 | Production API、Workspace/adapter、Dashboard 行为测试、Ruff/Mypy、前端构建与全量后端通过；每次 mutation 携带当前 revision；KSS candidate 只接受 exact、queryable、完整父级四元组；400/409/500/503 保留用户输入且不 blind rebase；独立子 Agent 复验 |
| `feature_context.md` 更新 | 已创建 |
| ADR 处理 | 执行 ADR-0009、ADR-0011 与 ADR-0211；Draft candidate 与 executable KSS binding/profile 保持分离，新增 Production route 不改变 SQL schema |

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

## 26. Slice 6 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立子 Agent `PASS / NO_BLOCKING_FINDINGS` |
| 最高风险等级 | P1 |
| 公开 interface | `AgentConfigurationWorkspace.update_contract(...)`；读取复用 `get_draft(...)` |
| 可观察行为 | GET 返回既有完整 Contract Bundle；PATCH 合并三个可选 YAML 文件，整包校验后以 expected revision CAS 保存，并原子追加 Draft operation audit 与全局 audit |
| 兼容边界 | 保持 HTTP method/path、`agent.view`/`agent.edit` 权限和成功响应；`expected_revision` 为可选兼容字段，旧调用在 Route 读取当前 revision 后仍由 Workspace 最终 CAS 防止竞态覆盖 |
| 范围外 | Skill Pack 专用编辑、canonical seed bootstrap、production Contract endpoint、validation/publication/activation/rollback、schema、部署 |
| ADR 判断 | 不需要；执行现有 Workspace ownership、Contract Bundle 与 Draft CAS 规则 |

## 27. Slice 6 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-CT-ROOT | Operator 读取或保存 raw Contract | Delivery 只调用 Workspace interface | Contract Bundle projection | HTTP interface 与 AST 删除测试 | P1 |
| ACW-CT-MAIN-1 | PATCH 含三个可选 YAML 文件与 expected revision | Workspace 从 revisioned Draft 合并候选 Bundle，保留 extra files 与 advanced fields | 完整 candidate Draft | partial update、preservation tests | P1 |
| ACW-CT-MAIN-2 | candidate 构建完成 | injected adapter 在临时目录编译、加载 manifest 并校验 Business Flow Skill Packs | candidate 可提交 | valid/invalid/no-residue tests | P1 |
| ACW-CT-MAIN-3 | 整包校验通过 | Configuration UoW 以 expected revision 保存 Draft，并在同一事务追加 operation/global audit | revision +1 | CAS、audit、commit failure tests | P1 |
| ACW-CT-BRANCH-1 | client revision 已过期或校验期间并发写入 | precheck 或 repository CAS 拒绝 | stable 409；不覆盖赢家 | stale/interleaving tests | P1 |
| ACW-CT-BRANCH-2 | YAML、compiler、manifest 或 Skill Pack 校验失败 | adapter 收敛临时路径与底层错误；Delivery 返回稳定 400 | Draft/audit 不变 | invalid/fault/error tests | P1 |
| ACW-CT-BRANCH-3 | adapter/UoW 抛非预期异常 | Delivery 返回稳定 500，不暴露内部路径或异常文本 | 无部分写入 | OSError/RuntimeError tests | P1 |
| ACW-CT-BOUND-1 | Contract 保存成功 | 不创建 Validation Record、Published Version、activation 或 rollback | 仅 Draft revision 改变 | negative assertions | P1 |

## 28. Slice 6 TDD 任务

### Task ACW-CT1：Workspace Contract 行为

- RED：从 Workspace interface 证明局部文件合并、revision CAS、整包校验、双层 audit 与 lifecycle 负向边界。
- GREEN：实现 `update_contract(...)`，只依赖 injected validator 与 Configuration UoW。
- 停止条件：需要拆分 module-specific typed commands、改变 public Contract schema 或数据库 schema。

### Task ACW-CT2：Local validator 与 Delivery 删除

- RED：现有 GET/PATCH route 直接依赖 Local store，PATCH 组合 compiler、manifest loader 与 Skill Pack 校验。
- GREEN：引入无 concrete store 依赖、自动清理临时目录的 Local validator；GET/PATCH 只保留权限、请求/响应和稳定错误映射；删除 Contract 专用 route helpers。
- 停止条件：需要迁移 Skill Pack 专用 route 或 canonical seed bootstrap。

### Task ACW-CT3：Dashboard CAS 与独立复核

- RED：Dashboard raw Contract 保存不发送当前 Draft revision，旧 PATCH 允许 last-write-wins。
- GREEN：client/request 增加可选 `expected_revision`，页面保存显式传递当前 revision；旧调用兼容但仍由服务端 CAS 关闭竞态。
- 验证：主代理执行聚焦、全量、静态与前端门禁；独立子 Agent 按 scope→diff、权限、候选校验、CAS、事务/audit、无残留、旧实现删除、错误映射和范围隔离清单复验。

## 29. Slice 7 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS / NO_BLOCKING_FINDINGS` |
| 最高风险等级 | P1 |
| 公开 interface | `get_business_flow_skill_packs(...)`、`create_business_flow_skill_pack(...)`、`update_business_flow_skill_pack(...)`、`delete_business_flow_skill_pack(...)` |
| 可观察行为 | GET 返回 revisioned projection；mutation 以完整 typed command 更新 manifest binding 与 package-local definition，经 adapter 校验后 CAS 保存并追加双层 audit |
| 兼容边界 | 保持 HTTP method/path、`agent.view`/`agent.edit` 权限与既有字段；新增 `revision` 响应字段和可选 `expected_revision`，旧调用由 Route 读取当前 revision 后仍受最终 CAS 保护 |
| 范围外 | canonical seed bootstrap、production Skill Pack endpoint、raw Contract 语义变更、KSS binding 编辑、validation/publication/activation/rollback、schema、部署 |
| ADR 判断 | 不需要；执行现有 Workspace ownership、Contract Bundle、Draft CAS 与 ADR-0210 KSS 权威边界 |

## 30. Slice 7 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-SP-ROOT | Operator 读取或编辑 Skill Pack | Delivery 只调用 Workspace interface | revisioned Skill Pack projection | interface 与 AST 删除测试 | P1 |
| ACW-SP-MAIN-1 | GET 当前 Draft Skill Pack | Workspace 读取 revisioned Draft，由 injected adapter 在自动清理目录内编译与投影 | 稳定逻辑引用与配置问题 | 无残留、无临时绝对路径 | P1 |
| ACW-SP-MAIN-2 | POST/PATCH/DELETE 携带 expected revision | Control typed command 同时构建 manifest binding 与 definition candidate | 完整 Contract Bundle | create/update/delete 行为 | P1 |
| ACW-SP-MAIN-3 | candidate 构建完成 | adapter 校验完整 Skill Pack set 并生成 candidate projection | 可提交候选 | schema、stage、capability ref Gate | P1 |
| ACW-SP-MAIN-4 | inspection 通过 | Configuration UoW CAS 保存 Draft，并在同一事务追加 operation/global audit | revision +1 | audit、commit failure、lifecycle negative | P1 |
| ACW-SP-BRANCH-1 | client revision 过期或 inspection 期间并发写入 | precheck 或 repository CAS 拒绝 | stable 409；不覆盖赢家 | stale/interleaving tests | P1 |
| ACW-SP-BRANCH-2 | binding、definition、loader 或 adapter 拒绝 | Delivery 返回稳定 400；Draft/audit 不变 | 无部分写入 | invalid/path safety tests | P1 |
| ACW-SP-BRANCH-3 | adapter/UoW 非预期异常 | Delivery 返回稳定 500，不暴露内部异常 | 无 fallback | fault tests | P1 |
| ACW-SP-BOUND-1 | Skill Pack 保存成功 | 不创建 Validation Record、Published Version、activation 或 KSS mutation | 仅 Draft revision 改变 | negative assertions | P1 |

## 31. Slice 7 TDD 任务

### Task ACW-SP1：Workspace typed authority

- RED：从 Workspace interface 证明完整 create、update、delete、revision CAS、inspection 期间并发冲突、双层 audit 与 lifecycle 负向边界。
- GREEN：把 Contract Bundle mutation 收入 Control-owned Skill Pack command module；Workspace 只依赖 injected inspector 与 Configuration UoW。
- 停止条件：需要改变 runtime Skill Pack admission、KSS binding 或数据库 schema。

### Task ACW-SP2：Local inspector 与 Delivery 删除

- RED：现有四个 route 直接依赖 Local store、YAML、compiler、manifest loader 与 projection helpers，并保留长期 `compiled_projection`/`compiled_validation` 目录。
- GREEN：引入无 concrete store 依赖且自动清理临时目录的 Local inspector；route 只保留权限、request/response 和稳定错误映射；删除旧 Skill Pack helpers/imports。
- 停止条件：需要迁移 canonical seed bootstrap 或 raw Contract 高级入口。

### Task ACW-SP3：Dashboard 单命令与独立复核

- RED：Dashboard 创建完整 Skill Pack 先 POST 再 PATCH，mutation 不发送当前 revision。
- GREEN：create request 一次携带全部字段；create/update/delete 显式发送当前 Skill Pack projection revision，成功响应立即推进 revision。
- 验证：主代理执行聚焦、全量、静态与前端门禁；独立子 Agent 按 scope→diff、权限、typed authority、CAS、事务/audit、临时路径安全、单命令、旧实现删除、错误映射、KSS/生命周期范围隔离清单复验。

## 32. Slice 8 总体方案：恢复 Production Agent Detail 配置交互

| 项 | 内容 |
| --- | --- |
| 用户目标 | 找回 Agent Detail 的 Workflow、Knowledge、Tools、Policy、Model、Memory、Response 与 Skill Pack 交互，并适配新的 Workspace 与 KSS 权威 |
| 根因 | Production capability 只声明 `general` 可编辑，且 Production composition 未注入 Contract、Workflow Stage 与 Skill Pack inspector；Knowledge 旧编辑器随 KSS 切换被删除 |
| 推荐方案 | 按四个垂直切片恢复：8A Contract 模块、8B Workflow、8C Skill Pack、8D KSS Knowledge binding |
| 不采用方案 | 只在前端显示 Save；恢复旧 Knowledge Source/Hybrid API；一次开放全部 Production route |
| 共同不变量 | `agent.edit` 权限、调用方 revision CAS、Draft operation audit 与全局 audit 同事务、稳定错误映射、失败不落盘、保存不等于验证或发布 |
| 验证方式 | 每个切片先完成 RED/GREEN/REFACTOR 与聚焦门禁，再启动独立子 Agent 按明确清单复验 |

## 33. Slice 8A 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS_WITH_ENV_LIMITATION` |
| 最高风险等级 | P1 |
| 公开 interface | Production `PATCH /api/config/agents/{agent_id}/drafts/{draft_id}/contract`；Control 复用 `AgentConfigurationWorkspace.update_contract(...)` |
| 可观察行为 | Tools、Policy、Model、Memory、Response 显示结构化编辑器；保存完整 Agent YAML candidate，成功后 revision 增加并刷新页面 |
| 兼容边界 | GET Contract 与 Development PATCH 路径/响应不变；Production 新增同路径 PATCH；不改变数据库 schema |
| 范围外 | Workflow Stage、Skill Pack、Knowledge/KSS binding、validation、publication、activation、rollback |
| ADR 判断 | 不需要新增 ADR；执行 ADR-0009、ADR-0011 与既有 Workspace、Draft CAS、Contract Bundle 决策。Production public route 的批准设计记录即本节与用户明确请求 |

## 34. Slice 8A 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-PCT-ROOT | Production Operator 保存五个 Contract 模块之一 | Production Delivery 只调用 Workspace `update_contract(...)` | Contract Bundle | route delegation 与 AST/import 边界 | P1 |
| ACW-PCT-MAIN-1 | 请求携带 Agent YAML 与 expected revision | Pydantic 严格校验；Workspace 构建完整 candidate | 待校验 Draft | 未知字段、缺 revision、空请求 | P1 |
| ACW-PCT-MAIN-2 | candidate 构建完成 | Production composition 注入无持久化权威的临时 Contract validator | 有效 candidate | 合法/无效 YAML、自动清理、无路径泄漏 | P1 |
| ACW-PCT-MAIN-3 | candidate 校验通过 | PostgreSQL Configuration UoW 以 expected revision 提交 Draft 与 audit | revision +1 | CAS、双层 audit、事务回滚 | P1 |
| ACW-PCT-BRANCH-1 | stale revision | Workspace 或 repository CAS 拒绝 | 稳定 409 | 不覆盖并发赢家；前端提示并要求刷新 | P1 |
| ACW-PCT-BRANCH-2 | candidate 无效 | 返回稳定 400 `agent_contract_invalid` | Draft/audit 不变 | 不泄漏临时路径或底层异常 | P1 |
| ACW-PCT-BRANCH-3 | validator/UoW 非预期失败 | 返回稳定 500 `agent_contract_update_failed` | 无部分写入 | OSError/RuntimeError fault test | P1 |
| ACW-PCT-BOUND-1 | 保存成功 | capability 只增加五个模块；Workflow、Skills、Knowledge 仍只读 | 生命周期权威不变 | negative route/capability assertions | P1 |

## 35. Slice 8A TDD 任务

### Task ACW-PCT1：Production HTTP 契约 RED/GREEN

- RED：Production Contract PATCH 当前为 405，Production Draft 只声明 `general` 可编辑。
- GREEN：新增严格请求模型、`agent.edit` 权限、Workspace delegation 与稳定 400/404/409/500 映射；capability 仅加入 Tools、Policy、Model、Memory、Response。
- 停止条件：需要改变 Workflow、Skill Pack、Knowledge 或 lifecycle route。

### Task ACW-PCT2：Production composition 与 PostgreSQL 权威

- RED：Production Workspace 缺少 Contract validator，调用 `update_contract(...)` 返回 `agent_contract_update_unavailable`。
- GREEN：composition 注入既有临时整包 validator；持久化仍只使用 PostgreSQL Configuration UoW。
- 停止条件：validator 需要持久化本地文件或新增数据库 schema。

### Task ACW-PCT3：Dashboard 保存与独立复核

- RED：Production capability 下五个模块只显示配置文件投影，没有保存控件。
- GREEN：服务端 capability 驱动既有结构化编辑器；保存显式发送当前 revision，成功刷新 Draft/Contract；失败保留当前编辑与错误提示。
- 验证：后端 route/Workspace/PostgreSQL 聚焦测试、Dashboard 每模块保存测试、Ruff、Mypy、TypeScript、build、domain-context、diff；完成后启动独立子 Agent 复验权限、CAS、audit、错误映射、模块边界和生命周期隔离。

## 36. Slice 8B 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS / NO_BLOCKING_FINDINGS` |
| 最高风险等级 | P1 |
| 公开 interface | Production Workflow Template catalog/detail；Production Workflow Stage update/preview；Core 保存继续复用 Contract PATCH |
| 可观察行为 | Workflow 模块显示 Template、Core 参数、Stage Inspector 与 Context Preview；Core/Stage 保存分别为单命令，均携带当前 Draft revision |
| 兼容边界 | 保持 Development HTTP method/path、请求/响应与权限语义；Production 新增相同路径；不改变数据库 schema |
| 范围外 | Skill Pack、Knowledge/KSS binding、validation、publication、activation、rollback |
| ADR 判断 | 不需要新增 ADR；执行既有 Workflow Stage Configuration、Prompt Authority Boundary、Workspace 与 Draft CAS 决策 |

## 37. Slice 8B 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-PWS-ROOT | Production Operator 打开 Workflow | 读取 backend-owned Template catalog/detail 和当前 Contract | 完整 Workflow Editor | production route 与 descriptor contract | P1 |
| ACW-PWS-MAIN-1 | 保存 Core 参数 | 复用 Slice 8A Contract PATCH | revision +1 | revision、candidate validation、stale handling | P1 |
| ACW-PWS-MAIN-2 | 保存 template、descriptor version 与 stages | Production Delivery 调用 `update_workflow_stages(...)` | revision +1 | 单命令、Prompt Gate、CAS、双层 audit | P1 |
| ACW-PWS-MAIN-3 | 预览未保存的 Prompt/context | Delivery 调用 `preview_workflow_stage(...)` | 脱敏、限长 preview | 无模型、工具、Run、Draft 或 audit 写入 | P1 |
| ACW-PWS-BRANCH-1 | descriptor、stage、Prompt 或 context 无效 | 返回稳定 400；不保存 | Draft/audit 不变 | 不泄漏路径或 Prompt | P1 |
| ACW-PWS-BRANCH-2 | stale revision 或提交期间并发写入 | Workspace/PostgreSQL CAS 拒绝 | 稳定 409 | 不覆盖赢家；前端保留编辑并提示刷新 | P1 |
| ACW-PWS-BRANCH-3 | inspector/UoW 非预期失败 | 返回稳定 500 | 无部分写入 | fault tests | P1 |
| ACW-PWS-BOUND-1 | Workflow 闭环完成 | capability 只新增 `workflow`；Skills、Knowledge 仍只读 | 生命周期权威不变 | negative capability/route assertions | P1 |

## 38. Slice 8B TDD 任务

### Task ACW-PWS1：共享 HTTP contract 与 Production route

- RED：Production Template 请求为 404，Stage update/preview 为 404/405，Workflow capability 不可编辑。
- GREEN：提取 Development/Production 共用的严格 Workflow request/serialization；新增 Production catalog/detail、update/preview route 与稳定错误映射。
- 停止条件：需要改变 Skill Pack、Knowledge 或 lifecycle route。

### Task ACW-PWS2：Production composition 与安全边界

- RED：Production Workspace 未注入 Workflow Stage inspector。
- GREEN：注入既有自动清理 inspector；保持 PostgreSQL 为唯一 Draft/audit 持久化权威；preview 不写状态。
- 停止条件：inspector 需要持久化本地编译目录或执行模型、工具、Run。

### Task ACW-PWS3：Dashboard stale-state 与独立复核

- RED：Production Workflow 只显示只读投影；保存冲突未证明保留编辑内容。
- GREEN：capability 驱动既有 Workflow Editor；Core/Stage 保存都发送 revision；409 后不自动升级 revision 或覆盖并发赢家，用户刷新后重新编辑。
- 验证：聚焦后端、Dashboard Workflow、静态、构建、domain-context、diff；切片完成后独立子 Agent 复验 catalog、权限、CAS/audit、Prompt 安全、preview 无执行、错误映射、stale UX 和生命周期隔离。

## 39. Slice 8C 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS_WITH_ENV_LIMITATION / NO_BLOCKING_FINDINGS` |
| 最高风险等级 | P1 |
| 公开 interface | Production Skill Pack GET、Business Flow create/update/delete；复用现有 Workspace typed commands |
| 可观察行为 | Skills 模块显示 revisioned Pack 列表；Drawer 可创建、更新、删除；成功响应立即推进 projection revision |
| 兼容边界 | 保持 Development HTTP method/path、字段、响应和权限语义；Production 新增相同路径并强制调用方 revision；不改变数据库 schema |
| 范围外 | Knowledge/KSS binding、validation、publication、activation、rollback |
| ADR 判断 | 不需要新增 ADR；执行既有 Workspace、Contract Bundle、Skill Pack 与 KSS 权威边界 |

## 40. Slice 8C 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-PSP-ROOT | Production Operator 打开 Skills | Workspace inspector 返回 revisioned projection | Pack list 与配置问题 | GET permission、稳定 projection、无路径泄漏 | P1 |
| ACW-PSP-MAIN-1 | 创建完整 Pack | typed create command 一次构建 binding 与 definition | revision +1 | 单命令、schema/ref Gate、双层 audit | P1 |
| ACW-PSP-MAIN-2 | 更新或删除 Pack | target ID 与调用方 revision 固定；Workspace 构建完整 candidate | revision +1 | identity、CAS、audit、definition cleanup | P1 |
| ACW-PSP-MAIN-3 | candidate 构建完成 | 自动清理 inspector 编译、校验和投影 | 可提交 candidate | package-local path、临时目录、trace-safe issue | P1 |
| ACW-PSP-BRANCH-1 | stale revision | Workspace/PostgreSQL CAS 拒绝 | 稳定 409 | 不 retarget、不 blind rebase；显式 Reload Latest | P1 |
| ACW-PSP-BRANCH-2 | binding/definition/ref 无效 | 稳定 400 | Draft/audit 不变 | loader 前置边界、无 raw ref/path 泄漏 | P1 |
| ACW-PSP-BRANCH-3 | inspector/UoW 非预期失败 | 稳定 500 | 无部分写入 | fault tests | P1 |
| ACW-PSP-BOUND-1 | Skill Pack 闭环完成 | capability 只新增 `skills`；Knowledge 仍只读 | 生命周期权威不变 | KSS/lifecycle negative assertions | P1 |

## 41. Slice 8C TDD 任务

### Task ACW-PSP1：共享 HTTP contract 与 Production route

- RED：Production Skill Pack GET/POST/PATCH/DELETE 为 404，Skills capability 不可编辑。
- GREEN：提取 Development/Production 共用的严格请求、Control command translation 和 projection serialization；Production mutation 强制 expected revision。
- 停止条件：需要改变 KSS binding、runtime admission 或 lifecycle route。

### Task ACW-PSP2：Production composition 与安全边界

- RED：Production Workspace 未注入 Skill Pack inspector。
- GREEN：注入既有自动清理 inspector；持久化仍只使用 PostgreSQL UoW；所有 definition ref 在 loader 前失败关闭。
- 停止条件：inspector 需要持久化本地编译目录或访问 package 外文件。

### Task ACW-PSP3：Dashboard stale-state 与独立复核

- RED：Production Skills 只显示只读投影。
- GREEN：capability 驱动既有 Skills editor；mutation 使用 projection revision；409 保留输入、冻结原 target，只有显式 Reload Latest 后才能重新保存。
- 验证：聚焦后端、Dashboard Skills、静态、构建、domain-context、diff；切片完成后独立子 Agent 复验权限、typed authority、CAS/audit、路径安全、trace-safe projection、stale UX、错误映射和 KSS/lifecycle 隔离。

## 42. Slice 8D 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | 主代理 `LOCAL_VERIFIED`；按 ADR-0211 实现的 Draft KSS Release Binding Candidate 独立复验 `PASS_WITH_ENV_LIMITATION` |
| 最高风险等级 | P1 |
| 公开 interface | Production Agent Knowledge binding GET/PATCH；Workspace typed read/update；Dashboard exact Release selector |
| 可观察行为 | Knowledge 模块显示 KSS readiness、queryable Release catalog 与当前 Draft candidate；保存携带当前 revision，成功只更新 Draft authoring state |
| 权威边界 | KSS 拥有 Catalog/Release；Draft 只保存 secret-free exact identity tuple；deployment profile 与 Phase F publisher 仍拥有 executable binding construction |
| 兼容边界 | 不恢复 manifest `knowledge_bindings`、旧 Source/Hybrid API 或本地 fallback；Development Knowledge 保持可见只读且不调用 Production 专用 route；不改变 Production lifecycle capability；Draft 使用现有 JSONB，无 SQL schema migration |
| 范围外 | KSS Space/Source/Base/Release 管理、credential/scorer 编辑、正式 Phase F publication integration、activation、rollback、当前问答运行时切换 |
| ADR 判断 | ADR-0211：Draft candidate 与 executable binding/profile 分离是不可逆且易被误解的权威决策 |

## 43. Slice 8D 设计树

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-PKB-ROOT | Production Operator 打开 Knowledge | Workspace 读取 Draft 与 live KSS catalog | revisioned catalog + current candidate | `agent.view` 与 `knowledge_source.view`、trace-safe projection | P1 |
| ACW-PKB-MAIN-1 | Operator 选择 exact Release 并保存 | strict typed command 固定 Space/Base/Base Version/Release tuple | Draft candidate | 不接受 `latest`、retired、missing 或 parent mismatch | P1 |
| ACW-PKB-MAIN-2 | KSS catalog 验证通过 | Workspace 在 PostgreSQL Configuration UoW 中以 Draft revision CAS 保存 candidate 与双层 audit | revision +1 | CAS、audit 原子性、metadata 无 secret | P1 |
| ACW-PKB-BRANCH-1 | KSS unavailable 或 Release 不可查询 | fail closed，返回稳定 400/503 | Draft/audit 不变 | 无 local fallback、无底层 URL/credential 泄漏 | P1 |
| ACW-PKB-BRANCH-2 | stale revision | 返回稳定 409，保留用户选择并冻结重试 | 显式 Reload Latest | 不 blind rebase、不改变 Active Version | P1 |
| ACW-PKB-BOUND-1 | Draft candidate 保存成功 | capability 只新增 `knowledge`；lifecycle actions 继续关闭 | authoring state only | publisher/runtime/env binding 负向隔离 | P1 |

## 44. Slice 8D TDD 任务

### Task ACW-PKB1：领域 contract 与 Workspace 权威

- RED：Draft 无 first-class KSS candidate；Workspace 无 exact Release catalog/read/update interface。
- GREEN：新增 secret-free candidate contract、catalog inspector port 与 revisioned Workspace result；save-time 校验 ready/queryable/exact parent tuple，并以 CAS 和双层 audit 原子提交。
- 停止条件：需要把 credential、scorer、Source 配置或 KSS content 写入 Draft。

### Task ACW-PKB2：Production HTTP/composition 与失败关闭

- RED：Production Knowledge 仅显示旧 manifest 字段的只读空投影，Agent-specific KSS binding route 不存在。
- GREEN：Production GET/PATCH 只委托 Workspace；组合既有 KSS management client 作为 catalog inspector；要求 Agent 与 Knowledge view/edit 权限，提供稳定 400/404/409/500/503。
- 停止条件：需要恢复 Hybrid/local fallback 或开放 production lifecycle route。

### Task ACW-PKB3：Dashboard 交互与独立复核

- RED：Production Knowledge 无 selector 或保存控件。
- GREEN：Production 显示 authoring-only 状态、readiness 与 queryable Releases；保存发送 projection revision；409 保留选择并要求显式 Reload Latest；Development 保留 Knowledge Contract 只读投影且不请求 Production 专用 route。
- 验证：Workspace/API/PostgreSQL 聚焦、Dashboard Knowledge、权限/错误/审计/隔离负向、静态与全门禁；完成后启动独立子 Agent 复验。

## 45. Slice 8E 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `TDD_INPUT_READY`；补充发布前作者侧配置只读聚合，显式展示正式 publisher 未绑定 Workspace Draft，不开放正式生产发布命令 |
| 最高风险等级 | P1 |
| 公开 interface | Workspace `get_publication_configuration(...)`；Production `GET /api/config/agents/{agent_id}/drafts/{draft_id}/publication-configuration`；Dashboard `publication` lifecycle tab |
| 可观察行为 | 展示同一 Draft revision 的 Workflow、精确 KSS Release、生产模型角色、作者侧检查项，以及正式 publisher 的通用 Phase F、online smoke 和 PostgreSQL 原子激活要求；正式状态固定为 `workspace_draft_not_bound` |
| 权威边界 | Workflow、Knowledge、Model、Tools、Memory 等源模块继续拥有各自保存命令；发布配置不新增持久化字段，也不读取凭据或生成发布批准 |
| 兼容边界 | Production 只新增 GET route 与 capability tab；Development 不请求该 route；现有 `ProductionAgentPublicationService`、CLI、独立候选输入、权限和 Phase F Gate 行为不变，不声称它消费 Workspace Draft |
| 范围外 | Dashboard publish/activate、Phase F evidence 上传或保存、smoke question 保存、credential 解析、正式 online smoke、Blue/Green deployment、rollback |
| ADR 判断 | 不新增 ADR；复用 ADR-0168 的服务端就绪度聚合模式、ADR-0208 的 Gate 不减配原则，以及 ADR-0211 的 Draft candidate/正式发布边界 |

## 46. Slice 8E 设计树与 TDD 任务

| 节点 | 触发条件 | 处理方案 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ACW-PPC-ROOT | Production Operator 打开「发布配置」 | Workspace 从同一 Draft revision 读取 Contract，结合 live KSS catalog 与 Shared Model Connection reader | trace-safe publication projection | 双权限、revision identity、无 credential/base URL/path | P1 |
| ACW-PPC-MAIN-1 | Draft 合同可解析 | projector 检查 Contract/Draft identity、production workflow、package/legacy Knowledge 禁令、Tools/Memory、fail-closed review、inline credential 禁令与所有模型角色 | 作者侧 `ready` 或稳定 blockers | 与 production admission 规则对齐；identity mismatch、未知、缺失或 inline credential 配置失败关闭 | P1 |
| ACW-PPC-MAIN-2 | Draft 选择 exact KSS Release | 对实时 catalog 做完整父级身份与 `queryable` 匹配 | Knowledge candidate 状态 | 不接受 `latest`、不构造 executable binding | P1 |
| ACW-PPC-MAIN-3 | 配置聚合完成 | Dashboard 在 Release 分组展示来源、作者侧检查项、正式 Gate 要求和未绑定状态，并提供源模块导航 | 可审查的发布前作者侧快照 | 不出现 ready-to-publish 或 Publish 按钮；Development 不调用专用 route | P1 |
| ACW-PPC-BRANCH-1 | KSS/model catalog 或 Contract 不可用 | 返回稳定 blocker 或 400/503/500 | 无 side effect | 不泄漏内部 detail，不读取 secret | P1 |
| ACW-PPC-BOUND-1 | 作者侧配置检查通过 | 仍保持 `workspace_draft_not_bound` 与 `can_publish_from_dashboard=false` | 不产生正式发布就绪、发布或激活结论 | 现有正式 publisher 继续使用独立候选输入；绑定 Workspace Draft 必须另立 authority integration 切片 | P1 |

### Task ACW-PPC1：Control projector 与 Workspace 聚合

- RED：不存在发布配置 projector 和 Workspace interface。
- GREEN：生成无密钥 Workflow、KSS、Model role 与 blocker projection；KSS 和模型均读取 live authority。
- 停止条件：需要保存 Phase F evidence、credential、smoke question 或 release approval。

### Task ACW-PPC2：Production HTTP 与 Dashboard

- RED：Production route 为 404，Release 分组只有「版本」。
- GREEN：新增双权限 GET route、稳定错误映射和 capability 驱动的「发布配置」页；源配置继续在各模块保存。
- 停止条件：需要开放 publish、activate 或 rollback mutation。

### Task ACW-PPC3：验证与独立复核

- 覆盖完整/阻断 Draft、KSS queryability、Shared Model Connection lifecycle/provider/credential authority、权限、错误不泄漏、Development 隔离和无 publication side effect。
- 运行聚焦与仓库级 backend、Dashboard/Chat、Ruff、Mypy、TypeScript、build、domain-context、diff 与 lock；完成后启动独立子 Agent 复验。

## 47. Slice 8F 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `TDD_INPUT_READY`；修复 Agent Detail 已复现的 revision、脏状态、Validation freshness、计数、回滚确认和 Development session 断点 |
| 最高风险等级 | P1 |
| 公开 interface | Development Draft metadata PATCH 增加可选 `expected_revision`；Development `/api/auth/session` 返回本地 Operator 投影；其他 HTTP path/method 不变 |
| 可观察行为 | 页面显示配置流程、当前 revision、保存状态和 Validation freshness；未保存配置阻断 Validation；旧 Validation 阻断 Development publish；Monitor 采用 Draft Validation Record 计数；rollback 先确认 |
| 权威边界 | Dashboard 只投影并前置失败关闭；Workspace 继续最终校验 validation freshness、执行 revision CAS 和 active pointer CAS |
| 兼容边界 | 未提供 `expected_revision` 的 Development 调用方继续由服务端读取当前 revision；Production metadata request 和 OIDC session 语义不变 |
| 范围外 | Workspace Draft 到正式 publisher 的 candidate binding、Phase F evidence、在线 KSS smoke、生产激活、Blue/Green deployment rollback、全站中英文重写 |
| ADR 判断 | 不新增 ADR；本切片执行 ADR-0009/0011 的 Draft 与 lifecycle 分离，以及现有 Workspace CAS/rollback 权威规则 |

## 48. Slice 8F 目标流程

[SOURCE: ADR-0009、ADR-0011、Slice 8E publication projector 与当前实现 | CONFIDENCE: HIGH]

| 阶段 | Operator 行为 | 服务端权威 | 完成条件 | 失败关闭点 |
| --- | --- | --- | --- | --- |
| 1. 创建与身份 | 从服务端模板创建 Draft，填写名称与用途 | Agent Configuration Workspace | Draft ID 与 revision 可读 | 不从浏览器传 manifest path |
| 2. 模块配置 | 在 Workflow、Skills、Knowledge、Tools、Policy、Model、Memory、Response 间迭代 | 各模块 typed command 或 Contract command | 所有修改已保存到一个明确 revision | 跨模块未保存状态不触发生命周期动作 |
| 3. 作者侧预检 | 查看配置流程和 Production 发布配置聚合 | 服务端 projector | authoring blockers 可定位到源模块 | 作者侧通过不等于正式发布批准 |
| 4. Validation | 对已保存的精确 revision 运行 governed Harness | Workspace validation orchestration | Validation Record 与 operation audit 绑定同一 Draft/revision | 未保存配置、运行冲突或 blocker 均拒绝 |
| 5. 发布准备 | Development 选择当前 Validation；Production 查看 exact KSS/model/Phase F 通用要求 | Development Workspace 或独立正式 publisher | Development freshness 通过；Production 仍显示正式绑定状态 | 旧 Validation、KSS 不可查或 `workspace_draft_not_bound` 不得绕过 |
| 6. 发布与激活 | Development 生成 immutable version；未来 Production 由正式 publisher 执行 smoke 与 CAS | Workspace 或 ProductionAgentPublicationService | immutable version 与 active pointer 原子提交 | Dashboard 不成为第二发布权威 |
| 7. 观察与回滚 | 对照 Draft Validation Record、Run Store 和 active version；确认后切换历史 version pointer | Run/Trace authority 与 Configuration Workspace | 计数语义明确，rollback target 可审查 | 不删除或改写 Published Version history |

## 49. Slice 8F TDD 任务

### Task ACW-FLOW1：Development metadata revision contract

- RED：真实 Dashboard PATCH 携带 `expected_revision`，Development request 因 unknown field 返回 422。
- GREEN：request 接受可选正整数 revision；提供时原样交给 Workspace，未提供时保留兼容读取；stale writer 返回稳定 409 且不覆盖赢家。

### Task ACW-FLOW2：保存状态与生命周期门禁

- RED：Policy 等模块的未保存 YAML 可跨 tab 保留，但 Validation 仍运行服务端旧 Draft；旧 Validation 在 Draft 保存后仍显示可发布。
- GREEN：记录脏模块，持续展示 revision/保存状态；Validation 加入未保存 blocker；Development publish 复用 Workspace 的最新 operation/revision 判定在 UI 失败关闭。

### Task ACW-FLOW3：计数、回滚与 Development session

- RED：Draft 已有 Validation Record 时 Monitor 仍显示 0；rollback 单击立即执行；Development `/api/auth/session` 因缺少 middleware state 返回 500。
- GREEN：Monitor 接收 Draft Validation Record count；rollback 使用显式确认对话框；Development session 投影本地 Operator，Production 缺失 resolution 仍返回 401。

### Task ACW-FLOW4：真实页面复验

- 使用临时 Configuration/History 目录启动真实 backend 与 Dashboard；不重置用户 canonical store。
- 复验 metadata PATCH 200/revision +1、未保存 Validation blocker、旧 Validation publish blocker、Monitor 计数、rollback 确认和 auth session 200；保存关键截图。
- 运行聚焦 backend、Dashboard 全量、TypeScript/build、Ruff、Mypy、domain-context 与 diff-check；不把本地 Development 结果表述为 Production approval。

## 50. Slice 8G 准入结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `LOCAL_VERIFIED`；Agent Detail 配置项已按写入 authority 与 canonical schema 重新核对，修复实际阻断主流程的字段漂移和跨模块保存问题 |
| 最高风险等级 | P1 |
| 公开 interface | 不新增后端 interface；Dashboard 继续使用 metadata PATCH、raw Contract PATCH、Workflow Stage command、Skill Pack CRUD、Knowledge binding、Validation、Development publication/version pointer 与 Production publication snapshot |
| 兼容边界 | 移除 Dashboard 对已退役 manifest 字段的写入；不接受旧字段作为兼容别名，继续由编译校验失败关闭 |
| 范围外 | Workspace Draft 到正式 publisher 的 binding、Phase F evidence、Production online KSS smoke、PostgreSQL activation 与部署 Gate |

## 51. Slice 8G 配置责任矩阵

| Agent Detail 项 | 写入/读取 authority | 核对结果 |
| --- | --- | --- |
| 概览 | Draft metadata PATCH + revision CAS | 基础信息与 Contract dirty state 隔离；无变更不写 |
| Workflow | Contract core + typed Workflow Stage command | Template 同步 descriptor version；不再写 retired runtime/checkpointer |
| Skills | typed Business Flow Skill Pack CRUD | revisioned create/update/delete；不经 raw YAML 旁路 |
| Knowledge | Production exact KSS Release candidate；Development Contract 只读投影 | KSS authority 与环境边界不变 |
| Tools | raw Contract 的 `capabilities.tools` | 移除错误顶层 `tools` 投影；启用缺 file 时前端阻断，服务端继续校验完整 Tool Contract |
| Policy | raw Contract `policy.file` + bundle policy YAML | 文件引用与规则内容边界保持 |
| Model | raw Contract `model`、`react`、`review`、`context` | `max_plan_rounds`、Review controls 与 role/shared model source 对齐 |
| Memory | raw Contract `capabilities.memory` + `context.source_policies.memory_recall` | capability 与 recall policy 分层；不把 Memory 冒充 governed evidence |
| Response | raw Contract `response` | optional root 缺失时可首次插入并保存 |
| 验证与测试 | saved exact Draft revision | 未保存配置阻断；无可准入证据时返回 `REFUSED_NO_EVIDENCE` |
| Contract 视图 | 服务端保存态只读投影 | 不承担编辑 authority |
| 发布配置 | Production authoring snapshot | 继续只读且报告 `workspace_draft_not_bound` |
| 版本/监控 | Development immutable version + active pointer；Run Store/Validation Record 分源统计 | 发布、观察和显式确认回滚主链路通过 |

## 52. Slice 8G TDD 任务

### Task ACW-ADF4：canonical schema 与 optional section

- RED：Model 保存 `react.max_steps` 被服务端拒绝；Workflow template 变更重新写入 retired runtime；Tools 编辑顶层 section 且缺失时形成无效 no-op；Response 缺失时无法插入。
- GREEN：字段只投影到当前 manifest canonical path；通用 YAML helper 支持安全插入缺失顶层 section；Tools 使用专用 normalizer。

### Task ACW-ADF5：模块级保存隔离

- RED：Policy 未保存修改可被 Model 的保存按钮提交；Tools no-op 仍推进 revision。
- GREEN：记录 dirty module，跨模块保存失败关闭；同模块保存和 Workflow Stage 原子 command 仍可执行；无差异保存直接返回。

### Task ACW-ADF6：真实流程复验

- 验证：临时 Development store 中验证 Model canonical 保存、Tools no-op、精确 revision Validation、immutable Development publication、Monitor 投影和确认式 active-pointer rollback。

## 2026-09-07 Dashboard configuration completion (current request)

[KNOWN | HIGH] Current authority: AGENTS-COMMON.md, ADR-0242 and
`proof_agent/contracts/manifest.py`; older KSS scope above is historical.
The user authorizes analysis, local implementation and verification of a systematic,
usable configuration service. Existing Workspace/UoW, capabilities and publication
boundaries remain authoritative; no new runtime or production publication profile.

| Task / acceptance | Outcome and evidence entry | State |
| --- | --- | --- |
| CFG-1 orientation | Overview and compact mobile navigation explain each advertised module, editing availability and configuration/validation/version sequence; no inferred readiness | verified locally |
| CFG-2 retrieval | Knowledge editor exposes effective global top_k, min_score, max_queries and query_timeout_seconds with bounds, units and default semantics; save through existing revisioned Contract command | verified locally |
| CFG-3 policy | Policy and Tools pages edit actual policy_yaml/tools_yaml alongside paths, atomically through existing validator/CAS; invalid/conflicting save retains input | verified locally |
| CFG-4 edit integrity | Draft reads are revision-consistent; Draft/Versions hooks ignore obsolete responses; unsaved Contract/Dataset changes are isolated during module navigation; explicit discard | verified locally |
| CFG-5 verification | UI interaction tests, Dashboard suite/build, affected backend contracts, actual rendered browser with synthetic data, current documentation | verified locally |

Design tree: Agent catalog → Draft overview (CFG-1) → capability-selected module
(CFG-2/3) → revisioned Workspace update → exact-revision validation → immutable
version → monitor. CFG-4 applies across reads and edits. Production actions follow
server capabilities. Loading failures have explicit error exits, invalid input has
inline errors, save failures preserve input, conflicts require explicit reload.

[KNOWN | HIGH] Existing specialized model/workflow/Skills/tools/memory/response editors
cover the remaining advertised modules. `retrieval.query_concurrency`, rewrite and
rerank flags are not established as effective in the synchronous Dify path; they must
not be presented as working controls. Per-binding top_k is capped by global top_k;
score threshold uses the stricter global/per-binding value. Dify transport caps
query_timeout_seconds at 60 seconds (`bootstrap/composition.py`). Provider availability
requires real verification; local configuration completeness cannot establish it.

Verification evidence will be recorded in `dashboard-completion-verification.md`.
