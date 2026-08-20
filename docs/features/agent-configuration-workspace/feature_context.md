# Agent Configuration Workspace Feature Context

## 1. 需求基本信息

| 字段 | 内容 |
| --- | --- |
| 需求名称 | 深化 Agent Configuration Workspace module |
| Feature ID | `agent-configuration-workspace` |
| 需求来源 | 用户请求；架构评审报告 Phase 3；ADR-0009、ADR-0011 |
| 所属版本 | 待确认；本轮仅处理本地架构切片 |
| 业务、研发、测试、发布负责人 | 未提供；不在本地实现中推定 |
| 当前状态 | `PARTIAL_VERIFICATION` |
| 当前切片 | Slice 5：Workflow Stage Configuration editing authority；主代理 `LOCAL_VERIFIED`，独立子 Agent `PASS` |

## 2. 需求目标与范围

| 目标 | 说明 | 验收口径 |
| --- | --- | --- |
| 深化 Workspace module | 把 Draft inventory、读取、元数据更新、版本列表、validation 和 development publication 收进 Control-owned module | Delivery 通过稳定 interface 使用生命周期规则；validation/publish route 不再自行组合 concrete store 与业务规则 |
| 建立 focused persistence seam | module 依赖 `ConfigurationUnitOfWork` 与 `AgentLifecycleRepository`，不依赖 Local 或 PostgreSQL 实现 | Local 与 PostgreSQL adapter 继续满足同一 port；Control 不 import adapter |
| 保持生命周期权威 | 元数据更新、publication 与 rollback 分别保持 CAS、原子审计和 production sole-Agent 限制 | 现有 API 响应、安全门禁和正式 Phase F publication 权威不变 |

### 范围内

| 范围项 | 说明 | 依据 |
| --- | --- | --- |
| Workspace application module | inventory、Draft 读取、基础元数据更新、版本列表 | 架构评审推荐的首个垂直切片 |
| Delivery adapter 迁移 | development 与 production route 调用 Workspace interface | Delivery 不应认识具体 store |
| Local/PostgreSQL seam | 复用现有 Configuration UoW 和 Agent lifecycle adapters | 两个真实 adapter 已存在 |
| 行为测试 | 通过 Workspace interface 验证多 Agent 读取、sole-Agent 限制、CAS 与审计 | interface 是测试表面 |
| Draft validation orchestration | Workspace 约束执行证据身份、revision CAS、Validation Record 与审计；Local adapter 执行编译、Harness、Run 和可选 Full Capture | Delivery 只做权限与 HTTP 映射；validation 不发布、不激活 |
| Development Draft publication | Workspace 校验当前 Draft revision 的成功 Validation Record，生成 immutable version，并用 Draft CAS、active pointer CAS 和审计原子发布 | publish route 不直接读取 Local store；失败时 Published Version 与 active pointer 不变 |
| Agent Version rollback | Workspace 校验 target Published Version，以 exact active-pointer expectation 原子切换 activation 与全局 audit | rollback route 不直接读取 Local store；不修改 version history 或重算 KSS binding |

### 范围外

| 范围项 | 排除原因 | 影响 |
| --- | --- | --- |
| 正式生产 Phase F publication | `ProductionAgentPublicationService` 还包含 KSS release evidence、online smoke 与生产 admission | 不与 development Draft publication 合并；不生成生产发布结论 |
| Blue/Green deployment rollback | 属于应用发布与运行角色 fencing 协议 | 不与 Agent Version pointer rollback 合并 |
| Contract 与 Skill Pack 编辑迁移 | 需要各自独立的编译与校验 module 设计 | 本轮仍由现有 development route 处理 |
| 数据库 schema、迁移和生产部署 | 当前 focused ports 已可承载本切片 | 不生成生产发布结论 |
| 删除整个 `LocalAgentConfigurationStore` | 仍有未迁移的 development-only 编辑用例 | 只删除本切片 Delivery 的具体 store 依赖 |

## 3. 设计树

| 节点 | 类型 | 触发条件/输入 | 处理方案 | 输出/状态变化 | 验证点 | 风险等级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | Delivery 需要读取或更新 Agent Draft | 调用 Control-owned Workspace interface | 返回稳定领域结果 | module 行为测试 | P1 | 已确认 |
| MAIN-1 | inventory | 任意 Agent 或 production sole Agent | 通过 lifecycle port 汇总 Draft、version、active pointer | `AgentConfigurationInventory` | 多 Agent 与空 inventory | P1 | 已确认 |
| MAIN-2 | Draft 读取 | `agent_id`、`draft_id` | 在 Workspace 内应用 scope 并读取 repository | revisioned Draft | not-found 与 sole-Agent 拒绝 | P1 | 已确认 |
| MAIN-3 | 元数据更新 | Draft、expected revision、actor | UoW 内更新 Draft、追加 audit、提交 | revision 增加 | CAS、原子审计、冲突 | P1 | 已确认 |
| MAIN-4 | 版本列表 | `agent_id` | 同一 Workspace 读取 Published Versions 与 active pointer | 稳定版本投影 | 空列表与 active pointer | P1 | 已确认 |
| MAIN-5 | Draft validation | question、capture 策略、actor | adapter 产生执行证据；Workspace 校验身份并以 revision CAS 附加 Validation Record 与审计 | 新 Draft revision 与 validation evidence | scope、身份、capture 互斥、CAS、事务失败 | P1 | 已确认 |
| MAIN-6 | Draft publication | 当前 Draft、Validation Run、actor | Workspace 校验 validation outcome/freshness/blockers，构建 immutable version，并原子更新 active pointer 与 audit | Published Agent Version + Active Agent Version | failed outcome、Draft CAS、pointer CAS、审计、无 rollback | P1 | 已完成；独立复验 `PASS` |
| MAIN-7 | Agent Version rollback | target Published Version、actor | Workspace 读取当前 pointer，以 exact expectation 原子切换 activation 与 audit | rollback result + target immutable binding | not-found、pointer CAS、事务失败、KSS binding、历史不变 | P1 | 主代理 `LOCAL_VERIFIED`；独立复验 `PASS` |
| BRANCH-1 | adapter 失败 | Local/PostgreSQL repository 抛错 | 不建立 fallback，由 Delivery 映射稳定错误 | 无部分写入 | fault 与 rollback 行为 | P1 | 已确认 |
| BOUND-1 | rollback 范围 | Agent Version rollback 完成 | 不执行 Source rollback-Draft、Phase F 或 Blue/Green deployment rollback | 其他权威不变 | 负向回归 | P1 | 已确认 |

## 4. 核心业务规则

| 规则编号 | 业务域 | 规则说明 | 输入 | 输出 | 边界/例外 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| ACW-R01 | 架构 | Delivery 只调用 Workspace interface，不读取具体 Local/PostgreSQL store | HTTP command | 领域结果 | 未迁移用例暂时保留现状 | 已确认 |
| ACW-R02 | 一致性 | Draft 元数据更新与审计在同一 Configuration UoW 提交 | expected revision、actor | 新 revision 与 audit | 冲突时不覆盖 | 已确认 |
| ACW-R03 | scope | production 只允许 sole Agent；development 可读取已导入 Agent | Agent ID | 结果或 stable not-found | 不改变 production policy | 已确认 |
| ACW-R04 | 权威 | 保存 Draft 不等于 validation、publication 或 activation | Draft mutation | Draft 状态 | 不调用 publication module | 已确认 |
| ACW-R05 | 验证证据 | Validation execution、Full Capture 与 Draft 必须具有一致的 Run/Draft 身份；capture 与 capture error 互斥 | adapter evidence | Validation Record 或稳定失败 | 非预期错误不向 HTTP 暴露内部 detail | 已确认 |
| ACW-R06 | 发布权威 | 只有当前 Draft revision 的成功且无 blocker Validation Record 可以发布；version、activation 与全局 audit 必须在一个 Configuration UoW 内提交 | Draft、validation run、active pointer expectation | immutable Published Agent Version | 失败 outcome 拒绝；不自动 rollback，不调用正式生产 Phase F publisher | 已确认 |
| ACW-R07 | 本地并发 | Local Configuration UoW 必须在同一外置权威锁下复制事务基线，并在安装前重验 configuration 与 audit 的真实目标摘要 | 两个交错 staging UoW | 单一赢家或稳定 conflict | 失败事务不得覆盖 version、active pointer 或 audit | 已确认 |
| ACW-R08 | 回滚权威 | Agent Version Rollback 只选择既有 immutable Published Agent Version；activation 与全局 audit 在同一 UoW 提交，并以读取到的 active pointer 做 exact CAS | target version、current pointer、actor | 新 Active Agent Version 与 rollback result | 不改 history；不重算或降级 target KSS binding；不调用部署 rollback | 已确认 |
| ACW-R09 | Stage 编辑权威 | Workflow Stage Configuration 保存必须通过 Workspace，以 Draft revision CAS 提交 Contract Bundle、Draft operation audit 与全局 audit | template、descriptor version、stage overrides、expected revision、actor | 新 Draft revision 与完整 Contract Bundle | 不保存 raw Prompt 到 audit；不验证、不发布、不激活 | 已确认 |
| ACW-R10 | Stage 预览 | Workflow Stage Context Preview 只读取 revisioned Draft，经受控编译检查后返回脱敏、限长投影 | stage id、Prompt、context options | preview projection | 不执行模型、工具或 Run；不写 trace、Draft 或 audit | 已确认 |

## 5. 高严谨业务系统风险基线

| 维度 | 是否涉及 | 已知规则/证据 | 待确认问题 | 风险等级 |
| --- | --- | --- | --- | --- |
| 领域业务逻辑严谨性 | 是 | Draft 与 Published Version 分离 | 无 | P1 |
| 金额与关键数值精度 | 否 | 不处理金额 | 无 | NONE |
| 交易与数据一致性 | 是 | Configuration UoW 原子提交 | 无 | P1 |
| 状态流转 | 是 | 修改 Draft、附加 Validation Record、发布 immutable version，或把 active pointer 切换到既有 version | 无 | P1 |
| 幂等与并发 | 是 | revision CAS 保持 | 无 | P1 |
| 权限与审计 | 是 | Delivery 权限不变；Workspace 追加 audit | 无 | P1 |
| 隐私与适用监管/合规 | 是 | audit 只记录 trace-safe metadata | 无 | P2 |
| 生产变更与回滚 | 是 | 本切片只迁移 Agent Version pointer rollback authority；不执行部署或正式生产发布 | 正式生产发布和 Blue/Green rollback 另行确认 | P1 |

## 6. 影响范围

| 类型 | 对象 | 影响说明 | 风险等级 |
| --- | --- | --- | --- |
| Control | `proof_agent/control/agent_configuration_workspace.py` | 建立 deep application module | P1 |
| Persistence port | `AgentLifecycleRepository`、`ConfigurationUnitOfWork` | 保持 focused interface | P1 |
| Local/PostgreSQL adapters | 现有 lifecycle repository 与 UoW | 复用，不增加第二权威 | P1 |
| Delivery | development/production configuration routers、app composition、local validation/publication adapters | route 依赖 Workspace；adapter 隔离本地编译与运行细节 | P1 |
| 测试 | Workspace、API、Local/PostgreSQL persistence | 替换内部实现导向测试 | P1 |

## 7. 测试与发布关注点

| 关注项 | 类型 | 优先级 | 证据或说明 |
| --- | --- | --- | --- |
| 多 Agent inventory 与 production sole-Agent scope | contract | P1 | development/production 现有差异 |
| revision CAS 与原子 audit | consistency | P1 | hicode coding rules |
| Delivery deletion test | architecture | P1 | 本切片 route 不直接调用 Local store |
| publication version、activation、audit 原子提交 | authority/consistency | P1 | Agent lifecycle 分层要求 |
| validation evidence 身份与 Full Capture 互斥规则 | contract/security | P1 | 防止错误 Run/Capture 绑定到 Draft |
| validation 500 稳定且不泄漏内部 detail | security | P1 | HTTP 负向契约 |
| Local/PostgreSQL adapter 回归 | persistence | P1 | 两个真实 adapter |

## 8. 待确认问题

无未关闭 P0/P1 准入问题。Slice 5 只迁移 development Workflow Stage Configuration 保存与预览；Contract、Skill Pack、正式生产 Phase F publication、Blue/Green deployment rollback 不在范围内。本轮结果不代表 Agent Configuration Workspace 已全部迁移。

## 9. Slice 2：Draft validation orchestration

| 项 | 内容 |
| --- | --- |
| 目标 | 让 development Delivery 通过 Workspace 的一个 interface 调用完成 Draft 编译、Validation Run、可选 Full Capture、Validation Record、revision CAS 和审计写入 |
| 范围内 | development `validate` route、Workspace validation interface、本地执行 adapter、Validation Record 原子提交、现有响应兼容 |
| 范围外 | production validation endpoint、publication、rollback、Contract/Workflow/Skill 编辑、数据库 schema、部署 |
| 验收标准 | Delivery 不再组合 compiler、RunStore 与 concrete configuration store；Workspace 行为测试覆盖成功、capture failure 和 revision conflict；现有 validation API 回归通过 |
| 最高风险 | P1：Validation Run 产生外部 artifact 后，Draft CAS 可能冲突；必须拒绝覆盖，残留 artifact 作为明确后续清理风险 |

## 10. Slice 3：Development Draft publication authority

| 项 | 内容 |
| --- | --- |
| 目标 | 让 development publish route 通过 `AgentConfigurationWorkspace.publish_draft(...)` 完成 validation freshness/blocker 检查、Published Agent Version 构建、active pointer CAS 与审计提交 |
| 范围内 | development `publish` route、Workspace publication interface、本地 package/publication validation adapter、Configuration UoW 原子 publication、稳定错误映射 |
| 范围外 | rollback、production publish endpoint、正式 Phase F release publisher、Contract/Workflow/Skill 编辑、schema、部署 |
| 验收标准 | publish route 不再组合 compiler 或 Local store；只有当前 Draft revision 的成功 validation 可发布；version、activation 与 audit 原子提交；真实 Local 交错事务与 Draft/pointer 冲突失败关闭；现有 API 响应保持兼容 |
| 最高风险 | P1：错误复用旧 Validation Run 或遗漏 active pointer expectation 会把未经当前配置验证的版本设为 active |

## 11. Slice 4：Agent Version rollback authority

| 项 | 内容 |
| --- | --- |
| 目标 | 让 development rollback route 通过 `AgentConfigurationWorkspace.rollback_version(...)` 完成 target 校验、exact active-pointer CAS、activation/audit 原子提交和 immutable KSS binding 恢复投影 |
| 范围内 | Workspace rollback interface、adapter-neutral activation command、Local/PostgreSQL lifecycle adapters、development API route、稳定错误映射、旧 direct-store rollback 删除 |
| 范围外 | 正式 Phase F publisher、production publication endpoint、Source rollback-Draft、Blue/Green deployment rollback、Contract/Workflow/Skill 编辑、schema、部署 |
| 验收标准 | route 不再调用 concrete store；target 必须属于 Agent；并发 writer 只允许一个赢家；activation 与 audit 原子；历史 versions 不变；响应保留 target immutable KSS binding |
| 最高风险 | P1：缺少 exact pointer CAS 或把 audit 放在事务外，会让并发回滚覆盖较新的 activation，或留下不可审计的 active state |

## 12. Slice 5：Workflow Stage Configuration editing authority

| 项 | 内容 |
| --- | --- |
| 目标 | 让 development Workflow Stage 保存与 Context Preview 只通过 `AgentConfigurationWorkspace`，删除 route 内的 YAML mutation、编译、Local store 与 preview 组合逻辑 |
| 范围内 | Workspace Stage update/preview interface、受控本地 Draft inspection adapter、revision CAS、Draft operation audit、全局 audit、稳定错误映射、Dashboard 单次保存 |
| 范围外 | raw Contract 编辑、Skill Pack 编辑、production Stage endpoint、validation/publication/rollback、schema、部署 |
| 验收标准 | 保存一次原子更新 template、descriptor version 与 stages；stale revision 返回稳定 conflict；audit 不含 Prompt 文本；预览不执行 Run 或写状态；route 不读取 concrete store/compiler/YAML；Dashboard 不再先保存整份 Contract |
| 最高风险 | P1：现有 Dashboard 两次顺序写入可能形成部分保存，且旧 route 缺少调用方 revision，存在 stale writer 覆盖风险 |
