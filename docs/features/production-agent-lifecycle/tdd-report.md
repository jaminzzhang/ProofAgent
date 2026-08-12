# Production Agent Lifecycle TDD 与辅助编码报告

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `PARTIAL_VERIFICATION` |
| 最高风险等级 | P1 |
| 模式 | 本地修改 |
| 结论依据 | production API、应用服务、安全中间件、Dashboard、完整默认后端测试、Ruff、mypy 和前端构建均通过；本环境未提供隔离 PostgreSQL，因此新增 repository 查询和真实事务路径只收集到 skip 证据，不能标记为 `LOCAL_VERIFIED` |

## 2. 测试目标与范围

| 项 | 内容 |
| --- | --- |
| 测试目标 | 修复 production Dashboard 创建唯一 Agent 时落入通用 404；建立 server-owned template、PostgreSQL Draft/UoW、OIDC/CSRF、权限、幂等、revision CAS、审计和 capability UI 闭环 |
| 测试范围 | production list/create/get/PATCH/contract/versions；development 同构创建入口；Agent repository Draft 列表；production composition；Dashboard Agents/Create Wizard/Agent Detail/API client |
| 不覆盖范围 | production validation、publication、rollback、activation；任意 Agent；生产部署；真实 OIDC/Vault；真实 PostgreSQL 事务执行；浏览器端到端部署验证 |

## 3. 测试场景

| 编号 | 场景 | 类型 | 优先级 | 风险等级 |
| --- | --- | --- | --- | --- |
| PAL-T01 | production 注册 list/create/read/update/contract/version 路由，不注册 import/validate/publish/rollback | contract/negative | P1 | P1 |
| PAL-T02 | 首次创建使用服务器模板，返回 `201`、revision 和受限 capability | application/API | P1 | P1 |
| PAL-T03 | 同 key 同指纹重放；同 key 不同指纹和第二次初始化冲突 | consistency | P1 | P1 |
| PAL-T04 | Draft 与 trace-safe audit 通过同一 UoW 提交 | transaction/audit | P1 | P1 |
| PAL-T05 | Draft 元数据 PATCH 使用 revision CAS，陈旧 revision 返回稳定冲突 | concurrency | P1 | P1 |
| PAL-T06 | OIDC Session、same-origin CSRF 和命名权限先于应用服务执行 | security | P1 | P1 |
| PAL-T07 | production 请求拒绝 `manifest_path`，Dashboard 不呈现或发送浏览器路径 | security/cross-surface | P1 | P1 |
| PAL-T08 | Dashboard 按 capability 隐藏不支持模块、validation、publication 和 rollback | UI/negative | P1 | P1 |
| PAL-T09 | development 仍可显式 import，并支持同构的 server-owned create | regression | P2 | P2 |
| PAL-T10 | PostgreSQL repository 返回带 revision、按更新时间倒序的 Draft | integration | P1 | P1 |

## 4. Given-When-Then 用例

| 编号 | Given | When | Then |
| --- | --- | --- | --- |
| PAL-GWT01 | production app 完成必需依赖注入 | 检查 `/api/config/agents` 路由 | GET/POST/read/PATCH/contract/versions 存在，development-only mutation 不存在 |
| PAL-GWT02 | 有 `agent.edit`、有效 Session/CSRF 和新 idempotency key | POST 显示名称与用途 | 服务端固定唯一 Agent 和 V3 template，原子写 Draft/audit，返回 revision 1 |
| PAL-GWT03 | 创建请求已经成功 | 使用相同 key 和同一 payload 重试 | 返回相同 Draft、HTTP 200，不追加 Draft 或 audit |
| PAL-GWT04 | key 已用于一个 payload | 使用同 key 发送不同 payload | 返回 `409 idempotency_key_mismatch`，原状态不变 |
| PAL-GWT05 | Draft revision 为 1 | PATCH 携带 revision 2 | 返回 `409 agent_draft_revision_conflict`，不追加 audit |
| PAL-GWT06 | production 浏览器无 Session 或缺少 CSRF | POST 创建 | 分别返回 401 或 403，应用服务没有写入 |
| PAL-GWT07 | production capability 禁止 manifest import/publish/rollback | 渲染 Agents 和 Agent Detail | 不显示 manifest path、Workflow、Validate、Publish、Rollback；General 更新携带当前 revision |
| PAL-GWT08 | development operator 有编辑权限 | POST `/api/config/agents` | 使用安装包内同一 canonical template 创建本地 Draft；显式 import 路由继续存在 |

## 5. Mock、数据与断言

| 项 | 规则 | 风险 |
| --- | --- | --- |
| 身份 | 使用虚构 OIDC subject `operator-1`、虚构 Session ID 和命名权限；不读取真实身份配置 | 低 |
| 幂等 | 测试使用非敏感 key；持久化与审计只断言 SHA-256 摘要，禁止 raw key | 低 |
| Agent | 只使用 `agent_management_insurance_specialist` 和安装包内 canonical example | 低 |
| PostgreSQL | repository 集成测试依赖隔离 DSN；当前环境缺失时由 fixture skip | 高：真实 SQL、排序和跨 repository 事务尚无本次执行证据 |
| 审计 | 断言事件类型、actor、target、revision metadata 和同一 UoW commit 请求 | 中：真实回滚仍依赖 PostgreSQL 集成 |
| UI | Vitest/jsdom 断言请求和可见操作；TypeScript production build 验证类型闭环 | 中：不是部署后的真实浏览器证据 |

## 6. RED-GREEN-REFACTOR 记录

| 步骤 | 行为 | 文件 | 结果 |
| --- | --- | --- | --- |
| RED-1 | production route inventory 要求 Agent API | `tests/test_application_security_composition.py` | 失败：实际路由集合为空 |
| GREEN-1 | 注册独立 production router，不挂载 development router | `proof_agent/observability/api/app.py`、`proof_agent/delivery/production_agent_configuration.py` | 通过：路由存在，import/validate/publish/rollback 缺席 |
| RED-2 | create API 期望 server-owned DTO 和 revision | `tests/test_production_agent_configuration_api.py` | 失败：stub 返回 503 |
| GREEN-2 | 实现 create/list/read/PATCH/contract/versions 与稳定错误映射 | production delivery/application files | 6 项 API 测试通过 |
| RED-3 | application 首次创建、重放、inventory、CAS update | `tests/test_production_agent_configuration_service.py` | 依次失败于缺失模块、重放冲突和缺失方法 |
| GREEN-3 | 实现 singleton、fingerprint、UoW audit、revision CAS 和 history | `proof_agent/control/production_agent_configuration.py` | 6 项服务测试通过 |
| RED-4 | development list capability 和同构 POST | `tests/test_agent_configuration_api.py` | 失败：meta 缺 capability，POST 返回 404 |
| GREEN-4 | 增加 development server-owned create，保留显式 import | `proof_agent/delivery/configuration_api.py` | 相关回归通过 |
| RED-5 | production Draft capability 禁止 validate/publish/rollback | production API test | 失败：响应缺少 action capability |
| GREEN-5 | 返回显式 action capability | production delivery | API contract 通过 |
| RED-6 | Dashboard 不暴露 path、调用 create、发送 revision、隐藏禁止操作 | Dashboard 四个测试文件 | 4 项失败，分别命中旧 import/path/revision/navigation 行为 |
| GREEN-6 | capability-driven Agents/Detail 和无路径 Create Wizard | Dashboard client/types/hooks/pages/components | 61 项聚焦测试和 226 项 Dashboard 全量测试通过 |
| REFACTOR | 提取 production application、复用 Configuration UoW、使用安装分发包定位模板、补严格 DTO 和稳定错误码 | backend 与 Dashboard | Ruff、mypy、TypeScript build 通过 |

## 7. 修改文件清单

| 文件 | 修改类型 | 说明 |
| --- | --- | --- |
| `proof_agent/control/production_agent_configuration.py` | 新增 | production sole-Agent application、server template、幂等、CAS、audit 和读模型 |
| `proof_agent/delivery/production_agent_configuration.py` | 新增 | production Agent API 和 capability projection |
| `proof_agent/observability/api/app.py`、`proof_agent/bootstrap/production_roles.py` | 修改 | production fail-closed 依赖注入和 PostgreSQL UoW composition |
| `proof_agent/contracts/ports/agent_lifecycle.py`、local/PostgreSQL adapters | 修改 | 增加 revisioned Draft 列表 port 与实现 |
| `proof_agent/delivery/configuration_api.py` | 修改 | development capability 和 server-owned create；显式 import 保留 |
| `dashboard/src/api/`、`hooks/useConfigAgents.ts` | 修改 | capability、revision 和 idempotent create contract |
| `dashboard/src/pages/AgentsPage.tsx`、`AgentDetailPage.tsx`、`CreateAgentWizard.tsx` | 修改 | 移除创建路径输入，按 capability 限制生产操作 |
| backend 与 Dashboard 对应测试 | 新增/修改 | route、service、security、repository、client 和 UI 回归 |
| `docs/features/production-agent-lifecycle/`、项目上下文 | 新增/修改 | Scope、TDD 和验证边界证据 |

## 8. 受限命令执行记录

| 命令 | 范围 | 是否执行 | 结果 | 未执行原因 |
| --- | --- | --- | --- | --- |
| 聚焦 production/development/persistence 测试 | 8 个相关 backend 文件 | 是 | 91 passed，7 skipped | 7 项 PostgreSQL repository 测试缺少隔离 DSN |
| `uv run --extra dev python -m pytest -q` | 默认 backend suite | 是 | 首轮 3182 passed；最终复跑在 3179 passed 后有 4 个无关 Gateway loopback 用例超时，134 skipped，13 deselected | 4 个用例单独复跑仍因本地 socket 响应超时失败；本功能聚焦测试保持通过，不将 backend 全量标记为最终全绿 |
| `npm test` | Dashboard | 是 | 34 files、227 tests 全部通过 | 无 |
| `npm run build` | Dashboard TypeScript 与 production bundle | 是 | 成功 | 无 |
| `uv run --extra dev ruff check .` | workspace Python | 是 | 通过 | 无 |
| `uv run --extra dev mypy proof_agent` | 431 个 product source | 是 | 通过 | 无 |
| `uv lock --check` | Python lock | 是 | 通过；读取本机 uv cache 时按沙箱要求获得受控权限 | 无 |
| `npm run typecheck` | workspace 前端类型 | 是 | 通过 | 无 |
| `python3 scripts/check-domain-contexts.py` | domain context | 是 | 通过 | 无 |
| `git diff --check` | workspace diff | 是 | 通过 | 无 |
| 隔离 PostgreSQL Agent/UoW 集成 | 真实 PostgreSQL | 否 | 未验证 | 当前环境没有配置隔离 PostgreSQL test DSN |
| production-local rebuild/verify | Docker production-local stack | 否 | 未验证 | 用户只授权代码修复；本次不执行部署或外部状态变更 |
| production SQL、发布、回滚 | production | 否 | 未执行 | 明确超出范围且需要独立授权与 release Gate |

## 9. 风险与待确认问题

| 问题 | 等级 | 影响 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| 新增 `list_drafts` 和 Draft+audit 事务未在本次真实 PostgreSQL 上执行 | P1 | 本地逻辑和 SQL contract 已测试，但缺少数据库运行证据 | 在隔离 PostgreSQL 运行 Agent repository、Configuration UoW 和 production Agent service 集成后再升级为 `LOCAL_VERIFIED` | 测试/数据库负责人未指定 |
| 4 个无关 Gateway loopback 测试在最终全量与单独复跑中超时 | P2 | 阻止把最终 backend 全量回归声明为全绿；失败文件未被本功能修改 | 在允许稳定 loopback 调度的 host/CI 重跑 `test_remote_verify_gateway*`；不要把该结果归因于 Agent API | 测试负责人未指定 |
| 未重建 production-local 镜像和浏览器验证 | P1 | 当前运行栈不会自动包含源码修复 | 在候选镜像中运行 production-local prepare/verify，并通过真实 Dashboard 创建流程；不得自动发布 Agent | 发布负责人未指定 |
| 创建只初始化 Draft，不 validation、publish 或 activate | P1 | `/readyz` 的 Published Agent 条件不会因本修复自动转绿 | 继续走现有 candidate-bound Phase F 和 `ProductionAgentPublicationService` | Agent 发布负责人未指定 |
| default backend skip/deselect 中包含其他外部集成 | P2 | 完整默认 suite 不是所有生产依赖的证明 | 沿用正式 13-Gate 流程，不以本报告替代 | 发布/安全负责人未指定 |

## 10. 上下文更新建议

| 建议位置 | 类型 | 内容摘要 | 原因 |
| --- | --- | --- | --- |
| `docs/PROJ_CONTEXT.md` | Feature 状态 | 标记 `production-agent-lifecycle` 为 `PARTIAL_VERIFICATION` | 代码和默认测试完成，但真实 PostgreSQL 与部署证据缺失 |
| `docs/development-progress.md` | 当前事实 | 记录 production Agent Draft API、capability 和本地验证结果 | active behavior 已改变，需防止继续诊断为缺路由 |
| Agent domain context | 术语/决策 | 暂不更新 | Draft、publication、server-owned template 和 authority 边界已有术语与 ADR |
