# TDD 与辅助编码报告

> 历史报告：ADR-0153 已将模型 Secret Handle 替换为 PostgreSQL 加密凭据与外置版本化 keyring；本文中的旧验证数字和 Secret Handle 场景不代表当前实现证据。

## 1. 建议结论

| 项 | 内容 |
|---|---|
| 建议结论 | PARTIAL_VERIFICATION |
| 最高风险等级 | P1 |
| 模式 | 本地修改；真实测试 PostgreSQL |

[KNOWN | HIGH] 生产 Model Connection 的代码、真实 PostgreSQL 集成、Dashboard 交互和完整本地回归已通过。

[KNOWN | HIGH] 当前运行中的 `production-local` Docker 栈来自另一工作树，本轮没有把当前工作区源码同步进该栈，因此不能把本报告当作浏览器运行态验收或正式发布证据。

## 2. 测试目标与范围

| 项 | 内容 |
|---|---|
| 测试目标 | 生产 Model Connection API 不再落入 SPA 405，并通过 PostgreSQL、Secret Handle、权限、审计和 revision 边界管理连接 |
| 测试范围 | API 路由、生产服务、PostgreSQL repository/UoW、引用投影、模型运行时解析、Dashboard Models 表单和详情页 |
| 不覆盖范围 | Vault 密钥写入、生产 Agent publication cutover、真实供应商远程 smoke call、当前 Docker 栈重建 |

## 3. 测试场景

| 编号 | 场景 | 类型 | 优先级 | 风险等级 |
|---|---|---|---|---|
| PMC-001 | 生产应用挂载 Model Connection API | 组合测试 | P0 | P1 |
| PMC-002 | 授权操作者用 Secret Handle 创建并原子持久化连接与审计 | PostgreSQL API 集成 | P0 | P1 |
| PMC-003 | 生产 API 拒绝 env credential reference 和缺失权限 | API 契约 | P0 | P1 |
| PMC-004 | stale revision 不产生部分更新或审计 | API 集成 | P0 | P1 |
| PMC-005 | 真实草稿、发布版本和知识源引用进入影响评估 | PostgreSQL repository 集成 | P0 | P1 |
| PMC-006 | 高影响修改在有引用时要求显式确认 | API 契约 | P0 | P1 |
| PMC-007 | 验证和 smoke 结果可从保留审计中投影 | PostgreSQL API 集成 | P1 | P1 |
| PMC-008 | 生产模型运行时把 Secret Handle 传给受控 provider | 单元测试 | P0 | P1 |
| PMC-009 | Dashboard 按 capability 创建、编辑和归档生产连接 | 前端交互 | P0 | P1 |

## 4. Given-When-Then 用例

| 编号 | Given | When | Then |
|---|---|---|---|
| PMC-001 | production app 已组合 PostgreSQL UoW | 检查公开路由 | list/create/detail 路由存在且不由 StaticFiles 处理 |
| PMC-002 | 操作者具备 `model_connection.edit` | POST 有效 `model_credential` handle | 返回 201，连接版本与审计同事务可读 |
| PMC-003 | production API | POST env 引用或无 edit 权限 | 返回 422/403 且无持久化 |
| PMC-004 | 当前 revision 已变化 | PATCH 使用旧 revision | 返回 409 且连接和审计不变 |
| PMC-005 | PostgreSQL 含精确 shared model 引用 | 查询 references | 返回草稿出现次数、发布版本数和知识源出现次数 |
| PMC-006 | 高影响字段且存在引用 | 未确认 PATCH | 返回结构化 409；确认后才写入并审计 |
| PMC-007 | 已执行 handle validation/smoke | 重新 GET detail | 返回最近保留记录且不含秘密材料 |
| PMC-008 | Shared Model Connection 使用 Production Secret Handle | 解析运行时 ModelConfig | 只产生 `credential_secret_handle`，不产生 `api_key_env` |
| PMC-009 | list meta 声明 `secret_handle` | 操作者创建/编辑/归档 | 请求包含 handle 和当前 revision；开发模式仍提交 env 引用 |

## 5. Mock、数据与断言

| 项 | 规则 | 风险 |
|---|---|---|
| Operator Identity | 仅在 API 测试覆盖 FastAPI identity dependency | 不绕过被测权限函数 |
| PostgreSQL | 使用 `postgres_fixtures` 隔离 schema 与 `proof-test-only` 数据库 | 不连接生产数据库 |
| Secret Provider | 使用固定 protocol id 的边界 fake，不含 secret material | 不验证 Vault 网络、轮换或撤销行为 |
| Remote smoke | 只验证 Secret Handle 并返回 trace-safe `skipped` | 正式发布前仍需受控真实 provider smoke |

## 6. RED-GREEN-REFACTOR 记录

| 步骤 | 行为 | RED 证据 | GREEN 证据 |
|---|---|---|---|
| 路由组合 | production app 暴露 POST 路由 | 路由断言失败 | 组合测试通过 |
| 影响审查 | 有引用的高影响更新必须确认 | 实际 200，预期 409 | 结构化 409 与确认更新测试通过 |
| 引用投影 | PostgreSQL repository 计算精确引用 | `AttributeError`：方法缺失 | 真实 PostgreSQL 计数测试通过 |
| 运行时解析 | Production Secret Handle 进入 provider 参数 | `.credential_ref.name` 抛出 `AttributeError` | Env/Secret Handle 双路径 8 项测试通过 |
| 创建表单 | capability 为 Secret Handle 时隐藏 Env | 页面仍显示 Credential Env | 生产创建请求断言通过 |
| 详情表单 | Secret Handle 编辑和 revision 生命周期 | `undefined.trim()` 页面崩溃 | 生产编辑/归档交互测试通过 |
| 审计投影 | 刷新详情仍显示最近验证和 smoke | `last_validation` 为 null | 内存与真实 PostgreSQL 投影通过 |

## 7. 修改文件清单

| 文件 | 修改类型 | 说明 |
|---|---|---|
| `proof_agent/delivery/production_model_connections.py` | 新增 | 生产专用 Model Connection API、权限、revision、影响确认、审计投影 |
| `proof_agent/observability/api/app.py` | 修改 | production 模式挂载独立路由 |
| `proof_agent/contracts/agent_configuration.py` | 修改 | Env/Production Secret Handle 联合凭据契约 |
| `proof_agent/capabilities/persistence/postgres/model_repository.py` | 修改 | PostgreSQL 引用摘要 |
| `proof_agent/capabilities/persistence/postgres/audit_repository.py` | 修改 | 目标审计查询和嵌套 JSON 安全序列化 |
| `proof_agent/bootstrap/model_resolution.py` | 修改 | 运行时 Secret Handle 参数解析 |
| `proof_agent/delivery/configuration_api.py` | 修改 | 开发 API 显式保持 Env 边界 |
| `dashboard/src/api/{types,client}.ts` | 修改 | 联合凭据、revision、capability 类型 |
| `dashboard/src/pages/{ModelsPage,ModelConnectionDetailPage}.tsx` | 修改 | 生产创建、编辑和生命周期表单 |
| `tests/test_production_model_connection_api.py` | 新增 | API、权限、revision、审计、真实 PostgreSQL 覆盖 |
| `tests/test_postgres_shared_asset_repositories.py` | 修改 | 真实引用计数覆盖 |
| `tests/test_model_connection_resolution.py` | 修改 | 生产运行时解析覆盖 |
| `dashboard/src/pages/__tests__/*Model*.test.tsx` | 修改 | Env/Secret Handle 双模式交互覆盖 |

## 8. 验证执行记录

| 命令/范围 | 结果 |
|---|---|
| 完整后端（测试 PostgreSQL，排除 opt-in Hybrid） | `3126 passed, 1 skipped, 13 deselected` |
| PostgreSQL 生产 Model/引用/审计聚焦回归 | `13 passed` |
| Dashboard 完整测试 | `224 passed` |
| Dashboard production build | 通过 |
| mypy strict | `382 source files` 无问题 |
| Ruff（本次 Python 文件） | 通过 |

## 9. 风险与待确认问题

| 问题 | 等级 | 影响 | 建议动作 | 建议确认人 |
|---|---|---|---|---|
| 运行 Docker 栈来自另一工作树 | P1 | 当前源码修复尚未进入浏览器访问的容器 | 同步/重建该栈后执行 OIDC + CSRF + create/update/archive 浏览器验收 | 项目负责人 |
| 未执行真实 Vault resolve/rotate/revoke | P1 | 只能证明协议、权限和 trace-safe 边界 | 使用候选版本和专用测试 handle 形成发布证据 | 安全/运维负责人 |
| 远程 model smoke 有意返回 skipped | P1 | 不能证明 provider 网络和凭据有效 | 在默认拒绝 egress 下加入显式授权的受控 smoke | 发布负责人 |
| `in_flight_operation_count` 当前为 0 | P2 | 删除始终还受 audit retention 阻止，但运行中引用尚无独立投影 | 建立运行引用索引后替换占位投影 | 架构负责人 |

## 10. 上下文更新

- 已更新 `docs/development-progress.md`，记录本地实现与验证边界。
- 已更新 `docs/domain/tools-models-memory/decisions.md`，记录生产 Secret Handle 与独立 API 决策。
- 正式发布结论仍为 **NO-GO**；本地绿测不等于候选版本 Gate Evidence。
