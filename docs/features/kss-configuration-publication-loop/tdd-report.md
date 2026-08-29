# KSS 配置发布闭环 TDD 报告

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `PARTIAL_VERIFICATION` |
| 最高风险等级 | P1 |
| 模式 | 受控实现：TDD-01A/01B + TDD-02A 至 02G Preparation 核心 + TDD-03A 至 03E Reference Ledger 与 Release lifecycle 核心 |
| 日期 | 2026-08-29 |
| 依据 | 用户确认按既定 Scope 启动开发并继续下一 TDD 切片；ADR-0213/0214/0217、`feature_context.md`、`scope-plan.md`、仓库编码规则 |

[KNOWN | HIGH] TDD-01B 已将 HTTP snapshot Profile 生命周期接入 KSS PostgreSQL、受保护管理 HTTP 和显式受管运行组合。同步任务固定 Published Profile 的 ID、revision 和 configuration digest，Worker 重启后仍解析该 exact revision；Source Version 的不可变 artifact 保留并校验血缘。现有生产进程仍使用静态 registry，尚未切换。完整 TDD-01 和整体配置发布流程仍未完成。

[KNOWN | HIGH] TDD-02A/02B 已有持久化准入和管理 HTTP；TDD-02C 增加 lease/fencing；TDD-02D 增加 frozen-plan candidate 构建和 fenced `ready/failed` 最终提交；TDD-02E 增加服务端核心 `ready → expired/consumed` 和 exact Release 单事务发布；TDD-02F 增加 application-only `expire_next()`；TDD-02G 增加 application-only queued/running 协作取消、幂等收据/审计和 stale-result fencing。GET 可读全部已实现状态，POST start 重放仍返回原始 queued 回执；没有 `:publish`、expiry 或 cancel HTTP 命令。本轮真实 PostgreSQL/MinIO/OpenSearch 受影响回归为 357 passed、0 skipped。尚无常驻 Worker、自动过期调度、ready quarantine、ProofAgent 接线或生产切换；既有直接 Release 发布路径仍可绕过 Preparation，因此不能声称系统级唯一发布入口或生产发布流程完成。

[KNOWN | HIGH] TDD-03A 至 03E 新增 application-only exact Release Reference registration、可信 deregistration admission、`queryable → deprecated → retired` 普通生命周期、`queryable/deprecated → revoked` 紧急生命周期和 PostgreSQL migrations `0014` 至 `0018`。只有 owning authenticated client 加服务端注入 verifier 的 exact permanent-ineligibility 证明，才能把 Reference 从 `active` 转为 `deregistered`；普通退役仍由 active Reference、服务端 retention policy 和数据库时间共同控制。紧急撤销仅接受两个受控原因和 exact fail-closed 确认，由 KSS 锁定/统计 active References 并保留全部 Reference facts。Retired/revoked Release 均不可 Catalog query、不进入完整性扫描且既有 Query authorization 失败关闭。没有 Reference/lifecycle HTTP/BFF、ProofAgent verifier/证明签发、后台 reconciler、affected-reference 明细/通知、ProofAgent runtime/rollback 接线或生产配置，因此这仍是局部本地权威证据。

## 2. TDD-01A 范围记录（历史）

| 项 | 内容 |
| --- | --- |
| 公开接口 | `ConnectionProfileApplication.create/get/revise/validate/publish/resolve_for_synchronization/audit` |
| 可观察行为 | Draft revision、校验/发布状态、历史版本不变、管理投影、稳定错误码、幂等结果、成功操作审计、并发冲突 |
| 测试范围 | HTTP JSON Profile；exact Secret Handle version；部署策略校验接口；operator-scoped request fingerprint；状态/receipt/audit 原子写入的内存合同 |
| 不测试的实现细节 | 私有方法、内部调用次数、内部集合布局 |
| 本轮范围外 | PostgreSQL 迁移/仓储、配置与部署脚本、真实 Vault/egress/TLS 校验、PostgreSQL connector Profile、HTTP/BFF/角色授权、Source catalog 关联存在性验证、Worker 接线和 Source Version lineage |
| 当时的授权限制 | TDD-01A 未改 SQL/配置；用户随后单独同意 TDD-01B PostgreSQL migration/repository、管理 API 和 Worker 接线，限定本地实现与测试，不部署、不操作生产 |

## 3. 测试场景与 Given-When-Then

| 编号 | Given | When | Then | 风险 |
| --- | --- | --- | --- | --- |
| CP-001 | 合法 HTTP Profile 和测试部署策略 | 创建、校验、发布、解析 exact revision | 获得 Published revision；管理投影无 endpoint、Secret Handle、egress、trust-root 细节 | P1 |
| CP-002 | 内联 token、可变 Secret version、越权网络字段或不安全 URL | 解析合同 | 拒绝未知字段/不安全参数；错误字符串不回显测试 secret | P1 |
| CP-003 | 已发布 revision 1 | 修改凭据引用为 revision 2 Draft | revision 1 仍解析到原 Secret version；revision 2 不可同步 | P1 |
| CP-004 | 已成功执行的 operator/key/fingerprint | 重放原命令或改动 payload | 原请求返回原结果且无重复审计；改动请求冲突；不同 operator 的 key 隔离 | P1 |
| CP-005 | 策略依赖缺失、抛错、空 revision 或 revision 漂移 | 校验、发布或解析 | 失败关闭且无状态写入；下游错误不泄漏 | P1 |
| CP-006 | Published revision | 尝试重新校验、跨 Source/Space 使用或解析非正整数 revision | 拒绝降级和作用域漂移；`None/True/latest` 不得成为 latest 解析 | P1 |
| CP-007 | 外部策略校验等待期间出现新 Draft | 旧校验完成并尝试提交 | state-version CAS 冲突，较新 Draft 与审计不被覆盖 | P1 |

## 4. Mock、数据与断言

- 使用虚构 `*.example.test` endpoint、固定时间和仅用于测试的 Secret Handle；未读取任何凭据值。
- `DeploymentPolicy` 替代外部部署策略权威。它不是生产策略实现，也不证明 Vault、DNS、egress 或 TLS 连接通过。
- 测试使用真实应用代码和线程安全内存仓储，不 Mock 内部应用方法。并发用例在外部策略接口处用 Event 控制时序。
- 内存仓储仅用于测试，不注册为生产 fallback。TDD-01B 的 PostgreSQL adapter 已验证同一原子 state/receipt/audit 和 CAS 合同。

## 5. RED-GREEN-REFACTOR 记录

最小命令：

```text
uv run --extra dev pytest -q tests/contract/knowledge_service/test_connection_profiles.py
```

| 轮次 | RED 证据 | GREEN 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 新公开模块不存在，测试 collection 失败 | 1 passed | 创建 → 校验 → 发布 → exact 解析首条路径 |
| 2 | 7 个不安全 endpoint 未被拒绝 | 13 passed | HTTPS、凭据、query/fragment、port、控制字符校验 |
| 3 | `revise` 尚不存在 | 14 passed | 新 Draft revision 与历史 Published revision 隔离 |
| 4 | 缺少审计接口和原子幂等记录 | 15 passed | command fingerprint、receipt、成功审计与 CAS 一起提交 |
| 5 | 6 个策略失败用例未按稳定错误失败关闭 | 21 passed | 校验/发布/解析统一包装策略异常并拒绝空 policy revision |
| 6 | Published revision 可被重新校验降级 | 22 passed | 禁止重写已发布状态；编辑必须新建 revision |
| 7 | `None/True` 可解析当前 revision；其余非法类型错误不稳定 | 28 passed | exact revision 要求显式正整数，拒绝布尔值 |
| 回归扩展 | 已实现行为的并发、作用域、策略漂移、幂等隔离保护 | 37 passed | 未将已通过的回归补测伪称为 RED |
| REFACTOR | 仅格式整理 | 37 passed；影响范围 43 passed、5 skipped | 未改旧同步或管理执行路径 |

## 6. TDD-01A 验证记录（历史）

| 命令 | 结果 | 限制 |
| --- | --- | --- |
| `uv run --extra dev pytest -q -rs tests/contract/knowledge_service/test_connection_profiles.py tests/contract/knowledge_service/test_configured_snapshot_connections.py tests/contract/knowledge_service/test_knowledge_source_synchronization.py tests/contract/knowledge_service/test_management_http_api.py` | 43 passed、5 skipped | 5 个管理 HTTP 集成测试因未配置真实测试 PostgreSQL DSN 跳过 |
| `uv run --extra dev mypy`，参数为本轮 5 个新增产品文件 | Success: no issues found in 5 source files | 未跑全仓库类型检查 |
| `uv run --extra dev ruff check`，参数为本轮 6 个产品/测试文件 | All checks passed | 范围限定为本轮变更 |
| `uv run --extra dev ruff format --check`，同上 | 6 files already formatted | — |
| `python3 scripts/check-domain-contexts.py` | 通过 | — |
| `git diff --check` | 通过 | — |

## 7. TDD-01A 修改文件清单

| 文件 | 修改类型 | 说明 |
| --- | --- | --- |
| `knowledge_source_service/contracts/connection_profiles.py` | 新增 | immutable HTTP Profile 输入与 secret-free 管理投影 |
| `knowledge_source_service/domain/connection_profiles.py` | 新增 | 内部 revision record、command、receipt、audit event |
| `knowledge_source_service/ports/connection_profiles.py` | 新增 | 原子仓储与部署策略接口 |
| `knowledge_source_service/adapters/memory/connection_profiles.py` | 新增 | 测试用线程安全 CAS/幂等/审计仓储 |
| `knowledge_source_service/application/connection_profiles.py` | 新增 | 生命周期与 exact、scope-bound 同步解析接口 |
| `tests/contract/knowledge_service/test_connection_profiles.py` | 新增 | 37 个新合同用例 |
| 本 Feature 文档、`docs/PROJ_CONTEXT.md`、`docs/development-progress.md` | 更新 | 区分 TDD-01A 已实现内容与整体未完成范围 |

## 8. TDD-01A 受限命令记录（历史）

| 命令/动作 | 是否执行 | 结果或原因 |
| --- | --- | --- |
| Ruff 经 uv 缓存访问 | 是 | 首次沙箱拒绝缓存访问；按批准机制重试后通过 |
| SQL 迁移、生产配置、部署或发布 | 否 | 未取得独立变更确认；当前增量不需要 |
| 真实 PostgreSQL、Vault、egress、S3/OpenSearch | 否 | 本轮只有核心合同，不提供真实依赖证据 |
| Git commit/push/merge | 否 | 用户未请求 |

## 9. 残余风险与下一步

| 项 | 等级 | 影响与后续动作 |
| --- | --- | --- |
| 真实策略与上游连接适配器未装配 | P1 | 本轮 `DeploymentPolicy`、snapshot reader 为外部边界测试替身。真实 adapter 必须校验 connector、exact Secret 引用、egress、trust root 和硬限制，并只在 Worker 中解析凭据；字符串 revision 不是依赖准入证明 |
| 生产进程未切换 | P1 | `bootstrap/processes.py` 仍使用 `KSS_SNAPSHOT_CONNECTIONS_JSON`。新增能力只在显式 `compose_runtime(managed_connection_profiles=True, ...)` 组合中启用。切换前必须验证真实 adapter，协调 API/Worker、处理旧 v1 队列；旧二进制不能消费 v2 工作 |
| ProofAgent BFF/Dashboard/角色包未贯通 | P1 | KSS 已检查可信身份的 `knowledge_source.view/edit`；OIDC 三角色包到 BFF/KSS 的完整映射仍属 TDD-04。没有新增本地用户或 per-Space ACL |
| Preparation publication 仅完成核心事务与显式回收/取消原语 | P1 | TDD-02E 已实现 `ready → expired/consumed` 和 exact Release 单事务 CAS；TDD-02F 可显式回收一个到期 ready candidate；TDD-02G 可取消 queued/running 并 fence 旧结果，但没有对应 HTTP 命令、自动调度、常驻 Worker 或 ProofAgent 接线。既有直接 Release 发布路径仍可绕过 Preparation。旧构建可以留下未绑定的 immutable object/projection；后续需要对象回收、ready quarantine 与恢复策略。生产进程未启用；应用重建不等于数据库故障恢复演练 |
| 整体流程未完成 | P1 | Reference Ledger、正式 Agent 发布候选绑定、回滚与 Phase F 仍按后续切片实施；Source Version 和 Preparation 均不自动发布 KSS Release 或激活 Agent |
| 审计与保留边界 | P2 | 成功状态和回执原子写入；Profile 和 Preparation 管理路由的认证/权限/校验/状态拒绝写入独立安全审计。不是所有 KSS 管理命令的通用审计。当前不自动清理 revision、receipt 或 audit；分页、保留、备份恢复演练仍待补齐 |
| 新迁移的生产执行尚未评估 | P1 | `0009` 建立管理表与 exact Source 外键；`0010` 新增 lease/fence；`0011` 新增 ready/failed 与内部候选结果；`0012` 新增 expired/consumed、exact Release 外键和发布审计；`0013` 新增 cancelled 时间/约束并扩展命令收据 action。只在隔离测试库应用；旧二进制不能读取新状态，生产锁影响、切换顺序、备份和回滚需要独立评估与授权 |
| Worker 既有最终发布 fencing 边界 | P1 | 本轮保护 claim 和 pinned identity，但未重构已存在的 artifact/catalog 发布与最后一次 queue save 的跨事务窗口。实际进程切换前仍需验证 lease 丢失时的发布行为，不将旧 Worker fencing 测试当作该窗口已关闭的证明 |

## 10. 上下文更新

[KNOWN | HIGH] Feature 维持 `PARTIAL_VERIFICATION`。TDD-01B 的本地持久化、HTTP 和同步 Worker 协议接线，以及 TDD-02A 至 02G 的 Preparation 准入、租约、候选构建、fenced 结果、一次性核心发布、显式主动过期和协作取消已有证据；仍不代表真实 Secret/egress/TLS、系统级唯一发布入口、ProofAgent 管理流程、生产进程切换或完整 TDD-01/02。已批准的设计不重新 grilling。

## 11. TDD-01B 实现与验证

### 11.1 公开行为和数据权威

| 范围 | 已实现行为 | 边界 |
| --- | --- | --- |
| PostgreSQL | `0007_connection_profiles`：Profile head、历史 revision、成功回执/审计、拒绝审计；按 operator/key 串行化幂等，按 Profile state version CAS | 一个事务提交状态、回执和成功审计；不持有事务等待外部策略；Source/Space 使用外键；无自动删除 |
| 管理 HTTP | 创建、exact/当前读取、修订、校验、发布、审计；全局 `knowledge_source.view/edit`；严格输入和稳定脱敏错误 | 只信任服务端认证结果；request body 不能指定操作者或扩权；没有 Agent 发布权限 |
| 同步队列 | `0008_profile_synchronizations`；明确区分静态 v1 和受管 v2；v2 持久化 exact Profile tuple 与 digest | 原 v1 请求、回执 fingerprint 和资源不重写；受管模式拒绝静态连接或混合输入，不 fallback |
| Worker | 重新准入 exact Published revision，验证 scope/digest，延迟打开上游；独立检查 Profile 响应大小限制 | API 不打开快照；缺少策略、策略撤销/漂移、上游失败或超限均无 Source Version 写入 |
| Source Version | `structured-dataset-revision.v2` 保存完整 processing lineage；catalog 校验 lineage digest 后恢复安全 Profile 引用 | v1 artifact 保持可读；合法 object digest 不能掩盖伪造 processing lineage |
| 打包合同 | OpenAPI 包含新接口和 v2 同步；有序 migration contract 更新到 `0008` | 原候选绑定指纹不适用于这次变更，未沿用任何生产发布批准 |

### 11.2 RED → GREEN

| 轮次 | 实际 RED | GREEN / 补测 |
| --- | --- | --- |
| B1 | PostgreSQL Profile adapter 模块不存在 | 重启后读取 Profile、原始幂等回执、成功审计；迁移重放通过 |
| B1 回归 | 未伪造 RED | 同键并发创建只有一个资源/审计；历史 Published 不变；未知 Source 回滚；慢校验不能覆盖新 revision，共 5 个 PG 合同通过 |
| B2 | 管理 application 不接受 `connection_profiles` | HTTP 创建 → 校验 → 发布 → 编辑 → exact 历史读取与安全审计投影通过 |
| B3 | FastAPI 默认 422 回显虚构 `bearer_token` 输入 | 管理校验错误统一为 `invalid_management_request`，不返回 body、endpoint 或原始错误 |
| B4 | operator authenticator 不支持 named permissions | 只读身份可读、写入返回 403；未认证返回 401；已有 catalog 写入口同样拒绝只读身份 |
| B5 | 拒绝审计不存在 | 认证失败和权限拒绝持久化；只记录可信 actor、受限操作名/ID、稳定 code 和时间，不记录 headers/body/key |
| B6 | 运行组合不支持受管 Profile | API → PostgreSQL 队列 → 重启 Worker → Source Version 通过；期间编辑到 revision 2，任务仍使用 revision 1 |
| B7 | catalog 回读的 Source Version 没有 Profile 血缘 | 不可变 v2 artifact 保存血缘；真实 PostgreSQL + MinIO 往返可恢复 exact Profile tuple |
| B8 | Worker 对超出 Profile limit 的替身响应仍物化成功 | 捕获后、artifact 写入前检查 limit；5 个依赖失败场景和主路径通过 |
| B9 | canonical OpenAPI 缺少 Profile 接口 | 补齐公开合同并更新 exact fingerprint；未降低指纹断言 |
| 末轮回归 | 未伪造 RED | 未发布/跨 scope/latest/静态回退/操作者注入拒绝；伪造血缘和 claim 改写拒绝 |

### 11.3 依赖与命令

[KNOWN | HIGH] 使用独立 Compose 项目 `proofagent-kss-profile-tdd`，没有复用 `proofagent-production-local` 数据库、bucket 或索引。Compose 显式使用 `--env-file /dev/null`；未读取 `.env`。PostgreSQL fixture 每次创建随机 schema；S3 fixture 使用随机 versioned bucket；测试身份、凭据和数据均为仓库测试常量或虚构数据。

核心验证命令（测试连接参数由隔离环境注入，不抄入报告）：

```sh
KSS_REQUIRE_POSTGRES_TESTS=1 KSS_REQUIRE_S3_TESTS=1 KSS_REQUIRE_SEARCH_TESTS=1 \
  uv run --extra dev pytest -q -rs tests/contract/knowledge_service \
  tests/test_knowledge_service_management_client.py \
  tests/test_knowledge_service_management_api.py \
  tests/test_knowledge_source_service_client.py \
  tests/test_kss_authority_cutover.py \
  tests/test_knowledge_source_service_binding.py
uv run --extra dev mypy knowledge_source_service
uv run --extra dev --extra openai mypy proof_agent
uv run --extra dev ruff check knowledge_source_service tests/contract/knowledge_service
python3 scripts/check-domain-contexts.py
git diff --check
uv lock --check
```

| 检查 | 本地结果 | 限定 |
| --- | --- | --- |
| 全部 KSS 合同 + ProofAgent KSS/BFF 边界，三个真实依赖均 fail-if-missing | 205 passed、0 skipped，14.49 秒 | 包含 175 个 KSS 合同和 30 个 ProofAgent 边界测试；真实 PG/MinIO/OpenSearch，上游快照和部署策略仍为替身 |
| KSS mypy | 83 source files，无错误 | 非生产运行证据 |
| ProofAgent mypy | 357 source files，无错误 | 未改 ProofAgent 产品代码 |
| KSS Ruff | All checks passed | 覆盖 KSS 产品代码及合同测试 |
| Distribution 格式整理后的回归 | 19 passed | 未改行为，canonical OpenAPI/migration 指纹断言仍通过 |
| domain-context、`git diff --check` | 通过 | 文档与 whitespace 检查，不是部署验收 |
| `uv lock --check` | 通过，117 packages | 未改依赖或锁文件 |

受限命令记录：Docker 首次未启动，按批准机制启动后创建独立测试项目；`uv` 缓存/loopback 访问使用批准后的命令。`compose up --wait` 因一次性 `minio-init` 正常退出 0 返回非零；随后独立 `ps --all` 验证三个长驻依赖均 healthy，再执行 fail-if-missing 测试。没有把该命令返回值当作依赖验收证据。

测试结束后，仅对 `proofagent-kss-profile-tdd` 执行 `down --volumes`，清理本轮临时容器、网络和测试卷；其中的数据可由测试重建，没有保留恢复快照。未清理或变更既有 `production-local` 服务数据。

### 11.4 本轮文件与交付

- 新增 PostgreSQL adapter、迁移 `0007`/`0008` 和 `test_postgres_connection_profiles.py`。
- 更新 Profile contracts/ports/application/memory adapter，补安全拒绝审计与 pinned reference。
- 更新同步 contracts/domain/application/Worker/两个 repository、`bootstrap/runtime.py` 和管理 HTTP；没有修改 `bootstrap/processes.py` 或部署配置。
- 更新 JSON intake、Source Version domain、PostgreSQL catalog，记录并验证 v2 lineage。
- 更新 canonical OpenAPI 和 migration fingerprint 合同测试。
- 更新 Feature context、Scope、项目索引、进度与使用说明 `connection-profile-local-guide.md`。
- 未执行 Git commit、push、merge、部署或生产 SQL。

## 12. TDD-02A：Base Draft 与 Preparation 启动核心（历史）

### 12.1 范围与公开行为

[FRAME | HIGH] 本轮沿 ADR-0214/0217 推进局部核心，不以此关闭 TDD-01 的真实上游和生产接线依赖。使用 `hicode:tdd` 完整留痕路径，最高风险 P1。`graphify` 索引早于当前代码，查询未返回可用的 KSS 核心实现定位；以当前 catalog/release 源码和已批准 ADR 为依据。没有重建图谱或扩展到全仓库重构。

公开接口为 `KnowledgeBasePreparationApplication.save_draft/get_draft/start/get_preparation/audit`。

| 行为 | 输入与结果 | 限定 |
| --- | --- | --- |
| 保存 Draft | 已登记 Base/Source、同一 Space、非空且不重复的 Source 成员；首次 `expected_revision=0`，后续提交当前 revision | 保存新 revision，保留旧 revision；CAS 冲突不覆盖历史。Draft 可暂缺 ready version，启动时必须全部满足 |
| 冻结组合 | `start` 指定 exact 当前 Draft revision；成员为 `exact` 或 `latest_ready_at_preparation` | 在同一事务视图解析所有成员，生成仅含 exact IDs 的 Base Version，并和 `queued` Preparation 一起提交；不读取原文、不建索引、不发布 Release |
| latest 规则 | 按 catalog 首次可见时间 `ready_at`、再按 Source Version ID 排序，选择最后一项 | 延续既有 catalog `created_at, knowledge_source_version_id` 的确定性顺序；重放旧 Version 不更新其首次时间。该规则不进入 Query 或 Agent runtime |
| 幂等 | operator/key/action/完整请求 fingerprint | 同键同请求返回原结果，即使 Draft 或 catalog 已变化；改 action/revision/payload 冲突，不同 operator 隔离 |
| 原子性 | Draft 或 Preparation、原始回执、成功审计 | 内存仓储在一个串行事务中提交；异常全部回滚。Preparation ID 冲突不得覆盖已有计划 |
| 安全投影 | exact IDs、revision、digest、state、时间与成功操作审计 | 无 Source 内容、token、endpoint 或原始 key。存储异常映射为 `base_preparation_unavailable`，不回显内部错误 |

应用接口只接受可信服务端调用；`operator_id` 是审计身份，不是授权证明。本轮不暴露 HTTP，尚无角色映射、读写授权或拒绝审计。内存 adapter 的 catalog 登记方法仅构造测试 fixture，不是新的摄取入口或生产 catalog 镜像。

### 12.2 测试数据与判断边界

- 使用实际 `InMemoryKnowledgeCatalog` 构造虚构文档/CSV Source Version，再通过存储边界登记只含身份和 ready 时间的元数据；不 Mock 内部应用方法。
- 用固定时间、ID factory 和存储提交故障替代外部边界；用 Barrier/Event 控制并发，不依赖任意 sleep。
- 断言应用返回、历史读取、错误码、幂等结果及安全审计；不直接查询私有字典或依赖内部调用次数。
- `queued` 只是准入结果。尚未受理的启动失败不占用 key，可在依赖满足后重试；这不是对终态 `failed` Preparation 的原地重试。终态资源和新 identity 重试规则仍待 Worker 切片实现。
- 内存数据不跨进程保留；重新创建应用且复用同一测试仓储，仅验证回执重放，不称数据库重启恢复。没有自动删除、TTL、retention 或备份恢复能力。

### 12.3 RED → GREEN → REFACTOR

最小命令：

```sh
uv run --extra dev pytest -q tests/contract/knowledge_service/test_base_preparations.py
```

| 轮次 | 真实 RED | GREEN / 后续证据 |
| --- | --- | --- |
| A1 | Base Preparation 模块不存在 | 混合文档/结构化 Source 冻结为 exact 计划；1 passed |
| A2 | 过期保存未被拒绝，可覆盖同 revision | Draft CAS 和历史读取；2 passed |
| A3 | 新启动仍接受过期 Draft revision | 拒绝旧 revision，且无新 Preparation；3 passed |
| A4 | 编辑 Draft 后重放原启动失败，没有原回执 | 原始结果、operator-scoped receipt 与一次成功审计；4 passed |
| A5 | 一个 Draft 可重复选择同一 Source | 输入合同拒绝重复 Source；5 passed |
| A6 | 未登记/跨 Space Base 和 Source 保存均被接受 | 4 个作用域场景拒绝且不占用 key；9 passed |
| A7 | 启动请求可用另一个 Space 访问 Base | 请求和 Draft 的 Space 必须一致；10 passed |
| A8 | 新 Preparation 可覆盖碰撞 ID 的原计划 | 身份冲突失败且保留原计划；11 passed |
| A9 | 提交失败暴露存储内部异常 | 稳定错误、计划/回执/审计一起回滚；12 passed |
| A10 | exact Draft 读取接受 bool/float，或对非法 revision 静默返回空 | 6 个非法 revision 统一拒绝；18 passed |
| A11 | 重放 Draft 时重新调用时钟并重建结果 | 先查回执，不重新构造；19 passed |
| 回归补测 | 既有实现已满足，未标作 RED | exact/latest 时点、缺少 ready、跨 Source/Space、key 隔离和 3 类并发；29 passed |
| A12 | 重放旧 catalog Version 更新 ready 时间，错误成为 latest | 首次可见时间不被重放改写；30 passed |
| 边界补测 | 既有合同已拒绝，未标作 RED | 未知字段、含糊 selection、严格 revision、无效命令身份、缺少 Draft；51 passed |
| REFACTOR | GREEN 后格式整理，收窄仓储元数据读取为当前 Space 和选中 Sources | 51 passed；KSS Ruff/mypy 通过 |

A12 编辑测试时曾把既有碰撞测试的尾部断言误放入新测试，产生一次测试组织失败；已恢复到原测试，未删除或降低断言，全部 51 项随后通过。该次失败不算业务 RED。

### 12.4 本轮验证与未执行项

```sh
uv run --extra dev pytest -q -rs tests/contract/knowledge_service \
  tests/test_knowledge_service_management_client.py \
  tests/test_knowledge_service_management_api.py \
  tests/test_knowledge_source_service_client.py \
  tests/test_kss_authority_cutover.py \
  tests/test_knowledge_source_service_binding.py
uv run --extra dev ruff check knowledge_source_service tests/contract/knowledge_service
uv run --extra dev mypy knowledge_source_service
```

| 检查 | 结果 | 证据限定 |
| --- | --- | --- |
| 新增核心合同 | 51 passed、0 skipped | 测试用内存仓储；含真实应用路径与确定性并发 |
| KSS + ProofAgent KSS/BFF 受影响回归 | 212 passed、44 skipped | 42 个 PG 前置测试、1 个 S3 测试和 1 个 search 测试因本轮未配置隔离依赖而跳过；未使用 production-local，也未沿用上轮 205 项零跳过作为本轮结果 |
| KSS Ruff / mypy | 通过；88 source files 无类型错误 | 不代表部署通过 |
| 新增 6 个产品/测试文件格式 | 通过 | 仅本轮文件 |
| domain-context / `git diff --check` / `uv lock --check` | 通过；锁文件检查解析 117 packages | 未改依赖或锁文件 |

本轮没有修改 SQL、依赖、配置、OpenAPI、现有 Release API、运行组合或发布脚本；未启动容器、执行生产 SQL、读取 `.env`、提交、推送、合并或部署。数据库持久化、HTTP、Worker 和一次性发布不在本轮验证范围。

受限命令记录：末轮格式/锁文件检查首次因 uv 缓存沙箱权限失败；随后通过批准机制重试并通过。最终完整受影响回归为 212 passed、44 skipped，2.44 秒，退出码 0。跳过项保持可见，没有降低 fail-if-missing 断言或把缺依赖计作通过。

### 12.5 文件和后续切片

新增文件：

- `knowledge_source_service/contracts/base_preparations.py`
- `knowledge_source_service/domain/base_preparations.py`
- `knowledge_source_service/ports/base_preparations.py`
- `knowledge_source_service/adapters/memory/base_preparations.py`
- `knowledge_source_service/application/base_preparations.py`
- `tests/contract/knowledge_service/test_base_preparations.py`

更新本报告、Feature context、Scope、项目索引、开发进度和 Knowledge & Evidence 当前实现说明；没有新增 ADR 或改变已批准权威边界。

[FRAME | HIGH] 当时的下一步建议是 TDD-02B：把同一事务合同接到 PostgreSQL，持久化 Draft 历史、exact Base Version、queued Preparation、operator/key 回执与审计，验证 catalog 一致视图、跨连接并发和重建读取。新 SQL 与管理 HTTP 的后续授权和实现证据见第 13 节。Worker lease/fencing、取消/过期、Prepared Release 和一次性发布继续分小切片实现；在这些环节完成前保留旧直接 Release 路径的现状说明，不能宣称已切换。

## 13. TDD-02B：持久化准入与管理 API（历史）

### 13.1 授权、范围与公开行为

[KNOWN | HIGH] 用户单独确认新增 SQL、PostgreSQL 仓储和管理 API，限定本地开发与测试。本轮采用 `hicode:tdd` 的完整证据路径；不重新讨论已接受的 ADR-0214/0217。没有执行生产 SQL、改变部署配置或启用生产进程。

公共路径前缀为 `/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}`。

| 方法与后缀 | 可观察行为 | 权限与输入 |
| --- | --- | --- |
| `PUT /draft` | 保存新 Draft revision，返回 `200`；历史不变 | `knowledge_source.edit`、`Idempotency-Key`、完整 `SaveKnowledgeBaseDraftRequest`；body 中的 Space/Base 必须匹配路径 |
| `GET /draft` | 读取当前管理 Draft；`?revision=1` 读取 exact 历史 | `knowledge_source.view`；不存在返回 `404`；不接受 `latest` revision |
| `POST /release-preparations` | 冻结 exact Base Version 并返回 `202 queued`；`Location` 指向资源 | `knowledge_source.edit`、`Idempotency-Key`、完整 `StartReleasePreparationRequest`；明确指定当前 Draft revision |
| `GET /release-preparations/{preparation_id}` | 读取已持久化的原始 exact 计划 | `knowledge_source.view`；校验路径 Space/Base，无原文或 secret |
| `GET /preparation-audit` | 返回成功事件和安全拒绝事件 | `knowledge_source.view`；先核对已有 Draft 的 Scope |

可信服务端身份提供 operator 和 named permissions，请求体不能指定操作者或权限。继续使用粗粒度权限组合，没有新增本地用户、per-Space ACL 或强制四眼流程。ProofAgent BFF、Dashboard 和三角色映射仍待 TDD-04。

`compose_runtime(base_preparation_id_factory=..., authenticate_operator=...)` 显式装配 PostgreSQL 管理应用。不提供 ID factory 时保留原有路由；提供 factory 但缺少认证时拒绝组合。该参数不是 CLI 或环境变量开关，`bootstrap/processes.py` 未修改。没有 Preparation Worker，也没有 `:publish` 操作；现有直接 Release 路径未切换。

### 13.2 数据与事务边界

| 对象 | 持久化与约束 | 验证边界 |
| --- | --- | --- |
| Draft | `knowledge_base_drafts` 追加历史，绑定既有 Base/Space | 首次 revision 0 和后续 revision CAS 均由 Base 行锁串行化；没有可被单独改写的 head 副本 |
| Base Version | `knowledge_base_versions` 与有序 `knowledge_base_version_members` | exact Source Version、Source、Space 使用复合外键；计划重用必须 identity/JSON 一致；成员不能重标其他 Source 的 Version |
| Preparation | `knowledge_release_preparations` | 引用 exact Draft revision/digest 和 Base Version；当前唯一状态为 `queued`，不进入查询 catalog |
| 成功回执/审计 | `knowledge_base_preparation_commands` | operator/key 摘要唯一；resource、receipt 与成功事件在同一事务提交；原始结果永久保留 |
| 拒绝审计 | `knowledge_base_preparation_rejections` | 失败事务结束后单独写入；仅可信 actor、受限 operation/ID、稳定 code 和时间，无 body/header/key |

PostgreSQL 使用 `READ COMMITTED`。先获取 operator/key 事务 advisory lock，再读回执；同键等待结束后可读到已提交原结果。保存或启动时先锁既有 Base，再读当前 Draft，因此并发首次创建也只有一个 CAS 胜者。

启动通过一条 SQL 读取所有选中 Sources 的可见 Version 元数据，按 `created_at`、Version ID 解析 `latest_ready_at_preparation`。Draft 在此期间保持锁定；所有 Source 成员来自同一条语句的快照。这里不是整个事务的 `REPEATABLE READ`，也不在数据库事务内读取 S3、访问上游或构建索引。

读取时重新计算 Draft digest 和 Base Version plan digest/content identity，核对序列化资源、关系成员、exact Draft 及成功回执。持久化投影损坏以 `base_preparation_integrity_unavailable` 失败关闭，不返回部分计划。物理 Source artifact 的校验属于后续 Worker，不把 metadata 准入当作可查询 Release 证明。

认证、权限、缺失 key、输入校验和业务拒绝在这些已注册管理路由内留审计。拒绝审计无法持久化时返回 `503 base_preparation_audit_unavailable`。无效路由/方法不属于已执行的 Preparation 命令；尚未建立整个 KSS 的通用访问审计。

### 13.3 Given-When-Then 与测试数据

| 场景 | Given / When | Then | 风险 |
| --- | --- | --- | --- |
| 持久化与重放 | 混合文档/JSON Sources，保存、启动、编辑，再重建应用/仓储 | exact 历史、Preparation、回执、成功审计保持原样；迁移 runner 重放成功；没有 Release | P1 |
| 同键并发 | 四个连接同时提交相同 operator/key 的启动命令 | 同一 Preparation，只增加一次成功事件 | P1 |
| Draft CAS | 四个连接竞争首次创建或相同当前 revision 的保存 | 一个成功，其余冲突；不覆盖历史 | P1 |
| 冻结时点 | 启动已读取 Sources，期间新 Version 入库且另一个连接编辑 Draft | 原 Preparation 保留旧 exact 组合，编辑等待锁；后续新启动看到新组合；旧 key 仍返回旧结果 | P1 |
| 事务失败 | 在存储边界模拟提交前故障，或 Preparation ID 碰撞 | 无部分计划、回执或成功事件；原资源不变，可安全重试未受理的命令 | P1 |
| 受保护 HTTP | 只读身份写入、未认证、未知字段或虚构 token | `403/401/422`、无状态变化；拒绝审计跨应用重建保留且不含敏感输入 | P1 |
| 输入与 Scope | bool/latest/stale revision、跨 Space/Base、伪造 operator 或直接指定 Versions | 稳定拒绝、不消耗成功 key；修正未受理请求后可重试 | P1 |
| 存储完整性 | 测试库中单独破坏 Draft、Preparation 或 receipt 的 JSON | 公开应用接口失败关闭，不静默采用篡改计划 | P1 |
| 运行装配 | 默认组合、缺认证显式组合、完整显式组合 | 默认无新路由、缺认证拒绝、完整组合读写真实 PG | P1 |

- 22 项新增 PG/HTTP 合同位于 `test_postgres_base_preparations.py`；既有 51 项内存核心合同继续运行。
- 每项 PG 测试使用随机 schema，混合 Source 由真实 intake 应用写入 PG catalog。新增 Preparation fixture 的 artifact store 是内存替身，不声称新 Worker 已通过 S3 验证。
- 全套既有 S3/search 合同使用真实 MinIO/OpenSearch；外部策略和上游 snapshot reader 仍是替身。
- 时钟、ID factory、存储提交故障是外部边界替身；并发用 Barrier/Event 控制。不 Mock 私有应用方法，不依赖任意 sleep 或内部调用次数。
- 完整性测试仅在隔离 schema 注入损坏。没有读取生产数据、真实凭据或 `.env`。

### 13.4 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| B1 | PostgreSQL Preparation adapter 模块不存在 | 持久化、应用重建读取、历史回执和成功审计通过 |
| B2 | 修改 Preparation JSON 成员后仍可读取 | 核对 canonical plan、关系成员与 exact Draft，损坏拒绝 |
| B3 | 修改 Draft 或 receipt JSON 后仍被接受 | 重算 Draft digest，回执必须匹配持久化原资源 |
| B4 | management builder 不接受 `base_preparations` | 保存 → 受理 → Location 读取 → 应用重建往返通过 |
| B5 | Preparation 审计接口不存在 | 成功/拒绝审计与只读、未认证、脱敏输入测试通过 |
| B6 | runtime 不接受 `base_preparation_id_factory` | 显式 PG 装配、默认关闭与缺认证拒绝通过 |
| B7 | canonical OpenAPI 缺少新路径，migration contract 仍断言旧 head | 新路径、`0009` 和 exact fingerprints 通过；未降低指纹断言 |
| 回归补测 | 已满足的并发、Scope、幂等、故障与权限行为未标作 RED | 22 项 PG/HTTP 合同通过 |
| REFACTOR | GREEN 后格式整理 | KSS Ruff、89 个源文件 mypy、11 个受影响文件格式检查通过 |

最初 fixture 缺少 JSON intake 的必填参数，修正后才进入业务验证。末轮测试曾误把未实现 `POST :publish` 的预期状态写成 `404`，框架实际返回 `405`；改为精确 `405` 断言，保留不存在资源 GET 的 `404` 断言。两次均为测试设置/预期修正，不算业务 RED，也没有添加发布能力或放宽拒绝范围。

### 13.5 验证命令与结果

使用独立 Compose 项目 `proofagent-kss-preparation-tdd` 和 `--env-file /dev/null`。没有复用既有 production-local 数据。连接参数由隔离测试环境注入，报告不记录凭据。

```sh
KSS_REQUIRE_POSTGRES_TESTS=1 KSS_REQUIRE_S3_TESTS=1 KSS_REQUIRE_SEARCH_TESTS=1 \
  uv run --extra dev pytest -q -rs tests/contract/knowledge_service \
  tests/test_knowledge_service_management_client.py \
  tests/test_knowledge_service_management_api.py \
  tests/test_knowledge_source_service_client.py \
  tests/test_kss_authority_cutover.py \
  tests/test_knowledge_source_service_binding.py
uv run --extra dev ruff check knowledge_source_service tests/contract/knowledge_service
uv run --extra dev mypy knowledge_source_service
python3 scripts/check-domain-contexts.py
git diff --check
uv lock --check
```

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| 全部 KSS 合同 + ProofAgent KSS/BFF 受影响边界 | 278 passed、0 skipped，20.17 秒，退出码 0 | 真实 PG/MinIO/OpenSearch，三项依赖 fail-if-missing；不是全仓库测试或 Production GO |
| 新增 PG/HTTP 合同 | 22 项，包含在上述通过结果内 | 应用/仓储重建，不是 PostgreSQL 进程故障或备份恢复演练 |
| Service distribution | 19 passed，1.32 秒；全套复跑也通过 | canonical OpenAPI、migration head 与 exact 指纹保护仍启用 |
| KSS Ruff / mypy | All checks passed；89 source files 无类型错误 | ProofAgent 产品代码本轮未修改 |
| 本轮 11 个产品/测试文件格式 | 11 files already formatted | 包括 API、runtime、migration registry 和新增 PG adapter/tests |
| domain-context / `git diff --check` | 通过，退出码 0 | 文档和 whitespace 检查，不是发布验收 |
| `uv lock --check` | 通过，117 packages | 未改依赖或锁文件 |

本轮接口和 migration contract 的候选指纹如下；不沿用旧候选的任何发布批准：

```text
openapi.sha256=f6c24b670bfd87a6ff810f3d7eeb6595f4617aa082940dbf1eda979c51a02cb4
migrations.sha256=72328ba225fd4098cbdad1cb0a7c13985d08c5a381ef3ad834f7ae4f914dda23
head_revision=0009_base_preparations
```

受限命令记录：Docker socket 和测试 loopback 访问按批准机制执行；锁文件检查首次因 uv 缓存沙箱权限失败，获准重试后通过。没有通过更换环境或禁用断言掩盖依赖问题。第一次全套为 277 passed、1 failed，失败即上节 `405` 预期问题；修正后的最终完整运行结果以表格为准。

测试结束后，仅对 `proofagent-kss-preparation-tdd` 执行 `down --volumes`。临时 PostgreSQL、MinIO、OpenSearch 容器与网络已删除，随后 `ps --all` 返回空清单。测试数据可由 fixtures 重建，没有保留恢复快照；既有 production-local 服务和数据未被操作。

### 13.6 文件、交付与下一步

- 新增 `knowledge_source_service/migrations/0009_base_preparations.sql`、`adapters/postgres/base_preparations.py` 和 `tests/contract/knowledge_service/test_postgres_base_preparations.py`。
- 更新 Base Preparation contracts/application/ports/memory adapter，补安全拒绝事件与持久化仓储合同；未增加新的业务状态。
- 更新 migration registry、management HTTP、显式 runtime DI、canonical OpenAPI 和 distribution 指纹测试。
- 新增 [Base Draft 与 Preparation 本地接口使用说明](base-preparation-local-guide.md)，更新 Feature/Scope、项目索引、进度和领域当前实现状态；保留前几轮历史证据。
- 未执行 Git commit、push、merge、部署、生产 SQL 或生产配置变更。

[FRAME | HIGH] 后续建议为 TDD-02C 的 Worker 状态与 lease/fencing 小切片：先保护 claim、接管和 stale fence，再接构建工作；取消/过期、ready 校验和一次性发布继续按独立行为交付。新 SQL/运行进程/配置变更需按仓库门禁明确范围。未完成这些行为前，旧直接 Release 路径保持现状，Feature 仍为 `PARTIAL_VERIFICATION`。

后续引入状态推进时，还需保护原始启动回执：当前仓储可用完整 `queued` 资源比较回执，但资源状态变化后必须按不可变准入身份核对，不能用当前状态替换原回执，也不能把正常状态变化判为存储损坏。

## 14. TDD-02C：Worker 租约协调与回执保护

### 14.1 授权、公开接口与范围

[KNOWN | HIGH] 2026-08-27 用户单独确认新增 SQL、仓储和管理状态合同调整，仅限本地开发与隔离测试。采用 `hicode:tdd` 完整留痕路径，依据 ADR-0217、既有 Scope 和上一切片的原始回执要求；最高风险 P1。没有重启或启用生产进程，没有连接生产数据库，没有 Git commit/push/merge。

新增服务端 `BasePreparationWorker`，Interface 为 `claim_next()`、`renew(claim)`、`audit(base_id)`。它接受 PostgreSQL repository、受限 Worker ID 和正值且不超过一小时的 `lease_duration`，无浏览器或网络 Worker 命令。ID 是可信执行进程标识，不是新的用户、角色或授权凭据。

| Interface | 可观察结果 | 不具备的能力 |
| --- | --- | --- |
| `claim_next()` | 返回固定 admission plan、Worker ID、递增 fencing token 和服务端租约截止时间；资源变为 running | 不构建、不读取 artifact、不发布 Release |
| `renew(claim)` | 当前 owner/fence/plan 且租约未到期时延长截止时间；token 不变 | 不能续租过期或被接管的 claim；不能用调用者的截止时间延长权限 |
| `audit(base_id)` | 读取服务端 `claimed/renewed/taken_over` 协调事件 | 不是新增管理 HTTP 接口，也不是通用 Worker 拒绝审计 |
| 管理 GET Preparation | 返回当前 `queued/running` 和 immutable identity | 不返回 Worker ID、fencing token 或租约字段；running 不证明构建或健康状态 |
| 管理 POST 重放 | 仍返回原始 `202 queued` 回执与相同 Location | 不用当前状态改写历史回执；当前状态由 GET 读取 |

没有新增角色或 per-Space ACL。既有管理 GET/POST 继续使用服务端 `knowledge_source.view/edit` 和安全拒绝审计；Worker Interface 只供可信服务端调用，未装配进 `bootstrap/processes.py`，也未新增 CLI/配置开关或常驻循环。

### 14.2 持久化、时间和事务

- 新增 `0010_preparation_leases.sql`，不改写 `0009`：扩展 state 约束为 queued/running，增加 owner、fencing token、deadline 与一致性约束，以及领取索引和 `knowledge_preparation_worker_events`。
- Preparation 行本身是领取权威，没有另建可漂移的队列副本。每次按 submitted time、Preparation ID 排序，`FOR UPDATE SKIP LOCKED LIMIT 1` 领取一个 queued 或已超时 running 资源。空结果也可能表示候选被其他短事务锁定，不代表全队列为空。
- PostgreSQL `clock_timestamp()` 是租约时间权威。领取或续租在持有行锁并核对完整资源后计算截止时间；没有跨网络、S3、search 或构建工作的长事务。内存 adapter 仅在测试中接受受控时钟。
- 领取与接管使 token 增加一，续租保持 token；状态、owner、token、deadline 与一条成功协调事件在同一事务提交。到期边界为 `now >= deadline`，旧 claim 必须拒绝，即使 Worker ID 被重新使用。
- 续租检查持久化 owner、token、截止时间与完整 immutable admission；不信任 claim 中自报的截止时间。续租取已有 deadline 与新 deadline 的较大值，不缩短租约。重复续租是新的协调事件，并非使用管理幂等 key 的历史回执重放。
- Lease 到期不把 Preparation 变为 `expired`，接管也不新建 Preparation identity。它仍是同一 frozen plan 的新执行 attempt；ready candidate 的过期和失败终态重试仍待后续实现。
- 原始启动回执继续保存 queued。仓储读取当前资源并校验完整性后，恢复 immutable admission view 与回执比较；仅状态差异被分离，Draft、Base Version、成员、digest、时间和身份不能漂移。

新增协调事件无自动清理、TTL 或分页；无恢复快照或生产恢复演练。旧二进制不能识别 running，未来生产切换必须协调 API/Worker 与 migration，不能盲目回滚二进制或把 running 改回 queued。

### 14.3 Given-When-Then 与替身

| 场景 | Given / When | Then | 风险 |
| --- | --- | --- | --- |
| 首次领取 | queued exact plan，Worker 领取 | running、token 1、同一计划、一条 claimed 事件，没有 Release | P1 |
| 回执重放 | 已 running，重建应用后 POST 原请求/key | 原 queued 回执不变，成功管理审计仍可读；GET 为 running | P1 |
| 续租 | 当前 claim、未到期 | deadline 前进或保持，token/plan 不变，其他 Worker 无法领取 | P1 |
| 超时接管 | 原租约到期，新 Worker 或同名 Worker 领取 | 同一 Preparation、token 增加，旧 claim 续租被拒绝 | P1 |
| 并发领取 | 八个独立连接竞争 queued 或 expired-running | 一个有效 claim、一次对应协调事件 | P1 |
| 续租与接管竞争 | 过期 owner 续租，同时新 Worker 尝试领取 | 旧 owner 被拒绝；必要时在短锁释放后再领取，最终仅一个新 owner | P1 |
| 锁隔离 | 一个 Preparation 被外部事务锁定，另一个可领取 | Worker 跳过锁定行并领取另一资源 | P1 |
| 伪造 claim | 改 worker/fence/bool token/plan/identity 或自报未来 deadline | 稳定拒绝，无新的成功事件；当前真实 claim 仍可用 | P1 |
| 事务失败 | 在存储边界注入提交前故障 | running、lease、协调事件一起回滚；重试仍从 token 1 开始 | P1 |
| 历史迁移 | 先建立 0009 schema 和 queued 数据，再应用/重放 0010 | 原资源与回执保留，可被新 Worker 领取 | P1 |
| 管理投影 | GET running，POST 重放，读取管理审计 | exact identity 保持一致，HTTP schema 不包含 PreparationClaim | P1 |
| 输入与时间边界 | 无效 Worker ID、非正/超一小时/非 timedelta 租约、内存精确到期及回退时钟 | 无副作用、到期拒绝、续租不缩短 deadline | P1 |

新增 17 项 PG/HTTP 合同、9 项内存/输入合同。PG fixture 使用随机 schema 和真实摄取应用；artifact store 仍是测试用内存实现。到期测试只在该 schema 注入过期 deadline，锁竞争使用真实数据库行锁；不依赖任意 sleep。断言只通过应用/Worker/HTTP Interface 读取，不查询私有结构或以直接 SQL 查询证明结果。

时间、ID 与提交故障是外部边界替身，没有 Mock 内部应用方法。全部 S3/search 证据来自受影响全套的既有真实依赖合同，不能转称本切片已实现构建或 artifact 发布防护。

### 14.4 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN |
| --- | --- | --- |
| C1 | `base_preparation_worker` 模块不存在 | 真实 PG 首次领取，running、exact plan 与原子审计 |
| C2 | running 后重放 queued 回执被误判为 integrity unavailable | 不可变 admission 与当前状态分离，原始回执/管理审计保留 |
| C3 | Worker 没有 renew Interface | 当前 claim 可续租，token 与计划不变 |
| C4 | expired-running 无法被领取 | 过期接管、递增 token、旧 claim 拒绝 |
| C5 | HTTP GET 仍只接受 queued，running 触发 ResponseValidationError | GET 使用受限状态联合，POST 保持原 queued 回执 |
| C6 | 内存仓储没有租约时钟/协调实现 | 同一领取/续租/接管合同及精确到期边界通过 |
| C7 | OpenAPI 指纹、migration head 仍绑定旧合同 | 明确保护 running schema、Worker claim 不公开和新的 exact fingerprints |
| 回归补测 | 已满足的并发、故障、迁移、输入保护未标为 RED | 新增 26 项全部通过 |
| REFACTOR | 提取数据库时间读取并处理 nullable fetch 类型；格式整理 | mypy 90 个源文件、Ruff 和 12 文件格式检查通过；全套再次验证 |

续租/接管竞争测试最初错误要求非阻塞 `claim_next()` 在另一事务持锁时必须立即成功。实际 `SKIP LOCKED` 可以返回空；测试改为等待两个竞争调用结束后，最多再执行一次领取，并继续严格断言只有一个新 owner、一个接管事件。该次是测试预期修正，不算业务 RED，未改成阻塞队列或取消断言。

### 14.5 本轮验证与候选指纹

独立测试项目为 `proofagent-kss-lease-tdd`；Compose 显式使用 `--env-file /dev/null`。没有读取 `.env`、生产配置、凭据或生产数据，未操作既有 production-local。测试连接参数不写入报告。

```sh
KSS_REQUIRE_POSTGRES_TESTS=1 KSS_REQUIRE_S3_TESTS=1 KSS_REQUIRE_SEARCH_TESTS=1 \
  uv run --extra dev pytest -q -rs tests/contract/knowledge_service \
  tests/test_knowledge_service_management_client.py \
  tests/test_knowledge_service_management_api.py \
  tests/test_knowledge_source_service_client.py \
  tests/test_kss_authority_cutover.py \
  tests/test_knowledge_source_service_binding.py
uv run --extra dev mypy knowledge_source_service
uv run --extra dev ruff check knowledge_source_service tests/contract/knowledge_service
python3 scripts/check-domain-contexts.py
git diff --check
uv lock --check
```

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| Preparation 核心 + PG/HTTP + distribution | 118 passed，9.37 秒 | 60 核心、39 PG/HTTP、19 打包合同 |
| 全部 KSS + ProofAgent KSS 边界回归 | 304 passed、0 skipped，22.79 秒，退出码 0 | PG/MinIO/OpenSearch 均 fail-if-missing；不是全仓库或生产验证 |
| KSS mypy / Ruff | 90 source files 无类型错误；All checks passed | 本轮未改 ProofAgent 产品代码 |
| 受影响文件格式 | 12 files already formatted | 6 个文件整理格式后全套复跑通过 |
| domain-context / `git diff --check` | 通过，退出码 0 | 文档与 whitespace 检查，不是生产验收 |
| 锁文件检查 | 117 packages，退出码 0 | 未改依赖或锁文件 |

```text
openapi.sha256=af2eebacc4b6344dae73e39752f551593b1d59f5f78f0aac059625338b775de7
migrations.sha256=34fc7735af072dfff5061a45a90b1a8f846e854b56a8cf85fb13595846df5541
head_revision=0010_preparation_leases
```

上述指纹属于新候选，未沿用旧候选发布批准。Docker/loopback 命令按批准机制运行；`uv lock --check` 首次因缓存沙箱权限失败，获准重试后通过。所有运行结果均检查最终退出状态，不把进度点当作完成。

测试结束后，仅对 `proofagent-kss-lease-tdd` 执行 `down --volumes`，临时三个依赖容器与网络已删除；随后 `ps --all` 返回空清单。测试数据可由 fixtures 重建，没有保留恢复快照；未清理或变更 production-local 数据。

### 14.6 文件、文档与后续边界

- 新增 `application/base_preparation_worker.py` 和 `migrations/0010_preparation_leases.sql`。
- 更新 Base Preparation contracts/domain/ports/application、内存与 PostgreSQL adapter、migration registry、management HTTP。
- 扩展 `test_base_preparations.py`、`test_postgres_base_preparations.py` 和 distribution schema/指纹保护；没有删除测试或降低原始回执/权限/完整性断言。
- 更新本报告、Scope、Feature context、本地使用指南、项目索引、开发进度和领域当前实现说明。中文指南区分准入回执、当前状态、租约到期和未来 candidate 过期。
- 没有更改 `bootstrap/processes.py`、部署配置、既有直接 Release 发布路径或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] 下一片建议接入只消费 frozen plan 的构建执行器，并把最终结果提交与最新 owner/fence/lease/exact identity 校验放在同一短事务。不能用本片续租成功作为稍后写入的许可。取消、ready/failed、candidate expiry、一次性 publication、容量/重试策略和恢复演练仍需后续明确切片；当前整体保持 `PARTIAL_VERIFICATION`。

## 15. TDD-02D：候选构建与最终结果 fencing

### 15.1 授权、Interface 与范围

[KNOWN | HIGH] 2026-08-27 用户单独确认新增 SQL、构建 Interface、仓储和管理状态合同调整，仅限本地开发与隔离测试。采用 `hicode:tdd` 完整留痕路径；最高风险 P1。没有启用生产 Worker，没有连接生产数据库，没有执行 Git commit/push/merge、部署或 Release publication。

| Interface | 可观察结果 | 权威限制 |
| --- | --- | --- |
| `KnowledgeReleaseApplication.prepare(command)` | 构建并精确校验 immutable manifest，可返回 Prepared Knowledge Base Release | 不调用 catalog `put_release`，候选不可查询 |
| `KnowledgeReleaseCandidateBuilder.build(base_version)` | 只消费 frozen Base Version 的有序 exact Source Version IDs | 不解析 latest，不修改 Draft 或 plan |
| `BasePreparationWorker.run_next(builder, candidate_ttl)` | 领取一个任务；构建成功返回 `ready`，构建异常或无效候选返回 `failed`，无任务返回 `None` | 构建在事务外；最终状态只在 fenced 短事务提交 |
| 管理 GET Preparation | 返回 `queued/running/ready/failed` 的 secret-free 资源 | 不返回 owner、token、lease、candidate JSON 或 artifact reference |
| 管理 POST 重放 | 状态推进后仍返回原始 `202 queued` 回执与相同 Location | 当前状态只通过 GET 读取 |

`ready` 包含 exact Release ID、manifest digest、完成时间和到期时间，但没有 query authority。现有直接 `publish()` 保持兼容，也仍是独立的旧同步路径；本片没有把 Preparation 接入该路径。Worker Interface 没有 HTTP endpoint、CLI、常驻循环或生产组合。

### 15.2 构建、持久化与 fencing

- 新增 `0011_preparation_results.sql`，不改写 `0009/0010`。状态约束扩展为 `queued/running/ready/failed`；终态保留最后 fencing token，清除 owner/deadline，并约束内部 candidate JSON、终态时间及 candidate 到期时间。
- Worker 先在短事务中领取，再在事务外构建。构建器只能看到 frozen Base Version。候选必须与 Space/Base、Base Version、有序 Source Version IDs、manifest digest 和 content-derived Release ID 完全一致。
- `ready` 提交重新锁定 Preparation 行，使用 PostgreSQL 时间核对当前 owner、未到期 lease、fencing token 和完整 admission。candidate、公开资源与一条 `ready` Worker 事件同事务提交。
- 构建异常转成 `base_preparation_build_failed`；候选身份不一致转成 `base_preparation_invalid_candidate`。原始异常和 candidate 内部数据不进入管理资源。`failed` 与对应 Worker 事件同事务提交，不能再次领取。
- 构建期间租约到期并被接管时，旧 Worker 后续提交成功或失败结果都会得到 `base_preparation_stale_claim`。新 attempt 的状态和审计不会被覆盖。
- 最终结果事务失败时，candidate、状态和结果事件一起回滚。已提交的 running/claim 仍保留；租约到期后可按递增 token 接管。
- PostgreSQL 读取会交叉校验 ready 公开身份、内部 candidate、Base Version、成员、Draft 历史及 relational columns。内存 adapter 保持相同 Interface，仅供测试。

构建器可能在旧 lease 到期后完成 immutable object 或独立 projection generation。fencing 阻止旧 attempt 把这些对象绑定为 ready 或 queryable Release，但本片没有删除孤立对象。该限制需要后续回收和恢复策略，不能把「不可查询」表述成「没有产生外部对象」。

`candidate_ttl` 当前是可信服务端调用者提供的正值，没有生产默认值或上限策略。到期时间已持久化，但 `ready → expired` 转换尚未实现。

### 15.3 Given-When-Then 与测试替身

| 场景 | Given / When | Then | 风险 |
| --- | --- | --- | --- |
| 非查询候选 | exact Source Version 组合，调用 `prepare()` | manifest/artifact 已精确校验；catalog 中无 Release | P1 |
| ready 主路径 | queued plan，可信 Worker 执行 | frozen plan 构建；ready identity/expiry 持久化；无 queryable Release | P1 |
| 构建失败 | 构建器抛出含私有细节的异常 | failed + 稳定错误码；HTTP/资源无原始细节 | P1 |
| 无效候选 | 构建结果改变 Space、plan、digest 或 content identity | failed + `base_preparation_invalid_candidate` | P1 |
| stale 完成竞争 | 旧构建暂停，lease 到期，新 attempt 完成 ready，旧构建恢复 | 旧提交被拒；仅新 token 有 ready 事件 | P1 |
| 最终事务失败 | 在结果写入后、提交前注入存储故障 | 仍为 running，只有 claimed 事件；到期后可接管完成 | P1 |
| 历史升级 | 先建立 `0010` running claim，再应用并重放 `0011` | owner/token/deadline 保留；升级后公开续租成功 | P1 |
| 管理投影 | GET ready/failed，POST 重放原命令 | 终态安全可见；原 queued 回执不变；无私有能力字段 | P1 |

候选构建使用真实应用与 PostgreSQL catalog；Preparation PG fixture 的 artifact adapter 为测试内存实现。并发测试使用独立数据库连接和事件同步，不依赖任意 sleep。提交故障只在 repository seam 注入；断言通过应用、Worker、管理 HTTP 和 catalog Interface 读取。

### 15.4 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN |
| --- | --- | --- |
| D1 | `KnowledgeReleaseApplication` 没有 `prepare()` | 候选 manifest 精确生成，但不写 Release catalog；既有 `publish()` 仍通过 |
| D2 | Worker 没有 `run_next()` | frozen plan 构建并在内存事务提交 ready |
| D3 | 构建异常原样抛出 | 安全 failed 状态与稳定错误码 |
| D4 | PostgreSQL 最终提交缺少 `complete_claim`，安全包装为 Worker unavailable | `0011` + PostgreSQL ready 事务、内部 candidate 和原子结果事件 |
| D5 | malformed candidate 直接抛 `base_preparation_invalid_candidate`，未形成终态 | Worker 在提交前校验并原子记录 safe failed |
| D6 | OpenAPI 指纹和 migration head 仍绑定 TDD-02C | ready/failed 安全 schema、`0011` head 与新 exact fingerprints |
| D7 | ready candidate JSON 可把 Space 身份改标而不触发读取失败 | 读取交叉校验 Space/Base、content-derived Release ID、Base Version、成员和 artifact digest |
| 行为保护 | stale completion、failed persistence、提交回滚、0010 running 升级、ready/failed HTTP | 全部通过；未把既有 GREEN 误记为 RED |
| REFACTOR | candidate identity 校验在 adapter 重复；测试重复命令转换 | 集中领域校验并新增 `KnowledgeReleaseCandidateBuilder` adapter；mypy/Ruff/格式复验通过 |

`0010` 升级测试最初使用新仓储读取尚未迁移的历史表，因缺少 `candidate_json` 字段失败。修正为 disposable-schema 夹具直接建立历史 running 行，再通过升级后的公开 Worker 验证。该次是测试夹具错误，不算业务 RED，没有为兼容未迁移 schema 放宽生产仓储。

### 15.5 本轮验证与候选指纹

独立测试项目为 `proofagent-kss-build-tdd`，Compose 显式使用 `--env-file /dev/null`。没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| Preparation 核心 + PG/HTTP + 候选 tracer | 113 passed，12.68 秒 | 包含真实 PostgreSQL；不是生产数据库或恢复演练 |
| 全部 KSS + ProofAgent KSS 边界回归 | 316 passed、0 skipped，28.16 秒，退出码 0 | PG/MinIO/OpenSearch 均 fail-if-missing；不是全仓库或 Production GO |
| KSS mypy / Ruff | 91 source files 无类型错误；All checks passed | 未修改 ProofAgent 产品代码 |
| 受影响文件格式 | 13 files already formatted | 包括 builder、Worker、contracts、adapter 和测试 |
| domain-context / `git diff --check` | 通过，退出码 0 | 文档与 whitespace 检查，不是发布验收 |
| 锁文件检查 | 根项目 117 packages、KSS 服务 34 packages，退出码 0 | 未改依赖或锁文件 |

```text
openapi.sha256=10a44e04f998135bab8c75ec5d81c3a0e12732d8eda389dd8e61662e98da1c7f
migrations.sha256=612c8abdd25cc398fb67151cc35a361bfbe3dbc5a756af1134fbb6b57a785712
head_revision=0011_preparation_results
```

上述指纹只描述当前本地候选，未获得发布批准。Docker/loopback/uv-cache 命令按批准机制执行。锁检查首次因 uv 缓存沙箱权限失败，获准重试后通过。最终回归检查了完整输出和退出码。

测试结束后，仅对 `proofagent-kss-build-tdd` 执行 `down --volumes`。临时 PostgreSQL、MinIO、OpenSearch 容器与网络已删除，随后 `ps --all` 返回空清单。测试数据可由 fixtures 重建，没有保留恢复快照；既有 production-local 未被操作。

### 15.6 文件、文档与后续边界

- 新增 `application/base_preparation_builder.py` 和 `migrations/0011_preparation_results.sql`。
- 更新 Release application、Preparation Worker/contracts/domain/ports、内存与 PostgreSQL adapter、migration registry 和安全管理投影。
- 扩展核心、真实 PG/HTTP、候选 tracer 与 distribution 指纹保护；没有删除测试或降低既有断言。
- 更新本报告、Scope、Feature context、本地指南、项目索引、开发进度和知识证据领域说明。
- 没有更改 `bootstrap/processes.py`、部署配置、ProofAgent BFF/Dashboard 或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] 下一片建议实现 `ready → expired` 与一次性 publication CAS：只消费一个未到期 ready candidate，原子写入 exact Release 和 `consumed`，重复或 stale publication fail closed。取消、容量/重试策略、孤立对象回收、常驻 Worker、Reference Ledger、ProofAgent 三角色接线和 Phase F 仍需后续切片。当前整体保持 `PARTIAL_VERIFICATION`。

## 16. TDD-02E：一次性核心 Release publication CAS

### 16.1 授权、Interface 与范围

[KNOWN | HIGH] 2026-08-28 用户要求继续下一分片，专注核心功能并做好验证。本片只实现可信服务端应用 Interface 和本地持久化合同：`ready → expired`、`ready → consumed`、exact Release 与生命周期审计的单 PostgreSQL 事务提交。没有新增 Preparation `:publish` HTTP 路由、BFF/Dashboard、角色接线、常驻 Worker、主动过期调度、取消、部署、生产 SQL 或 Git 操作。

| Interface | 可观察结果 | 权威限制 |
| --- | --- | --- |
| `KnowledgeBasePreparationApplication.publish(preparation_id, operator_id)` | 未到期 ready 原子变为 `consumed`，exact Release 同时 queryable；到期 ready 持久化为 `expired` 后返回稳定错误 | 仅可信服务端调用；没有 HTTP/CLI；不接受浏览器凭据或调用者时间 |
| `get_preparation(preparation_id)` | 读取 durable `expired/consumed` 和 exact Release ID/digest/完成、到期及终态时间 | GET 不推进时间状态；过期但尚未尝试发布的 ready 可以继续显示 ready |
| `publication_audit(base_id)` | 读取 `expired/consumed`、operator、Space/Base/Preparation/Release exact identity、digest 和数据库时间 | 仅核心仓储 Interface；本片没有新增浏览器审计路由 |

Preparation identity 是一次性 CAS 键，不增加另一个 publication idempotency key。第一次成功后重复调用返回 `base_preparation_not_ready`，不创建第二条 Release 或生命周期事件。调用方在响应不确定时应通过 GET 恢复权威结果，不能用新请求猜测提交状态。

### 16.2 单事务、时间与完整性边界

- 新增 `0012_preparation_publications.sql`，不改写历史 migration。状态扩展为 `expired/consumed`，增加 `consumed_at`、`expired_at`、同 Space exact Release 复合外键、状态/候选/终态约束、ready 到期索引和每个 Preparation 唯一的 publication lifecycle event。
- PostgreSQL `clock_timestamp()` 是最终 CAS 时间权威；`now >= expires_at` 进入 expired。过期状态和审计先在事务中提交，应用随后抛出 `base_preparation_expired`，因此错误响应不等于事务回滚。
- publish 先锁定 Preparation 行，再重验 typed candidate、frozen admission、manifest digest、content-derived Release identity、确定性 artifact object key、artifact digest/size/media type 和 retrieval projection binding。最终 CAS 不访问 S3、OpenSearch 或其他网络依赖。
- 未到期路径在同一数据库事务中写入完整 Release header、有序成员、`consumed` Preparation、exact Release 外键及一条审计事件。提交前其他连接仍只能看到 ready 且看不到 Release；提交后同时看到 consumed 和完整 Release。
- 已存在的同 content-addressed Release 只有在 header、状态、artifact reference、有序成员和 projection 全部相等且 queryable 时才可复用。复用校验对 Release header 和成员持锁直至 consumed 事务提交，普通退役不能插入校验与提交之间。retired、部分成员、缺失或冲突记录全部失败关闭并回滚，不修补、不复活。
- consumed 是发布发生时的 durable 历史，不要求 Release 永远保持 queryable。后续合法 retired 不改变 consumed 资源或原始 queued 回执；历史读取仍严格核对 immutable header、artifact、成员和 projection。
- 任何审计写入、Release 外键或事务提交失败都会回滚 Release、成员、Preparation 和事件。并发八个独立连接只允许一个调用消费；其余观察到非 ready 并失败关闭。
- 内存仓储实现同一公开合同，并修正 terminal Preparation 被再次 claim 的测试适配器缺陷。它仍不是生产 fallback 或 PostgreSQL 原子性的替代证据。

本片信任已完成 Preparation 构建时对外部 immutable artifact 的验证，并在 CAS 内重验其持久化确定性绑定；它不在数据库事务中重新下载 artifact。数据库或对象存储介质级损坏仍由既有完整性 Worker、备份与恢复流程负责，不能由本片测试推导为已完成灾难恢复。

### 16.3 Given-When-Then 与失败矩阵

| 场景 | Given / When | Then | 风险 |
| --- | --- | --- | --- |
| 成功消费 | 未到期 ready，可信 operator 发布 | consumed、完整 queryable Release、单条 consumed 审计同事务可见 | P1 |
| 精确到期 | 数据库时间等于或晚于 expires | expired 和审计持久化；无 Release；应用返回 `base_preparation_expired` | P1 |
| 并发消费 | 八个独立连接发布同一 ready | 一次成功、七次 `base_preparation_not_ready`；无重复 Release/event | P1 |
| 提交可见性 | 在提交点暂停第一连接并从第二连接读取 | 提交前 ready/无 Release，提交后 consumed/完整 Release | P1 |
| 事务故障 | 审计写入前后注入故障 | Release header/member、状态和事件全部回滚，仍为原 ready | P1 |
| exact Release 重用 | 相同 queryable content-addressed Release 已存在 | 复用 exact Release，并消费 Preparation；不重复成员 | P1 |
| 复用与退役竞争 | publication 已校验既有 queryable Release，提交尚未完成 | retirement 被 Release 行锁阻塞；consumed 提交后才可退役 | P1 |
| consumed 后退役 | 成功消费后 Release 合法变为 retired | consumed 终态和原始 queued 回执继续可读；新 ready 仍不得复用 retired | P1 |
| 冲突 Release | 已存在 retired、部分或内容冲突 Release | `base_preparation_release_conflict`；不复活、不修补、不消费 | P1 |
| 候选污染 | object key、manifest 或 frozen identity 被改动 | 完整性错误；无 Release、无状态/审计副作用 | P1 |
| 历史升级 | 合法 `0011 ready` 数据应用并重放 `0012` | 资源保留，升级后可消费；migration 重放无重复副作用 | P1 |
| 管理投影 | HTTP GET 读取 consumed；尝试 `:publish` | GET secret-free；未实现命令保持 405 | P1 |

### 16.4 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| E1 | `KnowledgeBasePreparationApplication` 不存在 `publish()` | 内存 ready → consumed、exact Release、一次审计和重复拒绝通过 |
| E2 | PostgreSQL transaction 没有 publication Interface，调用被包装为 unavailable | 抽取 caller-owned catalog helper，在同一连接/事务写 Release 和 consumed |
| E3 | 内存 terminal resource 仍会被 `claim_next()` 重新领取 | claim 只接受 queued/running，expired/consumed/ready/failed 均不会复活 |
| E4 | catalog 冲突路径可能补写缺失成员 | existing Release 改为严格全量相等检查，部分/retired/conflicting 行不修复 |
| E5 | OpenAPI/migration contract 仍绑定 `0011` | 增加 expired/consumed 安全 schema、`0012` head 和新的 exact fingerprints |
| E6 | 既有 queryable Release 校验后可在 consumed 提交前并发 retired | 复用时锁定 Release header/有序成员直至提交，并补数据库 `lock_timeout` 交错合同 |
| E7 | consumed 指向的 Release 后续合法 retired 后，Preparation GET 和原始 POST replay 变为 integrity unavailable | 历史 exact-content 校验与“当前可复用”校验分离；生命周期变化不破坏 durable history |
| 行为保护 | 到期、并发、提交可见性、事务故障、exact 重用/冲突、候选污染、历史升级、HTTP 405 | 全部通过；没有用 sleep 或私有方法调用次数作为行为断言 |
| REFACTOR | 发布逻辑与既有 catalog transaction ownership 重叠 | 复用 caller-owned exact Release helper；直接 `put_release()` 仍保留自己的事务与兼容合同 |

历史升级测试第一次错误地用新 adapter 读取尚未应用 `0012` 的旧表，因缺少新列失败；修正为先按 `0011` 表结构建立合法 ready 历史行，再迁移后使用公开 Interface 验证。该次是 fixture 修正，不算业务 RED，也没有让新 adapter 兼容未迁移 schema。

### 16.5 验证结果与候选指纹

独立测试项目为 `proofagent-kss-publish-tdd`，Compose 显式使用 `--env-file /dev/null`。PostgreSQL、MinIO 和 OpenSearch 使用独立本机端口；没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| Preparation 核心 + PostgreSQL + distribution | 145 passed，退出码 0 | 66 个内存/应用合同、60 个真实 PostgreSQL 合同、19 个打包合同 |
| 全部 KSS + ProofAgent KSS/BFF 受影响边界 | 332 passed、0 skipped，29.90 秒，退出码 0 | PG/MinIO/OpenSearch 均 fail-if-missing；不是全仓库或 Production GO |
| KSS mypy / Ruff | 91 source files 无类型错误；All checks passed | 本轮未修改 ProofAgent 产品代码 |
| 受影响文件格式 / domain-context / diff | 11 files already formatted；检查通过，退出码 0 | 文档、格式与 whitespace 检查，不是部署验收 |
| 锁文件检查 | 根项目 117 packages、KSS 服务 34 packages，退出码 0 | 未改依赖或锁文件 |

```text
openapi.sha256=6fc81dcec5ea0c625e67aba7d7fd8e7ef503e27b8573f02aff54f31e2b8c6e5f
migrations.sha256=4b416dee7efa97d7a357734d14a3a0a753068aff219bec438d55acae6ffdd5ee
head_revision=0012_preparation_publications
```

上述指纹只描述当前本地候选，未获得部署、生产迁移或 Release 发布批准。Docker/loopback 命令按批准机制运行；两个 `uv lock --check` 首次因缓存沙箱权限失败，获准重试后通过。所有长测试均检查最终输出和退出码；没有把进度行或 isolated test 当作正式 GO。

测试结束后，仅对 `proofagent-kss-publish-tdd` 执行 `down --volumes`；临时 PostgreSQL、MinIO、OpenSearch 容器和网络已删除，随后 `ps --all` 返回空清单。隔离数据可由 fixtures 重建，没有保留恢复快照；既有 production-local 服务和数据未被操作。

### 16.6 文件、边界与下一片

- 新增 `migrations/0012_preparation_publications.sql`，扩展 Preparation contracts/domain/application/ports、内存与 PostgreSQL adapter，并抽取 caller-owned exact Release catalog helper。
- 扩展核心、真实 PostgreSQL、管理 GET、migration 和 distribution 指纹合同；没有删除测试或降低既有 fencing、原始回执、权限、secret-free 与 catalog 完整性断言。
- 更新本报告、Scope、Feature context、本地指南、项目索引、开发进度和知识证据领域说明。
- 没有修改 `bootstrap/processes.py`、部署配置、ProofAgent BFF/Dashboard、角色映射或生产 SQL；没有提交、推送、合并或发布。

[KNOWN | HIGH] 后续 TDD-02F 先补 application-only one-shot 主动过期，见第 17 节；TDD-02G 再补 application-only queued/running cancellation，见第 18 节；两者都没有增加自动调度或网络命令。publish/expiry/cancel HTTP、ProofAgent BFF 仍需单独收敛授权与运行责任。不能把当前 application-only Interface 当作浏览器可用流程。Reference Ledger、正式 Agent candidate binding、Phase F、online smoke、生产迁移/回滚仍属于后续独立范围；Feature 保持 `PARTIAL_VERIFICATION`。

## 17. TDD-02F：一次一个的主动过期回收

### 17.1 授权、Interface 与范围

[KNOWN | HIGH] 2026-08-28 用户要求继续下一切片并聚焦核心功能与验证。本片复用 `0012` 已有状态、约束、索引和 publication lifecycle audit，只增加可信服务端 `KnowledgeBasePreparationApplication.expire_next(operator_id)`。每次调用最多把一个到期 `ready` 资源变为 `expired`；没有新增 migration、公开状态、HTTP/BFF、CLI、常驻进程、自动调度、部署配置、生产 SQL 或 Git 操作。

| Interface | 可观察结果 | 权威限制 |
| --- | --- | --- |
| `expire_next(operator_id)` | 按到期时间和 Preparation ID 选择一个已到期 ready，原子提交 expired 与一条审计；没有候选时返回 `None` | 仅可信服务端调用；operator 受限校验；不接受 Preparation ID、调用者时间或批量大小 |
| `get_preparation(preparation_id)` | 提交后读取 durable expired；原始 POST replay 仍返回 queued 回执 | GET 保持只读，不扫描或推进时间状态 |
| `publication_audit(base_id)` | 按提交顺序读取主动或 publication-triggered expired 事件 | 复用现有审计结构；没有新增浏览器投影 |

`expire_next()` 是 one-shot 原语，不是队列深度或健康探针。PostgreSQL 的 `None` 既可能表示没有到期项，也可能表示到期行正被其他短事务锁定；调用者只能在后续受控调度轮次再次调用，不能据此宣称积压为空。

### 17.2 选择、锁与原子性

- PostgreSQL 使用 `state = 'ready' AND candidate_expires_at <= clock_timestamp()` 过滤，按 `candidate_expires_at, release_preparation_id` 排序，并以 `FOR UPDATE SKIP LOCKED LIMIT 1` 锁定一个资源。该查询复用 `0012` 的 ready expiry partial index。
- 持锁后重新读取并校验 typed resource、frozen Draft/Base Version 和完整 publishable candidate。选择、校验、`expired` 状态、`expired_at` 和唯一生命周期审计都在同一事务内；不创建或读取 queryable Release，不访问 S3、OpenSearch 或其他网络依赖。
- 主动过期和 publish 发现到期时调用同一个 adapter 内部过期原语，避免两条路径分别拼装状态和审计。审计写入或事务提交失败时，状态回滚为原 ready；候选和原始 queued 回执不被改写。
- 八个并发调用处理一个到期资源时，只有一个返回 expired，其余返回 `None`；只有一条事件。最早到期行被其他事务锁定时，本次调用跳过该行并处理下一到期项；锁释放后，后续调用可处理原行。
- 主动过期与 publish 竞争同一个已到期 ready 时，只产生一个 expired 终态和一条事件。根据锁顺序，另一调用观察 `None`、`base_preparation_expired` 或 `base_preparation_not_ready`；任何路径都不创建 Release。
- 到期候选的 frozen identity、manifest artifact 或完整 candidate 损坏时，调用返回 `base_preparation_integrity_unavailable`，事务保持原 ready 且不写事件。该资源会在后续轮次再次被选中，可能阻塞同一顺序后的资源；TDD-02G 的 cancelled 不适用于 ready，后续仍需独立 quarantine 权威，不能无审计地跳过或伪造 expired。
- 内存仓储提供相同的单资源、精确边界和回滚语义，用于快速合同测试。它没有跨连接 `SKIP LOCKED` 能力，也不是 PostgreSQL 并发证据或生产 fallback。

本片不清理 `candidate_json`、immutable artifact 或 projection generation。expired 仍保留候选绑定以支持完整性审计；孤立对象的保留、引用证明和物理回收需要独立设计，不能由状态回收推导为存储回收已经完成。

### 17.3 Given-When-Then 与失败矩阵

| 场景 | Given / When | Then | 风险 |
| --- | --- | --- | --- |
| 未到期 | 只有未到期 ready，调用 `expire_next()` | 返回 `None`；状态和审计不变 | P1 |
| 精确到期 | 内存时钟等于 `expires_at`，或 PostgreSQL 数据库时间已超过期限 | 返回一个 expired；无 Release；原 queued 回执不变 | P1 |
| 非法 actor | operator 包含控制字符 | `base_preparation_invalid_operator`；不访问仓储、不产生副作用 | P1 |
| 八路并发 | 八个独立连接处理同一到期项 | 一个 expired、七个 `None`、一条审计 | P1 |
| 锁跳过 | 最早到期行由另一事务持锁，另有到期项 | 本轮处理下一项；后续轮次处理已释放的原行 | P1 |
| 审计故障 | expired 更新后，事件插入触发数据库错误 | 整个事务回滚；资源保持 ready；无事件、无 Release | P1 |
| 候选损坏 | 到期 ready 的内部 candidate 绑定被篡改 | 完整性错误；资源保持 ready；无事件、无 Release | P1 |
| publish 竞争 | publish 与主动回收并发处理同一到期项 | 一个 expired 终态和一条事件；无 Release、无复活 | P1 |

### 17.4 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| F1 | 内存合同调用 `expire_next()` 时应用没有该方法，出现 `AttributeError` | 增加应用/端口/内存事务的单资源过期合同；精确边界、重复调用和原回执保护通过 |
| F2 | PostgreSQL transaction 没有 `expire_next()`，应用稳定包装为 `base_preparation_unavailable` | 增加数据库时间过滤、确定性排序和 `FOR UPDATE SKIP LOCKED LIMIT 1`；真实数据库主路径通过 |
| 行为保护 | 并发、锁跳过、审计失败、候选损坏、publish 竞争在最小实现后补充 | 六个 PostgreSQL 合同与一个内存合同全部通过；没有用 sleep、私有调用次数或生产数据作为断言 |
| REFACTOR | publish-triggered expiry 与主动 expiry 分别拼装相同终态 | 两个 adapter 各自收敛为一个内部过期原语；聚焦过期回归 6 passed |

### 17.5 验证结果

独立测试项目为 `proofagent-kss-expiry-tdd`，Compose 显式使用 `--env-file /dev/null`。PostgreSQL、MinIO 和 OpenSearch 使用独立本机端口；初选 MinIO 端口被其他进程占用后，仅为本测试项目改用另一个端口，没有停止或修改占用者。没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| Preparation 内存 + PostgreSQL | 133 passed，退出码 0 | 67 个内存/应用合同、66 个真实 PostgreSQL 合同 |
| Preparation + distribution | 152 个合同纳入完整回归 | 上述 133 个合同加 19 个打包合同；本轮未更改 OpenAPI 或 migration |
| 全部 KSS + ProofAgent KSS/BFF 受影响边界 | 339 passed、0 skipped，31.81 秒，退出码 0 | PostgreSQL/MinIO/OpenSearch 均 fail-if-missing；不是全仓库或 Production GO |
| KSS mypy / Ruff | 91 source files 无类型错误；All checks passed | 本轮未修改 ProofAgent 产品代码 |
| 受影响文件格式 | 6 files already formatted | 4 个产品文件和 2 个合同测试文件 |
| domain-context / diff / lock | 检查通过；根项目 117 packages | 未改依赖或锁文件；第一次受沙箱缓存限制，获准后重试通过 |

`openapi.sha256`、`migrations.sha256` 和 head revision 仍由第 16 节记录的 distribution 合同保护。本片没有更改 OpenAPI、migration registry 或 `0012`，因此不生成新的 schema/migration 指纹，也没有迁移批准可继承。

测试结束后，仅对 `proofagent-kss-expiry-tdd` 执行 `down --volumes`。临时 PostgreSQL、MinIO、OpenSearch 容器与网络已删除，随后 `ps --all` 返回空清单。测试数据可由 fixtures 重建，没有保留恢复快照；既有 production-local 和占用初选 MinIO 端口的其他服务均未被操作。

### 17.6 文件、边界与下一片

- 更新 Preparation application/port、内存与 PostgreSQL adapter，并扩展内存和真实 PostgreSQL 合同；没有新增产品模块或 migration。
- 更新本报告、Scope、Feature context、本地指南、项目索引、开发进度和知识证据领域说明。
- 没有修改 `bootstrap/processes.py`、部署配置、ProofAgent BFF/Dashboard、角色映射或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] 后续若增加自动调度，需要单独定义进程所有者、轮询/退避、批次上限、健康与积压信号、关闭语义和部署配置；不能用循环调用本 Interface 的局部测试替代运行责任设计。TDD-02G 后续只补 application-only queued/running cancellation，见第 18 节。Reference Ledger、publish/expiry/cancel HTTP/BFF、正式 Agent candidate binding、Phase F、online smoke、生产迁移/回滚仍属于后续独立范围；Feature 保持 `PARTIAL_VERIFICATION`。

## 18. TDD-02G：queued/running 协作取消核心

### 18.1 授权、Interface 与范围

[FRAME | HIGH] 2026-08-28 用户确认精确契约后进入本片。公开应用 Interface 为 `KnowledgeBasePreparationApplication.cancel(preparation_id, operator_id, idempotency_key)`；仅 queued/running 可变为 cancelled。状态、operator-scoped 幂等收据和成功审计在一个本地事务提交。没有自由文本原因、ready quarantine、artifact 删除、自动重试、HTTP/BFF/Dashboard/CLI、常驻进程、部署配置、生产 SQL 或 Git 操作。

| Interface | 可观察结果 | 权威限制 |
| --- | --- | --- |
| `cancel(preparation_id, operator_id, idempotency_key)` | queued/running 原子变为 cancelled；相同命令精确重放 | 仅可信服务端调用；不接受调用者时间、reason 或 lease/fence 参数 |
| `get_preparation(preparation_id)` | 读取 durable cancelled identity 与数据库 `cancelled_at` | 不暴露 worker、fence、lease、candidate、artifact 或取消命令 capability |
| `audit(base_id)` | 既有成功审计序列新增一条 cancel，包含 operator、exact Preparation/Base/Draft identity 与数据库时间 | receipt 即 append-only success audit；失败命令不伪造成功事件 |

ready、failed、expired、consumed 和 cancelled 返回 `base_preparation_not_cancellable`。失败重试通过新的 start Idempotency-Key 产生新 Preparation identity；不能把终态改回 queued/running。异常 ready 不属于 cancellation：它必须保留原候选和失败关闭状态，后续 quarantine 需要独立原因、修复、解阻和审计权威。

### 18.2 状态、幂等、锁与 fencing

- 新增 `0013_preparation_cancellations.sql`，不改写 `0009` 至 `0012`。它增加 `cancelled_at`、cancelled 状态/lease/terminal JSON 约束，并扩展现有 `knowledge_base_preparation_commands` action/result 约束。Migration head 与 canonical contract 同步前进。
- PostgreSQL 先按 exact identity `FOR UPDATE` 锁定资源，再读取并验证 frozen Draft/Base Version，使用 `clock_timestamp()` 产生 `cancelled_at`。queued 保持 fence 0；running 保留现有 monotonic fence，但 owner/deadline 清空。状态更新和 cancel receipt/audit 由 caller-owned repository transaction 一次提交。
- 同 operator、key、action 和 exact Preparation fingerprint 的并发重放由现有 advisory transaction lock 串行化，八个调用返回同一 cancelled 结果且只有一条 cancel 审计。相同 key 改绑另一 identity 返回 `base_preparation_idempotency_conflict`。
- queued claim 与 cancel 竞争同一行时按锁顺序线性化：cancel 先提交则 claim 跳过；claim 先提交则 cancel 接受 running。最终只有 cancelled 可继续读取，任何已返回 claim 随后 renew/complete/fail 都变为 stale。
- running Builder 在数据库事务外执行，因此 cancellation 不保证强杀外部 I/O。取消先提交后，Builder 可以结束计算或留下孤立 immutable artifact，但最终 fenced transaction 返回 `base_preparation_stale_claim`，不能写 ready/failed、Release 或终态 Worker 事件。
- receipt/audit 插入或 commit 失败会回滚 cancelled 状态和 lease 清理。测试注入的内部异常文本被稳定映射为 `base_preparation_storage_unavailable`，不进入公开错误。
- 管理 GET 的 union 增加 secret-free `CancelledReleasePreparation`；没有 `POST :cancel` 路由，合同测试固定为 405。原始 start POST replay 继续返回 immutable queued admission receipt，而 GET 返回当前 cancelled 状态。

### 18.3 Given-When-Then 与失败矩阵

| 场景 | Given / When | Then | 风险 |
| --- | --- | --- | --- |
| queued 取消 | durable queued + trusted operator/key | cancelled、数据库时间、receipt/audit 同事务；原 start receipt 不变 | P1 |
| running 取消 | active owner/fence/deadline | cancelled；清 owner/deadline、保留 fence；旧 claim stale | P1 |
| exact replay | 八路相同 operator/key/fingerprint | 八个相同结果、一条 cancel 审计 | P1 |
| key 改绑 | 相同 key 指向另一 Preparation | idempotency conflict；第二资源不变 | P1 |
| terminal 重复 | ready/failed/cancelled/expired/consumed | not cancellable；状态与成功审计不变 | P1 |
| claim 竞争 | queued claim 与 cancel 并发 | 一个 cancelled 终态；已返回 claim 不能续租或提交 | P1 |
| 在途构建 | Worker 已 claim 并在事务外构建，随后 cancel | 构建可结束但结果提交 stale；无 ready/failed/Release | P1 |
| 审计故障 | state update 后 command receipt insert 失败 | 整体回滚为原 queued，仍可正常 claim | P1 |
| 历史升级 | `0012` active running 与 start receipt | `0013` 应用/重放后可取消；旧 receipt 可读，旧 claim stale | P1 |
| 只读管理投影 | application 取消后 GET，尝试 `:cancel` | GET secret-free cancelled；网络命令保持 405 | P1 |

### 18.4 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| G1 | 内存 tracer 调用 `cancel()` 出现 `AttributeError` | 增加 Cancelled contract、应用 Interface、事务端口、纯状态转换及内存 adapter；queued/current GET/原 receipt/审计通过 |
| G2 | 真实 PostgreSQL 调用被稳定包装为 `base_preparation_unavailable` | 增加 `0013`、行锁/database-time transition、cancel receipt replay 和 PG resource/audit hydration |
| G3 | canonical OpenAPI 仍绑定旧 hash，migration contract head 仍期望 `0012` | 增加 secret-free cancelled schema，更新 exact OpenAPI/migration fingerprints 与 `0013` head |
| 行为保护 | replay/conflict、五个 terminal state、非法输入、八路并发、claim race、在途 build、audit rollback、历史升级、HTTP 405 | 新增 18 个参数化后计数的行为合同全部通过；没有 sleep、生产数据或内部调用次数断言 |
| REFACTOR | 新 union 与测试不符合标准格式 | 机械格式化 3 个文件后完整 Preparation/PG/distribution 170 tests 再次通过 |

### 18.5 验证结果与候选指纹

独立测试项目为 `proofagent-kss-cancel-tdd`，Compose 显式使用 `--env-file /dev/null`。Docker daemon 初始未运行，启动本机测试运行时后仅创建本项目。PostgreSQL、MinIO、OpenSearch 使用独立端口；`minio-init` 以 0 正常退出导致组合 `up --wait` 返回非零，随后 `ps --all` 明确证明 PostgreSQL/MinIO/OpenSearch healthy、init exited 0，未把该进度结果当作测试通过。没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| Preparation + PostgreSQL + distribution | 170 passed，24.09 秒，退出码 0 | 78 个内存/应用合同、73 个真实 PostgreSQL/HTTP 合同、19 个打包合同 |
| 全部 KSS + ProofAgent KSS/BFF 受影响边界 | 357 passed、0 skipped，39.78 秒，退出码 0 | PostgreSQL/MinIO/OpenSearch 均 fail-if-missing；不是全仓库或 Production GO |
| KSS mypy / Ruff | 91 source files 无类型错误；All checks passed | 本轮未修改 ProofAgent 产品代码 |
| 全仓库后端回归 | 主套件 2346 passed、24 个声明 skip、2 deselected；另行执行默认排除的 hybrid integration 为 2 passed | 合计 2348 个后端通过结果；真实 LLM opt-in 和 ADR-0210 已删除旧能力的 fixtures 仍按声明跳过 |
| 全仓库静态与前端 | mypy 448 source files、Ruff、typecheck、Dashboard 225 tests、Chat 35 tests、UI/Dashboard/Chat build 全部通过 | Authlib 弃用警告和 Chat 600.22 kB chunk 警告为既有非阻塞观察，不是 Production GO |
| 格式 / domain-context / diff / locks | 10 个受影响 Python 文件格式检查、domain-context、`git diff --check` 通过；根项目 117 packages、KSS distribution 34 packages lock check 通过 | 两个 lock check 首次受沙箱缓存权限限制，按批准重试后通过 |

```text
openapi.sha256=d8925dca3909a24534e19720b1614e21cc2665b8c68c8566c9da0ae30fa74e9c
migrations.sha256=c7964655e256ecd4d0de3045122f2d34cb001e00e94479fd18ddc298d796d5d8
head_revision=0013_preparation_cancellations
```

这些指纹只绑定当前本地候选。没有生产 migration、部署、Release、合并或 Production GO 可从旧候选或本轮测试继承。

全仓库 PostgreSQL 回归首次错误使用 `postgresql://` DSN，SQLAlchemy 因而选择未安装的 `psycopg2`，产生 72 个 fixture setup errors；没有业务测试失败。改为仓库约定的 `postgresql+psycopg://` 后，同一主套件得到上述 2346 passed 和退出码 0。该次属于测试环境参数修正，不是业务 RED，也没有通过安装额外 driver 或降低 fail-if-missing 规避失败。

验证结束后，仅对 `proofagent-kss-cancel-tdd` 执行 `down --volumes`；临时 PostgreSQL、MinIO、OpenSearch 容器与网络已删除，随后 `ps --all` 返回空清单。测试数据可由 fixtures 重建，没有保留恢复快照；其他 Compose 项目和 production-local 数据均未操作。

### 18.6 文件、边界与下一片

- 新增 `migrations/0013_preparation_cancellations.sql`；扩展 Preparation contracts/domain/application/port、内存与 PostgreSQL adapter、migration registry、核心/PG/HTTP/distribution 合同。
- 更新本报告、Scope、Feature context、本地指南、项目索引、开发进度和知识证据领域说明。
- 没有修改 `bootstrap/processes.py`、ProofAgent BFF/Dashboard、角色映射、部署配置或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] TDD-02G 完成的是深 application module：调用者只学习一个 cancel Interface，锁、数据库时间、receipt/audit、lease 清理和 fencing 留在事务实现内。下一片不应把 ready corruption 混入 cancelled；优先级应在产品 HTTP/BFF 接线、受控 Worker/reaper 运行责任、异常 ready quarantine 或 TDD-03 Reference Ledger 之间重新确认。Feature 保持 `PARTIAL_VERIFICATION`。

## 19. TDD-03A：exact Release Reference 注册核心

### 19.1 模式、接口与范围

[FRAME | HIGH] 用户确认进入 TDD-03 后，本片只交付 registration tracer，不将整个 Release lifecycle 合并进一个大切片。公开可信应用 Interface 为：

```python
application.register(
    request,
    authenticated_client_id="proof-agent",
    idempotency_key="publish-agent-version-001",
)
```

`request` 只接受 exact `knowledge_space_id`、`knowledge_base_id`、`knowledge_base_release_id`、`published_agent_version`、immutable external resource ID 和 `execution_or_rollback`。客户端认证仍是未来 delivery 责任；本片没有网络入口、浏览器 token、Agent configuration、secret、reason 或调用者时间。

| Interface | 可观察行为 | 隐藏实现 |
| --- | --- | --- |
| `register()` | 返回一个 secret-free active Reference；相同 client/key/fingerprint 返回原结果 | Release 行锁、advisory key lock、fingerprint、数据库时间、SQL/receipt/audit |
| `get(reference_id)` | 重建后读取同一不可变 Reference | JSON/列完整性校验 |
| `audit(release_id)` | 返回有序成功注册事件 | command receipt 同时承担 append-only success audit |

范围外：deprecate/retire/revoke、删除资格、deregister/reconciler、HTTP/BFF/Dashboard/CLI、ProofAgent formal publisher/activation、角色接线、部署、生产迁移和 Git 操作。

### 19.2 Given-When-Then 与高风险断言

| 场景 | Given / When | Then |
| --- | --- | --- |
| 主路径 | queryable exact Release；认证 client 注册 immutable Agent Version | active Reference、receipt、成功审计使用同一数据库时间原子提交；重建可读 |
| exact replay | 相同 client/key/fingerprint 重放或八路并发 | 返回同一 Reference；只有一条成功审计 |
| key 改绑 | 相同 client/key 指向另一 external resource | `release_reference_idempotency_conflict`；无第二引用/审计 |
| resource 改绑 | 同一 client/kind/resource 使用新 key 指向另一 Release | `release_reference_external_resource_conflict`；原引用不变 |
| Release admission | missing、retired 或 Space/Base tuple 不匹配 | 稳定失败关闭；无引用、receipt 或成功审计 |
| audit 故障 | reference insert 后 command/audit insert 被故障注入拒绝 | 整体回滚；移除故障后同一命令可正常注册 |
| 历史升级 | `0013` 已有 queryable Release | `0014` 升级与重复 migration application 后仍可注册并重建 |

### 19.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | 内存 tracer 收集失败：`ModuleNotFoundError: ...adapters.memory.release_references` | 增加 strict contracts、domain command/receipt、深 application Interface、事务 port 与 test-only memory adapter；主路径 `1 passed` |
| R2 | PostgreSQL tracer 收集失败：`ModuleNotFoundError: ...adapters.postgres.release_references` | 增加 `0014`、Release 行锁、client/key advisory lock、数据库时间、durable reference/receipt/audit 与完整性重建 |
| R3 | 首次 PG GREEN 运行在 `dict_row` 下按位置读取数据库时间，出现 `KeyError: 0` | 使用命名列读取 `clock_timestamp()`；真实 PG tracer `1 passed` |
| R4 | migration distribution 仍期望 `0013_preparation_cancellations` 与旧 hash | 将 canonical head 绑定到 `0014_release_references`，锁定新 migration fingerprint |
| 行为保护 | replay/conflict、跨 client scope、missing/scope、retired、八路并发、audit rollback、升级重放 | memory 5、真实 PG 5；无 sleep、生产数据、内部调用次数或客户端时间断言 |
| REFACTOR | Ruff format 与 Mypy 暴露 6 个格式文件和一个可能为 `None` 的数据库 row | 收敛命名读取和类型检查；本片 9 个文件格式、Ruff、Mypy 后再次执行合同回归 |

### 19.4 验证结果与候选指纹

独立测试项目为 `proofagent-kss-reference-tdd`，显式端口为 PostgreSQL `55453`、MinIO `59033`、OpenSearch `19223`。Compose `minio-init` 以 0 正常退出使 `up --wait` 返回非零；随后 `ps --all` 证明三个长期依赖均 healthy，未将该进度结果当作测试通过。没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| 新增 memory / PostgreSQL contracts | 5 passed / 5 passed | 包含 8 路同键并发、retired、audit rollback、`0013 → 0014` |
| KSS contracts | 337 passed | PostgreSQL/MinIO/OpenSearch 全部 fail-if-missing |
| ProofAgent KSS/BFF 相关合同 | 38 passed | 受影响合计 375 passed、0 skipped |
| 全仓后端 | 主套件 2356 passed、24 个声明 skip、2 deselected；显式 hybrid integration 2 passed | 合计 2358 个通过结果；不是生产运行或 Release Gate |
| Mypy / Ruff | 454 source files 无类型错误；全量 Ruff 通过 | 本片没有 ProofAgent 产品代码或前端代码变化 |
| 格式 / domain-context / diff / locks | 本片 9 个 Python 文件格式、domain-context、`git diff --check` 通过；根项目 117 packages、KSS distribution 34 packages lock check 通过 | 全 KSS format check 另显示 24 个既有非本片文件会被当前 formatter 重排，未机械改写 |
| 前端 | 未重复执行 | 本片无 OpenAPI、BFF、Dashboard、Chat 或 TypeScript 变化；上一切片整体前端证据不转化为本片生产批准 |

```text
openapi.sha256=d8925dca3909a24534e19720b1614e21cc2665b8c68c8566c9da0ae30fa74e9c
migrations.sha256=04bfa8b1af486976c19e13946c5aa10b12850999d493e0a808f9e891d93f7d44
head_revision=0014_release_references
```

OpenAPI 指纹未变，证明本片没有新增 Reference 网络命令。Migration 指纹只绑定当前本地候选，不继承任何生产 migration、部署、发布、合并或 Production GO 批准。全仓主回归使用仓库约定 `postgresql+psycopg://` DSN；显式 hybrid 首次因未设置 ProofAgent S3 变量而声明 skip，补齐同一隔离 MinIO endpoint/bucket 后得到 2 passed，没有降低 fail-if-missing。

验证结束后，仅对 `proofagent-kss-reference-tdd` 执行 `down --volumes`。临时 PostgreSQL、MinIO、OpenSearch 容器和网络已删除；随后 `ps --all` 返回空清单。测试数据可由 fixture 重建，未保留恢复快照；其他 Compose 项目和 production-local 环境未操作。

### 19.5 文件、边界与下一片

- 新增 Reference contracts/domain/application/port、内存/PostgreSQL adapter、`0014_release_references.sql` 及 memory/PG 合同；migration distribution 绑定新 head/hash。
- 新增 `release-reference-local-guide.md`；同步 Scope、Feature context、本报告、领域上下文、项目索引与开发进度。
- 没有修改 KSS/ProofAgent HTTP 或 runtime composition、ProofAgent formal publisher、Agent activation、角色映射、部署配置或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] TDD-03A 只证明 durable registration。下一片建议为 TDD-03B Release deprecation：在同一 Release 行锁权威中实现 `queryable → deprecated`，阻止新 Reference registration 而保留既有引用与 query；普通 retirement、emergency revocation 和 reconciler 继续分片。Feature 保持 `PARTIAL_VERIFICATION`。

## 20. TDD-03B：Release deprecation 核心

### 20.1 模式、接口与范围

[FRAME | HIGH] 本片只交付可信 application-only deprecation，不把普通退役、紧急撤销或网络权限混入同一状态转换。公开可信应用 Interface 为：

```python
lifecycle_application.deprecate(
    request,
    operator_id="knowledge-operator",
    idempotency_key="deprecate-release-001",
)
```

`request` 只接受 exact Space/Base/Release tuple。操作员身份必须由未来 delivery 完成认证与授权；请求不接受 reason、调用者时间、Reference count、retention 结论、secret 或替代 Release。

| Interface | 可观察行为 | 隐藏实现 |
| --- | --- | --- |
| `deprecate()` | 仅 `queryable → deprecated`；相同 operator/key/fingerprint 返回原结果 | operator/key advisory lock、Release 行锁、数据库时间、状态/receipt/audit 单事务 |
| `audit(release_id)` | 返回有序、secret-free 成功弃用事件 | lifecycle command row 同时承担永久 receipt 与 success audit |
| 既有读取 | Catalog query、完整性扫描、既有 Query Grant 与 active Reference 继续有效 | `deprecated` 属于可查询能力，但不再属于可采用能力 |

范围外：retire、emergency revoke、物理删除资格、deregister/reconciler、HTTP/BFF/Dashboard/CLI、ProofAgent formal publisher/activation、角色接线、部署、生产迁移和 Git 操作。

### 20.2 Given-When-Then 与高风险断言

| 场景 | Given / When | Then |
| --- | --- | --- |
| 主路径 | exact queryable Release；可信 operator 弃用 | 状态、数据库时间、receipt 与成功审计原子提交；重建后状态为 deprecated |
| 既有运行 | Release 已有 active Reference 和 Query Grant | Reference 不变；Catalog query、完整性扫描与原 Grant authorization 继续有效 |
| 新采用 | 弃用提交后注册新 Reference 或创建新 Query Grant | 稳定失败关闭；不产生新采用事实 |
| exact replay | 相同 operator/key/fingerprint 重放或八路并发 | 返回同一 deprecated 结果；只有一条成功审计 |
| 非法重放/状态 | key 改绑，或目标 missing、scope mismatch、deprecated、retired | 稳定领域错误；无第二状态转换或审计 |
| registration race | registration 与 deprecation 同时竞争 | 共用 Release 行锁；registration 要么先提交并被保留，要么在 deprecation 后被拒绝 |
| audit 故障 | 状态更新后 command/audit insert 被故障注入拒绝 | 状态与 receipt 整体回滚；Release 仍 queryable 且可注册 |
| 历史升级 | `0014` 已有 Release 与 active Reference | `0015` 升级和重复 migration application 后 Reference 不变且可精确弃用 |

### 20.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | 内存合同收集失败：无法导入 `KnowledgeBaseReleaseLifecycleApplication` | 增加 strict deprecation contracts、domain command/receipt、application Interface、事务 port，并在现有 memory authority 锁域中实现最小状态门控 |
| R2 | migration contract 仍返回 `0014_release_references` | 增加 `0015_release_deprecation.sql`，扩展 Catalog 状态约束并绑定 canonical migration fingerprint |
| R3 | PostgreSQL tracer 首次执行 | 在现有 Release row authority 上增加 operator/key replay、database-time update 与 lifecycle receipt/audit；主路径直接转绿 |
| 行为保护 | missing/scope/non-queryable、八路并发、registration race、audit rollback、既有 Query、升级回放 | memory 7；Release PG 10；Access PG 1；没有 sleep、生产数据、调用者时间或内部调用次数断言 |
| REFACTOR | Catalog 与 authorization 中存在不同语义的 `queryable` 判定 | 明确区分“可查询”和“可采用”：Catalog/既有 Grant 接受 deprecated；Release publication reuse、新 Grant 与新 Reference 仍只接受 queryable |

### 20.4 验证结果与候选指纹

独立测试项目为 `proofagent-kss-deprecation-tdd`，显式端口为 PostgreSQL `55454`、MinIO `59034`、OpenSearch `19224`。Compose `minio-init` 以 0 正常退出使 `up --wait` 返回非零；`ps --all` 随后证明三个长期依赖均 healthy。没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| TDD-03B 聚焦合同 | 37 passed | memory、Release PG、Access PG 与 distribution；含 8 路并发、race、rollback、`0014 → 0015` |
| KSS contracts | 344 passed | PostgreSQL/MinIO/OpenSearch 全部 fail-if-missing |
| ProofAgent KSS/BFF 相关合同 | 44 passed | 受影响合计 388 passed、0 skipped |
| 全仓后端 | 主套件 2363 passed、24 个声明 skip、2 deselected；显式 hybrid integration 2 passed | 合计 2365 个通过结果；不是生产运行或 Release Gate |
| Mypy / Ruff | 454 source files 无类型错误；全量 Ruff 通过 | 包含 KSS lifecycle、Catalog 与 Access Control 变更 |
| 前端 | typecheck、Dashboard 225 tests、Chat 35 tests、UI/Dashboard/Chat build 全部通过 | OpenAPI 仅扩展只读 Release summary enum；没有 lifecycle 命令 UI |
| domain / diff / locks | domain-context、`git diff --check` 通过；根项目 117 packages、KSS distribution 34 packages lock check 通过 | lock check 在受限沙箱内触发 uv system-configuration panic，按批准在沙箱外只读重试通过 |

```text
openapi.sha256=cbce49b2fcfc13615d224d84c4c14a430a4a3c709422bdc6453401ce817b9124
migrations.sha256=aff6840c278de46b34619608a30c7bff3a90d0ca473555e8969706d113fed2ff
head_revision=0015_release_deprecation
```

OpenAPI 指纹变化只来自只读 Release summary 增加 `deprecated`，不存在 deprecate 网络命令。Migration 与 OpenAPI 指纹只绑定当前本地候选，不继承生产 migration、部署、发布、合并或 Production GO 批准。

### 20.5 文件、边界与下一片

- 扩展 Release Reference contracts/domain/application/ports 与 memory/PostgreSQL authority；新增 `0015_release_deprecation.sql`。
- 更新 Catalog query/integrity visibility、既有 Query authorization 与管理只读 summary enum；新采用门保持 fail-closed。
- 同步 Scope、Feature context、本报告、领域上下文、项目索引、开发进度与本地调用指南。
- 没有新增 lifecycle HTTP/BFF、ProofAgent formal publisher、Agent activation、角色映射、部署配置或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] TDD-03B 只证明 deprecation。下一片建议先冻结 TDD-03C ordinary retirement admission：明确 retention authority，并验证只有 deprecated、零 authoritative active references 且满足 retention 的 Release 才能进入 retired；deregister/reconciler 与 emergency revoke 继续分别建模，避免由调用者自报引用数或把紧急止损混入普通清理。Feature 保持 `PARTIAL_VERIFICATION`。

## 21. TDD-03C：ordinary Release retirement admission 核心

### 21.1 模式、接口与范围

[FRAME | HIGH] 本片在既有 lifecycle application 增加普通退役，不把紧急撤销、Reference 对账或物理删除并入同一命令。可信应用 Interface 为：

```python
lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
    repository=repository,
    retention_policy=ReleaseRetentionPolicy(
        policy_id="release-retention-30d",
        minimum_age=timedelta(days=30),
    ),
)
lifecycle_application.retire(
    request,
    operator_id="knowledge-operator",
    idempotency_key="retire-release-001",
)
```

`request` 只接受 exact Space/Base/Release tuple。Retention policy 是服务端构造时注入的不可变配置；调用者不能报告 Reference 数、当前时间、保留截止时间或 eligibility。公开结果只包含 secret-free Release identity、policy ID、`deprecated_at`、`retention_eligible_at` 和数据库 `retired_at`。

| Interface | 可观察行为 | 隐藏实现 |
| --- | --- | --- |
| `retire()` | 仅 eligible `deprecated → retired`；相同 operator/key/fingerprint 返回原结果 | Release 行锁、active Reference 检查、数据库时间、服务端 policy、状态/receipt/audit 单事务 |
| `audit(release_id)` | deprecation 与 retirement 按共享 sequence 有序返回 | 两类 command row 是永久 receipt 与 success audit |
| 既有读取 | retired 不可 Catalog query、不进入完整性扫描、既有 Query authorization 失败关闭 | Catalog summary 仍可显示 retired lifecycle state |

范围外：deregister/reconciler、emergency revoke、物理删除或删除资格、HTTP/BFF/Dashboard/CLI、ProofAgent formal publisher/activation、角色接线、生产 retention 配置、部署、生产迁移和 Git 操作。

### 21.2 Given-When-Then 与高风险断言

| 场景 | Given / When | Then |
| --- | --- | --- |
| 主路径 | exact deprecated Release、零 active Reference、数据库时间到达 policy boundary | retired、policy/eligibility/database time、receipt 和审计原子提交；重建后不可查询 |
| active Reference | Ledger 仍有 active `published_agent_version` | `release_lifecycle_references_present`；状态、Reference 和审计不变 |
| retention pending | 数据库时间比 exact boundary 早 1 微秒 | `release_lifecycle_retention_pending`；无 retirement receipt/audit |
| policy authority | 未注入或 policy ID/时长无效 | 稳定失败关闭；请求 schema 不接受调用者 policy/time/count |
| exact replay | 相同 operator/key/fingerprint 重放或八路并发 | 返回同一 retired 结果；只有一条 retirement 成功审计 |
| key 改绑/非法状态 | 相同 key 改 exact tuple，或目标不是有效 deprecated | 稳定领域错误；无第二转换 |
| audit 故障 | Release update 后 retirement command insert 被故障注入拒绝 | 状态与 receipt 整体回滚；移除故障后同一命令可成功 |
| 历史升级 | `0015` 已有 deprecated Release | `0016` 升级和 migration 重放保留 `deprecated_at`，随后可按 policy 退役 |

### 21.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | 内存合同收集失败：无法导入 `RetireKnowledgeBaseReleaseRequest` | 增加 strict retirement contracts、server-owned retention policy、application gate、事务 port 与 test-only memory behavior；首个主路径转绿 |
| R2 | migration distribution 仍期望 `0015_release_deprecation` | 新增 `0016_release_retirement.sql`，保留历史 retired 兼容状态并绑定 canonical migration fingerprint |
| R3 | PostgreSQL adapter 只有 deprecation receipt/audit 和 `deprecated_at` | 增加 active Reference 检查、`retired_at`、共享有序 lifecycle audit、exact replay 与 atomic retirement persist；真实 PG 主路径直接通过 |
| 行为保护 | Reference blocker、boundary、无效 policy、八路并发、key conflict、Query denial、audit rollback、`0015 → 0016` | memory 11、Release PG 16、Access PG 1、distribution 20；合计 48 passed |
| REFACTOR | 生命周期结果和审计需要同时支持 deprecated/retired | 保持一个深 application Interface，在 repository 内隐藏分表与共享 sequence；目标文件格式、Ruff、Mypy 后复验 |

### 21.4 验证结果与候选指纹

独立测试项目为 `proofagent-kss-retirement-tdd`，显式端口为 PostgreSQL `55455`、MinIO `59035`、OpenSearch `19225`。Compose `minio-init` 以 0 正常退出使 `up --wait` 返回非零；`ps --all` 随后证明三个长期依赖均 healthy。没有读取 `.env`、生产配置、凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| TDD-03C 聚焦合同 | 48 passed | memory、Release PG、Access PG 与 distribution；含 8 路并发、rollback、`0015 → 0016` |
| KSS contracts | 355 passed | PostgreSQL/MinIO/OpenSearch 全部 fail-if-missing |
| ProofAgent KSS/BFF 相关合同 | 44 passed | 受影响合计 399 passed、0 skipped |
| 全仓后端 | 主套件 2374 passed、24 个声明 skip、2 deselected；显式 hybrid integration 2 passed | 合计 2376 个通过结果；不是生产运行或 Release Gate |
| Mypy / Ruff | 454 product source files 无类型错误；全量 Ruff 通过 | `mypy .` 额外扫描非基线脚本/fixtures，因既有第三方 stub 与重复模块失败；按仓库产品入口复验通过 |
| 格式 / domain / diff / locks | 11 个受影响 Python 文件格式、domain-context、`git diff --check` 通过；根项目 117 packages、KSS distribution 34 packages lock check 通过 | 两个 lock check 首次受沙箱 uv cache 权限限制，获准只读重试后通过 |
| 前端 | 未重复执行 | OpenAPI、BFF、Dashboard、Chat 和 TypeScript 均未变化；上一切片证据不转化为本片生产批准 |

```text
openapi.sha256=cbce49b2fcfc13615d224d84c4c14a430a4a3c709422bdc6453401ce817b9124
migrations.sha256=bd6f475e2cf74a18f91291ec4b68759091ff31b55ce50a5e51ffef9858bfae7d
head_revision=0016_release_retirement
```

OpenAPI 指纹未变，证明本片没有新增 lifecycle 网络命令。Migration 指纹只绑定当前本地候选，不继承生产 migration、部署、发布、合并或 Production GO 批准。显式 hybrid 首次因只设置 ProofAgent S3 定位变量、未设置 `S3ArtifactStore` 使用的标准 AWS 测试凭据而 2 failed；补齐同一隔离 MinIO 的测试变量后原命令 2 passed，没有修改代码或放宽断言。

验证结束后，仅对 `proofagent-kss-retirement-tdd` 执行 `down --volumes`。临时 PostgreSQL、MinIO、OpenSearch 容器和网络已删除；随后 `ps --all` 返回空清单。测试数据可由 fixture 重建，未保留恢复快照；其他 Compose 项目和 production-local 环境未操作。

### 21.5 文件、边界与下一片

- 扩展 Release Reference contracts/domain/application/ports 与 memory/PostgreSQL authority；新增 `0016_release_retirement.sql`。
- 保持 lifecycle application 为单一可信入口，在持久化实现内隐藏 deprecation/retirement receipt 分表和共享 audit sequence。
- 更新 retired 的 Catalog/integrity/既有 Query fail-closed 合同，以及 Scope、Feature context、本报告、领域上下文、项目索引、开发进度和本地调用指南。
- 没有新增 lifecycle HTTP/BFF、Reference deregistration、emergency revoke、ProofAgent formal publisher/activation、生产 retention 配置、部署配置或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] TDD-03C 只证明零 active Reference 的普通退役准入。已有 active Reference 的 Release 在缺少可信 deregistration/reconciliation 时会永久保守阻断，这是设计行为。下一片建议优先冻结 TDD-03D Reference deregistration/reconciliation admission：必须由认证客户端或服务端 verifier 证明 immutable external resource 已不可执行且不再保留为回滚目标，不能由调用者仅自报“无引用”。Emergency revocation 继续作为独立安全切片。Feature 保持 `PARTIAL_VERIFICATION`。

## 22. TDD-03D：Release Reference deregistration admission 核心

### 22.1 模式、接口与范围

[FRAME | HIGH] 本片只实现 Reference 注销准入，不把真实 ProofAgent 证明签发、后台 orphan 扫描、紧急撤销或网络命令混入同一个切片。可信 application Interface 为：

```python
reference_application = KnowledgeBaseReleaseReferenceApplication(
    repository=repository,
    deregistration_verifier=trusted_external_resource_retirement_verifier,
)
reference_application.deregister(
    DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id="release-reference-exact",
    ),
    authenticated_client_id="proof-agent",
    idempotency_key="deregister-agent-version-001",
)
```

请求只接受 exact Reference ID。`authenticated_client_id` 来自可信 delivery 身份；调用者不能提交 external resource 状态、回滚资格、证明时间、Reference 数量或 TTL。服务端注入 verifier 只能在确认 immutable external resource 永久失去执行资格且不再保留为回滚目标时返回 trace-safe verifier/verification identity。

外部验证不占用 PostgreSQL 事务。验证完成后，KSS 再次检查 client-scoped 永久 receipt、锁定 exact Reference、复核 owner/current state/verification identity，并使用数据库时间原子提交 `deregistered` current state、receipt 和成功审计。历史 registration receipt 保持原始 active admission 事实；同一 immutable external resource 不因注销而可被重新绑定。

范围外：ProofAgent verifier adapter、证明签发与储存、后台 reconciler/scheduler、Reference/lifecycle HTTP/BFF/Dashboard/CLI、emergency revocation、物理删除、ProofAgent formal publisher/activation、生产配置、部署、生产迁移和 Git 操作。

### 22.2 Given-When-Then 与高风险断言

| 场景 | Given / When | Then |
| --- | --- | --- |
| 主路径 | owning client、active exact Reference、匹配的 permanent-ineligibility verification | current state 变为 `deregistered`；proof identity、数据库时间、receipt、审计原子提交；普通退役不再被该 Reference 阻断 |
| 调用方越权 | 其他 authenticated client 请求注销 | `release_reference_not_owned`；verifier 不获得授权，状态与审计不变 |
| 证明缺失或错配 | verifier 未注入、返回空、invalid ID 或另一 Reference identity | 稳定失败关闭；active Reference 保留 |
| exact replay | 相同 client/key/fingerprint 顺序重放或八路并发 | 返回同一结果；精确重放无需再次依赖 verifier；只有一条注销审计 |
| 重复/改绑 | 不同 key 注销已注销 Reference，或相同 key 改另一 Reference | 前者不可注销，后者幂等冲突；无第二状态转换 |
| registration history | current Reference 已注销后重放原注册命令 | 返回原 active registration receipt；current GET 仍为 deregistered |
| deregister/retire race | deprecated Release 上同时注销与普通退役 | 退役只可能在观察到零 active Reference 后成功；否则保守拒绝并可在注销提交后重试 |
| audit 故障 | Reference update 后 command/audit insert 被故障注入拒绝 | current state 与 receipt 整体回滚；同一命令移除故障后可成功 |
| 历史升级 | `0016` 已有 active Reference | `0017` 升级与 migration replay 保留 Reference，随后可经可信验证注销 |

### 22.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | 内存 tracer 收集失败：无法导入 `DeregisterKnowledgeBaseReleaseReferenceRequest` | 增加 strict request/result/audit contracts、permanent-retirement verification fact、verifier port、application gate 与 memory authority；可信注销解除 retirement blocker 的主路径转绿 |
| R2 | PostgreSQL 同键八路测试中，一次请求在首轮未见 receipt、验证期间另一请求已提交，随后把 deregistered current state 错判为普通重复注销 | 观察到非 active current state 时再次检查永久 receipt；同 key 返回原结果，不同 key 继续 `release_reference_not_deregisterable` |
| 持久化 | `0017` 扩展 Reference lifecycle 和共用 command ledger | current state 保存 verifier/verification identity 与数据库时间；registration/deregistration 共享 client/key 幂等命名空间和 event sequence |
| 行为保护 | owner、proof mismatch、历史 registration replay、八路同键、不同键竞争、deregister/retire race、rollback、`0016 → 0017` | memory 15、Release PG 23、Access PG 1、distribution 19；合计 58 passed |
| REFACTOR | historical receipt 与 current Reference 不能再用整对象相等判断 | 提取 immutable Reference identity 比较；注册重放允许 current state 已合法演进，注销重放要求 current exact result 一致 |

### 22.4 验证结果与候选指纹

独立测试项目为 `proofagent-kss-deregistration-tdd`，显式端口为 PostgreSQL `55465`、MinIO `59045`、OpenSearch `19235`。没有读取 `.env`、生产配置、生产凭据、生产数据或生产日志。PostgreSQL fixture 使用随机 schema，KSS S3 fixture 使用随机 versioned bucket；显式 hybrid 使用仓库测试 bucket 和测试身份。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| TDD-03D 聚焦合同 | 58 passed | memory、Release PG、Access PG、distribution；含同键八路、不同键竞争、deregister/retire race、rollback、`0016 → 0017` |
| KSS + ProofAgent KSS/BFF 受影响回归 | 395 passed、0 skipped | PostgreSQL/MinIO/OpenSearch 全部 fail-if-missing；真实外部 verifier 仍未实现 |
| 全仓后端 | 2384 passed、24 个既有声明 skip、2 deselected | ProofAgent 与 KSS 共用隔离 PostgreSQL；不是生产运行或 Release Gate |
| 显式 hybrid integration | 2 passed、2408 deselected | PostgreSQL/MinIO 本地可互操作，不是 KSS 注销端到端证明 |
| Mypy / Ruff | KSS 97 + ProofAgent 357，共 454 个产品源文件无类型错误；全量 Ruff 通过 | 本片未修改 ProofAgent 产品代码或前端 |
| 格式 / domain / diff / locks | 受影响 Python 文件格式检查、domain-context、`git diff --check` 和两份 lock check 通过 | 全 KSS format check 仍会重排 24 个既有非本片文件，未批量修改 |

```text
openapi.sha256=cbce49b2fcfc13615d224d84c4c14a430a4a3c709422bdc6453401ce817b9124
migrations.sha256=1ca9d5a19b4e9b453e56524ee77b7e959652fd6a0be3ee62153eb4f3717150a5
head_revision=0017_release_reference_deregistration
```

OpenAPI 指纹未变，证明本片没有新增 Reference/lifecycle 网络命令。Migration 指纹只绑定当前本地候选，不继承生产 migration、部署、发布、合并或 Production GO 批准。

验证结束后，仅对 `proofagent-kss-deregistration-tdd` 执行 `down --volumes`。本轮临时 PostgreSQL、MinIO、OpenSearch 容器、网络和可重建测试数据已删除；未操作其他 Compose 项目或 production-local 环境。

### 22.5 文件、边界与下一片

- 扩展 Release Reference contracts/domain/application/ports 与 memory/PostgreSQL authority；新增 `0017_release_reference_deregistration.sql`。
- 保持一个深 Reference application Interface；外部 verifier 只返回最小 trace-safe identity，事务内隐藏 replay、row lock、数据库时间、current state、receipt 与审计。
- 更新 Scope、Feature context、本报告、领域上下文与决策、项目索引、开发进度、ADR-0216 和本地调用指南。
- 没有新增 ProofAgent verifier、后台 reconciler、Reference/lifecycle HTTP/BFF、emergency revocation、formal publisher/activation、生产配置、部署或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] TDD-03D 证明的是可信注销准入 seam，不是可运行的跨服务对账系统。下一片建议继续核心优先，单独冻结 TDD-03E emergency Release revocation：明确授权、reason taxonomy、立即 query denial、existing-reference 负向矩阵和普通 retirement 的隔离。ProofAgent verifier/证明签发与后台 reconciler 应在其真实运行责任切片中接入，不应由测试 verifier 替代。Feature 保持 `PARTIAL_VERIFICATION`。

## 23. TDD-03E：Emergency Knowledge Base Release Revocation 核心

### 23.1 模式、接口与范围

[FRAME | HIGH] 本片只实现 application-only 紧急撤销核心，不把网络角色接线、affected-reference 明细/通知、ProofAgent runtime/rollback 隔离或物理删除混入同一命令。可信应用 Interface 为：

```python
lifecycle_application.revoke(
    RevokeKnowledgeBaseReleaseRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-exact",
        reason_code="security_incident",
        confirmation="fail_closed_without_fallback",
    ),
    operator_id="security-operator",
    idempotency_key="emergency-revoke-release-exact",
)
```

`reason_code` 只允许 `security_incident` 或 `severe_data_integrity_failure`；`confirmation` 必须精确为 `fail_closed_without_fallback`。Delivery 必须在调用前认证并授权 operator；application 不接受浏览器自报角色、自由文本原因、调用者时间、Reference count、替代 Release 或 fallback。KSS 在 Release 行锁内锁定并统计 active Reference rows，再原子提交 `revoked` state、原因、确认、数据库时间、受影响数量、永久 receipt 和成功审计。

| Interface | 可观察行为 | 隐藏实现 |
| --- | --- | --- |
| `revoke()` | 仅 `queryable/deprecated → revoked`；保留 Reference facts；精确重放返回原结果 | operator/key advisory lock、Release/Reference row locks、数据库时间、KSS 计数、状态/receipt/audit 单事务 |
| `audit(release_id)` | 返回 bounded reason、exact confirmation、受影响 active count 和 authorized operator identity | revocation command 与 deprecation/retirement 共用 event sequence |
| 既有读取 | revoked 不可 Catalog query、不进入完整性扫描、既有 Query Grant authorization 与新 Reference registration 失败关闭 | 不 fallback、不自动选择 replacement；只读 Catalog summary 仍显示 revoked |

范围外：lifecycle HTTP/BFF/Dashboard/CLI、生产角色映射、affected-reference ID/client 明细和通知、ProofAgent Run/rollback preflight、自动替换、Reference 注销、物理删除/删除资格、部署、生产 migration、Git 操作和 Production GO。

### 23.2 Given-When-Then 与高风险断言

| 场景 | Given / When | Then |
| --- | --- | --- |
| 主路径 | exact deprecated Release 且存在 active Reference | `revoked`、bounded reason、exact confirmation、affected count=1、数据库时间、receipt/audit 原子提交；Reference 保持 active |
| 直接止损 | exact queryable Release 且无引用 | 不要求先 deprecate 或 retention；立即 revoked，affected count=0 |
| 原因/确认 | availability/free text reason 或非 exact confirmation | strict contract 拒绝，不能进入 application/transaction |
| 身份 | operator 或 idempotency identity 格式无效 | 稳定失败关闭；无状态或审计 |
| query denial | 既有 Catalog snapshot 与 Query Grant 在撤销前可用 | 撤销提交后 Catalog、完整性枚举、authorize 和新 Reference registration 均拒绝且不 fallback |
| exact replay | 相同 operator/key/fingerprint 顺序重放或八路并发 | 返回同一 revoked 结果；只有一个 receipt 和一条成功审计；key 改 reason 冲突 |
| registration race | 注册与撤销同时竞争 Release 行 | 注册要么先提交并被准确计入 affected count，要么在 revoked 后拒绝 |
| deregistration race | active Reference 注销与撤销竞争 | 两个命令都可完成；撤销计数在线性化点为 0 或 1，Reference 最终 retained deregistered |
| ordinary isolation | deprecated Release 的 retire 与 revoke 竞争 | 只允许一个终态；`retired` 与 `revoked` 不互相覆盖或复活 |
| audit 故障 | Release update 后 revocation command insert 被故障注入拒绝 | 状态、原因、时间与 receipt 整体回滚；移除故障后同一命令可成功 |
| 历史升级 | `0017` 已有 deprecated Release 和 active Reference | `0018` 升级/replay 保留 deprecation/reference facts，随后可精确撤销并计数 1 |

### 23.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | 内存 tracer 收集失败：无法导入 `RevokeKnowledgeBaseReleaseRequest` | 增加 strict request/result/audit contracts、`revoke()` application Interface、revoked domain state、事务 port 和 memory authority；带引用 deprecated 主路径转绿 |
| R2 | 真实 PostgreSQL tracer 在调用 `active_reference_count_for_update()` 时失败：`_Transaction` 没有该方法 | 新增 `0018_release_revocation.sql`、共享 lifecycle receipt/audit、Release/Reference locks、数据库时间与 atomic revocation persist；Catalog/Access 既有 fail-closed 查询自然覆盖 revoked |
| R3 | canonical OpenAPI 合同仍绑定旧 hash | 只读 Release summary enum 显式增加 `revoked`，更新 OpenAPI 和 migration head/hash 断言；没有新增 lifecycle command 网络路径 |
| 行为保护 | bounded reason/confirmation、trusted identity、terminal matrix、八路同键、三类 race、rollback、`0017 → 0018`、Catalog/Grant denial | memory、真实 PostgreSQL、Access 与 distribution 全部纳入最终 415 项受影响回归 |
| REFACTOR | 撤销需要小 Interface 隐藏状态、计数、锁和审计复杂度 | 继续复用一个深 lifecycle module；revocation 只新增一个公开方法和 strict contracts，不暴露 SQL、锁顺序或调用者计数 |

### 23.4 验证结果与候选指纹

隔离依赖项目为 `proofagent-kss-revocation-tdd`，显式端口为 PostgreSQL `55467`、MinIO `59046`、OpenSearch `19236`。早期 PostgreSQL RED 使用独立 `55466` 测试容器。所有 fixture 使用随机 schema/bucket 或仓库测试前缀；没有读取 `.env`、生产配置、生产凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| 首轮聚焦合同 | 69 passed | memory、Release PG、Access PG、distribution；随后新增 invalid operator/idempotency 保护也包含在最终受影响回归 |
| KSS + ProofAgent KSS/BFF/cutover 受影响回归 | 415 passed、0 skipped | PostgreSQL/MinIO/OpenSearch 全部 fail-if-missing；不是 ProofAgent runtime revocation E2E |
| 全仓后端 | 2396 passed、24 个既有声明 skip、2 deselected | 退出码 0；显式 hybrid 另行执行 |
| 显式 hybrid integration | 2 passed、2420 deselected | 使用隔离 PostgreSQL/MinIO；不是 KSS emergency revocation 跨服务证明 |
| Mypy / Ruff | KSS + ProofAgent 454 个产品源文件无类型错误；全量 Ruff 通过 | 未降低测试或忽略新类型错误 |
| 格式 / domain / diff / locks | 13 个受影响 Python 文件格式、domain-context、`git diff --check`、根项目 117 packages 与 KSS 34 packages lock check 通过 | `uv lock --check` 因受限 cache 首次失败后按批准只读重试通过 |
| 前端 | TypeScript 通过；Dashboard 225、Chat 35 tests；UI/Dashboard/Chat build 通过 | OpenAPI 只扩展只读 summary enum；Chat 仍有既有 600.22 kB chunk warning |

```text
openapi.sha256=d5ac3702b27a3c829fa6d5cf4d84e632162f9b12aeb934afba09f11edb7ee51c
migrations.sha256=7a382fd03b767c56b13bf8f8260b6a808ddec91ff0fb41ff014f6b6a64669fef
head_revision=0018_release_revocation
```

首轮 PostgreSQL 测试在无 DSN 时按仓库规则声明 skip，随后连接隔离容器取得真实业务 RED；沙箱内 `.venv` 首次被禁止访问 loopback，按批准在沙箱外重跑。显式 hybrid 首次误用历史 `HYBRID_TEST_*` 变量得到 2 个可见 skip；读取当前测试契约后改用 `PROOF_AGENT_TEST_*`，同两项最终 2 passed。没有删除 skip、降低 fail-if-missing 或把环境错误冒充业务 RED。

OpenAPI 变化只来自只读 `KnowledgeBaseReleaseSummaryResource.state` 增加 `revoked`；不存在 revoke HTTP 命令。Migration/OpenAPI 指纹只绑定当前本地候选，不继承生产 migration、部署、发布、合并或 Production GO 批准。

验证结束后，仅删除 `proofagent-kss-revocation-tdd` Compose 项目的容器、网络和可重建卷，以及早期 RED 使用的 `proofagent-tdd03e-postgres` 容器。后者的匿名 volume 通过本轮创建时间精确识别后单独删除；没有执行全局 volume prune，也未操作其他 Compose 项目或 production-local 数据。最终该 Compose 项目 `ps --all` 为空。

### 23.5 文件、边界与下一片

- 扩展 Release lifecycle contracts/domain/application/ports 与 memory/PostgreSQL authority；新增 `0018_release_revocation.sql`。
- 更新 Catalog summary state、migration/OpenAPI canonical contracts、Reference/lifecycle/Access 负向和并发合同。
- 同步 ADR-0215、Scope、Feature context、本报告、领域上下文/决策、项目索引、开发进度和本地调用指南。
- 没有新增 lifecycle HTTP/BFF、角色映射、affected-reference 明细/通知、ProofAgent runtime/rollback 接线、物理删除、部署或生产 SQL；没有提交、推送、合并或发布。

[FRAME | HIGH] TDD-03E 证明 KSS 本地紧急 query denial 权威，不证明受影响 Agent 已被通知、阻止运行或禁止回滚。下一片若继续核心优先，建议冻结 TDD-03F deletion-eligibility assessment：只计算可删除资格，不执行物理删除；明确 ordinary retired 与 emergency revoked 的不同保留/事件响应规则、active/deregistered Reference 与 artifact retention blocker，以及审计/幂等边界。若优先产品闭环，则应进入 TDD-04 lifecycle/affected-reference BFF 与角色接线。Feature 保持 `PARTIAL_VERIFICATION`。
