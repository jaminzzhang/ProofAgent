# KSS 配置发布闭环 TDD 报告

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `PARTIAL_VERIFICATION` |
| 最高风险等级 | P1 |
| 模式 | 受控实现：TDD-01A/01B + TDD-02A 至 02G Preparation 核心 + TDD-03A 至 03F Reference/lifecycle 核心 + TDD-04A 至 04F ProofAgent 管理 BFF 与 one-shot execution composition |
| 日期 | 2026-08-29 |
| 依据 | 用户确认按既定 Scope 启动开发并继续下一 TDD 切片；ADR-0213/0214/0217、`feature_context.md`、`scope-plan.md`、仓库编码规则 |

[KNOWN | HIGH] TDD-01B 已将 HTTP snapshot Profile 生命周期接入 KSS PostgreSQL、受保护管理 HTTP 和显式受管运行组合。同步任务固定 Published Profile 的 ID、revision 和 configuration digest，Worker 重启后仍解析该 exact revision；Source Version 的不可变 artifact 保留并校验血缘。现有生产进程仍使用静态 registry，尚未切换。完整 TDD-01 和整体配置发布流程仍未完成。

[KNOWN | HIGH] TDD-02A/02B 已有持久化准入和管理 HTTP；TDD-02C 增加 lease/fencing；TDD-02D 增加 frozen-plan candidate 构建和 fenced `ready/failed` 最终提交；TDD-02E 增加服务端核心 `ready → expired/consumed` 和 exact Release 单事务发布；TDD-02F 增加 application-only `expire_next()`；TDD-02G 增加 application-only queued/running 协作取消、幂等收据/审计和 stale-result fencing。GET 可读全部已实现状态，POST start 重放仍返回原始 queued 回执；TDD-04C/04D 已接 start/status BFF 与可选 one-shot execution runtime，TDD-04E 已接 controlled `:publish` KSS/BFF，TDD-04F 已接 controlled、Idempotency-Key-bound `:cancel` KSS/BFF。expiry 仍无网络命令。TDD-04F 当前本地与真实 PostgreSQL affected files 合计 238 passed；全仓后端 2471 passed、24 个既有声明 skip、2 deselected。尚无常驻 Worker、自动过期调度、ready quarantine、Dashboard 或生产切换；既有直接 Release 发布路径仍可绕过 Preparation，因此不能声称系统级唯一发布入口或生产发布流程完成。

[KNOWN | HIGH] TDD-03A 至 03F 新增 application-only exact Release Reference registration、可信 deregistration admission、`queryable → deprecated → retired` 普通生命周期、`queryable/deprecated → revoked` 紧急生命周期、只读删除资格和 PostgreSQL migrations `0014` 至 `0018`。只有 owning authenticated client 加服务端注入 verifier 的 exact permanent-ineligibility 证明，才能把 Reference 从 `active` 转为 `deregistered`；普通退役仍由 active Reference、服务端 retention policy 和数据库时间共同控制。紧急撤销仅接受两个受控原因和 exact fail-closed 确认，由 KSS 锁定/统计 active References 并保留全部 Reference facts。Retired/revoked Release 均不可 Catalog query、不进入完整性扫描且既有 Query authorization 失败关闭。删除资格还要求 ordinary retired history、零 active Reference 和服务端 artifact-retention clear，但不执行物理删除。没有 Reference/lifecycle HTTP/BFF、ProofAgent verifier/证明签发、后台 reconciler、生产 artifact-retention adapter、physical delete、affected-reference 明细/通知、ProofAgent runtime/rollback 接线或生产配置，因此这仍是局部本地权威证据。

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
| Preparation publication 仍非完整运行闭环 | P1 | TDD-02E 已实现 `ready → expired/consumed` 和 exact Release 单事务 CAS；TDD-02F 可显式回收一个到期 ready candidate；TDD-02G 可取消 queued/running 并 fence 旧结果；TDD-04E/04F 已公开 controlled publish/cancel KSS/BFF。仍没有 expiry HTTP、自动调度、常驻 Worker 或 Dashboard，既有直接 Release 发布路径也可绕过 Preparation。旧构建可以留下未绑定的 immutable object/projection；后续需要对象回收、ready quarantine 与恢复策略。生产进程未启用；应用重建不等于数据库故障恢复演练 |
| 整体流程未完成 | P1 | Reference Ledger、正式 Agent 发布候选绑定、回滚与 Phase F 仍按后续切片实施；Source Version 和 Preparation 均不自动发布 KSS Release 或激活 Agent |
| 审计与保留边界 | P2 | 成功状态和回执原子写入；Profile 和 Preparation 管理路由的认证/权限/校验/状态拒绝写入独立安全审计。不是所有 KSS 管理命令的通用审计。当前不自动清理 revision、receipt 或 audit；分页、保留、备份恢复演练仍待补齐 |
| 新迁移的生产执行尚未评估 | P1 | `0009` 建立管理表与 exact Source 外键；`0010` 新增 lease/fence；`0011` 新增 ready/failed 与内部候选结果；`0012` 新增 expired/consumed、exact Release 外键和发布审计；`0013` 新增 cancelled 时间/约束并扩展命令收据 action。只在隔离测试库应用；旧二进制不能读取新状态，生产锁影响、切换顺序、备份和回滚需要独立评估与授权 |
| Worker 既有最终发布 fencing 边界 | P1 | 本轮保护 claim 和 pinned identity，但未重构已存在的 artifact/catalog 发布与最后一次 queue save 的跨事务窗口。实际进程切换前仍需验证 lease 丢失时的发布行为，不将旧 Worker fencing 测试当作该窗口已关闭的证明 |

## 10. 上下文更新

[KNOWN | HIGH] Feature 维持 `PARTIAL_VERIFICATION`。TDD-01B 的本地持久化、HTTP 和同步 Worker 协议接线，TDD-02A 至 02G 的 Preparation 准入、租约、候选构建、fenced 结果、一次性核心发布、显式主动过期和协作取消，以及 TDD-04C 至 04F 的 start/status、one-shot execution、controlled publication/cancellation 接线已有本地证据；仍不代表真实 Secret/egress/TLS、系统级唯一发布入口、Dashboard 闭环、连续生产进程切换或完整 TDD-01/02。已批准的设计不重新 grilling。

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

## 24. TDD-03F：Release 删除资格只读评估

### 24.1 模式、Interface 与权威边界

[FRAME | HIGH] 本片是 P1 完整留痕受控实现。可信 application-only Interface 为：

```python
assessment = lifecycle_application.assess_deletion_eligibility(
    AssessKnowledgeBaseReleaseDeletionEligibilityRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-exact",
    )
)
```

请求只含 exact Space/Base/Release identity，不接受 operator、idempotency key、调用者时间、Reference 数、artifact-retention 结论或删除原因。评估使用 KSS PostgreSQL lifecycle 与 active/deregistered Reference facts；只有普通 `retired`、完整 `retired_at`、零 active Reference，且服务端注入的 `ReleaseArtifactRetentionAuthority` 对 exact Release 明确返回 `clear` 时才输出 `eligible=true`。

| Interface | 可观察行为 | 隐藏实现与限制 |
| --- | --- | --- |
| `assess_deletion_eligibility()` | 返回 exact identity、Release state、eligible、稳定 blockers、active/deregistered counts、lifecycle time、数据库 assessed time 与 trace-safe artifact assessment identity | PostgreSQL 一次 read、lifecycle row integrity、Reference state 聚合、artifact authority 校验；无 HTTP/OpenAPI |
| `audit()` | 评估前后 lifecycle audit 不变 | 评估不是 command，不写 receipt/audit，也没有幂等重放 |
| 未来 physical delete | 本片没有该 Interface | 不得信任旧 assessment；必须在未来删除事务中重验并写可存续审计 |

范围外：物理删除、incident clearance、生产 artifact-retention adapter、lifecycle HTTP/BFF/Dashboard/CLI、ProofAgent verifier/reconciler/runtime/rollback 接线、部署、生产配置、生产 SQL 和 Production GO。

### 24.2 Given-When-Then 与 blocker 规则

| 场景 | Given / When | Then |
| --- | --- | --- |
| 普通正路径 | application-command retired、完整 `retired_at`、零 active、artifact `clear` | eligible；空 blockers；评估不新增审计 |
| artifact 未确认 | authority 缺失/返回 `None`/返回 `blocked` | `artifact_retention_unverified` 或 `artifact_retention_blocked`；失败关闭 |
| 历史 Reference | 一个 Reference 已由可信 verifier 注销 | active=0、deregistered=1；历史保留但不阻断 |
| 普通状态 | queryable 或 deprecated | `release_not_retired`；不调用 artifact authority |
| 紧急状态 | revoked，可仍有 active Reference | incident-retention 与 active-reference blockers；不调用 artifact authority |
| 旧版/旁路历史 | retired 即使带时间戳，但没有匹配的 ordinary-retirement command history | `release_retirement_history_unavailable`；不推断资格或调用 artifact authority |
| 作用域/完整性 | missing/scope mismatch 或 artifact assessment 绑定其他 Release | 稳定 not-found/scope/integrity failure；不输出 permissive assessment |

Blocker 顺序稳定为 lifecycle/history、active Reference、artifact retention。`deregistered` 只进入历史计数。Revoked 即使未来 artifact clear 也不能由本 Interface 变为 eligible；incident clearance 必须作为独立、明确授权的未来设计。

### 24.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | 内存 tracer 收集失败：无法导入 `AssessKnowledgeBaseReleaseDeletionEligibilityRequest` | 增加 strict request/result、只读 application Interface、deletion facts 与 artifact-retention port；普通 retired + clear 主路径转绿 |
| R2 | 真实 PostgreSQL tracer 失败：`PostgresReleaseLifecycleRepository` 没有 `deletion_facts()` | 增加单次数据库 facts read，返回数据库 assessed time 与 active/deregistered counts；未新增 migration |
| R3 | 最终审阅新增 PostgreSQL RED：手工设置 retired 与完整时间戳但没有 retirement receipt 时被误判 eligible | deletion facts 额外要求 exact Space/Base/Release、deprecated/retired time 和 retention boundary 匹配唯一 ordinary-retirement command；无匹配 history 失败关闭 |
| 行为保护 | revoked、missing/blocked artifact、deregistered history、queryable/deprecated、missing/scope mismatch、mismatched artifact、legacy retired history | 内存 28 项、Release PostgreSQL 34 项全部通过 |
| REFACTOR | lifecycle row integrity 在 locked command read 与 deletion facts read 重复 | 抽取同 adapter 内部 `_validated_lifecycle_row()`，保持 application Interface 与合同不变；完整 PG 回归后仍为 GREEN |

一次 revoked 测试的首个断言只期望 incident blocker，实际实现还返回独立 active-reference blocker。依据已冻结的“active Reference 必须阻断删除”规则，测试改为同时要求两个 blocker；这是补强独立阻断事实，不是降低断言或隐藏失败。

### 24.4 验证结果与限定

隔离真实依赖项目为 `proofagent-kss-deletion-tdd`，端口为 PostgreSQL `55469`、MinIO `59047`、OpenSearch `19237`；首个 PostgreSQL RED 使用独立 `proofagent-tdd03f-postgres` 容器和端口 `55468`。所有数据库 fixture 使用随机 schema，S3 fixture 使用随机 bucket 或版本化测试 bucket；没有读取 `.env`、生产配置、生产凭据、生产数据或生产日志。

| 检查 | 本轮结果 | 限定 |
| --- | --- | --- |
| 内存 / Release PostgreSQL | 28 passed / 34 passed | application Interface 与真实 PostgreSQL facts；不是生产 artifact authority |
| KSS + ProofAgent KSS/BFF/cutover 受影响回归 | 422 passed、0 skipped | PostgreSQL/MinIO/OpenSearch 均 fail-if-missing；无 physical delete |
| 全仓后端 | 2408 passed、24 个既有声明 skip、2 deselected | 修正 DSN 后退出码 0；不是 Release Gate |
| 显式 hybrid integration | 2 passed、2432 deselected | PostgreSQL/MinIO 隔离互操作；不是 deletion E2E |
| Mypy / Ruff | 454 个产品源文件无类型错误；全量 Ruff 通过 | 未降低检查或增加 ignore |
| 格式 / domain / diff / locks | 8 个受影响 Python 文件格式、domain-context、`git diff --check`、根项目 117 packages 与 KSS 34 packages lock check 通过 | 无 dependency、migration 或 OpenAPI 变化 |
| 前端 | TypeScript 通过；Dashboard 225、Chat 35 tests；UI/Dashboard/Chat build 通过 | 本片无 UI/API 改动；Chat 保留既有 600.22 kB chunk warning |

```text
openapi.sha256=d5ac3702b27a3c829fa6d5cf4d84e632162f9b12aeb934afba09f11edb7ee51c
migrations.sha256=7a382fd03b767c56b13bf8f8260b6a808ddec91ff0fb41ff014f6b6a64669fef
head_revision=0018_release_revocation
```

第一次全仓运行给 SQLAlchemy 使用了 `postgresql://`，导致它选择未安装的 `psycopg2` 并产生 72 个同因 setup errors；当次已有 2336 passed。未安装依赖或改测试，改用仓库支持的 `postgresql+psycopg://` 后完整重跑为 2408 passed。显式 hybrid 首次因缺 `PROOF_AGENT_TEST_S3_BUCKET` 得到两个可见 skip；补齐隔离 Compose 已创建的 versioned bucket 与标准 AWS 测试凭据变量后，同两项最终 2 passed。两次环境问题都没有作为业务 RED，也没有删除 skip 或降低 fail-if-missing。

最终候选在 managed-retirement 修正后重新取得 422 项受影响回归、2408 项全仓主套件和 2 项显式 hybrid 的完整 GREEN；未沿用修正前的总回归结果。

验证结束后删除了精确命名的 `proofagent-kss-deletion-tdd` Compose 容器、网络和可重建卷，以及 RED 使用的 `proofagent-tdd03f-postgres`、`proofagent-tdd03f-history-postgres` 容器及其匿名卷。没有执行全局 prune，也没有操作其他 Compose 项目或 production-local 数据；最终 Compose 项目和 `proofagent-tdd03f*` 容器清单均为空。

OpenAPI 与 migration canonical bytes 未变化；上述指纹继续绑定当前本地候选，不表示生产 migration、部署、发布、合并或 Production GO。

### 24.5 文件、状态与下一片

- 扩展 Release lifecycle strict contracts、domain facts、application Interface、ports 与 memory/PostgreSQL adapters；没有新增 SQL 或网络命令。
- 更新 ADR-0215、Scope、Feature context、本报告、领域上下文/决策、项目索引、开发进度与本地调用指南。
- 本片建议结论为 `LOCAL_VERIFIED`；Feature 仍为 `PARTIAL_VERIFICATION`。
- 本轮开始前已按用户授权把 TDD-01 至 TDD-03E 提交为 `f755b3c`；TDD-03F 当前改动尚未提交。没有 push、merge、deploy、production migration 或 physical delete。

[FRAME | HIGH] 下一核心切片不应直接实现 physical delete：生产 artifact-retention authority、事件清除权威、可存续删除审计和跨存储原子/恢复语义尚未冻结。若继续产品闭环，优先进入 TDD-04 lifecycle/affected-reference BFF 与三类简单角色权限接线；若继续后端 authority，先冻结独立 physical-delete command 的保留、审计与恢复合同，再由用户单独确认。

## 25. TDD-04A：Release lifecycle/reference-summary 同源只读 BFF

### 25.1 模式、Interface 与范围

[FRAME | HIGH] 本片沿用 P1 完整留痕受控实现。它把 TDD-03F 的 exact Release
删除资格评估接入两个只读资源：

```text
GET /v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility
GET /api/config/knowledge-service/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility
```

KSS 资源和 ProofAgent BFF 都要求认证主体具有 `knowledge_source.view`。ProofAgent
通过受保护的服务端客户端读取 exact KSS resource，浏览器只接收
`knowledge-service-release-deletion-eligibility.v1` 投影。

| Interface | 可观察行为 | 隐藏或删除的内容 |
| --- | --- | --- |
| KSS management GET | 返回 exact identity、Release state、eligible、稳定 blockers、active/deregistered Reference 数、lifecycle/assessment time 与 artifact-retention state | KSS 内部持久化与 authority 调用仍由 application 管理 |
| guarded management client | 要求 exact response identity 与 strict wire schema | identity drift、额外字段和非合同 state 失败关闭 |
| ProofAgent same-origin BFF | 返回独立、secret-free 的浏览器投影 | 不返回 KSS endpoint/token、外部资源 identity、artifact authority/assessment identity 或 raw problem |

本片只扩展既有 Release 列表类型以读取 `queryable`、`deprecated`、`retired`、
`revoked` 四种状态。范围外包括 lifecycle/Reference 命令、affected-reference 明细或
通知、Dashboard 页面或动作、physical delete、角色管理、SQL/migration、部署、生产
配置和 Git 操作。

### 25.2 Given-When-Then 与失败关闭

| 场景 | Given / When | Then |
| --- | --- | --- |
| 授权 exact read | KSS 与 BFF 调用方均有 `knowledge_source.view`，response identity 精确匹配 | 返回 200 与 secret-free 投影 |
| ProofAgent 权限缺失 | Operator Session 没有 `knowledge_source.view` | BFF 在调用 KSS client 前返回 403 |
| KSS 权限缺失 | KSS 调用方只有 edit 等其他权限 | KSS 返回 403 |
| 上游漂移 | KSS response 的 Space/Base/Release identity 与请求不一致 | guarded client 拒绝响应，不建立浏览器事实 |
| 合同外字段 | KSS response 注入 `token` 等未知字段 | strict wire contract 拒绝响应 |
| 生产形态组合 | PostgreSQL 中是 ordinary retired，但 runtime 未注入 production artifact-retention authority | 返回 `artifact_retention_unverified`，不得推断 eligible |
| 信息最小化 | KSS 结果含 trace-safe authority/assessment identity | BFF 投影删除这些 identity，只保留浏览器所需状态 |

### 25.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | ProofAgent public API tracer 期望 200，实际因路由不存在返回 404 | 增加 BFF strict projection、权限检查与 exact GET route |
| R2 | management client tracer 因没有 deletion-eligibility 方法产生 `AttributeError` | 增加 guarded exact KSS client method、strict wire model 和 identity drift 检查 |
| R3 | KSS HTTP tracer 因 app builder 不接受 `release_lifecycle` 失败 | 对 management HTTP 注入 lifecycle application，并增加 `knowledge_source.view` 保护的 exact GET |
| R4 | canonical OpenAPI contract 因新增资源与 schema 保持旧 hash 而失败 | 把资源纳入 canonical OpenAPI，并更新与当前 bytes 绑定的 hash |
| 行为保护 | BFF/KSS 缺权限、identity drift、unknown secret-like field、敏感 authority identity 投影 | 对应负向测试全部保持 GREEN |
| REFACTOR | production runtime 与 OpenAPI composition 需要同一 lifecycle application seam | runtime 使用 PostgreSQL lifecycle repository；OpenAPI 使用 in-memory repository；公开合同不暴露 adapter |

### 25.4 验证结果与限定

隔离真实依赖项目为 `proofagent-kss-bff-tdd04a`，端口为 PostgreSQL `55470`、
MinIO `59048`、OpenSearch `19238`。Compose `up --wait` 的命令退出码为 1，是因为
一次性 `minio-init` 成功退出；后续 `compose ps` 显示 PostgreSQL、MinIO 和 OpenSearch
均为 healthy。该基础设施状态没有被当作业务失败或放宽测试条件。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 四个核心 tracer 文件 | 32 passed | BFF、guarded client、KSS HTTP 与 canonical OpenAPI |
| production-shaped PostgreSQL runtime | 1 passed | 首次受 sandbox loopback 限制，获准在同一隔离依赖上重跑后通过 |
| KSS + ProofAgent KSS/BFF 受影响回归 | 427 passed、0 skipped | PostgreSQL/MinIO/OpenSearch 均 fail-if-missing；无命令或 physical delete |
| 全仓后端 | 2416 passed、24 个既有声明 skip、2 deselected | 退出码 0；不是 Release Gate |
| 显式 hybrid integration | 2 passed、2440 deselected | 隔离互操作；不是生产 E2E |
| Mypy / Ruff | 454 个产品源文件无类型错误；全量 Ruff 通过 | 未降低检查或新增 ignore |
| 锁文件 | 根项目 117 packages、KSS 34 packages lock check 通过 | 无 dependency 变更 |
| 前端 | TypeScript 通过；Dashboard 225、Chat 35 tests；UI/Dashboard/Chat build 通过 | 仅类型兼容；Chat 保留既有 600.22 kB chunk warning |

```text
openapi.sha256=e75e6d8e677017f22397d91d8d71bcc89b4888ad3f18b5246b997c35bc94b4c5
migrations.sha256=7a382fd03b767c56b13bf8f8260b6a808ddec91ff0fb41ff014f6b6a64669fef
head_revision=0018_release_revocation
```

[KNOWN | HIGH] 全仓、受影响套件和前端结果均来自当前本地候选；测试没有读取
`.env`、生产凭据、生产数据或生产日志。OpenAPI hash 因新增只读 resource/schema
变化，migration bytes 与 head 未变化。这些证据不表示 deployment、Production GO、
release、merge 或生产删除授权。

验证结束后，已用 `down -v` 删除精确命名的 `proofagent-kss-bff-tdd04a`
容器、网络和可重建卷，最终该 Compose 项目清单为空。没有执行全局 prune，也没有
停止或修改 `proofagent-production-local` 项目。

### 25.5 文件、状态与下一片

- 增加 KSS deletion-eligibility management GET、runtime composition、OpenAPI 合同、
  ProofAgent guarded management client、same-origin BFF strict projection 与权限测试。
- 更新 Dashboard API Release state 类型，使既有列表可读取四种 lifecycle state；没有
  增加页面或操作。
- 更新 ADR-0215、Scope、Feature context、本报告、领域上下文/决策、项目索引、开发
  进度与本地调用指南。
- [KNOWN | HIGH] 本片建议结论为 `LOCAL_VERIFIED`；Feature 仍为
  `PARTIAL_VERIFICATION`。TDD-03F 与 TDD-04A 改动均尚未提交。

[FRAME | HIGH] 下一核心垂直切片建议为 TDD-04B：在当前同源、secret-free、exact
identity 和简单角色权限模型上，接通 Connection Profile 的只读/变更生命周期与 exact
Synchronization Task 发起/状态读取，让 “Profile → Sync” 成为首个可操作闭环。该片应
先冻结权限、secret-handle 投影、幂等、任务身份与失败状态；不同时引入 lifecycle
commands、物理删除、复杂角色管理或生产切换。

## 26. TDD-04B：Connection Profile → Synchronization 同源管理 BFF

### 26.1 冻结范围与权威

[FRAME | HIGH] 本片不修改 KSS Profile、同步、Secret、egress 或数据权威，只把既有
KSS TDD-01B 核心通过 ProofAgent guarded management client 和同源 BFF 暴露给受信
浏览器会话。公开路径为：

- `POST /api/config/knowledge-service/connection-profiles`；
- `GET|PUT /api/config/knowledge-service/connection-profiles/{id}`；
- `POST /api/config/knowledge-service/connection-profiles/{id}:validate`；
- `POST /api/config/knowledge-service/connection-profiles/{id}:publish`；
- `POST /api/config/knowledge-service/synchronizations`；
- `GET /api/config/knowledge-service/synchronizations/{id}`。

读取检查 `knowledge_source.view`，变更检查 `knowledge_source.edit`。浏览器可提交
结构化 HTTPS endpoint、versioned Secret Handle 引用、egress/trust policy 引用和
硬大小限制，但响应不得返回这些配置、KSS operator token 或 raw upstream problem。
所有变更精确转发 `Idempotency-Key`；同步首次创建保持 `202`，相同 KSS receipt
重放保持 `200`。本片不增加 Dashboard 页面、真实 Vault/egress/TLS reader、生产
进程切换、终端操作者委托身份、Base Draft/Preparation BFF、Reference/lifecycle
command、SQL/migration、部署、生产配置或 Git 操作。

### 26.2 Given / When / Then 与负向矩阵

| 场景 | Given | When | Then |
| --- | --- | --- | --- |
| Profile 创建 | 受权 Knowledge editor 和完整严格 Draft | 经 BFF 创建 | `201 draft`；只返回 ID/revision/digest/state，`Location` 为同源路径 |
| exact lifecycle | 已存在 Profile revision | current/exact GET、revision CAS PUT、validate、publish | exact identity/state 保持；上游漂移或额外字段失败关闭 |
| 同步准入 | exact Published Profile ID/revision | 提交同步 | 首次 `202 queued`；固定 Profile ID/revision/digest 和同源 self link |
| 幂等重放 | 同 operator/key/fingerprint 已有同步 receipt | 重放提交 | 返回同一任务且 BFF 状态为 `200`，不创建第二任务 |
| 状态读取 | exact synchronization ID | viewer GET | 返回严格状态字段；成功才有 Source Version，失败才有最小 problem |
| secret-like 输入 | Profile 或同步含 `token` 等未知字段 | BFF 校验 | 固定安全 `422`，不回显请求输入，不调用 KSS |
| 权限拒绝 | viewer 执行变更，或 editor 缺少 view 执行读取 | 调用 BFF | `403`，client 不执行对应操作 |
| 上游错误 | KSS problem 带 detail/trace/blocker detail | guarded client 投影 | 只保留 code/retryable/blocker code；其余字段不进入浏览器响应 |
| 身份漂移 | KSS 返回不同 Profile/Space/Source/task/link | guarded client 解析 | `PA_KNOWLEDGE_002` 失败关闭，不建立浏览器事实 |

### 26.3 RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN / 说明 |
| --- | --- | --- |
| R1 | Profile create BFF tracer 期望 `201`，实际路由不存在返回 `404` | 增加 strict secret-sensitive input、safe Profile projection、edit permission 和同源 `Location` |
| R2 | guarded client create tracer 因无方法产生 `AttributeError` | 增加 exact KSS wire model、`Idempotency-Key` 转发和 create identity/state 校验 |
| R3 | Profile current/exact read、revise、validate、publish BFF tracer 返回 `404` | 增加 view/edit 权限、revision/CAS 命令和四个生命周期路径 |
| R4 | guarded client lifecycle tracer 因无 read/revise/transition 方法产生 `AttributeError` | 增加 current/exact URL、strict revision/state/Scope 检查和 validate/publish helper |
| R5 | unknown `token: synthetic-inline-secret` 触发 FastAPI 默认 `422` 并回显输入 | router-local validation route 返回固定 `invalid_knowledge_service_management_request`，不序列化原始错误 input |
| R6 | Synchronization submit/status BFF tracer 返回 `404` | 增加 strict request/projection、同源 link、`202` create / `200` replay 和 view/edit 权限 |
| R7 | guarded client synchronization tracer 因无方法产生 `AttributeError` | 增加 v2 wire contract、exact Scope/Profile/task/link 校验和 raw problem 最小化 |
| 行为保护 | replay、权限拒绝、invalid identity、extra token、raw detail/trace 泄漏 | 对应负向测试全部保持 GREEN |
| REFACTOR | Profile transition helper 接受任意字符串，输入模型的不可变映射需稳定序列化 | operation 收窄为 `validate | publish`；field type 映射冻结后显式序列化；未新增 fallback 或 ignore |

### 26.4 纵向合同与验证结果

[KNOWN | HIGH] 新增真实纵向合同在隔离 PostgreSQL 上组合 KSS managed Profile runtime，
使用 in-process guarded HTTPS adapter 接入 ProofAgent management client，再通过真实
ProofAgent BFF 依次创建 Space/Source、创建/校验/发布 Profile、提交与重放同步、读取
状态。该测试验证 BFF → client → KSS HTTP → PostgreSQL，而非只验证 mock；上游
reader 未配置，因此任务保持 `queued`，没有伪造 Source Version 成功事实。

隔离项目为 `proofagent-kss-profile-bff-tdd04b`，端口为 PostgreSQL `55471`、MinIO
`59049`、OpenSearch `19239`。Compose `up --wait` 因一次性 `minio-init` 成功退出而
返回 1；`compose ps` 随后确认三个长期服务均 healthy。纵向测试首次在沙箱内因
loopback `Operation not permitted` 失败，在获准使用同一隔离服务重跑后通过；没有
修改代码或放宽断言来掩盖环境失败。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| BFF + guarded client focused | 22 passed | Profile、同步、权限、脱敏与 fail-closed wire contract |
| BFF → KSS → PostgreSQL 纵向合同 | 1 passed | 真实 KSS Profile/receipt/task 持久化；无上游 reader |
| KSS + ProofAgent KSS/BFF 影响集 | 440 passed | PostgreSQL/MinIO/OpenSearch 均 fail-if-missing |
| 全仓后端 | 2429 passed、24 个既有声明 skip、2 deselected | 同时配置 ProofAgent/KSS PostgreSQL 与 S3；退出码 0 |
| 显式 Hybrid integration | 2 passed、2453 deselected | PostgreSQL/S3 互操作；不是生产 E2E |
| Mypy / Ruff / format | 454 个产品源无类型错误；Ruff 全量通过；6 个受影响文件格式通过 | 无新增 ignore 或降低检查 |
| 锁文件 | 根项目 117 packages、KSS 34 packages | 无 dependency 变更 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build 均通过 | 本片没有 Dashboard 页面；Chat 保留既有 600.22 kB warning |

```text
openapi.sha256=e75e6d8e677017f22397d91d8d71bcc89b4888ad3f18b5246b997c35bc94b4c5
migrations.sha256=7a382fd03b767c56b13bf8f8260b6a808ddec91ff0fb41ff014f6b6a64669fef
head_revision=0018_release_revocation
```

[KNOWN | HIGH] 本片没有修改 KSS HTTP/OpenAPI 或数据库 schema；以上指纹由影响集中的
canonical distribution contract 复核并保持不变。验证后已用 `down -v` 删除精确命名
项目的容器、网络和可重建卷，并确认项目清单为空；没有全局 prune，也没有停止或修改
`proofagent-production-local`。

### 26.5 状态与剩余风险

- [KNOWN | HIGH] TDD-04B 建议结论为 `LOCAL_VERIFIED`；Feature 仍为
  `PARTIAL_VERIFICATION`。当前工作树同时包含尚未提交的 TDD-03F、TDD-04A 和
  TDD-04B，不能把本片验证误称为独立 commit 或 merge 证据。
- [KNOWN | HIGH] 浏览器无法读取 endpoint、Secret Handle 或 egress/trust 配置；因此
  当前 BFF 支持安全状态读取，但编辑时必须由受信操作者重新提供完整 Draft。尚无
  Dashboard 交互或安全的 detail-edit projection。
- [KNOWN | HIGH] KSS 写入审计当前记录 ProofAgent 配置的服务 operator；BFF 已验证
  终端权限，但尚无不可伪造的终端操作者委托/关联进入 KSS audit。这是生产启用前的
  P1 可追责性缺口。
- [KNOWN | HIGH] 无真实 Vault Secret Provider、default-deny egress、TLS trust-root 或
  upstream reader 证据；`bootstrap/processes.py` 仍选择静态 registry。不能据此声明
  managed Profile 已切换到生产。
- [FRAME | HIGH] 下一核心切片建议为 TDD-04C：复用同一 guarded、same-origin、
  secret-free 与简单 named-permission 模型，接通 Base Draft save/exact read 和
  Preparation start/status，使已物化 Source Version 能进入异步 Release candidate。
  应先覆盖 Draft revision CAS、exact task identity、`Idempotency-Key`、状态最小化和
  权限拒绝；暂不同时引入 Dashboard 页面、publish/cancel/expiry command、常驻
  Worker 调度、Reference/lifecycle command 或生产切换。

## 27. TDD-04C：Base Draft → Release Preparation 同源管理 BFF

### 27.1 冻结范围与公开合同

[FRAME | HIGH] 2026-08-29 用户要求继续下一切片。本片只把既有 KSS Base Draft 与
Preparation authority 接入 ProofAgent guarded management client 和同源 BFF；没有
修改 KSS 核心、OpenAPI、migration 或持久化模型。Graphify 查询没有返回与当前 Draft/
Preparation 接线相关的可靠节点，因此只用于排除旧导航路径；以下实现事实以当前源码、
ADR-0214/0217 和可执行合同为准。

| BFF Interface | 行为 | 权限与边界 |
| --- | --- | --- |
| `PUT /api/config/knowledge-service/spaces/{space}/bases/{base}/draft` | 保存 `expected_revision + members`；client 注入 path Scope 并精确转发 `Idempotency-Key` | `knowledge_source.edit`；body 不能重复声明或改写 Scope |
| `GET .../draft?revision={n}` | 只读取一个 exact Draft revision | `knowledge_source.view`；不提供 mutable latest 读取 |
| `POST .../release-preparations` | 以 exact `draft_revision` 启动；首次与 exact replay 都保留 KSS `202` queued receipt | `knowledge_source.edit`；不伪造 created/replayed 差异 |
| `GET .../release-preparations/{id}` | 读取 exact current state | `knowledge_source.view`；不推进状态、不触发 Worker 或过期 |

公开 `knowledge-service-base-draft.v1` 投影只含 Scope、revision、digest、更新时间和
typed members。`knowledge-service-release-preparation.v1` 投影覆盖
`queued/running/ready/failed/cancelled/expired/consumed`，保留 frozen Base Version、
安全终态字段和同源 self link，但拒绝 Worker ID、fencing token、lease deadline、
artifact reference、未知字段和 raw failure detail。Draft/Preparation 写入仍由 KSS
负责 CAS、幂等 receipt 与审计；BFF 不是第二权威。

本片明确不增加 Worker/调度、publish/cancel/expiry command、Preparation audit、
Dashboard 页面、终端操作者委托身份、SQL、部署、生产配置或 Git 操作。Preparation
`ready` 仍不可查询；本片不会创建或激活 Release/Agent。

### 27.2 RED → GREEN → REFACTOR 与负向矩阵

| 阶段 | RED 证据 | GREEN / 保护结果 |
| --- | --- | --- |
| Base Draft BFF | PUT/GET tracer 均返回 `404` | route-owned Scope、strict member union、revision CAS request、exact read 与 view/edit permission 通过 |
| Base Draft client | `save_base_draft()` 不存在，产生 `AttributeError` | KSS body 注入 exact Space/Base，PUT/GET URL、revision、members、digest 与 identity 全量核对 |
| Preparation BFF | POST/GET tracer 均返回 `404` | `202`、same-origin Location、Retry-After、queued admission 与 ready status 投影通过 |
| Preparation client | `start_release_preparation()` 不存在，产生 `AttributeError` | exact KSS Location、Scope/Draft/Base Version/Preparation identity 与全部状态结构 fail closed |
| 安全负向 | viewer 写、editor 读、unknown worker token、identity/state/Location 漂移 | 在调用权威前返回 `403/422`，或映射为稳定 `PA_KNOWLEDGE_002`；测试私有值不回显 |
| REFACTOR | 五个文件不符合 canonical format | Ruff 机械格式化后 focused、纵向、lint、format、Mypy 和 diff 再验证通过 |

客户端 wire model 对每个状态执行封闭校验：queued/running 不得带终态字段；failed 只
允许稳定 `failure_code/failed_at`；ready/expired/consumed 必须有完整 Release candidate
字段和对应终态时间；cancelled 只接受 `cancelled_at`。任何额外 Worker/lease/fence 或
raw detail 都由 `extra=forbid` 拒绝。BFF 路由级安全 validation 继续返回固定
`invalid_knowledge_service_management_request`，不序列化原始输入。

### 27.3 真实纵向合同

[KNOWN | HIGH] 新增合同在隔离 PostgreSQL 上组合启用 Base Preparation 的 KSS runtime，
使用 in-process guarded HTTPS adapter 接入 ProofAgent client，再通过真实 BFF 创建
Space/Source/Base。测试使用同一 PostgreSQL catalog 和测试内存 artifact adapter 物化
一个 synthetic Source Version，随后只通过 BFF 保存/读取 Draft、启动/重放/读取
Preparation。结果保持 `queued`，frozen Base Version 只含 exact Source Version，KSS
Release catalog 仍为空。

隔离 Compose 项目为 `proofagent-kss-base-preparation-bff-tdd04c`，端口为 PostgreSQL
`55472`、MinIO `59050`、OpenSearch `19240`。第一次纵向 pytest 在默认沙箱内连接
loopback 时收到 `Operation not permitted`；获准连接同一隔离服务后通过，未修改代码
或断言。最终已用 `down -v --remove-orphans` 删除这个精确命名的测试项目，并由
`compose ps -a` 确认无残留容器；没有操作 `proofagent-production-local`。

### 27.4 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| BFF + guarded client focused | 37 passed | Draft、Preparation、权限、脱敏和 fail-closed wire contract |
| BFF → KSS → PostgreSQL 纵向合同 | 1 passed | 真实 Draft history、queued receipt/current state；无 Release |
| focused 影响集 | 115 passed | 上述 BFF/client/runtime 加完整 PostgreSQL Preparation 合同 |
| 全仓后端 | 2445 passed、24 个既有声明 skip、2 deselected | ProofAgent/KSS PostgreSQL 与 KSS S3/Search 均配置；退出码 0 |
| 显式 Hybrid integration | 2 passed、2469 deselected | PostgreSQL/S3 互操作；不是生产 E2E |
| Mypy / Ruff / format | 454 个产品源无类型错误；Ruff 全量通过；6 个受影响文件格式通过 | 无新增 ignore 或降低检查 |
| 锁文件与文档检查 | 根项目 117 packages、KSS 34 packages；domain 与 `git diff --check` 通过 | 无 dependency 变更 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build 均通过 | 本片没有 Dashboard 页面；Chat 保留既有 600.22 kB warning |

第一次全仓命令只配置 KSS PostgreSQL，虽以 `2372 passed / 96 skipped / 2 deselected`
退出 0，但因 ProofAgent PostgreSQL 合同未执行，不采纳为最终全量证据；补齐两个 DSN
后得到上表结果。两个 `uv lock --check` 第一次因沙箱无法读取现有 `~/.cache/uv` 失败，
获准读取同一缓存后分别解析 117 与 34 packages。Authlib deprecation 和 Chat chunk
size 均为既有 warning，本片未扩大或静默消除。

### 27.5 状态、文件边界与下一片

- [KNOWN | HIGH] TDD-04C 建议结论为 `LOCAL_VERIFIED`；Feature 仍为
  `PARTIAL_VERIFICATION`。当前工作树包含多片累计未提交改动，不能把本片证据称为
  独立 commit、merge、部署或 Production GO。
- [KNOWN | HIGH] 本片产品代码只扩展 ProofAgent management contracts、guarded client
  和 BFF；测试扩展两个 focused 文件与一个真实 runtime composition 文件。KSS 产品
  实现、OpenAPI、migration、依赖和 Dashboard 页面均未变化。
- [KNOWN | HIGH] 浏览器现在可以把已物化 Source Version 冻结为 queued Preparation，
  但没有常驻 Preparation Worker 或公开 publication Interface，因此还不能通过产品链
  得到 queryable Release。KSS audit 仍只看到配置的 ProofAgent service operator，终端
  操作者委托/关联仍是生产前 P1 缺口。
- [FRAME | HIGH] 下一核心切片建议为 TDD-04D：先冻结并接入一个受控、可停止、容量有界
  的 Preparation execution responsibility，使 queued frozen plan 能推进为 ready/failed，
  并验证重启、lease/fence、失败恢复和私有 artifact 边界。publish/cancel/expiry BFF、
  Dashboard、终端操作者委托、Reference/lifecycle commands 与生产切换继续分片，避免
  在一个切片中同时引入执行调度和发布权限。

## 28. TDD-04D：one-shot Release Preparation execution runtime

### 28.1 冻结范围与 Interface

[FRAME | HIGH] 本片只组合 TDD-02C/02D 已验证的 Worker、frozen-plan candidate builder
和 candidate TTL，不新增另一套领取、构建或结果提交逻辑。新增外部 Interface 为：

```python
runtime = compose_runtime(
    ...,
    base_preparation_execution=BasePreparationExecutionConfiguration(
        worker_id="base-preparation-worker-local-1",
        lease_duration=timedelta(seconds=30),
        candidate_ttl=timedelta(hours=1),
    ),
)
result = runtime.base_preparation_executor.run_once()
```

`run_once()` 一次最多处理一个 queued 或可接管 running Preparation，返回
`ReadyReleasePreparation`、`FailedReleasePreparation` 或 `None`。Worker identity、lease
和 candidate TTL 由可信 runtime composition 持有，调用者不再逐次传入 builder 或 TTL。
没有提供 `base_preparation_execution` 时，runtime handle 为 `None`，API runtime 不会在
请求内隐式执行后台工作。

本片明确不增加 CLI、`PROCESS_ROLES`、常驻循环、batch size、自动重试、健康/积压信号、
publish/cancel/expiry HTTP/BFF、Dashboard、终端操作者委托、SQL/migration、OpenAPI、
部署、生产配置或 Git 操作。`ready` 仍不可查询，Release catalog 只会由既有可信
publication CAS 或旧兼容直接入口改变。

### 28.2 可观察行为与负向边界

| 场景 | Given / When | Then |
| --- | --- | --- |
| 主路径与重建 | 默认 API runtime 已经通过 BFF 保存 queued Preparation；重新组合 execution runtime 并调用一次 | 同一 durable identity 进入 ready；默认 runtime handle 仍为 `None` |
| 容量上限 | 同一 frozen Draft 有两个 queued Preparation | 一次 `run_once()` 只推进按既有确定顺序领取的一个；另一个保持 queued |
| 配置失败关闭 | candidate TTL 为零、负值或布尔值 | runtime/executor 构造阶段拒绝；不领取任务、不产生 Worker audit |
| 私有边界 | execution 已生成 candidate | BFF current status 只显示 safe ready identity；无 Worker、lease、fence 或 artifact 字段 |
| 发布隔离 | execution 成功返回 ready | exact Release catalog 仍为空；没有 query authority 或 Agent activation |
| 恢复与竞争 | 既有 lease 到期、接管、stale completion、构建异常或结果事务失败 | 继续由完整 PostgreSQL Preparation 合同验证；本片 wrapper 不绕过现有 fence/rollback |

重建测试复用同一个测试内存 artifact adapter 和同一隔离 PostgreSQL；它证明 runtime
composition 与应用对象重建后可继续 durable work，不是 S3 进程重启、数据库故障切换、
备份恢复或生产进程演练。

### 28.3 RED → GREEN → REFACTOR

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| runtime tracer | 测试收集因 `BasePreparationExecutionConfiguration` 不存在而 `ImportError` | 增加 optional config、runtime handle 与 executor；真实 PostgreSQL vertical `1 passed` |
| composition reconstruction | 默认沙箱连接隔离 PostgreSQL 被 `Operation not permitted` 拒绝 | 在获准连接同一测试服务后，默认 API runtime 不执行、重建 execution runtime 进入 ready |
| 容量保护 | 既有 Worker 已满足单次领取，本轮未伪造 RED | 通过新增 executor Interface 验证一次只推进一个 queued resource |
| 配置保护 | 新 executor 构造校验 candidate TTL | 三个非法值在领取前稳定失败，无 Worker audit |
| REFACTOR | runtime caller 需要同时了解 Worker、builder 和 candidate TTL | 把三者封装到一个 `run_once()` 深 module Interface；Ruff/format/Mypy 后保持 GREEN |

### 28.4 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-preparation-executor-tdd04d`，端口为 PostgreSQL
`55473`、MinIO `59051`、OpenSearch `19241`。所有数据库 fixture 使用随机 schema；S3
fixture 使用随机或仓库 versioned 测试 bucket。未读取 `.env`、生产配置、生产凭据、
生产数据或生产日志。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 单个 runtime tracer | 真实 RED 后 `1 passed` | BFF queued → 重建 execution runtime → ready；无 Release |
| one-shot / 配置保护 | `1 passed` + `3 passed` | 一次最多一个；非法 TTL 在 claim 前拒绝 |
| Preparation 核心 + PostgreSQL + runtime composition | 160 passed | 包含 lease takeover、stale fence、构建失败、事务回滚和安全管理投影 |
| KSS + ProofAgent KSS/BFF 影响集 | 460 passed、0 skipped | PostgreSQL/MinIO/OpenSearch 全部 fail-if-missing |
| 全仓后端 | 2449 passed、24 个既有声明 skip、2 deselected | 退出码 0；默认排除的 Hybrid integrations 另行执行 |
| 显式 Hybrid integration | 2 passed | 隔离 PostgreSQL/S3 互操作；不是 Preparation 生产进程 E2E |
| Mypy / Ruff / format | 454 个产品源无类型错误；全量 Ruff 与 4 个受影响文件格式通过 | 无新增 ignore 或降低检查 |
| domain / diff / locks | domain-context、`git diff --check`；根 117、KSS 34 packages | 无 dependency、migration 或 OpenAPI 变化 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build | 本片无页面；Chat 保留既有 600.22 kB warning |

全仓保留一个既有 Authlib deprecation warning。24 个 skip 与 2 个默认排除均为既有
声明范围，没有因 TDD-04D 增加或删除。锁检查首次受沙箱 uv cache 权限限制，获准进行
同一只读检查后通过。所有长测试均检查最终退出码，没有把进度行当作完成。

### 28.5 文件、状态与下一边界

- 产品代码只更新 `application/base_preparation_worker.py` 与 `bootstrap/runtime.py`；
  测试只扩展 Preparation core 和 service runtime composition。
- 没有修改 `bootstrap/processes.py`、`cli.py`、KSS OpenAPI、migration、ProofAgent BFF、
  Dashboard、部署配置或生产 SQL。
- [KNOWN | HIGH] 本片建议结论为 `LOCAL_VERIFIED`；Feature 仍为
  `PARTIAL_VERIFICATION`。当前工作树包含多个累计未提交切片，不能把结果称为独立
  commit、merge、部署或 Production GO。
- [FRAME | HIGH] 下一片不应立即加入常驻循环。若继续核心管理流程，优先单独接入
  Preparation publication BFF，使一个未到期 ready candidate 通过既有 one-use CAS 进入
  consumed/queryable Release；该命令必须先冻结权限、幂等恢复、状态/Location、浏览器
  投影和失败原子性。取消、过期、Dashboard、process role 和生产切换继续分片。

## 29. TDD-04E：受控 Preparation publication BFF

### 29.1 冻结范围与接口

[FRAME | HIGH] 本片只把既有 one-use publication CAS 接到 KSS 管理 HTTP、ProofAgent
guarded management client 和同源 BFF：

```text
POST /v1/knowledge-spaces/{space}/knowledge-bases/{base}/release-preparations/{id}:publish
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{id}:publish
```

两个命令都不接受 request body。ProofAgent BFF 要求 `knowledge_source.edit`，KSS 操作者
身份继续由可信服务端认证组合提供。成功返回 `200`、`state="consumed"`，`Location` 指向
同一个 Preparation GET 资源。命令不增加 `Idempotency-Key`：既有 application CAS 只允许
一个未过期 ready candidate 成功消费；响应不确定、重复调用、到期或其他终态都必须 GET
exact Preparation 恢复权威状态，不能把网络重试伪装成新的发布。

本片没有新增 publication 事务、SQL、migration、依赖、Worker 进程或 Agent publication。
KSS HTTP 只在变更前核对路径 Scope，再复用既有 `KnowledgeBasePreparationApplication.publish()`；
Release 与 consumed Preparation 仍在同一个 PostgreSQL 事务提交。取消/主动过期 BFF、
Dashboard、常驻 execution process role、CLI、终端操作者委托、系统级旧入口移除、部署与
生产配置继续在范围外。

### 29.2 RED → GREEN 与负向合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| ProofAgent BFF tracer | 发布路径返回 `405 Method Not Allowed` | 新增 edit-protected、no-body 同源命令和同源 `Location`；focused `1 passed` |
| guarded client tracer | concrete client 没有 publication Interface | 固定 exact path、无 body/Idempotency-Key、强校验 consumed identity 与 KSS `Location` |
| KSS HTTP tracer | 管理发布路径返回 `405` | 复用既有 one-use CAS；真实 PostgreSQL ready → consumed/queryable `1 passed` |
| body 边界 | KSS/BFF 曾接受带合成 token 的 body 并发布 | 两层均固定拒绝 `422`，不回显 body；KSS 记录 trace-safe publish rejection audit |
| public contract | canonical OpenAPI 保留旧 fingerprint | 新增 no-requestBody/consumed-response 断言，指纹更新为 `97e8667b7bc14b28cc7d34a6aab927cce6ab2b184ecfc64003b745039ea221a1` |

负向合同覆盖缺少 edit permission、路径 Space/Base 漂移、queued/consumed 重放、数据库时间
到期、响应 identity/state/额外字段/Location 漂移。真实纵向合同从 BFF 创建 queued，重组
one-shot execution runtime 得到 ready，再由 BFF 发布为 consumed；发布前 catalog 为空，
发布后只有一个 exact queryable Release，Preparation GET 可恢复同一 consumed 终态，浏览器
投影不含 Worker、lease、fence、artifact 或 secret。

### 29.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-preparation-publication-bff-tdd04e`，端口为 PostgreSQL
`55474`、MinIO `59052`、OpenSearch `19242`。数据库 fixture 使用随机 schema，S3 fixture
使用随机 versioned bucket；显式 Hybrid 使用仓库 versioned 测试桶。没有读取 `.env`、
生产配置、生产凭据、生产数据或生产日志。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| BFF/client/KSS focused 与真实纵向合同 | 全部通过 | 包含实际 RED、权限、body、drift、expiry、replay 与 catalog 可见性 |
| KSS + ProofAgent KSS/BFF 影响集 | 480 passed、0 skipped | PostgreSQL/MinIO/OpenSearch 均 fail-if-missing；不是生产 E2E |
| 全仓后端 | 2461 passed、24 个既有声明 skip、2 deselected | 退出码 0；默认排除的 Hybrid integrations 另行执行 |
| 显式 Hybrid integration | 2 passed、2485 deselected | 隔离 PostgreSQL/S3 互操作；不是 publication 生产流程证明 |
| Mypy / Ruff / format | 454 个产品源无类型错误；全量 Ruff；9 个本片文件格式通过 | 无新增 ignore 或降低检查 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build | 无新增页面；Chat 保留既有 600.22 kB warning |
| domain / diff / locks | domain-context、`git diff --check`；根 117、KSS 34 packages | 无 dependency 或 migration 变化；OpenAPI 变化已精确绑定 |

第一次影响集运行得到 `468 passed` 后出现 `1 failed + 11 errors`，全部是 MinIO endpoint
拒绝连接。原因是一次初始化命令遗漏本切片端口变量，Compose 将 MinIO 从 `59052` 重建到
默认 `59000`；没有业务断言失败。按同一隔离项目恢复 `59052`、重新确认 healthy/versioned
bucket 后，原命令完整复跑为 480 passed。没有修改产品代码、删除测试或降低 fail-if-missing。
全仓保留一个既有 Authlib deprecation warning；所有长测试均核对最终退出码。
最终使用 `down -v --remove-orphans` 删除上述精确命名的隔离项目，并由 `compose ps -a`
确认无残留；没有操作其他 Compose 项目或 production-local。

### 29.4 状态与下一边界

- [KNOWN | HIGH] TDD-04E 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树未形成独立 commit、merge、部署或 Production GO。
- [KNOWN | HIGH] 本片新增的是受控 KSS/ProofAgent 网络入口，未改变 KSS 作为唯一可执行
  Knowledge authority，也未让 Preparation lease、ready 或 Release publication 激活 Agent。
- [FRAME | HIGH] 下一片仍应保持小步。优先在“cancel BFF”与“continuous execution process
  role”中择一并单独冻结；不要把取消、调度、Dashboard、Agent formal publication 与生产
  切换合并为一个切片。

## 30. TDD-04F：受控 Preparation cancellation BFF

### 30.1 冻结范围与接口

[FRAME | HIGH] 本片只把 TDD-02G 已有的 queued/running 协作取消事务接到 KSS 管理
HTTP、ProofAgent guarded management client 和同源 BFF：

```text
POST /v1/knowledge-spaces/{space}/knowledge-bases/{base}/release-preparations/{id}:cancel
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{id}:cancel
```

两个命令都不接受 request body，并要求 `Idempotency-Key`。ProofAgent BFF 要求
`knowledge_source.edit`；KSS operator identity 只来自可信服务端认证。成功返回 `200`、
`state="cancelled"` 和指向同一 Preparation GET 的 `Location`。相同 operator、key、action
和 Preparation identity 重放原结果；key 改绑另一个 Preparation 失败冲突，以新 key
操作终态资源返回 not-cancellable。响应不确定时读取 exact Preparation，不创建第二个状态
权威。

本片不新增取消算法、SQL、migration、依赖、Worker/调度进程、Dashboard、CLI 或部署配置。
KSS HTTP 在变更前读取 exact Preparation 并核对路径 Scope，再调用既有
`KnowledgeBasePreparationApplication.cancel()`。数据库锁、数据库时间、running lease
清理、fencing token 保留、stale Worker result 阻断、cancelled 状态、幂等收据和成功审计
仍由同一个 PostgreSQL 事务负责。取消不强杀外部 I/O，不清理 artifact，不允许取消
ready/terminal，不发布 Release，也不激活 Agent。

### 30.2 RED → GREEN 与负向合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| ProofAgent BFF tracer | `:cancel` 返回 `405 Method Not Allowed` | 新增 edit-protected、no-body、Idempotency-Key-bound 同源命令；focused `1 passed` |
| guarded client tracer | concrete client 没有 cancellation Interface，触发 `AttributeError` | 固定 exact KSS path、无 body、原样转发 key，并强校验 cancelled identity/state/Location |
| KSS HTTP tracer | 真实 PostgreSQL 下 `:cancel` 返回 `405` | 复用既有 cancellation 事务；queued → cancelled、exact replay 与单审计通过 |
| public contract | canonical OpenAPI 仍绑定旧 fingerprint | 新增 no-requestBody/cancelled-response 断言，指纹更新为 `ce34e8b4fbcd16c90201890cb8e466980132aedbbfc0dce35dedec155749ce3a` |

负向合同覆盖缺少 BFF edit permission、缺少 Idempotency-Key、KSS/BFF body、路径
Space/Base 漂移、key 改绑另一个 Preparation、终态新命令、上游 identity/state/额外字段/
Location 漂移。body 与 Scope 拒绝均发生在取消前，且同一 key 随后的合法 exact 请求仍可
成功；取消成功不会创建 Release，浏览器投影不含 Worker、lease、fence、artifact、KSS
credential 或 raw problem。真实纵向在同一 BFF → guarded client → KSS HTTP → PostgreSQL
链上新增 queued target，取消及 exact replay 后 GET 恢复同一 cancelled 终态；原先 published
Release 数量保持不变。

### 30.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-preparation-cancel-bff-tdd04f`，端口为 PostgreSQL
`55475`、MinIO `59053`、OpenSearch `19243`。数据库 fixture 使用随机 schema，KSS S3
fixture 使用随机 versioned bucket；显式 Hybrid 使用仓库测试桶。没有读取 `.env`、生产配置、
生产凭据、生产数据或生产日志。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 本片 local affected files | 152 passed | BFF/client、in-memory core 与 distribution/OpenAPI |
| 真实 PostgreSQL affected files | 86 passed | KSS cancellation、replay/conflict/Scope/body 与真实 BFF vertical |
| 全仓后端 | 2471 passed、24 个既有声明 skip、2 deselected | 退出码 0；默认排除的 Hybrid integrations 另行执行 |
| 显式 Hybrid integration | 2 passed、2495 deselected | 隔离 PostgreSQL/S3 互操作；不是生产流程证明 |
| Mypy / Ruff / format | 454 个产品源无类型错误；全量 Ruff；9 个本片文件格式通过 | 无新增 ignore 或降低检查 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build | 本片无页面；Chat 保留既有 600.22 kB warning |
| diff / contract | `git diff --check`；canonical OpenAPI exact hash | migration head、依赖和 lock 未变化 |

第一次全仓命令只配置 KSS DSN，得到 `2399 passed、96 skipped`；其中 72 条
ProofAgent PostgreSQL 测试被环境条件跳过，因此没有用作最终完整证据。第二次补充普通
`postgresql://` ProofAgent DSN 后，SQLAlchemy 选择未安装的 psycopg2，得到 72 个 setup
error；改用仓库实际依赖的 `postgresql+psycopg://` 后完整复跑为上述 2471 passed。
显式 Hybrid 首跑也因误用项目名前缀凭据变量而得到 2 个 `NoCredentialsError`；改用 boto3
标准测试变量后原命令为 2 passed。以上均为测试命令配置，不是产品断言失败；没有修改
产品逻辑、删测试或降低 fail-if-missing。全仓保留一个既有 Authlib deprecation warning。
最终使用 `down -v --remove-orphans` 删除上述精确命名的隔离项目，并由后续
`compose ps -a` 空结果确认无残留；没有操作其他 Compose 项目或 production-local。

### 30.4 状态与下一边界

- [KNOWN | HIGH] TDD-04F 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树未形成新的 commit、merge、部署或 Production GO。
- [KNOWN | HIGH] 本片没有改变 KSS 是唯一可执行 Knowledge authority，也没有把取消解释为
  物理中断、artifact cleanup、ready quarantine、Release publication 或 Agent activation。
- [FRAME | HIGH] 若继续保持简单核心切片，下一片优先考虑只读 Preparation audit 同源 BFF，
  先冻结安全投影、view permission、分页/上限和 ProofAgent service-operator 与终端 operator
  的身份边界；暂不同时引入 Dashboard、连续 execution process、expiry scheduler、artifact
  cleanup、Agent formal publication 或生产切换。

## 31. TDD-04G：有界 Preparation audit 只读 BFF

### 31.1 冻结范围与分层

[FRAME | HIGH] 本片只复用 KSS 既有 Base Preparation audit collection，并新增 ProofAgent
同源只读入口：

```text
GET /api/config/knowledge-service/spaces/{space}/bases/{base}/preparation-audit
    ?offset=0&limit=50
```

KSS 继续拥有审计事实；guarded management client 负责严格 wire/Scope 校验、secret-free
投影和有界分页；BFF 只负责 `knowledge_source.view` 权限与委托。公开 schema 为
`knowledge-service-preparation-audit.v1`，offset 范围 0 至 20,000，limit 范围 1 至 100。
success 与 rejection 按数据库记录时间合并排序；识别出的 actor 明确标记为
`kss_service_operator`。该身份是 KSS 观察到的可信服务操作者，不是浏览器或终端操作者，
本片不构造尚不存在的委托身份链。

本片不修改 KSS persistence、SQL、migration、OpenAPI 或审计写入；不新增 Dashboard、
continuous process、expiry command/scheduler、artifact cleanup、formal Agent publication、
部署或生产配置。当前 offset 页基于每次 KSS 当前读取，不承诺跨请求稳定 cursor；当前 Base
audit 也不合并 Worker audit 或独立 publication audit。

### 31.2 RED → GREEN 与失败关闭合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| BFF tracer | exact audit path 返回 `404` | 新增 view-protected GET、固定默认值和 offset/limit 上限；focused `1 passed` |
| guarded client tracer | concrete client 没有 `preparation_audit`，触发 `AttributeError` | 读取 exact KSS path，严格解析 success/rejection、校验 Scope、排序并投影完整有界页；focused `1 passed` |
| 负向合同 | 非法输入或上游漂移没有公开合同 | limit/offset、缺少 view permission、事件 Scope 漂移、rejection Scope 漂移、非法 operator、Worker 私有字段和 raw detail 全部失败关闭 |

真实纵向合同沿 BFF → guarded client → KSS HTTP → PostgreSQL 保存 Draft、启动并发布一项
Preparation，再启动并取消另一项；两个 audit 页只返回四条既有 Base management success
事实。所有 actor 均为 `proof-agent-management` KSS 服务操作者，浏览器身份不在投影中。
publish success 属于独立 publication audit，不被错误拼接到当前 Base audit；响应不含
credential、Worker、lease、fence、artifact 或 raw detail。

### 31.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-preparation-audit-bff-tdd04g`，端口为 PostgreSQL
`55476`、MinIO `59054`、OpenSearch `19244`。数据库 fixture 使用随机 schema，S3/Hybrid
使用隔离测试配置。没有读取 `.env`、生产配置、生产凭据、生产数据或生产日志。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| BFF/client focused files | 59 passed | 包含权限、边界、secret-free 与 wire/Scope drift |
| 真实依赖 affected set | 145 passed | 包含真实 PostgreSQL BFF vertical；依赖 fail-if-missing |
| 全仓后端 | 2479 passed、24 个既有声明 skip、2 deselected | 退出码 0；默认排除的 Hybrid integrations 另行执行 |
| 显式 Hybrid integration | 2 passed、2503 deselected | 隔离 PostgreSQL/S3 互操作；不是生产流程证明 |
| Mypy / Ruff / format | 454 个产品源无类型错误；全量 Ruff 与本片格式通过 | 无新增 ignore 或降低检查 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build | 本片无页面；Chat 保留既有 600.22 kB warning |
| domain / diff / locks | domain-context、`git diff --check`；根 117、KSS 34 packages | 无 dependency、migration 或 KSS OpenAPI 变化 |

Compose 首次 `up --wait` 因 one-shot `minio-init` 成功退出而返回非零；`compose ps -a`
确认 PostgreSQL、MinIO、OpenSearch 均 healthy 且初始化任务 exit 0。真实纵向首次在 sandbox
内因受限 uv cache 权限失败，使用同一命令和隔离依赖在获批环境复跑通过；这些是执行环境
问题，不是产品断言失败。没有修改产品逻辑、删除测试或降低 fail-if-missing。全仓保留一个
既有 Authlib deprecation warning。最终使用 `down -v --remove-orphans` 删除精确命名的隔离
项目，并以 `compose ps -a` 空结果确认无残留；没有操作其他 Compose 项目或
production-local。

### 31.4 状态与下一边界

- [KNOWN | HIGH] TDD-04G 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前 TDD-04G 工作树未形成新 commit、merge、部署或 Production
  GO。
- [KNOWN | HIGH] 本片保持三层单一责任：KSS 持有事实，guarded client 校验和投影，BFF
  授权和委托。它不新增审计事实或状态权威，也不改变 Agent activation 权威。
- [FRAME | HIGH] 若继续下一片，优先单独冻结 controlled expiry HTTP/BFF；不要同时引入
  scheduler、Dashboard、Worker 常驻进程、artifact cleanup、正式 Agent publication 或生产
  切换。

## 32. TDD-04H：精确 Release Preparation 过期 BFF

### 32.1 冻结范围与分层

[FRAME | HIGH] 本片只把既有 `ready → expired` 事务公开为 exact-resource 命令：

```text
POST /v1/knowledge-spaces/{space}/knowledge-bases/{base}/release-preparations/{id}:expire
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{id}:expire
```

两个命令都不接受 request body 或 `Idempotency-Key`。ProofAgent BFF 要求
`knowledge_source.edit`；KSS 使用可信 operator authentication，并在 mutation 前读取 exact
Preparation、校验路径 Scope。成功返回 `200`、`state="expired"` 和同一 Preparation GET
`Location`。状态事务由 KSS PostgreSQL adapter 持有：锁定 exact row、使用数据库时间判断
`now >= expires_at`，验证 frozen candidate 后原子写入 expired 与一条 publication audit，
不创建 Release。

已经 expired 的 exact identity 自然重放同一 durable terminal state，不新增第二份 receipt
或重复 audit；不确定响应通过 exact GET 或相同 exact 命令恢复。网络合同故意不公开全局
`expire_next()`：该 application-only one-shot 会选择当前“下一个”到期候选，若暴露到网络，
一次响应不确定后的重试可能过期另一资源，不能作为 exact command 的重放语义。

本片保持三层：KSS 持有状态与审计权威，ProofAgent guarded client 严格验证 KSS wire、
identity/state/Location 并生成 secret-free 投影，BFF 只做 named permission 与同源委托。
没有新增 SQL、migration、依赖、scheduler、continuous process、Dashboard、artifact cleanup、
Agent formal publication、部署或生产配置。

### 32.2 RED → GREEN 与失败关闭合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| application tracer | `KnowledgeBasePreparationApplication` 没有 `expire()`，触发 `AttributeError` | 精确校验 identity/operator，并委托 transaction `expire_ready()`；due/replay `1 passed` |
| PostgreSQL tracer | transaction 缺少 exact expiry 方法，返回 `base_preparation_unavailable` | exact row lock、database time、candidate integrity 与既有原子终态原语；`1 passed` |
| KSS HTTP tracer | `:expire` 返回 `405 Method Not Allowed` | no-body、edit-protected、Scope-first mutation 与 same-resource `Location`；`1 passed` |
| guarded client tracer | concrete client 没有 expiry Interface，触发 `AttributeError` | exact POST、无 body/key，严格验证 expired identity/state/Location；`1 passed` |
| ProofAgent BFF tracer | exact same-origin path 返回 `405 Method Not Allowed` | `knowledge_source.edit`、no-body、安全投影；`1 passed` |
| public contract | canonical OpenAPI 保留旧 fingerprint | 新增 no-requestBody/expired-response 断言，指纹更新为 `cdb847191bc5f3658d4592f420852b1b990c5b7ca550b3138b07e69699b99ca2` |

负向合同覆盖 not-due、queued/non-ready、非法 operator/identity、缺少 edit permission、body、
路径 Space/Base 漂移、上游 identity/state/额外私有字段/foreign Location 漂移。八路并发 exact
调用全部返回同一 Preparation identity，只产生一个 expired 和一条 publication audit；already
expired replay 保留首次 transition operator，不用重试 operator 重写历史。真实纵向合同沿
BFF → guarded client → KSS HTTP → PostgreSQL 创建第三个 queued Preparation，经 one-shot
executor 进入 ready，再由测试 fixture 只把 exact candidate 的数据库 expiry 推到边界，最后
由 BFF expire/replay/GET 恢复同一终态。原已发布 Release 数量不变，浏览器投影不含 Worker、
lease、fence、artifact、credential 或 token。

### 32.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-preparation-expiry-bff-tdd04h`，端口为 PostgreSQL
`55477`、MinIO `59055`、OpenSearch `19245`。数据库 fixture 使用随机 schema，S3/Hybrid
使用隔离测试配置。没有读取 `.env`、生产配置、生产凭据、生产数据或生产日志。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 本片 focused RED/GREEN 与负向合同 | 29 passed、231 deselected | application/KSS/client/BFF/OpenAPI exact tracer |
| 六个直接受影响文件 | 260 passed | 隔离 PostgreSQL/MinIO/OpenSearch，包含真实 BFF vertical 与并发 |
| 全仓后端 | 2493 passed、24 个既有声明 skip、2 deselected | 退出码 0；默认排除的 Hybrid integrations 另行执行 |
| 显式 Hybrid integration | 2 passed、2517 deselected | 隔离 PostgreSQL/S3 互操作；不是生产流程证明 |
| Mypy / Ruff / format | 454 个产品源无类型错误；全量 Ruff；本片文件格式通过 | 无新增 ignore 或降低检查 |
| 前端 | TypeScript；Dashboard 225、Chat 35；UI/Dashboard/Chat build | 本片无页面；Chat 保留既有 600.22 kB warning |
| domain / diff / locks | domain-context、`git diff --check`；根 117、KSS 34 packages | 无 dependency 或 migration 变化；OpenAPI 变化已精确绑定 |

全仓和显式 Hybrid 均连接精确命名的隔离依赖并核对最终退出码。全仓保留一个既有 Authlib
deprecation warning；前端 Chat build 保留既有 chunk-size warning。没有修改产品逻辑、删除
测试或降低 fail-if-missing 来换取通过。最终使用 `down -v --remove-orphans` 删除精确命名的
隔离项目，并由 `compose ps -a` 空结果确认无残留；没有操作其他 Compose 项目或
production-local。

### 32.4 状态与下一边界

- [KNOWN | HIGH] TDD-04H 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。TDD-04H 后与 TDD-05A 按共同证据边界提交为 `5535a19`；没有
  push、merge、部署或 Production GO。
- [KNOWN | HIGH] 本片只关闭“操作员对一个已知 due-ready Preparation 做精确过期”的网络
  缺口，不建立自动回收责任，也不把 expired/artifact 状态解释为物理清理完成。
- [FRAME | HIGH] 若继续保持核心优先和简单分层，下一片应在 continuous execution/expiry
  process role 与 Formal Production Agent Candidate tracer 中单选其一重新冻结。前者先定义
  有界 `run_once` 驱动、健康与停止责任；后者开始跨越 KSS Release 到 exact Agent Draft 的
  正式发布权威，范围更大。不要与 Dashboard、artifact cleanup、Reference/lifecycle command
  或生产切换合并。

## 33. TDD-05A：精确 Formal Production Agent Candidate 只读装配

### 33.1 冻结范围与分层

[FRAME | HIGH] 本片只建立正式候选的 application-only tracer。调用方必须提交 named Agent、
exact Draft ID 和 exact Draft revision；Control 从 Agent Configuration Store 读取当前 exact
Draft，使用既有 `ProductionAgentPublicationConfigurationProjector` 对 live KSS catalog 和 live
Shared Model Connection facts 做完整重验，再把 Draft-owned exact KSS Release 与
deployment-owned Production KSS Binding Profile 组合为 immutable Formal Production Agent
Candidate。

Profile 只包含 binding identity、versioned Knowledge credential handle、Admission Scorer
identity/revision 和 `failure_mode="required"`，strict contract 拒绝任何额外 Release identity。
候选保留 exact Agent/Draft/revision、display/purpose、Contract Bundle、Draft KSS tuple、live
catalog revision、resolved KSS binding、既有 Contract+binding digest，以及额外绑定 Draft
identity/revision 的 formal candidate digest。读取流程不提交 Unit of Work，也不产生 audit、
Reference、Release Record、Published Version 或 Active pointer 变化。

本片没有修改既有 `ProductionAgentPublicationService` 的 manifest/environment Release 输入，
没有新增 HTTP、CLI、Dashboard、Release Operator 权限、production composition、配置、SQL、
migration、依赖或部署。正式 publisher cutover、KSS Reference-first ordering、Phase F、online
smoke 和 activation CAS 仍是后续切片。

### 33.2 RED → GREEN 与失败关闭合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| public contract tracer | `ProductionKssBindingProfile` 无法从公共 contracts 导入，测试 collection 失败 | 新增 strict Profile 与 immutable Formal Candidate contracts |
| exact Draft tracer | 仓库没有 formal candidate assembler | exact named Draft/revision 从 Configuration UoW 读取；stale/missing 在读取 KSS 前拒绝 |
| live revalidation | formal candidate 无 live catalog 重验路径 | 复用既有 projector；catalog failure、无 revision、非 ready、deprecated 或 parent tuple 漂移失败关闭 |
| authority split | deployment profile 可能夹带环境 Release | strict extra-forbid；resolved Release 只读取 Draft candidate，Profile 仅补 credential/scorer/binding facts |
| trace binding | 既有 Knowledge Release digest 不区分内容相同的 Draft revision | 保留既有 digest 供当前 Phase F 语义，并新增绑定 exact Draft root 与 catalog observation 的 formal digest |

负向合同还覆盖 unversioned credential、错误 Secret purpose 和上游异常 detail 不泄漏。相同
Contract/Release/Profile 在 Draft revision 11 与 12 下产生相同 Knowledge Release digest、不同
formal candidate digest，明确区分“可执行内容绑定”和“正式提交根”两个用途。

### 33.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 本片 focused RED/GREEN 与负向合同 | 10 passed | pure Control/contracts；无外部依赖 |
| 直接受影响 publication/Workspace/contracts | 115 passed | 既有 publisher 行为未改 |
| 全仓后端 | 2264 passed、263 dependency-conditioned skips、2 deselected | 退出码 0；本片不需要 PostgreSQL、KSS HTTP、S3 或 OpenSearch |
| Mypy / Ruff / format | 455 个产品源无类型错误；全量 Ruff；本片 Python 文件格式通过 | 无新增 ignore 或降低检查 |

首次沙箱内全量运行有 8 个既有 localhost-binding 测试因 `PermissionError` 失败；对应 4 个
文件在允许绑定 `127.0.0.1` 后 45 passed，随后同一环境的最终全量运行取得上述单次退出码 0。
该限制和重跑不涉及外部网络、生产依赖或生产数据。此前 TDD-04H 的隔离 PostgreSQL/KSS/S3/
OpenSearch 证据仍属于 04H，不冒充为本片的新依赖证据。

### 33.4 状态与下一边界

- [KNOWN | HIGH] TDD-05A 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。TDD-04H 与 TDD-05A 已按共同证据边界提交为 `5535a19`；没有
  push、merge、部署或 Production GO。
- [KNOWN | HIGH] 本片只关闭“从 exact Draft revision 形成可追溯正式候选”的缺口；现有正式
  publisher 仍可走独立 manifest/environment Release 路径，因此系统级唯一发布入口尚未成立。
- [FRAME | HIGH] 下一片建议为 TDD-05B candidate-bound Phase F preparation：只让新的正式
  发布准备路径消费 `FormalProductionAgentCandidate` 与 exact evidence，并证明 Phase F record
  绑定 `formal_candidate_sha256`，输出未持久化、未激活的 provisional version。不要在同片加入
  Reference registration、online smoke、activation、Delivery/Dashboard 或生产切换；Reference-first
  ordering 和原子激活留给后续切片。

## 34. TDD-05B：候选绑定的 Phase F 准备

### 34.1 冻结范围与分层

[FRAME | HIGH] 本片只新增 application-only、无持久化副作用的 Phase F preparation。Control
入口接受一个 TDD-05A `FormalProductionAgentCandidate`、Shadow/Capacity/Acceptance/Recovery
四类 exact evidence 和可信 actor；它先重算 Knowledge Release digest 与 formal candidate
digest，再解析候选 Contract 的 Workflow Stage 可用性与有效配置。

通过本地校验后，Control 封装 strict immutable Formal Phase F Record。该 Record 同时绑定
formal candidate digest、Knowledge Release digest、四类 evidence、创建身份与时间；四个
evidence digest 必须互不相同。只有独立 `FormalProductionAgentPhaseFAuthority` 明确返回批准，
入口才输出 `FormalProductionAgentPhaseFPreparation`。其中的
`ProvisionalProductionAgentVersion` 使用 `prepared_at/prepared_by`，保留 exact Draft revision、
resolved KSS binding、Phase F Record 和 Workflow Stage facts，但不声称 published 或 active。

本片没有修改既有 `ProductionAgentPublicationService`，没有写 Agent Store 或 audit，没有注册
KSS Reference、执行 online smoke、创建 `PublishedAgentVersion`、更新 Active pointer，也没有
新增 Delivery、Dashboard、production composition、配置、SQL、migration、依赖或部署。

### 34.2 RED → GREEN 与失败关闭合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| public contract tracer | 测试无法导入 `FormalProductionAgentPhaseFRecord`，collection 失败 | 新增 strict Phase F Record、Provisional Version 与 preparation contracts |
| candidate integrity | retained candidate 可在装配后被替换 digest | preparation 前重算两类 digest；任一漂移在 authority 调用前拒绝 |
| evidence binding | 既有 Release Record 只绑定 Knowledge Release digest | 新 Record 同时绑定 formal/Knowledge Release 两类 digest，并拒绝重复或漂移 evidence |
| workflow facts | provisional output 可能缺少可执行 Stage 事实 | 从 exact candidate Contract 解析 availability、effective config 和独立 source trace；不可解析则拒绝 |
| authority boundary | 本地构造 Record 可能被误认为批准 | 只有独立 authority 明确返回 `True` 才返回 preparation；deny 与 exception 使用稳定错误并失败关闭 |
| lifecycle wording | 复用 Published Version 会提前声称已发布 | 使用独立 Provisional contract 和 preparation metadata，不写 Store、不激活 |

负向合同覆盖 formal digest 篡改、Knowledge Release digest 篡改、重复 evidence、evidence
漂移、authority deny/exception，以及内容自洽但 Workflow Stage 不可解析的候选。失败路径不会
调用后续 authority，或在 authority 已被调用的 deny/unavailable 情况下返回任何 preparation；
异常 detail 不对外泄漏。

### 34.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 本片 focused RED/GREEN 与负向合同 | 18 passed | pure Control/contracts；无外部依赖 |
| 直接受影响 publication/Workspace/Workflow/contracts | 113 passed | 既有 publisher 与持久化行为未改 |
| 全仓后端 | 2272 passed、263 dependency-conditioned skips、2 deselected | 退出码 0；本片不需要 PostgreSQL、KSS HTTP、S3 或 OpenSearch |
| Mypy / Ruff / format | 456 个产品源无类型错误；本片 Ruff 与格式检查通过 | 无新增 ignore 或降低检查 |
| domain / diff | domain-context、`git diff --check` 通过 | 无 schema、migration、OpenAPI 或 lock 变化 |

首次沙箱内全量运行的 8 个既有 localhost-binding 测试因 `PermissionError` 失败；允许绑定
`127.0.0.1` 后，最终全量运行取得上述单次退出码 0。该重跑不使用外部网络、生产依赖、
生产凭据或生产数据。263 个 skip 是既有依赖条件跳过，不是本片通过证据。

### 34.4 状态与下一边界

- [KNOWN | HIGH] TDD-05B 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。本片改动尚未提交，没有 push、merge、部署或 Production GO。
- [KNOWN | HIGH] 本片只关闭“正式候选与 Phase F evidence/authority 之间的可追溯准备”缺口。
  现有正式 publisher 仍接受独立 manifest/environment Release；Provisional Version 也不是
  可执行或可回滚的 Published Version。
- [FRAME | HIGH] 下一片建议为 TDD-05C Reference-first formal publication staging：只让新的
  Control 编排消费本 preparation，为 provisional version 的 exact KSS Release 注册
  `published_agent_version` Reference，并保留注册成功但后续失败时的可对账孤儿 Reference。
  本片先不加入 online smoke、Published Version 写入、Active pointer CAS、Delivery/Dashboard
  或生产切换，以单独验证跨服务失败顺序和幂等身份。

## 35. TDD-05C：Reference-first 正式发布暂存

### 35.1 冻结范围与分层

[FRAME | HIGH] 本片只建立 application-only Reference staging。Control 入口接受一个 TDD-05B
`FormalProductionAgentPhaseFPreparation`，并依赖注入的
`FormalProductionAgentReleaseReferenceRegistrar` port。Control 不导入 KSS 服务内部 package，
不持有 KSS credential 或 transport。

入口在任何 registrar 调用前重验 Formal Candidate digest、Phase F Record digest 和 preparation
结构。Reference 请求只包含 Draft-owned exact Space/Base/Release、固定
`external_resource_kind="published_agent_version"`、provisional version ID 和固定
`purpose="execution_or_rollback"`。幂等 key 为
`formal-agent-reference:<provisional-version-id>`，由 Control 确定性生成，不接受调用方输入。

返回的 strict active Reference receipt 必须逐项匹配请求。Scope、Release、external resource、
purpose、kind 或 state 漂移均失败关闭。若 KSS 已完成注册但回执不可验证，Control 不做补偿性
注销；Reference 保守保留为后续 authenticated reconciler 可处理的安全孤儿。Staging 只保留
Phase F preparation 与 active Reference，不含 smoke、Published Version、Active pointer 或执行
权限。

本片不新增 KSS HTTP/BFF/production adapter，不写 Agent Store/audit，不修改现有 publisher，
也不新增 Delivery、Dashboard、production composition、配置、SQL、migration、依赖或部署。

### 35.2 RED → GREEN 与失败关闭合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| public contract tracer | 测试无法导入 `ProductionAgentReleaseReferenceRequest`，collection 失败 | 新增 strict request、active receipt、staging contracts 与 registrar port |
| exact registration | 尚无 Control Reference-first 入口 | 从 preparation 构造 exact request，以确定性 key 调用 registrar，并返回不含发布/激活声明的 staging |
| external resource integrity | 合法格式的 provisional version ID 漂移不会触发拒绝 | 第二个 RED 证明错误 Reference 可被注册；Phase F Record 随后绑定 provisional version 与 validation run identity |
| preparation integrity | retained candidate 或 Phase F Record 可能被内部复制后篡改 | 跨服务调用前重验 candidate、record 和 preparation；漂移时 registrar 调用数为零 |
| registrar failure | 上游异常可能泄漏 detail 或被误当作成功 | 映射为 `reference_registration_unavailable`，不返回 staging，不暴露私有 detail |
| receipt integrity | 上游可能返回另一 Scope/Release/resource 或非 active 状态 | strict 重建并逐项匹配；失败后保留已注册 Reference，不盲目注销 |
| replay | 重试可能生成新 key 或新 Reference | 相同 preparation 两次调用使用同一 key，并恢复同一 active Reference |

负向合同还覆盖 invalid external resource、unknown Release selection 字段、validation run ID 漂移、
kind/purpose 漂移，以及 receipt state 伪装。测试 fake 只模拟 port 行为；它不是 KSS transport、
KSS PostgreSQL 或生产授权证据。

### 35.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 本片 focused RED/GREEN 与负向合同 | 34 passed | pure Control/contracts；registrar 为本地 fake |
| 直接受影响 publication/Workspace/Workflow/contracts 与 KSS Reference core | 157 passed | 既有 publisher、KSS application 和持久化行为未改 |
| 全仓后端 | 2288 passed、263 dependency-conditioned skips、2 deselected | 退出码 0；允许既有 socket-bound tests 绑定 `127.0.0.1` |
| Mypy / Ruff / format | 457 个产品源无类型错误；全仓 Ruff；本片 Python 文件格式通过 | 无新增 ignore 或降低检查 |
| domain / diff | domain-context、`git diff --check` 通过 | 无 schema、migration、OpenAPI 或 lock 变化 |

全量运行保留一个既有 Authlib deprecation warning。没有连接外部网络、生产 KSS、生产
PostgreSQL、生产凭据或生产数据。263 个 skip 是既有依赖条件跳过，不是本片通过证据；本片也
没有新增需要前端验证的页面或合同。

### 35.4 状态与下一边界

- [KNOWN | HIGH] TDD-05C 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。TDD-05B 与 TDD-05C 当前均未提交，没有 push、merge、部署或
  Production GO。
- [KNOWN | HIGH] 当前证明的是 Reference-first Control ordering 和严格 port 合同，不是 KSS
  中已存在 durable Reference。没有 concrete transport/composition 时，formal publisher 仍未
  消费 staging，系统级唯一发布入口也未成立。
- [FRAME | HIGH] 下一片建议为 TDD-05D authenticated Reference registration transport：只新增
  KSS 受认证的 exact registration HTTP contract、ProofAgent guarded registrar adapter 和真实
  KSS application vertical，复用现有 PostgreSQL Reference 原子性。暂不加入 online smoke、
  Agent Store/Published Version、Active CAS、浏览器 BFF/Dashboard 或生产切换。

## 36. TDD-05D：受认证的 Reference 注册传输

### 36.1 冻结范围与分层

[FRAME | HIGH] 本片只实现 TDD-05C registrar port 的真实跨服务传输。KSS public client API
新增 `POST /v1/knowledge-base-release-references`，复用既有 Bearer client authentication 与
`Idempotency-Key`。Body 是 strict `RegisterKnowledgeBaseReleaseReferenceRequest`，不接受
`authenticated_client_id`；服务端只从认证结果取得 client identity。首次 ensure 与 exact replay
均返回 `200` 和同一 active `knowledge-base-release-reference.v1` resource。

[FRAME | HIGH] ProofAgent 使用独立 `KnowledgeSourceServiceReleaseReferenceRegistrar`：只接受
HTTPS origin，经 `GuardedHttpClient` 使用专用 client authorization factory 发出 exact JSON 和
Control-owned key，strict 解析 KSS wire response 后映射为
`RegisteredProductionAgentReleaseReference`。它不复用 management/operator credential 或 client。
KSS production-shaped runtime 使用既有 `PostgresReleaseReferenceRepository`，不新增 schema、
migration 或依赖。

本片不增加 BFF/Dashboard、formal publisher consumption、online smoke、Agent Store/audit、
Published Version、Active pointer CAS、deregistration/reconciler、生产 Secret/egress 配置、部署或
Git 提交。

### 36.2 RED → GREEN 与失败关闭合同

| 阶段 | 实际 RED | GREEN / 保护结果 |
| --- | --- | --- |
| KSS HTTP tracer | `create_application()` 不接受 `release_references`，测试 collection 后调用失败 | public client route 委托既有 application；首次与 exact replay 返回同一 Reference 和单审计 |
| public negative contract | `ReleaseReferenceError` 越过 FastAPI，Pydantic 默认 `422` 回显字段位置 | 认证/key/validation/conflict/not-admissible/storage-integrity 映射为稳定、无输入回显 problem |
| ProofAgent registrar tracer | concrete module 不存在，测试 collection 为 `ModuleNotFoundError` | 独立 HTTPS guarded adapter 发送 exact request/key，并把 strict KSS resource 映射为本地 receipt |
| wire integrity | 尚无 concrete response parser | redirect、非 `200`、过大/非法/unknown response，以及 Scope/Release/resource/kind/purpose/state 漂移全部失败关闭 |
| runtime/OpenAPI | runtime 未组合 Reference application，canonical contract 无 route | runtime 组合既有 PostgreSQL repository；OpenAPI 加入 request/response schema，fingerprint 更新为 `55abbced8899e32e4633fffb44a679aca6fc5f3b2dc14c4797d19f7d0fbaf187` |
| combined delivery isolation | management validation handler 覆盖 public Reference contract，真实 runtime 返回 `invalid_management_request` | runtime 按 public-client path 分发共享 validation/key handler；Reference 保持 `invalid_knowledge_service_request`，management 合同不变 |
| real vertical | 只有 in-memory HTTP 与 fake registrar 证据 | ProofAgent → guarded HTTP → KSS runtime → PostgreSQL 首次/重放收敛到同一 active Reference 与一条 audit |

负向合同覆盖缺失/无效 Bearer、空白或非法 key、key 改绑另一 external resource、Release Scope
漂移、caller-forged client identity、unknown request/response field、upstream status/redirect、响应
byte bound 和存储/完整性不可用。任何错误都不回显 credential、sentinel body 或内部数据库
error code；Reference 注册成功也不生成 Published/Active Agent Version。

### 36.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-reference-tdd05d`，只启动 PostgreSQL 17.5，loopback 端口
为 `55489`。fixture 为每项 KSS 和 ProofAgent PostgreSQL 测试创建随机 schema。没有读取
`.env`，也没有连接生产凭据、生产数据、生产服务或外部网络。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| KSS HTTP + ProofAgent registrar focused | 27 passed | in-memory KSS HTTP 与 guarded transport 正/负合同 |
| 直接受影响集 | 161 passed | 含 Reference core、真实 PostgreSQL repository/runtime、OpenAPI、Query HTTP 与 TDD-05C Control |
| 真实 PostgreSQL Reference/runtime | 39 passed | 含 ProofAgent-to-ledger exact replay 纵向；不是生产部署证明 |
| 全仓后端 | 2541 passed、37 dependency-conditioned skips、2 deselected | PostgreSQL 测试 fail-if-missing；S3/OpenSearch 等未提供依赖仍按既有声明 skip；退出码 0 |
| Mypy / Ruff / format | 458 个产品源无类型错误；全仓 Ruff；8 个本片 Python 文件格式通过 | 无新增 ignore 或降低检查 |
| domain / diff / contract | domain-context、`git diff --check`、canonical OpenAPI exact hash 通过 | migration、依赖和 lock 未变化 |

第一次真实纵向在默认沙箱内因本机 loopback 连接被拒绝，属于执行权限限制，不是产品 RED；
允许连接刚启动的隔离 PostgreSQL 后原测试为 `1 passed`。完整后端保留一个既有 Authlib
deprecation warning。37 个 skip 是未提供 S3/OpenSearch 等依赖的既有条件项，不是本片通过
证据。最终使用精确项目名执行 `down -v --remove-orphans`，再由 `compose ps -a` 空结果确认
容器、网络和临时卷无残留；未操作其他 Compose 项目或 production-local。

### 36.4 状态与下一边界

- [KNOWN | HIGH] TDD-05D 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。TDD-05B 至 TDD-05D 当前均未提交，没有 push、merge、部署或
  Production GO。
- [KNOWN | HIGH] 当前关闭的是“Reference-first staging 能通过受认证网络形成 durable KSS
  Reference”的缺口。KSS client identity 仍由 KSS 独立认证，ProofAgent 没有获得生命周期或
  注销权威。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05E 只建立 registered staging 之后的 exact
  online smoke Control port 与失败顺序：smoke 失败不得写 Published Version 或 Active pointer，
  已注册 Reference 保守保留。暂不同时实现 Store transaction、activation CAS、Delivery、
  Dashboard、reconciler 或生产切换。

## 37. TDD-05E：exact online smoke Control

### 37.1 冻结边界

[FRAME | HIGH] 本片只关闭“active Reference 已注册后，如何执行 exact online smoke 并在失败时
保持 publication/activation 零写入”的 Control 缺口。输入必须是 TDD-05C/05D 的 strict
`FormalProductionAgentReferenceStaging`，不能用 Phase F preparation、latest Release 或调用方
自报成功替代。Control 构造的 request 固定绑定 agent、provisional version、validation run、
formal/Knowledge Release digest、Space/Base/Release、active Reference ID 和非空 question；validator
只拥有执行 smoke 并返回结果的能力。

[FRAME | HIGH] 成功结果必须与 request 的 agent/version/run/Reference identity 完全一致，outcome
为 `ANSWERED_WITH_CITATIONS`，accepted citation count 至少为 1，并提供互不相同的 exact trace
与 receipt artifact。输出是 `FormalProductionAgentOnlineSmokeQualification`，明确不含
Published Version、Active Version 或 publication timestamp。本片不注入 Agent Store、Active
pointer、audit writer 或 KSS deregistrar，不增加真实 runner adapter、formal publisher cutover、
HTTP/CLI/Dashboard、Delivery、配置、SQL、migration、部署或 Git 提交。

### 37.2 RED → GREEN → REFACTOR

| 阶段 | 证据 | 结果 |
| --- | --- | --- |
| RED | 先增加 exact request/result/qualification、Reference-before-smoke、失败保留 Reference、identity drift、非 distinct evidence 和 unknown-field 合同测试 | 测试收集因 `FormalProductionAgentOnlineSmokeQualification` 尚不存在而失败，退出码 2 |
| GREEN | 增加 3 个 strict immutable contract、单一 `FormalProductionAgentOnlineSmokeValidator` port 和 application-only qualification service | 聚焦文件 43 项通过 |
| REFACTOR | 增加 inactive Reference 前置拒绝和 result agent identity drift；统一稳定错误，格式化新 Control 模块 | 聚焦文件最终 45 项通过；Ruff、format 和 Mypy 聚焦检查通过 |

实现后的顺序为：

1. 对 staging 进行 strict 重建，并重验 Formal Candidate 与 Phase F Record；
2. 确认 Reference contract 仍为 active 且与 exact preparation 匹配；
3. 规范化 question，由 Control 构造 exact smoke request；
4. 调用唯一 online validator port；
5. strict 重建结果，拒绝 unknown/malformed、identity drift、失败 outcome、零引用和 evidence 混用；
6. 只返回仍未发布、未激活的 qualification。

validator exception 映射为 `online_smoke_unavailable`；非法 staging、question、request、结果与失败
outcome 分别使用稳定 code，均不回显私有 runner detail。service 没有任何 publication、activation
或 deregistration port，因此失败路径结构上不能写 Published Version/Active pointer，也不能删除
已注册 Reference。测试中的 registrar ledger 在全部失败与不确定路径后仍保留同一 active
Reference。

### 37.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05E focused | 45 passed | exact smoke 正向、前置 active Reference、失败/漂移/异常、unknown field 和零副作用合同 |
| 直接受影响集 | 322 passed、4 skipped | Agent Configuration contracts/store/API、formal candidate/Phase F/Reference/smoke、旧 production publisher/readiness 与 Workflow Stage contracts |
| 全仓后端 | 2326 passed、263 dependency-conditioned skips、2 deselected、1 warning | 同一完整命令在允许 loopback 的环境退出码 0；无真实 KSS/model online runner |
| Mypy / Ruff / format | 459 个产品源无类型错误；`proof_agent`、KSS 与 tests 全量 Ruff 通过；4 个本片 Python 文件 format 通过 | 全仓 format baseline 仍有 251 个既有文件待格式化；本片未扩大处理 |
| lock / domain / diff | `uv lock --check`、domain-context、`git diff --check` 通过 | 无 dependency、lock、SQL 或 migration 变更 |

第一次全仓命令在默认沙箱内有 8 项失败，全部是 socket-bound 测试绑定 `127.0.0.1` 时收到
`PermissionError: [Errno 1] Operation not permitted`；不是产品断言失败。相同完整命令在允许
loopback 后通过。263 个 skip 是未提供 PostgreSQL/S3/OpenSearch 等真实依赖的既有条件项；本片
是 application-only Control，不以这些 skip 证明真实 online smoke。既有 Authlib deprecation
warning 保留。由于本片没有前端、OpenAPI、依赖或数据库变更，未重复 npm build/test、OpenAPI
fingerprint 或真实 PostgreSQL Compose 纵向。

全仓 `ruff format --check proof_agent knowledge_source_service tests` 报告 251 个既有文件会被
重排；本片 4 个变更 Python 文件单独检查通过。为避免把全仓机械格式化混入核心切片，没有修改
这些无关文件，也不把全仓 format 记为通过。

### 37.4 状态与下一边界

- [KNOWN | HIGH] TDD-05E 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。TDD-05B 至 TDD-05E 当前均未提交，没有 push、merge、部署或
  Production GO。
- [KNOWN | HIGH] 当前只证明 registered staging 后的 exact smoke port、成功 qualification 和
  失败顺序。没有真实 online runner、Published Version persistence、publication audit、Active
  pointer CAS、Delivery 或生产 composition。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05F 让唯一 formal publisher 编排已完成的
  candidate → Phase F → Reference → smoke 链，并在 smoke 前冻结 Active pointer expectation，
  最后以一个 PostgreSQL transaction 原子写入 immutable Published Version、publication audit 和
  Active CAS。仍不加入 HTTP/Dashboard、Delivery、reconciler 或生产切换。

## 38. TDD-05F：formal publisher core 与原子激活

### 38.1 冻结边界

[FRAME | HIGH] 本片只关闭“已经分片验证的 exact candidate → Phase F → Reference → smoke
如何汇入一次不可分割的 Published Version/Active/audit 提交”的 application core 缺口。新的
`FormalProductionAgentPublisher` 依次调用既有四个 Control 服务，不允许调用者传入独立
manifest、latest Draft、环境选择的 Release、Active expectation 或上游自报通过结果。

[FRAME | HIGH] Phase F 通过后、首次持久副作用 Reference 注册前，publisher 使用短只读
Configuration UoW 读取唯一生产 Agent 的 Active pointer expectation 并立即关闭事务。Reference
注册与 online smoke 期间不得持有数据库事务。smoke 通过后，最终一个 Configuration UoW 必须
同时执行 exact Draft revision check、Active pointer CAS、immutable Published Version 与 activation
写入、trace-safe publication audit，并且仅全部成功后 commit。

[FRAME | HIGH] Published Version 新增单一 strict formal evidence envelope，保留 exact Draft
revision、Formal Phase F Record、active Release Reference receipt 和 exact online smoke result。
本片复用既有 repository/UoW，不新增 SQL/migration，也不修改旧 manifest publisher、Delivery、
runtime composition、HTTP/CLI/Dashboard、reconciler/deregistration、生产配置或部署。真实 online
runner 与持久化幂等的公开正式发布命令继续后置；因此该 core 还不是可安全重试的网络入口。

### 38.2 RED → GREEN → REFACTOR

| 阶段 | 证据 | 结果 |
| --- | --- | --- |
| RED | 先增加 publisher tracer，要求 exact evidence、短只读 Active snapshot、Reference/smoke 期间零事务、最终单事务提交 | 测试收集因 `FormalProductionAgentPublicationEvidence` 不存在而失败，退出码 2 |
| GREEN | 增加 strict evidence envelope、Published Version/AgentPublicationRecord 交叉校验和 application-only publisher | 聚焦测试先达到 46 项通过 |
| REFACTOR | 增加 Draft/Active 并发漂移、audit 回滚、smoke 失败、外来 Active Agent、unknown-field/evidence drift、formal record CAS 负向合同，并补 PostgreSQL round-trip | 聚焦测试最终 53 项通过；真实 PostgreSQL repository/UoW 12 项通过 |

实现后的关键顺序为：

1. 从 exact Agent/Draft revision 装配候选，并完成 candidate-bound Phase F；
2. 通过短只读 UoW 冻结 `ActiveAgentPointerExpectation`，验证唯一生产 Agent 约束；
3. 关闭事务后执行 Reference-first registration 与 exact online smoke；
4. 构造 strict formal evidence、`PUBLISHED` operation audit、Published Version 和 publication audit；
5. 在最终一个 UoW 内执行 Draft revision check、Active CAS、Version/activation/audit 写入与 commit；
6. 对 repository 返回值进行 strict 重建和完全一致性校验，任何异常由 UoW 回滚。

Draft revision 或 Active pointer 在外部调用期间漂移时，最终 CAS 稳定失败且不留下部分
Version/Active/audit。audit/storage exception 同样回滚最终事务。已经成功注册的 KSS Reference
有意保留，用于后续可信对账，不做无权威的补偿注销。

### 38.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05F focused | 53 passed | exact evidence、顺序、并发、回滚、失败关闭和无部分写入 |
| 真实 PostgreSQL repository/UoW | 12 passed | formal evidence JSON round-trip、Draft revision check、Active CAS 与 UoW 原子性 |
| 直接受影响集 | 373 passed、4 dependency-conditioned skips | Agent contracts/store/workspace、formal chain、旧 publisher/readiness、PostgreSQL repository/UoW |
| 全仓后端 | 2561 passed、37 dependency-conditioned skips、2 deselected、1 warning | 隔离 PostgreSQL 强制启用；退出码 0；S3/OpenSearch 等未提供依赖仍按既有声明 skip |
| Mypy / Ruff / format | 460 个产品源无类型错误；全仓 Ruff 通过；6 个本片 Python 文件 format 通过 | 无新增 ignore；未把 251 个既有全仓 formatter 差异混入本片 |
| lock / domain / diff | `uv lock --check`、domain-context 通过；文档完成后重跑 `git diff --check` | 无 dependency、lock、SQL 或 migration 变更 |

隔离 Compose 项目为 `proofagent-formal-publication-tdd05f`，只启动 PostgreSQL 17.5，loopback
端口为 `55490`。默认沙箱中的首次数据库命令因 loopback 访问收到 `Operation not permitted`，
12 项均停在 fixture connection，未进入产品断言；允许连接同一隔离实例后原命令 12 项全部
通过。完整后端保留一个既有 Authlib deprecation warning。最终对精确项目执行
`down -v --remove-orphans`，再由 `compose ps -a` 只有表头确认容器、网络与临时卷无残留；未操作
其他 Compose 项目、生产凭据、生产数据或 production-local。

### 38.4 状态与下一边界

- [KNOWN | HIGH] TDD-05F 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前工作区还包含此前 TDD-05B 至 TDD-05E 的未提交改动；本片没有
  commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] 当前只证明新的 formal publisher core 能消费 exact qualification 并原子写入
  Published Version、Active pointer 与 audit。旧 manifest publisher 仍存在，runtime/Delivery
  没有切换到该 core，因此尚不能称为系统级唯一正式发布入口。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05G 只实现真实 online smoke runner adapter，
  复用既有 governed execution 路径并返回 exact trace/receipt/citation facts。仍不同时加入公开
  publication command、幂等 receipt、Dashboard、reconciler 或生产切换；待真实 runner 边界独立
  验证后，再为正式发布入口设计持久化幂等命令。

## 39. TDD-05G：governed online smoke runner adapter

### 39.1 范围与权威边界

[KNOWN | HIGH] 本片只关闭 TDD-05E validator port 到既有 governed execution 的 concrete adapter。
Control 把自身已重验的 `FormalProductionAgentReferenceStaging` 与 strict request 一并传入 runner；
runner 再次验证 Agent、provisional version、validation run、两类 candidate digest、Space/Base/Release
和 active Reference identity，不通过 mutable latest lookup 或全局候选注册表恢复执行输入。

[KNOWN | HIGH] Runner 从 provisional `ContractBundle` 安全物化私有只读临时 Agent package，拒绝
路径穿越和 core contract shadow，然后用 `RunPurpose.VALIDATION`、exact run ID、exact resolved KSS
binding、冻结的 Workflow Stage runtime facts 和部署注入的 Institution Authorization 调用既有
`execute_published_agent_run` 路径。它只计数同时满足 `accepted` 与非空 citation 的 Evidence Chunk；
Trace/Receipt 必须是非空、有大小上限的普通文件，并分别写入 immutable artifact store 后 exact
read-back。是否形成 qualification 仍由 TDD-05E Control 的 cited-answer Gate 决定。

[FRAME | HIGH] 本片没有增加 SQL/migration、KSS API、public Delivery/HTTP/CLI/Dashboard、公开且
持久化幂等的 formal publication command、旧 manifest publisher/runtime composition 切换、
reconciler/deregistration、生产 Secret/egress 配置或部署。测试执行边界使用受控 fake，因而证明的是
concrete production-path adapter 合同，不是真实 KSS/model 上游联机或 Production GO。

### 39.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | Tracer 导入并实例化 `FormalProductionAgentOnlineSmokeRunner`，要求 exact governed validation、citation 计数、immutable Trace/Receipt 与临时目录清理 | 聚焦测试在收集阶段因目标类不存在产生 `ImportError`，退出码 2 |
| GREEN | 增加 staging-aware validator port、共享 governed smoke runtime、safe ContractBundle materializer 与 concrete runner | 初始聚焦 54 项通过；旧 validator 与 materializer 兼容集 14 项通过 |
| REFACTOR | 增加无有效 citation、request/staging Release 漂移、artifact exact read-back 失败合同，并移除未消费的运行统计 | 聚焦测试最终 57 项通过；核心受影响集 76 项通过 |

关键失败顺序为：

1. Control 先验证 staging 并构造 strict request；
2. runner 在任何执行前重验 request/staging/candidate/Phase F exact identity；
3. ContractBundle 只在私有临时目录按安全路径物化并加载；
4. governed execution 只以 `VALIDATION` purpose 和 exact run identity 运行；
5. 本地 Trace/Receipt 通过边界检查后才写 immutable store 并 exact read-back；
6. runner 返回事实，Control 独立判断 outcome 与 cited count；失败不注销 KSS Reference。

### 39.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05G focused | 57 passed | tracer、strict identity、citation、artifact、cleanup 与稳定失败合同 |
| 核心兼容集 | 76 passed | formal chain、旧 production validator、materializer、run execution 与 snapshot |
| 直接受影响集 | 144 passed、15 dependency-conditioned skips | Agent contracts、formal chain、KSS Reference transport/composition、PostgreSQL repository 默认门控 |
| 全仓后端 | 2338 passed、264 dependency-conditioned skips、2 deselected、1 warning | 同一完整命令在允许 loopback 的环境退出码 0；无真实 KSS/model 上游联机 |
| Mypy / Ruff / format | 460 个产品源无类型错误；全仓 Ruff 通过；4 个本片 Python 文件 format 通过 | 无新增 ignore |
| lock / domain / diff | `uv lock --check`、domain-context、`git diff --check` 通过 | 无 dependency、lock、SQL 或 migration 变更 |

默认沙箱首次完整回归有 8 项既有测试因禁止绑定 `127.0.0.1` 返回 `Operation not permitted`；在
允许 loopback 的环境重跑完全相同命令后全绿。完整套件保留一个既有 Authlib deprecation warning。
TDD-05G 不改 SQL、repository 或 transaction，因此没有重复启动 TDD-05F 已验证的隔离 PostgreSQL
Compose，也没有用默认 skip 外推数据库或生产上游证据。无前端、OpenAPI 或依赖变更，故未运行
Dashboard build、OpenAPI snapshot 或依赖安装。

### 39.4 状态与下一边界

- [KNOWN | HIGH] TDD-05G 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树尚未形成新 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] 当前 concrete runner 已可把 exact staging 交给现有受治理执行链并保留可验证
  Trace/Receipt/citation 事实，但旧 manifest publisher/runtime composition 尚未切换，也没有真实
  KSS/model 上游环境证据。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05H 只设计并实现公开 formal publication
  command 与 durable `Idempotency-Key` receipt，使重试能恢复同一最终结果或稳定失败。该切片将涉及
  新的持久化权威与网络入口，需先冻结 exact request、receipt、并发和失败恢复边界；runtime cutover、
  Dashboard 和生产部署继续留在后续独立切片。

## 40. TDD-05H：持久化幂等的公开正式发布命令

### 40.1 冻结边界

[KNOWN | HIGH] 本片新增服务端命令
`POST /api/config/agents/{agent_id}/drafts/{draft_id}/formal-publications`，只允许
`agent.publish`。路径提供 Agent/Draft identity，strict body 只接受 exact Draft revision、四类
`KnowledgeReleaseEvidenceSet` 和 online smoke question；操作者来自可信 OIDC 上下文，
`ProductionKssBindingProfile` 只能由部署注入。调用方不能提供 Profile、Release/Version/Run/
Reference/Active identity、actor、timestamp 或结果。

[KNOWN | HIGH] 幂等范围固定为 `(actor subject, Idempotency-Key)`，canonical fingerprint 绑定路径与
strict body。首次请求先在短 PostgreSQL transaction 写入 `in_progress` receipt 并 commit，再执行
Phase F、KSS Reference 注册与 online smoke。exact replay 返回同一 durable receipt；不同
fingerprint 在外部调用前返回稳定冲突；进程在终态前退出时保留 `in_progress`，本片不按超时自动
接管或重跑。

[KNOWN | HIGH] 成功 receipt 与 immutable Published Version、Active CAS、publication audit 在同一个
最终 Configuration UoW 内完成。失败 receipt 在外部调用结束后的独立短事务完成；如果最终提交结果
不确定而数据库已保存成功，终态读取返回原成功结果，不能降级为失败。公开 receipt 不包含
Idempotency-Key、原始问题、Evidence/Bundle、Secret、上游详情或 artifact bytes。

[FRAME | HIGH] 本片不增加 Dashboard、GET/list/cancel、自动恢复器、lease/takeover、删除/保留任务、
新 KSS API、生产 Secret 配置、真实上游部署或旧 publisher/runtime 的系统级切换。`create_app` 只提供
可注入 command seam；生产角色 composition 尚未装配 concrete command，所以该网络合同还不是当前
生产栈的唯一发布入口，也不构成 Production GO。

### 40.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | 先增加公开命令 Tracer，要求 success receipt、exact replay 与外部调用只执行一次 | 聚焦测试收集因 `FormalProductionAgentPublicationCommandRequest` 不存在而失败，退出码 2 |
| GREEN-1 | 增加 strict request/result/receipt、actor-scoped canonical fingerprint、短事务 reservation、稳定失败完成和 publisher 事务内 success completion | formal chain 聚焦文件先达到 58 项通过 |
| RED-2 | 增加稳定失败 replay，要求保留 online-smoke 的稳定 code | 首次得到 `formal_publication_command_unavailable`，1 failed、62 passed |
| GREEN-2 | 命令服务显式保留 candidate/Phase F/Reference/smoke/publisher 的稳定错误 code | formal chain 最终 63 项通过 |
| RED-3 | 增加真实 PostgreSQL reservation/terminal/UoW 合同 | 测试收集因 PostgreSQL command repository 不存在而失败，退出码 2 |
| GREEN-3 | 增加 `0022_formal_publish_cmd`、repository 与 Configuration UoW 接线 | 真实 PostgreSQL migration/repository/UoW/concurrency 9 项通过 |
| RED-4 | 增加 public HTTP success/replay/in-progress/failure/权限/strict-body 合同 | 4 项均因 endpoint 尚不存在返回 404 |
| GREEN-4 | 增加 `agent.publish` 保护的公开 endpoint、稳定状态码和 trace-safe payload | HTTP 聚焦 4 项通过 |
| REFACTOR | 增加 changed-request、process-exit、terminal non-downgrade、receipt-write rollback、nested private input 和并发同键合同；全仓回归发现并修正 production-local 显式迁移 head | 受影响集 170 项通过；最终全仓 2578 项通过 |

命令执行顺序为：

1. 校验 strict body、actor、Idempotency-Key，并计算 path/body canonical SHA-256；
2. 以 `(actor subject, key)` 原子预留 durable `in_progress` receipt 并关闭事务；
3. replay 直接返回现有终态或 `202 in_progress`，fingerprint 不同则在外部调用前拒绝；
4. 新命令调用既有 exact candidate → Phase F → Reference → governed smoke → formal publisher；
5. 成功时在最终 UoW 内原子提交 Version、Active CAS、command success receipt 和 audit；
6. 已知或未知失败只持久化稳定 code，且终态 repository 永不覆盖既有成功或失败。

### 40.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05H formal command focused | 63 passed | success/exact replay、changed request、process exit、稳定失败、原子 rollback、strict input |
| 真实 PostgreSQL migration/repository/UoW | 9 passed | empty-to-head/repeat migration、并发同键唯一创建者、terminal non-downgrade、未 commit 回滚 |
| 直接受影响集 | 170 passed、1 warning | Agent contracts/formal chain/Delivery、安全 composition、production roles、PostgreSQL agent/UoW/migration |
| 全仓后端 | 2578 passed、37 dependency-conditioned skips、2 deselected、1 warning | 强制使用隔离 PostgreSQL；退出码 0；skip 仍是未提供的其他外部依赖 |
| Mypy / Ruff / format | 367 个产品源无类型错误；全仓 Ruff 通过；15 个本片 Python 文件 format 通过 | 无新增 ignore；保留既有未触及 formatter baseline |
| lock / domain | `uv lock --check`、domain-context 通过 | 无依赖或 lock 变化 |

隔离 Compose 项目为 `proofagent-formal-command-tdd05h`，只启动 PostgreSQL 17.5，loopback 端口为
`55491`。默认沙箱首次数据库命令因 loopback 访问收到 `Operation not permitted`，未进入产品
断言；允许连接同一隔离实例后 migration/repository/UoW 9 项全部通过。首次全仓回归进一步暴露
`docker-compose.production-local.yml` 的显式 target 仍为 `0021_metadata_workbook_v2`；只把该
production-like 本地迁移任务更新到新 expand-only head `0022_formal_publish_cmd` 后，目标测试
20 项和最终全仓均通过。正式 Blue/Green 示例、发布候选 schema 和部署授权未在本片修改。
最终只对精确项目执行 `down -v --remove-orphans`；随后 `compose ps -a` 仅有表头，确认容器、
网络和临时卷无残留，未操作其他 Compose 项目或生产数据。

完整套件保留一个既有 Authlib deprecation warning。没有真实 KSS/model online 调用、生产 OIDC、
Vault、发布候选构建、部署演练、Dashboard 或浏览器验证；这些缺口不能由本地数据库和 fake 上游
合同外推。

### 40.4 状态与下一边界

- [KNOWN | HIGH] TDD-05H 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树尚未形成新 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] 现在已有公开、严格且持久化幂等的正式发布命令合同；成功 receipt 与
  Version/Active/audit 原子提交，失败和不确定路径可稳定 replay。进程退出后留下的 `in_progress`
  不会自动超时接管，这是明确的安全保守状态，不是已完成恢复。
- [KNOWN | HIGH] production role 尚未注入 concrete command，旧 manifest publisher/runtime 仍存在，
  因此当前只证明 application/Delivery/persistence 闭环，不宣称系统级唯一发布入口或真实上游可用。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05I 只完成 production composition cutover：从
  部署权威装配 exact Binding Profile、concrete online runner 与新 command，关闭旧正式 publisher
  的并行入口，并用 composition/negative tests 证明 production API 缺依赖即启动失败。后台
  reconciler、Dashboard 和真实环境 smoke 仍分别后置。

## 41. TDD-05I：production composition cutover

### 41.1 冻结边界

[KNOWN | HIGH] 本片只把 TDD-05H 的 durable formal publication command 接入 production API
composition root。装配依赖为 PostgreSQL Configuration UoW、live KSS catalog、deployment-owned
`ProductionKssBindingProfile`、独立 Phase F authority、专用且版本化的 KSS Reference service-client
credential、TDD-05G governed online smoke runner、immutable artifact store、model/runtime dependencies
和可信 Institution Authorization。Draft 继续独占 exact Release 选择；部署 Profile 不接受 Release。

[KNOWN | HIGH] `create_app(mode="production")` 把 formal command 作为启动强制依赖。旧
`production-publish-agent` manifest CLI 和 `compose_production_agent_publisher` production composition
被移除，不能再绕过 exact Draft、Reference-first chain 与 durable command receipt。Development
仍允许不注入 command，调用该 endpoint 时保持既有稳定不可用结果。

[FRAME | HIGH] 本片不增加 SQL/migration、command recovery/takeover、GET/list/cancel、Dashboard、
reconciler/deregistration、runtime revocation、真实 KSS/model 联机、production Compose/Blue-Green
配置、secret 值、部署或 Git 提交。当前 checked-in production-local 尚未提供新要求的 dedicated
Reference client Secret/Grant，因此该环境会在 composition 阶段失败关闭；本片不能被解释为生产
发布或 Production GO。

### 41.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | production `create_app` 缺 formal command 必须启动失败 | 测试预期 `ValueError`，实际未抛出；1 failed |
| GREEN-1 | 把 formal command 加入 production exact-composition required set | 单项通过 |
| RED-2 | 要求 Phase F concrete authority、新 formal command composition、旧 composition/CLI 不可达 | 分别得到 missing method、missing composition helper、旧 symbol 仍存在、旧 CLI 仍解析；4 failed |
| GREEN-2 | 装配 exact chain、复用 guarded Phase F verifier、移除旧 production entry | 6 项 composition/entry tracer 通过 |
| REFACTOR | 增加专用 Reference client identity/version 断言、secret version drift 失败关闭和 Release 不来自部署 Profile 的合同 | 最终聚焦 16 项通过；受影响集 180 项通过、13 skips |

生产装配顺序为：

1. 构造 PostgreSQL UoW、runtime shared assets、guarded egress、Vault Secret Provider 与 KSS runtime；
2. 从部署值构造不含 Release 的 strict Binding Profile；
3. 以独立 evaluator Secret Handle 装配 Phase F authority；
4. 以独立、版本化 Reference client Secret Handle 装配 guarded KSS registrar；
5. 注入 governed smoke runner、artifact store、model/runtime dependencies 与 Institution Authorization；
6. 形成 formal publisher 和 durable command，并作为 production `create_app` 强制依赖注入。

### 41.3 验证结果与限定

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05I focused | 16 passed、1 existing warning | production required dependency、exact chain、dedicated client/version drift、旧入口移除 |
| 直接受影响集 | 180 passed、13 dependency-conditioned skips、1 warning | production roles、安全 composition、formal chain、Reference registrar、公开 API 与 CLI |
| 全仓后端 | 2354 passed、267 dependency-conditioned skips、2 deselected、1 warning | 8 个 socket-bound 用例在 loopback-capable 环境重跑后进入并通过产品断言；退出码 0 |
| Mypy / Ruff | 367 个产品源无类型错误；全仓 Ruff 通过 | 无新增 ignore |
| lock / domain / diff | `uv lock --check`、domain-context、`git diff --check` 通过 | 无依赖、lock、SQL 或 migration 变化 |

默认沙箱首次完整回归有 8 项测试在绑定 `127.0.0.1` 时收到 `Operation not permitted`，当时已有
2346 项通过、267 项依赖条件跳过；它们尚未进入产品断言。允许 loopback 后以完全相同的完整命令
重跑，最终 2354 项通过。完整套件保留一个既有 Authlib deprecation warning。因本片没有修改
SQL、repository、transaction 或 migration，未重复启动隔离 PostgreSQL；267 个 skip 不作为外部
依赖通过证据。

没有连接真实 KSS/model、生产 OIDC/Vault、生产 PostgreSQL/S3 或生产数据，也没有构造真实发布
候选、调用 formal endpoint、运行 deployment rehearsal、Dashboard 或浏览器验证。专用 Reference
credential 的测试只使用受控 fake，并证明 handle/version 隔离和失败关闭，不证明真实 Secret 或
KSS client Grant 存在。

### 41.4 状态与下一边界

- [KNOWN | HIGH] TDD-05I 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。production API 已成为 durable formal command 的唯一 production
  composition root；旧 manifest CLI/composition 已移除。当前累计工作树没有新 commit、push、
  merge、部署或 Production GO。
- [KNOWN | HIGH] checked-in production-local 配置尚未声明 dedicated Reference client Secret
  Handle/version，也没有证明 KSS 存在匹配 client identity/Grant。实际启动将按设计失败关闭；不能用
  fake composition 测试外推生产可用性。
- [FRAME | HIGH] 下一片若继续保持简单，建议 TDD-05J 只补 production-local dedicated Reference
  client 配置合同与隔离 KSS client/Grant vertical：证明 API composition 能启动且 registrar 只以该
  client 注册 exact Reference。仍不执行真实 model smoke、正式 Agent publication、stuck-command
  recovery、Dashboard、生产部署或 Production GO。

## 42. TDD-05J：production-local dedicated Reference client

### 42.1 冻结边界

[KNOWN | HIGH] 本片只补 checked-in production-local 的专用、版本化 Reference client Secret
Handle、独立 Vault fixture、KSS service-client identity bootstrap 和隔离注册纵向。KSS migration
成功后，一次性 bootstrap 必须先幂等注册 client identity，KSS API 才能启动。production formal
composition 必须拒绝 Reference Handle 与 Knowledge Operator 或 runtime Query Handle 复用。

[KNOWN | HIGH] 当前 `knowledge_client_grants` 只表达 exact-Release Knowledge Query Grant；
Reference registration 的现有授权边界是已认证 service-client identity。本片不把 Query Grant
误写成 Reference Grant，也不为专用 Reference client 创建查询权限。纵向必须证明该身份能注册
exact Reference，但在没有 Query Grant 时无法创建 Knowledge Query。

[FRAME | HIGH] 本片不调用 formal publication endpoint，不创建或激活 Published Agent Version，
不运行真实模型或完整 online smoke，不新增 KSS 管理 API、Query Grant provisioning、SQL migration、
reconciler、Dashboard、恢复器或生产部署。验证不读取 `.env`、secret 值、生产数据或生产日志，
也不启动或修改既有 `proofagent-production-local` 项目。

### 42.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | production-local 必须声明专用 Reference client bootstrap、Secret Handle/version 与 Vault fixture | 聚焦测试读取 Compose 时缺少 `kss-reference-client-bootstrap`，1 failed |
| GREEN-1 | 增加独立 fixture、Handle locator、一次性 KSS bootstrap 和 KSS API 启动依赖 | 原聚焦测试通过；Compose config 通过 |
| RED-2 | Reference Handle 复用 runtime Query 或 Operator Handle 时必须启动失败 | 2 个参数化用例均未抛错，2 failed |
| GREEN-2 | production formal composition 显式拒绝两类 Handle 复用 | 正向装配与 2 个负向用例共 3 项通过 |
| RED-3 | production-local 必须提供 TDD-05I composition 已要求的 Phase F evaluator endpoint | 配置合同缺少 `PA_KNOWLEDGE_EVALUATION_ENDPOINT`，1 failed |
| GREEN-3 | 绑定既有本地受管 evaluator origin `https://models.internal:9448` | 聚焦配置合同通过 |
| REFACTOR | 把 bootstrap 收拢到 KSS 自身模块；增加 secret 不回显、专用 owner receipt、exact replay 和无 Query Grant 的 `403` 保护 | 聚焦 5 项、隔离 vertical 1 项、受影响 593 项通过 |

一次性 bootstrap 只解析部署注入的 PostgreSQL DSN、trace-safe client ID 和受控 secret 输入，调用
`PostgresKnowledgeAccessControl.register_client`。KSS 只持久化 credential digest；标准输出只包含
client ID，不包含 credential。相同 identity/credential 可幂等重放，漂移仍由既有 access-control
冲突合同失败关闭。

### 42.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-reference-tdd05j`，只启动 PostgreSQL 17.5；测试使用显式
loopback 端口和仓库测试身份。KSS 与 ProofAgent fixtures 为每项 PostgreSQL 测试创建随机 schema。
没有读取 `.env`，也没有连接生产凭据、生产数据、生产服务或外部网络。验证结束后，只对该项目
执行 `down --volumes --remove-orphans`；随后 `compose ps --all` 返回空清单。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05J focused | 5 passed、1 existing warning | Compose/Vault/bootstrap、dedicated Handle、secret 不回显、Handle 复用失败关闭 |
| PostgreSQL/KSS/registrar vertical | 1 passed | exact Reference 首次/重放、专用 authenticated owner、无 Query Grant 时稳定 `403` |
| 直接受影响集 | 593 passed、13 dependency-conditioned skips、1 warning | KSS contracts、formal chain、Reference registrar、production composition；未提供 S3/OpenSearch |
| 全仓后端 | 2588 passed、37 dependency-conditioned skips、2 deselected、1 warning | PostgreSQL 测试全部要求执行；未提供的 S3/OpenSearch 等依赖仍按既有声明 skip |
| Mypy / Ruff / format | 368 个产品源无类型错误；全仓 Ruff；6 个本片 Python 文件 format-clean | 无新增 ignore |
| lock / Compose / domain / diff | `uv lock --check`、production-local `compose config --quiet`、domain-context、`git diff --check` 通过 | 无依赖、lock、SQL 或 migration 变化 |

第一次 PostgreSQL-enabled 全仓命令把 ProofAgent SQLAlchemy DSN 写成 `postgresql://`，76 个
fixture 在产品断言前因未安装 `psycopg2` 报错，当时已有 2512 项通过。该结果不计为完整通过。
把同一隔离数据库的 ProofAgent DSN 更正为项目要求的 `postgresql+psycopg://` 后，原测试集合
最终 2588 项通过。完整套件只保留一个既有 Authlib deprecation warning。

没有构造正式发布请求，没有启动 production-local 全栈，没有调用真实 KSS/model 上游，也没有
验证 OIDC、Vault server、TLS gateway、S3 artifact retention、浏览器或发布 Gate。checked-in
fixture 只证明配置合同和隔离纵向，不能外推生产 Secret、真实 runtime Query Grant 或服务可用性。

### 42.4 状态与下一边界

- [KNOWN | HIGH] TDD-05J 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。production-local 已有专用 Reference client 的 Secret/identity 配置
  合同，KSS API 启动依赖该 identity bootstrap，production composition 也会拒绝 Handle 复用。
  当前累计工作树没有新增 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] 专用 Reference client 没有 Query Grant，这是预期的最小权限结果，不是缺少
  Reference Grant。formal online smoke 仍需要另一个 runtime Query client 的 exact-Release Query
  Grant；本片没有提供、伪造或绕过该权威。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05K 只设计并实现 runtime Query client 的
  exact-Release Grant provisioning seam 与隔离 online-query vertical。先证明 Grant 绑定 Draft
  选择的 exact Release、Space 和预算，且不能扩大或复用 Reference credential；仍不执行正式
  Agent publication、真实模型 smoke、Dashboard、恢复器或生产部署。

## 43. TDD-05K：runtime Query client exact-Release Grant provisioning core

### 43.1 冻结边界

[FRAME | HIGH] 本片只新增 KSS application-only、secret-free Query Grant provisioning
core，复用既有 `knowledge_client_grants` PostgreSQL 权威，不新增 migration。受信
composition 以 immutable policy 注入已注册 runtime client identity、allowed strategies、
最大 execution budget 和 effective access-scope digest。每次 provisioning 调用只接受
Draft 后续传入的 exact `knowledge_base_release_id`；不接受 client、credential、Space、
strategy、budget 或 scope。

[FRAME | HIGH] KSS 必须从 exact Release 权威反推 Space 并返回 strict、secret-free
receipt。Grant identity 由 policy 与 exact Release 全部事实内容寻址生成；同事实
精确重放，不同 policy 不得对同一 client/Release 原地扩权。隔离纵向必须
证明 runtime credential 只能查询获授 exact Release 并且不超过 Grant 预算；
另一 queryable Release、超预算请求和专用 Reference credential 均必须失败关闭。

[FRAME | HIGH] 本片不新增 KSS HTTP/管理 API、ProofAgent transport、formal publisher
composition、Compose/Vault/egress/TLS 或 Dashboard，不调用 formal publication endpoint，不运行
真实模型、不部署且不提交 Git。验证只使用独立 PostgreSQL schema、本地 KSS
HTTP application 和受控 fixture；不读取 `.env`、secret 值、生产数据或日志。

### 43.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | 现有 runtime 纵向必须经过 application-only Grant provisioning seam，不再直接手工写 Grant | 聚焦测试收集失败：`ModuleNotFoundError: knowledge_source_service.application.query_grants`，1 error |
| GREEN | 增加 strict request/receipt、内容寻址 Grant ID 和 PostgreSQL receipt；同事实重放、Space 反推、预算/其他 Release/Reference credential 拒绝 | 隔离 PostgreSQL/KSS HTTP 聚焦纵向 1 passed |
| REFACTOR | 把 client、strategies、budget 和 scope 从 per-call request 收回 immutable policy；per-call 只留 exact Release，增加非法 client/Space/budget 字段拒绝 | 重构后同一隔离纵向 1 passed；Ruff、format 和聚焦 Mypy 通过 |

`KnowledgeQueryGrantPolicy` 只保留 trace-safe identity 和权限上限，不包含 bearer token
或 Secret Handle。`ProvisionKnowledgeQueryGrantRequest` 只包含 exact Release ID。
`PostgresKnowledgeAccessControl` 仍只持久化 credential digest 和既有 Grant 表；本片只把
已写入权威事实返回为 `knowledge-query-grant.v1` receipt，不改表结构。

### 43.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-query-grant-tdd05k`，只启动 PostgreSQL 17.5，
显式绑定 loopback 端口 `55491`。KSS fixture 为每项 PostgreSQL 测试创建随机
schema 并在结束时删除；没有连接生产凭据、生产数据、生产服务或外部网络。
验证后只对该隔离项目执行 `down --volumes --remove-orphans`，随后 `compose ps --all`
返回空清单；既有 `proofagent-production-local` 项目未启动或修改。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05K focused PostgreSQL/KSS HTTP vertical | 1 passed | exact replay、KSS-derived Space、strict per-call input、不扩权、exact Release、budget 和 Reference client denial |
| KSS contracts | 411 passed、13 dependency-conditioned skips | 未提供 S3/OpenSearch 等非本片依赖，skip 不作为外部依赖通过证据 |
| PostgreSQL-enabled 全仓后端 | 2588 passed、37 skipped、2 deselected、1 existing warning | ProofAgent 与 KSS PostgreSQL 测试强制执行；未提供的外部依赖仍按既有条件 skip |
| Ruff / format / Mypy | 全仓 Ruff 通过；4 个本片 Python 文件 format-clean；467 个产品源无类型错误 | 无新增 ignore |
| lock / domain / diff | `uv lock --check`、domain-context 和 `git diff --check` 通过 | lock 检查在默认沙箱内因 uv/macOS 系统网络配置原生 panic 未执行完；沙箱外只读重试通过 |

没有运行 production-local 全栈、正式 Agent publication、真实 KSS/model 上游 smoke、
OIDC/Vault/TLS gateway、S3 artifact retention、Dashboard、浏览器或发布 Gate。新 core 仍没有
网络 provisioning 入口，也没有被 formal publisher 调用，因此不能证明 production-local
formal online smoke 已可用。

### 43.4 状态与下一边界

- [KNOWN | HIGH] TDD-05K 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。本片只完成 KSS application-only Grant core 和隔离查询纵向，
  当前累计工作树没有新 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] 调用方不能提交 client、credential、Space、strategy、budget 或
  scope；这些事实由受信 policy 锁定。Reference client 没有 Query Grant，也没有被
  当作 runtime client 复用。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05L 只增加受信的 KSS
  Query Grant provisioning HTTP transport 和 ProofAgent guarded adapter：传输只携带 Draft 选择的
  exact Release，并严格复核 secret-free receipt。暂不把它接入 formal publisher，不运行
  真实模型或生产部署。

## 44. TDD-05L：Query Grant operator transport 与 ProofAgent guarded adapter

### 44.1 冻结边界

[FRAME | HIGH] 本片只在既有 KSS operator 管理认证和 `knowledge_source.edit` 权限后增加
`POST /v1/knowledge-query-grants`。KSS runtime 只有同时注入 TDD-05K immutable policy 与
operator authentication 时才暴露该入口；缺 operator authority 时在数据库访问前失败关闭。
strict 请求只含 `knowledge_base_release_id`，不能提交 client、credential、Space、strategy、预算
或 scope。runtime Query 与 Reference service-client credential 均不能认证该 operator 命令。

[FRAME | HIGH] ProofAgent 只新增 provider-neutral `KnowledgeQueryGrantProvisioner` port、strict
secret-free request/receipt 和 guarded HTTPS adapter。Adapter 必须发送 exact Release，拒绝非 HTTPS
origin、redirect、非 200、超限或未知响应、inactive receipt、重复 strategy 和 Release 漂移。它不
复制或覆盖 KSS policy，也不接 formal publisher。

[FRAME | HIGH] 本片更新 canonical OpenAPI，但不新增 SQL/migration、operator-command audit store、
Secret Handle、Compose/Vault/egress/TLS、Dashboard/BFF 或 production 配置，不调用 formal
publication endpoint，不运行真实模型、不部署且不提交 Git。durable Grant row/receipt 是查询授权
事实，不是完整 operator 审计证据。

### 44.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | 真实 KSS runtime 必须从受信 policy 装配 operator-protected Grant HTTP | `compose_runtime()` 不接受 `query_grant_policy`，聚焦测试 1 failed |
| GREEN-1 | 增加条件 runtime composition、operator edit 权限、strict request/receipt 与 `409/503` 映射 | 隔离 PostgreSQL/KSS vertical 1 passed；operator exact replay、runtime credential `401`、伪造 policy 字段 `422` |
| RED-2 | ProofAgent 必须有 provider-neutral request 与 guarded provisioner | 测试收集失败：缺少 `source_service_query_grant_provisioner`，1 error |
| GREEN-2 | 增加 port、strict receipt 与 HTTPS transport | 成功 wire 合同 1 passed；payload 只有 exact Release |
| RED-3 | schema 合法但 response Release 漂移必须失败关闭 | 参数组得到 1 failed、3 passed；漂移响应未抛错 |
| GREEN-3 | Adapter 在 strict validation 后复核 exact Release | adapter 合同 16 passed，覆盖 drift、unknown、inactive、重复 strategy、redirect、错误、响应上限、HTTPS 与 Bearer |
| RED-4 | canonical OpenAPI 必须公开 Grant transport 且请求 schema 只有 exact Release | 分发合同缺 `/v1/knowledge-query-grants`，1 failed |
| GREEN-4 | canonical builder 注入 contract-only Grant seam，并更新确定性摘要 | OpenAPI 路径/schema 通过；新 SHA-256 为 `ddac946a73bbbcffb14b271c63302590e7557109a3711c90f79021fd0623a349` |
| REFACTOR | 真实 vertical 改由 ProofAgent adapter 调用 KSS transport；增加无 operator auth 启动拒绝和 bounded problem 合同 | 纯合同聚焦 25 passed；隔离 PostgreSQL/KSS/ProofAgent vertical 1 passed；Ruff/format/Mypy 通过 |

### 44.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-query-grant-http-tdd05l`，只启动 PostgreSQL 17.5，
loopback 端口为 `55432`。KSS 与 ProofAgent fixtures 使用独立测试 schema；未读取 `.env`、生产
凭据、生产数据或生产日志，未连接外部网络。真实纵向为：ProofAgent provisioner port → guarded
HTTP client → KSS operator transport → immutable Grant policy → PostgreSQL Grant → exact Query。
验证结束后只对该隔离项目执行 `down --volumes --remove-orphans`；随后 `compose ps --all` 仅返回
表头，确认无测试容器残留，未启动或修改其他 Compose 项目。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| TDD-05L focused | 25 passed | KSS transport、权限、bounded problem、ProofAgent adapter、canonical OpenAPI 和 runtime fail-closed |
| PostgreSQL/KSS/ProofAgent vertical | 1 passed | exact replay、strict policy input、operator/runtime/Reference authority、Release/budget Query enforcement |
| KSS contracts | 418 passed、13 dependency-conditioned skips | 未提供 S3/OpenSearch 等非本片依赖；skip 不作为外部依赖通过证据 |
| PostgreSQL-enabled 全仓后端 | 2611 passed、37 skipped、2 deselected、1 existing warning | PostgreSQL 测试强制执行；warning 为既有 Authlib deprecation |
| Ruff / format / Mypy | 全仓 Ruff 通过；12 个本片 Python 文件 format-clean；469 个产品源无类型错误 | 无新增 ignore |

没有启动 production-local 全栈、正式 Agent publication、真实 KSS/model online smoke、生产
OIDC/Vault/TLS gateway、S3 artifact retention、Dashboard、浏览器或发布 Gate。ProofAgent adapter
仍未注入 formal publisher；因此本片不能证明正式发布会在 online smoke 前获得 exact Grant，也
不能把本地回归外推为生产服务可用。

### 44.4 状态与下一边界

- [KNOWN | HIGH] TDD-05L 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树没有新 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] runtime/Reference service-client 不能自授 Grant；ProofAgent adapter 只传 exact
  Release 并严格验证 receipt。KSS deployment policy 仍独占 client、Space、strategy、预算和 scope。
- [KNOWN | HIGH] 本片没有独立 operator-command audit store；Grant row/receipt 不能证明终端操作员
  委托链。formal publisher integration 还必须处理 Grant 已创建但后续 smoke/publication 失败时的
  保守残留授权语义，不能隐式当作已解决。
- [FRAME | HIGH] 下一片若继续保持简单，建议 TDD-05M 只新增 candidate-bound Query Grant Control
  staging：从已验证 Formal Candidate 取 exact Release，调用 provisioner 并复核 receipt，再把 staging
  作为 online smoke 的显式前置输入。暂不在同片增加撤销/reconciler、operator audit migration、
  production-local Secret/egress 配置、真实模型调用或部署。

## 45. TDD-05M：candidate-bound Query Grant Control staging

### 45.1 冻结边界

[FRAME | HIGH] 本片只在已验证 `FormalProductionAgentReferenceStaging` 之后、formal online
smoke 之前增加一个 Control-owned Query Grant staging。Stager 只能从 Formal Candidate 读取 exact
`knowledge_base_release_id`，调用既有 provider-neutral `KnowledgeQueryGrantProvisioner`，并要求
strict active receipt 的 Release 与 Knowledge Space 同 Candidate 完全一致。client、Space、strategy、
预算和 scope 继续由 KSS immutable deployment policy 独占。

[FRAME | HIGH] Online smoke strict contract 升级为
`formal-production-agent-online-smoke-qualification.v2`，唯一输入为
`FormalProductionAgentQueryGrantStaging`；旧的 Reference-staging-only 调用形态删除。Formal
publisher 顺序固定为 Candidate → Phase F → active expectation → Reference → Query Grant → smoke →
final UoW。production composition 复用既有 KSS operator Secret boundary，不新增凭据或配置字段。

[FRAME | HIGH] Grant 已成功但后续 smoke/publication 失败时，本片保留 KSS 中 exact、
policy-bounded 的 durable Grant，不伪造补偿撤销。该 Grant 不代表 Agent 已发布、激活或获得用户侧
Run 权限。本片不新增 selective revoke/reconciler、operator-command audit migration、SQL、
production-local Query Grant policy/egress/TLS 配置、Dashboard/BFF、真实模型调用、部署或 Git 提交。
决策见 ADR-0220。

### 45.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | Query Grant staging 必须只从 exact Formal Candidate Release 构造请求并返回严格契约 | 聚焦测试收集失败：缺少 `FormalProductionAgentQueryGrantStaging`，1 error |
| GREEN-1 | 新增 strict staging contract 与 Control stager，复核 Reference/Candidate/Phase F 和 Grant Release/Space | tracer bullet 1 passed；中间测试曾因 fixture Space 漂移按预期失败关闭，修正 fixture 后通过 |
| RED-2 | online smoke 不得继续接受 Reference staging | 新接口测试因 `qualify()` 不接受 `query_grant_staging` 得到 1 failed |
| GREEN-2 | online smoke qualification 升级到 v2，Control 与 concrete runner 只接受 Query Grant staging | 新前置输入测试 1 passed；旧调用形态移除 |
| RED-3 | formal publisher 必须在 Reference 与 smoke 之间调用 Grant stager | publisher 构造因缺少 `query_grant_stager` 得到 1 failed |
| GREEN-3 | publisher 和 production composition 注入 guarded provisioner；顺序固定且失败在 smoke/最终写前关闭 | 顺序测试 1 passed；Reference → Query Grant → smoke |
| REFACTOR | 增加 unavailable、inactive、Release/Space drift、smoke 失败保留 Grant/Reference、production operator Secret composition 证据 | formal focused 72 passed；production composition 11 passed；受影响 141 passed、13 skipped |

### 45.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-query-grant-staging-tdd05m`，只启动 PostgreSQL 17.5，
loopback 端口为 `55432`。ProofAgent 与 KSS PostgreSQL 测试均启用 fail-if-missing 开关；未读取
`.env`、生产凭据、生产数据或生产日志，未连接外部网络。验证后只清理该项目的容器、网络和测试
卷，`compose ps --all` 只返回表头。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| Formal Candidate / Grant staging focused | 72 passed | exact Candidate Release、strict receipt、失败顺序、保守残留 Grant/Reference、无旧 smoke 旁路 |
| Production composition focused | 11 passed、1 existing warning | guarded provisioner 复用 operator Secret boundary；warning 为既有 Authlib deprecation |
| 受影响回归 | 141 passed、13 dependency-conditioned skips、1 existing warning | 未启用 PostgreSQL 的首次受影响运行；skip 不作为依赖通过证据 |
| PostgreSQL-enabled 全仓后端 | 2620 passed、37 skipped、2 deselected、1 existing warning | ProofAgent/KSS PostgreSQL 测试强制执行；其余未提供依赖保持既有条件 skip |
| Ruff / format / Mypy | 全仓 Ruff 通过；9 个本片 Python 文件 format-clean；470 个产品源无类型错误 | 无新增 ignore |
| lock / domain / diff | `uv lock --check`、domain-context 和 `git diff --check` 通过 | lock 检查因沙箱 uv cache 权限失败后在获批环境只读重试通过 |

没有启动 production-local 全栈、真实 KSS/model online smoke、生产 OIDC/Vault/TLS gateway、S3
artifact retention、Dashboard、浏览器或发布 Gate。当前 production-local KSS 尚未注入 TDD-05K
immutable Query Grant policy，因此本片不能证明完整 formal publication 在该环境可联机执行。

### 45.4 状态与下一边界

- [KNOWN | HIGH] TDD-05M 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树没有新 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] Formal publication 现在只有 Reference → Query Grant → online smoke 单一路径。
  Grant provisioning 失败或 receipt 漂移不会进入 smoke/最终 UoW；smoke 或最终写失败不会虚构
  Grant 撤销。
- [KNOWN | HIGH] Grant row/receipt 仍不是完整 operator-command audit；本片也没有 selective revoke
  或 reconciler。已创建 Grant 的保守残留授权必须在生产 Gate 中作为显式风险审查。
- [FRAME | HIGH] 下一片若继续聚焦核心，建议 TDD-05N 只补 production-local immutable Query Grant
  policy/bootstrap 与隔离 Reference → Grant staging 纵向，证明 checked-in 环境能暴露 operator-protected
  provisioning 并严格绑定 runtime client/exact Release。仍不运行真实模型、不做 revoke/reconciler、
  operator audit migration 或部署。

## 46. TDD-05N：production-local immutable Query Grant policy/bootstrap

### 46.1 冻结边界

[FRAME | HIGH] 本片只关闭 checked-in production-local 中两个缺口：KSS API 进程必须从一个 strict、
secret-free deployment value 读取 TDD-05K `KnowledgeQueryGrantPolicy`；KSS migration 后必须用一次性
hardened bootstrap 注册现有 runtime Query client credential digest。policy 与 bootstrap 的 client
identity 必须完全一致，KSS API 等待 runtime 与 dedicated Reference client 两个 bootstrap 成功后
才能启动。

[FRAME | HIGH] `KSS_QUERY_GRANT_POLICY_JSON` 存在时必须完整通过 frozen Pydantic contract；JSON、
未知字段、strategy、预算、scope digest 或 client identity 无效时在配置阶段失败关闭。配置完全缺失
时保留既有「不暴露 Query Grant provisioning route」语义。runtime bootstrap 只调用
`register_client`，不能创建 Grant；Grant 仍只能由独立 operator-authenticated exact-Release command
创建。

[FRAME | HIGH] 本片复用既有 runtime 与 operator Secret，不新增 SQL、Secret Handle、egress/TLS
规则、Dashboard/BFF、selective revoke/reconciler 或 operator-command audit。隔离纵向读取 checked-in
policy/bootstrap facts，按 Reference → Grant → bounded Query 顺序验证，但不启动 production-local
全栈、不调用真实模型、不执行 formal publication、部署或 Git 提交。决策见 ADR-0221。

### 46.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | KSS process configuration 必须加载 strict immutable Query Grant policy | 聚焦测试因 `ApiRuntimeConfiguration` 没有 `query_grant_policy` 得到 1 failed |
| GREEN-1 | 将单一 `KSS_QUERY_GRANT_POLICY_JSON` 解析为 frozen `KnowledgeQueryGrantPolicy`，无配置返回 `None` | tracer bullet 1 passed；malformed JSON 与 unknown field 均返回无输入回显的稳定配置错误 |
| RED-2 | API process 必须把 typed policy 交给 `compose_runtime` | composition 测试因缺少 `query_grant_policy` 参数得到 1 failed |
| GREEN-2 | 仅 API role 注入 policy；其他角色保持无 provisioning authority | 两项 policy/configuration focused 测试通过 |
| RED-3 | production-local 必须有独立 runtime client bootstrap | 测试收集因 `knowledge_source_service.bootstrap.runtime_client` 不存在得到 1 error |
| GREEN-3 | 新增只注册 credential digest 的一次性 bootstrap，输出不含 bearer token | bootstrap focused 1 passed |
| RED-4 | checked-in Compose 必须绑定 policy/runtime client 并等待 bootstrap | static contract 因缺少 `kss-runtime-client-bootstrap` 得到 1 failed |
| GREEN-4 | Compose 复用现有 runtime Secret，注入 secret-free policy，并让 KSS API 等待 runtime/Reference bootstrap | production-local static contract 1 passed |
| REFACTOR | 隔离纵向改为读取 checked-in policy、调用 runtime bootstrap，并按 Reference → operator Grant → exact Query 验证 | 受影响集 84 passed；KSS contract 422 passed、13 skipped |

### 46.3 验证结果与限定

隔离 Compose 项目为 `proofagent-kss-query-grant-policy-tdd05n`，只启动 PostgreSQL 17.5，loopback
端口为 `55432`。测试使用仓库测试常量和随机 schema；未读取 `.env`、生产凭据、生产数据或生产日志，
未连接外部网络。纵向从 checked-in Compose 读取 policy 与 runtime client identity，但没有启动
`proofagent-production-local` 服务。

验证结束后，仅对该隔离项目执行 `down --volumes`。临时 PostgreSQL 容器和网络已删除，随后
`compose ps --all` 只返回表头。测试数据可由 fixture 重建；没有操作其他 Compose 项目或
production-local 数据。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| policy/bootstrap/production-local composition 受影响集 | 84 passed、1 existing warning | 覆盖 strict config、API composition、runtime bootstrap、operator-only provisioning 与 production role 静态合同 |
| KSS contract | 422 passed、13 dependency-conditioned skips | PostgreSQL 测试强制执行；S3/OpenSearch 未提供，因此对应 skip 不作为依赖通过证据 |
| PostgreSQL-enabled 全仓后端 | 2624 passed、37 skipped、2 deselected、1 existing warning | ProofAgent/KSS PostgreSQL 测试强制执行；warning 为既有 Authlib deprecation |
| Ruff / format / Mypy | 全仓 Ruff 通过；6 个本片 Python 文件 format-clean；471 个产品源无类型错误 | 无新增 ignore |
| Compose config | `docker compose --env-file /dev/null ... config --quiet` 退出 0 | 未设置变量警告来自刻意不读取 secret env；静态渲染不证明服务已启动 |
| lock / domain / diff | `uv lock --check`、domain-context 和 `git diff --check` 通过 | lock 首次因沙箱 uv cache 权限失败，获批后只读重试通过 |

第一次全仓强制 PostgreSQL 命令把 ProofAgent DSN 误写为 `postgresql://`，SQLAlchemy 因而尝试加载
未安装的 `psycopg2`，得到 2548 passed、37 skipped、2 deselected 和 76 setup errors。改用项目约定
的 `postgresql+psycopg://` 后完整重跑并得到上表 GREEN 结果；前一次环境错误不作为代码失败或
通过证据。

没有启动 production-local 全栈、真实 KSS/model online smoke、formal publication、生产
OIDC/Vault/TLS gateway、Dashboard、浏览器或发布 Gate。checked-in local scope digest 只标识本地
harness policy，不证明生产 access-scope enforcement 或 Production GO。

### 46.4 状态与下一边界

- [KNOWN | HIGH] TDD-05N 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。当前累计工作树没有新 commit、push、merge、部署或 Production GO。
- [KNOWN | HIGH] checked-in production-local 现在具备匹配的 runtime client identity bootstrap 与
  immutable policy，KSS API 可据此装配 operator-protected Query Grant provisioning。bootstrap 本身
  不创建 Grant，runtime/Reference credential 仍不能自授。
- [KNOWN | HIGH] 隔离纵向证明 Reference → exact Grant → bounded Query 可运行；它没有证明完整
  formal publication、真实模型质量、生产 Vault/egress/TLS 或最终发布 Gate。
- [FRAME | HIGH] 下一片若继续聚焦闭环，建议先单独确认 TDD-05O：只扩充 production-local verifier，
  对已存在的 exact Release 检查 runtime identity、policy、operator provisioning 和 Grant-bounded
  Query。该动作会启动本地全栈并创建可重放的本地 Grant，因此不在本片隐式执行；仍不加入 revoke、
  reconciler、operator audit migration 或 Production GO。

## 47. TDD-05O：production-local exact Query authority verifier

### 47.1 冻结边界

[FRAME | HIGH] 本片只增加一个显式的 production-local 验证入口。调用者必须传入一个已存在的
exact KSS Release；入口不接受占位值，不查询 `latest`，也不自动选择 Release。verifier 先通过
既有 operator Secret Handle 请求 policy-owned Query Grant，再用独立 runtime client Secret Handle
执行一次 `single_pass` Query。它严格重验 runtime client、Release、strategy、预算和结果中的
Release/access-scope identity。

[FRAME | HIGH] 成功输出只包含 secret-free 的 Release、Space、Grant、Query、strategy、候选数量和
预算使用量。已知输入、Grant transport 或一致性失败只输出稳定 JSON 错误码并退出非零，不回显
异常正文。入口不启动或停止 Compose，不创建 Release、Reference 或 Published Agent，不修改
readiness，不增加 SQL、revoke/reconciler、operator-command audit、Dashboard/BFF、部署或 Git 提交。

### 47.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | host verifier 必须拒绝缺失/占位 Release，并按 operator Grant → runtime Query 顺序验证 exact authority | 目标模块与脚本不存在，聚焦集合得到 6 failed |
| GREEN-1 | 增加 pure verifier、production composition 和单参数 host script；严格复核 client、Release、strategy、预算和 access scope | 初始聚焦 9 passed；Ruff、format 与 shell syntax 通过 |
| RED-2 | 保留既有 production-local 卷升级时，runtime credential bootstrap 必须继续幂等 | 全栈在 bootstrap 因同一 token 已绑定历史 client identity 而触发 PostgreSQL unique violation |
| GREEN-2 | checked-in local policy、ProofAgent runtime 与 bootstrap 继续使用既有 `proof-agent-production-local` identity；通用 bootstrap 默认值不变 | 当前检出版本保留旧卷启动成功，bootstrap 退出 0；静态 identity 合同通过 |
| RED-3 | 已知 Grant 冲突不得输出 Python traceback 或异常正文 | live 409 首次输出完整 traceback；bounded-failure 测试因缺少 `cli()` 得到 1 failed |
| GREEN-3 | CLI 将已知失败映射为 secret-free schema/error code，并只在 verifier 进程抑制已知 Authlib JOSE 弃用告警 | verifier 8 passed；live 冲突最终只输出一条 `PA_KNOWLEDGE_002` JSON 并退出 1 |
| REFACTOR | Compose-derived 集成断言改为比较实际 deployment policy identity，不保留通用 client 名称硬编码 | 独立 PostgreSQL exact Grant → Query 聚焦集合 15 passed |
| LIVE | 由 verifier 外部的既有 KSS 管理发布 API 提供无冲突 exact Release；同一 verifier 重复运行必须精确重放 Grant，同时创建独立 Query | 两次 verifier 均退出 0；Grant ID 相同，Query ID 不同；只读 PostgreSQL 核验为 1 个 target Grant、2 个 succeeded Query |

### 47.3 验证结果与限定

[KNOWN | HIGH] 当前检出版本的 ProofAgent/KSS application images 已在保留既有 production-local
数据卷的条件下重建并启动；配置未变的长期基础设施容器被 Compose 复用，不是 clean-room 全量
重建。API、KSS、
Gateway、OIDC、Vault、PostgreSQL、OpenSearch、私有模型兼容路由、S3 versioning 与 KSS authority
isolation 通过既有 `production-local-verify.sh`；脚本退出 0。ProofAgent `/readyz` 仍因
`published_agent=not_ready` 返回预期 HTTP 503，本片没有发布或激活 Agent。

[KNOWN | HIGH] 操作者显式选择了一个已存在、queryable 的本地 smoke Release。operator provisioning
在 Query 前返回 `409 knowledge_query_grant_conflict`。只读核验表明，当前三个 queryable Release
均已绑定历史 smoke Grant；这些 Grant 使用历史 ID 与 access-scope digest，不能被新内容寻址 policy
当作精确重放，也不能原地改写。系统因此正确失败关闭。未删除、停用、撤销或改写任何既有 Grant，
未创建新 Release，也没有提交 Query。

[KNOWN | HIGH] 为获得独立正向证据，本片在临时 PostgreSQL 17.5 项目和随机 schema 中执行现有
KSS HTTP/runtime 纵向，证明 deployment policy → operator Grant → exact bounded Query 可运行。
验证后已删除该临时容器、网络和数据卷；没有操作 production-local 数据。

[KNOWN | HIGH] 随后，操作者在 verifier 外部使用 production-local 已装配的 KSS 管理 catalog
publication API 创建独立测试 Base `base-query-authority-tdd05o-20260831`，复用同一 Space 下两个
既有 immutable Source Version，发布 queryable exact Release
`release-86ecc0652a74b27d0effb1e0`。发布前只读检查确认目标 runtime client/Release 的 Grant 数为
0。该准备动作不属于 verifier，也没有创建 Reference、Grant 或 Published Agent。当前
production-local 未装配 Base Preparation 管理端点，因此该动作只提供 Query verifier 所需的本地
catalog fixture，不是受控 Preparation 发布路径的生产证据。

[KNOWN | HIGH] verifier 第一次运行创建 active Grant
`query-grant-4936a3b9424d3268f03532b6` 和 succeeded Query
`knowledge-query-d85b7ea5fca442c2a206172066ced51f`；第二次运行精确重放同一 Grant，并创建
succeeded Query `knowledge-query-c7240c779c0a4ec9b35e1f612220602b`。两次结果均绑定同一
Release/Space/runtime client，使用 `single_pass`，各返回 3 个候选，预算使用量为 1 round、0 model
calls、0 model tokens、3 candidates、0 ms。只读 PostgreSQL 核验确认目标只有 1 个 active Grant、
2 个独立 succeeded Query；保留数据库总计 4 个 Release 和 4 个 Grant。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| verifier/HTTP/Compose/真实 PostgreSQL 正向聚焦 | 15 passed | 临时随机 schema；受控 projection/model fixture，不是外部真实模型 |
| 受影响回归 | 100 passed、1 existing warning | 覆盖 production-local、KSS policy/bootstrap、operator transport、PostgreSQL Grant 和 runtime composition |
| PostgreSQL-enabled 全仓后端 | 2633 passed、37 skipped、2 deselected、1 existing warning | ProofAgent/KSS PostgreSQL 强制执行；未提供的其他外部依赖保持条件 skip |
| 最终 production-local build/up + baseline | 退出 0 | 当前检出镜像；保留既有卷；`published_agent=not_ready` 为预期 |
| 显式 exact Release verifier | 退出 1，单条 `PA_KNOWLEDGE_002` JSON | 历史 immutable Grant 冲突；证明负向 fail-closed，不是正向 Query 成功 |
| 新 exact Release verifier 第一次运行 | 退出 0；1 个 active Grant；1 个 succeeded Query；3 candidates | verifier 外部先准备无冲突 Release；本地 compatibility dependencies，不是外部真实模型 |
| 同一 exact Release verifier 第二次运行 | 退出 0；复用同一 Grant；新增 1 个 succeeded Query；3 candidates | 证明 immutable Grant 精确重放和 Query identity 隔离 |
| 最终 verifier 聚焦回归 | 30 passed、1 existing warning | verifier 与 production migration/static contract |
| live 后 production-local baseline | 退出 0 | `/readyz` 仍只因 `published_agent=not_ready` 返回预期 HTTP 503 |
| Ruff / format / Mypy / shell syntax | 通过；472 个源无类型错误 | verifier、产品源、聚焦测试与 host script |

### 47.4 状态与下一边界

- [KNOWN | HIGH] TDD-05O 已完成负向冲突失败关闭、正向 live Grant 创建和第二次 exact replay。
  本片结论为 `LOCAL_VERIFIED`；Feature 继续为 `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] 409 不是可绕过的兼容问题。ADR-0218 要求同一 client/Release 的 policy drift
  冲突失败；旧 Grant 不能被静默采用、覆盖或扩权。
- [KNOWN | HIGH] 新 Release、Base、Grant 和两条 Query 是保留卷中的持久化本地验证记录。当前没有
  selective revoke，本片不删除这些记录，也不修改三个历史 Grant。
- [FRAME | HIGH] 下一功能切片仍应与 selective revoke/reconciliation、operator audit migration、
  真实外部上游 smoke 和正式 Agent 发布分开确认。当前 local compatibility 结果不是部署批准或
  Production GO。

## 48. TDD-05P：production-local Formal Candidate 只读预检

### 48.1 冻结边界

[FRAME | HIGH] 本片只为 production-local 增加一个显式的 Formal Candidate 只读预检入口。调用者
必须传入 exact `agent_id`、`draft_id` 和正整数 `draft_revision`；Draft 继续选择 Release，production
composition 继续注入 Binding Profile。预检复用既有候选装配器，只输出 secret-free 的 Draft、
Release、catalog、Profile 公开标识和两个候选摘要，并固定 `publication_authorized=false`。

[FRAME | HIGH] 预检不预留 formal publication command，不运行 Phase F，不注册 Reference，不创建
或重放 Query Grant，不运行 online smoke，不创建 Published Agent Version，不修改 Active pointer、
Draft 或 readiness。已知候选阻断输出稳定 JSON 并退出非零，不回显异常正文。本片不增加 HTTP
发布入口、SQL、Dashboard、部署配置、Grant reconciliation/revoke、外部模型证据或 Git 提交。

### 48.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | production formal command 必须能只读装配候选，且不得预留命令或进入 Phase F | 聚焦测试因 command service 缺少 `preflight()` 得到 1 failed |
| RED-2 | production-local 必须提供三参数预检器与 host script | 目标 Python 模块和脚本不存在，聚焦集合合计 8 failed |
| GREEN-1 | publisher/command service 增加复用同一 deployment Profile 的只读 `preflight()`，`publish()` 也通过该单一候选入口装配 | 只读行为测试证明仅打开 1 个未提交 UoW，Phase F/Reference/Grant/smoke/command/version/audit 均为零 |
| GREEN-2 | 新增 secret-free verifier、bounded failure JSON 与三参数 host script | success/输入拒绝/identity drift/bounded failure/static script 合同通过 |
| LIVE | 在保留卷当前 Draft@12 上运行最终镜像 | 稳定返回 `formal_candidate_authoring_blocked` + `memory_must_be_disabled`，退出 1；无 traceback 或私有正文 |
| REFACTOR | 只在 verifier 进程抑制已知 Authlib 弃用告警，保持 stderr 为单条机器可读 JSON | 最终 live 输出仅包含 failure JSON；测试、Ruff、Mypy 继续通过 |

### 48.3 验证结果与限定

[KNOWN | HIGH] 当前 production-local Draft
`agent_management_insurance_specialist/c8191d9e-ee0a-5324-8c6d-e0b88622ab61@12`
实际配置为 Tools disabled、Memory enabled。Formal Candidate 规则要求首期生产 Memory disabled，因此
预检正确以 `memory_must_be_disabled` 失败关闭。该阻断发生在候选装配阶段，早于已知旧 Release 的
历史 Query Grant 冲突；本片没有修改 Draft 或绕过规则，也没有生成候选摘要供发布批准。

[KNOWN | HIGH] 预检前后只读 PostgreSQL 计数完全一致：Formal Command `0 → 0`、Agent Version
`0 → 0`、Active Version `0 → 0`、KSS Reference `0 → 0`、Query Grant `4 → 4`、Knowledge Query
`19 → 19`。这证明本次 live 运行没有进入 formal command reservation、Reference、Grant、Query 或
Agent 发布状态变化。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 预检 RED | 9 failed | 缺少 `preflight()`、verifier 与 host script，失败位置符合冻结契约 |
| 预检聚焦 GREEN | 9 passed、1 existing warning | 覆盖 application-only 只读边界、secret-free 输出、稳定失败和 host script 静态合同 |
| formal/production 受影响回归 | 172 passed、1 existing warning | 覆盖 formal chain、production composition/API、安全 composition、migration/static contract |
| 完整默认后端回归 | 2412 passed、267 dependency-conditioned skips、2 deselected、1 existing warning | 未配置的 PostgreSQL/S3/OpenSearch 等集成保持条件 skip；TDD-05O 已有 PostgreSQL-enabled 全仓证据，本片未改 SQL/仓储 |
| Ruff / format / Mypy / shell syntax / diff | 通过 | Mypy 覆盖 3 个本片 Python 源；无新增 ignore |
| 最终 production-local build/up + baseline | 退出 0 | 保留既有卷；`published_agent=not_ready` 仍为预期 HTTP 503 |
| 当前 exact Draft preflight | 退出 1；单条 stable JSON | `memory_must_be_disabled`；未生成候选摘要，不是发布授权 |
| live 后持久化计数 | 六类计数全部不变 | 没有 command、Reference、Grant、Query、Version 或 Active 写入 |

### 48.4 状态与下一边界

- [KNOWN | HIGH] TDD-05P 的只读预检能力建议结论为 `LOCAL_VERIFIED`；当前 exact Draft 候选仍为
  `BLOCKED`，Feature 继续为 `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] production-local 仍未发布或激活 Agent，readiness 继续只因
  `published_agent=not_ready` 返回预期 503。本片不是 Production GO，也不是 formal publication
  command approval。
- [FRAME | HIGH] 下一片若继续，应单独确认是否通过既有 Agent Draft 编辑/CAS 权威只把 Memory
  改为 disabled、形成新 revision 后重新预检。该状态变更不得隐式沿用本次同意；即使候选装配成功，
  旧 Release 的历史 Grant 冲突、Phase F、真实模型和全部发布 Gate 仍是独立阻断。

## 49. TDD-05Q：exact Draft Memory repair 与 Candidate 核心闭环

### 49.1 冻结边界

[FRAME | HIGH] 本片只允许对 production-local exact
`agent_management_insurance_specialist/c8191d9e-ee0a-5324-8c6d-e0b88622ab61@12`
执行一次 Memory disable CAS。入口必须要求 Tools disabled、Memory enabled，并复用既有
Workspace 的完整 Contract 校验、revision CAS、原子保存和审计。不新增 SQL、通用
Contract 编辑器或第二写入路径。

[FRAME | HIGH] 修改后只重跑 TDD-05P read-only preflight。不预留 formal command，不运行
Phase F、Reference、Query Grant、Query、online smoke、Version、Active pointer 或 readiness
变更。旧 Release 的历史 Grant 冲突与发布 Gate 不在本片修复范围。

### 49.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | 必须有 exact Agent/Draft/revision 三参数入口，只经 Workspace 执行 CAS，且输出 secret-free | 缺少 Python 入口与 host script，13 failed；既有 preflight 合同通过 |
| GREEN-1 | YAML 节点精确定位 Memory 布尔标量，保留注释、顺序与其余原始字节；严格拒绝 identity/revision/shape 漂移 | 14 passed；Ruff/Mypy/shell syntax 通过 |
| LIVE-1 | 完整 Contract 校验必须先于写入 | 首次 live 返回 `draft_contract_update_rejected`；Draft 仍为 12，audit 仍为 6 |
| RED-2 | disabled Memory 不得保留 provider，也不得隐式扩大清理 scopes | 只读确认当前有 provider、无 scopes；新契约 3 failed |
| GREEN-2 | 同一候选中把 `enabled` 改为 false 并移除唯一 provider 行，Memory 外语义与字节不变 | 聚焦 14 passed；受影响核心 271 passed |
| REFACTOR | 已 disabled 的干净形态必须先返回稳定 no-op 拒绝，不因 provider 已移除误报 invalid | 最终聚焦 16 passed；live replay 返回 `draft_memory_already_disabled` |

### 49.3 production-local 核心验证

[KNOWN | HIGH] 最终命令只生成 Draft revision `12 → 13`，Tools 保持 disabled，Memory 变为
disabled，contract-update audit `6 → 7`。对 revision 13 重放失败关闭，未生成
revision 14。

[KNOWN | HIGH] TDD-05P read-only preflight 随后成功装配 exact Draft@13 与 Release
`release-a4b70851cb914862000e15c3`。Knowledge Release candidate SHA-256 为
`569d3eaf5d5d3cebc12e7a164f0ca48a8150757c5b06c521fd6d2943650d6503`，Formal Candidate
SHA-256 为 `ecd122b4a85e0bf5d0899e07e26e69eda043814880b9b3be59660475dccaf272`，输出仍固定
`publication_authorized=false`。

[KNOWN | HIGH] 发布/KSS 副作用基线保持：Formal Command `0 → 0`、Agent Version `0 → 0`、
Active Version `0 → 0`、KSS Reference `0 → 0`、Query Grant `4 → 4`、Knowledge Query
`19 → 19`。唯一预期持久化变化是 Draft revision 和一条 configuration audit。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 聚焦合同 | 16 passed、1 existing warning | exact CAS、Memory normalization、输出边界、失败关闭、重放 |
| 受影响核心 | 271 passed、1 existing warning | Workspace CAS/审计、Contract loader、production API、Formal Candidate/preflight |
| 完整默认后端 | 2427 passed、267 dependency-conditioned skips、2 deselected、1 existing warning | 首次受沙箱 loopback 限制有 8 个非产品失败；允许端口绑定后全量退出 0 |
| Ruff / format / Mypy / shell syntax / diff | 通过 | 无新增 ignore；入口不回显 Contract/YAML/异常正文 |
| 最终镜像/API | build 与 health 通过 | 保留现有数据卷；不是生产部署证据 |

### 49.4 状态与下一边界

- [KNOWN | HIGH] TDD-05Q 建议结论为 `LOCAL_VERIFIED`，Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] authoring-level Memory blocker 已解除，但候选装配不是 formal command
  approval，也不是 Published Version、Active Agent 或 Production GO。
- [FRAME | HIGH] 下一片不应直接执行完整发布；旧 Release 的历史 Query Grant
  冲突已知，应先单独设计最小的 Grant conflict 处置/候选更换切片，并继续保留真实
  上游 smoke 与正式发布授权边界。

## 50. TDD-05R：versioned runtime client 与新 Grant

### 50.1 冻结边界

[FRAME | HIGH] 用户明确要求不处理已有历史 Grant 的兼容，并创建新的 Grant。本片不读取旧
Grant 判断兼容性，不修改同一 client/Release 的不可变事实，也不增加 SQL、revoke 或
reconciliation。active checked-in production-local runtime authority 切换到
`proof-agent-production-local-v2`，并使用独立 Secret Handle、Vault path 和新生成的本地凭据。

[FRAME | HIGH] ProofAgent runtime、KSS immutable policy 和 KSS runtime-client bootstrap 必须
使用同一 v2 identity。bootstrap 仍只注册 credential digest；新的 exact-Release Grant 仍由既有
operator-authenticated endpoint 创建。旧 client、Secret 和 Grant 保持原状，不宣称已撤销。
本片不执行 formal publication，不创建 Version/Active/Reference，不改变 readiness，不提供真实
外部模型或 Product Release Authority 证据。具体决策见 ADR-0222。

### 50.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | checked-in active runtime 必须使用独立 v2 identity、Secret Handle、Vault path 和新生成 token | 聚焦 Compose 契约仍读到 `knowledge/source-service/client`，得到 1 failed；失败位置符合目标 |
| GREEN | 同步切换 ProofAgent runtime、KSS policy、runtime bootstrap、Vault locator/init 与 prepare secret | 聚焦契约 1 passed；完整 migration/Compose 文件 24 passed；Shell 与 Compose config 通过 |
| REFACTOR | 在真实 PostgreSQL 合同中先建立同一 Release 的旧 client Grant，再证明 v2 client 可创建独立 Grant | 默认环境 1 passed、5 skipped；一次性 PostgreSQL 17.5 强制运行后 6 passed |
| LIVE | 最终源码镜像注册 v2 client，针对 Draft@13 exact Release 创建并重放新 Grant，运行两次 bounded Query | 两次 verifier 均退出 0；Grant ID 相同、Query ID 不同、每次 3 个候选 |

### 50.3 production-local 核心验证

[KNOWN | HIGH] 最终 production-local active runtime client 为
`proof-agent-production-local-v2`。新 Grant
`query-grant-decb201089f91b5fb90dc392` 绑定 exact Release
`release-a4b70851cb914862000e15c3`。两次 verifier 精确重放同一 Grant，并分别创建 Query
`knowledge-query-478829adb403485189c2310057cc6b5c` 和
`knowledge-query-e25e662b381b4d0889fd5611d9f1499c`；每次返回 3 个 Candidate Evidence，预算使用
为 1 round、0 model call、3 candidates。

[KNOWN | HIGH] 只读数据库检查确认 v2 client 只有 1 条 active Grant 和 2 条 Query。总 Grant
`4 → 5`，总 Query `19 → 21`。Formal Command、Agent Version、Active Version 和 active KSS
Reference 均为 0。production-local baseline 退出 0，readiness 继续只因
`published_agent=not_ready` 返回预期 HTTP 503。

[KNOWN | HIGH] v2 Secret Handle 属于 deployment Binding Profile，因此 Draft@13 的新 Formal
Candidate SHA-256 为
`9b76665641d00354876deeb7ed2ff79a90c4a15dbc6eda2e270df4cc7a2dc50e`，Knowledge Release
Candidate SHA-256 为
`21875bc15ac7f5a101f7a6a3b2e2315818b773b4a11cd7b3388692d48bc5f67b`。preflight 仍固定
`publication_authorized=false`；旧候选摘要或批准不得沿用。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| RED | 1 failed | 当前 Handle 仍是旧值，目标失败成立 |
| 聚焦 GREEN | 1 passed、1 existing warning | v2 locator/policy/bootstrap/prepare 契约 |
| migration/Compose | 24 passed、1 existing warning | 部署静态契约与角色依赖 |
| 受影响组合 | 74 passed、5 dependency-conditioned skips、1 existing warning | migration、roles、安全 composition、verifier、KSS distribution/runtime |
| 真实 PostgreSQL runtime composition | 6 passed | 一次性 PostgreSQL 17.5；测试后容器已删除 |
| 完整默认后端 | 2427 passed、267 dependency-conditioned skips、2 deselected、1 existing warning | 没有把本地真实依赖结果冒充 Production GO |
| 静态与文档 | Ruff、format、Mypy 370 source files、lock、domain-context、Shell、Compose、diff 全部通过 | 无新增 ignore；未读取 `.env` 或输出凭据 |
| production-local build/up + baseline | 退出 0 | 最终源码镜像；ProofAgent/KSS API 健康；Agent 仍未发布 |
| exact Grant + Query | 两次退出 0 | 同一 v2 Grant，两次独立 Query，各 3 个候选 |
| exact Draft@13 preflight | 退出 0 | 新候选摘要；`publication_authorized=false` |

### 50.4 状态与下一边界

- [KNOWN | HIGH] TDD-05R 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] 当前 exact Release 的 v2 Grant 已可由 formal publisher 精确重放，但本片没有
  运行 Phase F、Reference、formal online smoke、Version 或 Active CAS。
- [FRAME | HIGH] 下一片应优先处理 formal publication command 的 process-loss
  recovery/takeover。正式发布前还需真实外部 KSS/model smoke、旧 credential 生命周期、回滚与全部
  Product Release Authority Gates；不得从本片推断 Production GO。

## 51. TDD-05S：formal publication command 租约接管

### 51.1 冻结边界

[FRAME | HIGH] 本片只恢复 durable `in_progress` formal command。公开入口、strict body、可信
actor、`(actor subject, Idempotency-Key)` 范围和 request SHA-256 保持不变。内部增加数据库时间
租约、opaque owner 和 monotonic fencing token。未到期重放不执行外部工作；到期后只有一个重放
可以接管。旧 fence 不能完成 success 或 failure。

[FRAME | HIGH] command ID 稳定派生 Phase F Record、provisional Version 和 validation Run
identity，Phase F timestamp 固定为原始 command `started_at`。因此进程退出发生在 Reference 或
online smoke 之后时，接管仍使用同一 Reference request/idempotency identity。本片不增加后台
reconciler、heartbeat、cancel、正式发布授权或真实外部模型调用。具体决策见 ADR-0223。

### 51.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | 进程退出后，未到期重放保持 `in_progress`；到期重放接管并完成 | 构造函数不接受 `execution_owner`，1 failed；失败位置符合目标 |
| GREEN-1 | 增加内部 execution claim、1–3600 秒租约和 reservation `acquired` 语义 | 聚焦 tracer 1 passed |
| RED-2 | 两个进程使用不同随机 ID 生成器时，接管仍必须复用 external identities | 两次 Reference request 分别使用 `version-first` 与 `version-second`，1 failed |
| GREEN-2 | command ID 派生 Phase F/Version/Run identities | identity tracer 转绿；Reference request 与 smoke identities 相同 |
| RED-3 | 同一 Phase F Record ID 的 timestamp 和 digest 也必须稳定 | 两个 authority 收到不同 Record，1 failed |
| GREEN-3 | Phase F timestamp 固定为原始 command `started_at` | 两次 Phase F Record 逐字段相同 |
| RED-4 | PostgreSQL 必须执行到期接管并 fence 旧 completion | 4 项因 repository 不接受 `lease_duration` 失败 |
| GREEN-4 | 增加 `0023_formal_publish_claim`、数据库时间 lease、并发 takeover 和 exact-fence completion | repository/migration 10 passed；补 legacy null-claim 合同后纳入受影响回归 |
| RED-5 | production composition 必须消费 deployment-owned lease 秒数 | 配置 600 秒时服务仍使用默认 900 秒，1 failed |
| GREEN-5 | production composition 校验并注入租约；production-local 固定 900 秒 | composition/Compose 聚焦 2 passed |

### 51.3 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| formal command 行为 | 74 passed | process exit、未到期 replay、到期 takeover、稳定 external identity、终态原子性 |
| 真实 PostgreSQL 17.5 | 11 passed | `0023` migration、并发唯一接管、legacy null-claim takeover、stale fence rejection、UoW rollback |
| 受影响组合 | 178 passed、1 existing warning | formal chain、PostgreSQL、Delivery、安全 composition、production roles/Compose |
| 完整默认后端 | 2428 passed、269 dependency-conditioned skips、2 deselected、1 existing warning | 默认未提供外部依赖；不是 Production GO |
| 静态检查 | Ruff、format、Mypy 371 source files、Shell、Compose、diff 通过 | 无新增 ignore 或依赖 |
| production-local build/up + baseline | 退出 0；最终复核镜像 `02ed2c22103c74dec0e23ff63c0b1cfdffe93bed2ea015eb5229c2f38009dbde` | schema head=`0023_formal_publish_claim`；API/KSS 健康 |
| production-local 状态 | formal command=0、Version=0、Active=0 | readiness 继续仅因 `published_agent=not_ready` 返回预期 HTTP 503 |

隔离 PostgreSQL 使用本机已有 `postgres:17.5-alpine` 镜像和端口 `55440`。首次尝试
`postgres:17.5` 因 Docker credential helper 无进度而中止，未创建容器；随后以 `--pull never`
启动已有镜像。首次测试 URL 误选未安装的 psycopg2，未进入产品断言；改用
`postgresql+psycopg` 后完成 RED/GREEN。最终测试容器已停止并删除。

### 51.4 状态与下一边界

- [KNOWN | HIGH] TDD-05S 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] 本片没有调用 formal publication endpoint。production-local 保留数据中没有新增
  command、Version 或 Active pointer，旧 KSS Grant/Query 事实保持不变。
- [FRAME | HIGH] 下一片建议只增加 durable candidate checkpoint：首次 preflight 后冻结 exact
  formal candidate digest，接管必须重验相同摘要后才进入 Phase F。后台恢复进程、真实外部模型、
  Reference/Grant 生命周期和 Product Release Authority Gates 继续分片处理。

## 52. TDD-05T：durable Formal Candidate checkpoint

### 52.1 冻结边界

[FRAME | HIGH] 当前 fenced claim 在只读 Candidate 装配后、Phase F 前原子写入
`formal_candidate_sha256`、`knowledge_release_candidate_sha256` 和 PostgreSQL 时间。checkpoint
属于 command 内部恢复权威，不进入公开 receipt、请求 body 或 Dashboard。

[FRAME | HIGH] 到期接管仍须从 exact Draft revision、live KSS catalog 和 deployment Profile
重新装配 Candidate。两个摘要与 checkpoint 完全一致时才可进入 Phase F；任一漂移都以
`formal_publication_candidate_checkpoint_conflict` 结束旧 command，并且不调用本次接管的 Phase F、
Reference、Grant、smoke 或 publisher。完整决策见 ADR-0224。

[BOUNDARY | HIGH] 本片只存摘要，不存完整 Candidate payload。它不增加后台 recovery process、
heartbeat、cancel、Reference/Grant 清理、真实外部模型或正式发布授权。

### 52.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | 进程退出后 catalog revision 漂移，接管必须在 Phase F 前失败 | 当前实现错误返回 `SUCCEEDED`，1 failed；失败位置准确证明缺少 Candidate identity 冻结 |
| GREEN-1 | command 先调用只读 preflight，以当前 claim checkpoint 两个摘要，再把同一 Candidate 交给 publisher | 聚焦 tracer 1 passed；formal command 文件 76 passed |
| RED-2 | PostgreSQL 首次写入、精确重放、摘要不可改绑与 completion 绑定 checkpoint | repository 不存在 `checkpoint_candidate`，1 failed |
| GREEN-2 | 增加 `0024_formal_candidate_checkpoint`、数据库时间和 claim-bound checkpoint CAS | PostgreSQL tracer 1 passed；repository/migration/production migration 37 passed |
| REFACTOR | 收窄为 `publish_checkpointed_candidate`，publisher 再校验 command identity 和两个摘要；补并发唯一 checkpoint、stale claim 和 terminal completion 保护 | publisher 摘要漂移 tracer 1 passed，且 Phase F 零调用；应用层与 repository 82 passed；受影响回归 196 passed |

### 52.3 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| formal command 行为 | 76 passed | checkpoint 时序、publisher 二次校验、接管同摘要、漂移失败、稳定 external identity、终态原子性 |
| 真实 PostgreSQL 17.5 | repository/migration/production migration 37 passed | `0024`、并发 immutable checkpoint、stale fence、completion exactness |
| 受影响组合 | 196 passed、1 existing warning | formal chain、Persistence、Delivery、安全 composition、production roles/Compose |
| 完整默认后端 | 2430 passed、271 dependency-conditioned skips、2 deselected、1 existing warning | 默认未提供外部依赖；不是 Production GO |
| 静态检查 | Ruff、Mypy 372 source files 通过 | 无新增 ignore 或依赖；最终 format、lock、domain-context、Shell、Compose、diff 在收尾复核 |
| production-local build/up + baseline | 退出 0；镜像 `9ea9b8a726e5c38c6b535d00c26f5078ba6515493fa2a961813fb3340c971493` | schema head=`0024_formal_candidate_checkpoint`；API/KSS 健康 |
| production-local 状态 | command=0、in-progress=0、checkpoint=0、Version=0、Active=0 | 未调用 formal endpoint；readiness 仅因 `published_agent=not_ready` 返回预期 HTTP 503 |

隔离 PostgreSQL 使用本机已有 `postgres:17.5-alpine` 镜像和端口 `55441`。测试完成后，容器已
停止并由 `--rm` 删除。未读取 `.env`、Secret 文件或生产数据。

### 52.4 状态与下一边界

- [KNOWN | HIGH] TDD-05T 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] Candidate checkpoint 不授权发布。production-local 未新增 command、checkpoint、
  Version 或 Active pointer。
- [KNOWN | HIGH] TDD-05U 源码复核确认，exact POST 已是未到期重放和到期接管的唯一
  recovery mutation，因此不再新增第二个 runner。TDD-05U 只增加 actor-owned exact command
  status read。真实外部模型、Reference/Grant 生命周期、operator command audit 和
  Product Release Authority Gates 继续保持独立边界。

## 53. TDD-05U：actor-owned exact formal command status read

### 53.1 收窄恢复边界

[KNOWN | HIGH] 源码复核确认，ADR-0223 的既有 POST 已经是显式恢复入口：
同一 actor、path、body 和 `Idempotency-Key` 在租约到期后可原子接管。新增第二条
recovery 写路径会分裂权威；而且 durable command 只保留 request SHA-256，不能脱离
原请求自动重建。

[FRAME | HIGH] TDD-05U 因此只增加
`GET /api/config/agents/{agent_id}/drafts/{draft_id}/formal-publications/{command_id}`。
读取要求 `agent.publish` 和 command 创建者的 exact actor subject。missing、foreign actor、
Agent/Draft path mismatch 都返回 `formal_publication_command_not_found`。响应只使用既有
trace-safe receipt，不暴露 actor、Key、claim、checkpoint 或原请求。完整决策见 ADR-0225。

[BOUNDARY | HIGH] GET 不提交 UoW，不续租、接管或改变 command。本片不增加列表、
cross-operator audit、后台扫描、request body 持久化、Dashboard、真实外部模型或发布批准。

### 53.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | 原操作者通过 exact GET 读取 trace-safe receipt | 路由尚不存在，得到 HTTP 404，1 failed |
| GREEN-1 | 增加 `agent.publish` 保护的 exact-resource GET | 聚焦 API tracer 1 passed |
| RED-2 | actor、Agent、Draft 或 command mismatch 必须共享 not-found，查询不写状态 | application service 缺少 `get_receipt`，1 failed |
| GREEN-2 | application 通过 actor-owned Persistence port 读取并重验 path identity | 聚焦 application tracer 1 passed |
| RED-3 | API 不得把 hidden-resource not-found 映射为依赖失败 | 实际返回 HTTP 503，1 failed |
| GREEN-3 | 稳定 `formal_publication_command_not_found` 映射为 HTTP 404 | 聚焦 API 安全 tracer 1 passed |
| REFACTOR | PostgreSQL 使用 exact command UUID + actor subject 只读查询，不加锁或续租 | 一次性 PostgreSQL tracer 1 passed；完整 repository/migration 38 passed |

### 53.3 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 聚焦公开行为 | 3 passed | exact receipt、权限、actor/path 隔离、无内部字段 |
| formal application + API | 131 passed | 既有 POST replay/takeover 行为保持不变 |
| 真实 PostgreSQL 17.5 | repository/migration/production migration 38 passed | exact owner read 不改变 lease；schema 无变更 |
| 受影响组合 | 201 passed、1 existing warning | formal chain、Persistence、Delivery、安全 composition、production roles |
| 完整默认后端 | 2433 passed、272 dependency-conditioned skips、2 deselected、1 existing warning | 默认未提供外部依赖；不是 Production GO |
| 静态检查 | Ruff、Mypy 372 source files 通过 | 无新增 ignore、依赖或 schema |
| production-local build/up + baseline | 退出 0；镜像 `030ce1a17c01768206759250bfb8b9db98133ff43ec2399e55d6f23e6cd33fb1` | schema head=`0024_formal_candidate_checkpoint`；API/KSS 健康 |
| production-local 状态 | command=0、in-progress=0、checkpoint=0、Version=0、Active=0 | 未调用 formal POST 或 status GET；readiness 仅因 `published_agent=not_ready` 返回预期 HTTP 503 |

隔离 PostgreSQL 使用本机已有 `postgres:17.5-alpine` 镜像和端口 `55442`。验证后容器已
停止并由 `--rm` 删除。未读取 `.env`、Secret 文件或生产数据。

### 53.4 状态与下一边界

- [KNOWN | HIGH] TDD-05U 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] status GET 不是 recovery mutation 或 publication approval。需要恢复时，仍由原操作者
  重放 exact POST。
- [FRAME | HIGH] 下一核心切片应优先收集真实外部 KSS/model online-smoke 证据，
  且保持在发布授权之外。cross-operator audit/listing、后台 recovery、Grant lifecycle 和
  Product Release Authority Gates 继续独立处理。

## 54. TDD-05V：exact Formal Candidate external-dependency probe

### 54.1 冻结边界

[FRAME | HIGH] 本片新增一个显式 production-local host 入口，只接受 exact Agent ID、Draft ID
和正整数 revision。它复用 production composition 的只读 Candidate assembler；Draft 选择 exact
Release 与 model-role configuration，deployment 注入 Binding Profile、Secret Handle、egress、
Admission Scorer 和预算。问题是 checked-in 非敏感 fixture，调用者不能选择 Release、model、
credential、Profile、question 或 budget。完整决策见 ADR-0226。

[BOUNDARY | HIGH] materializable Candidate 使用 governed `RunPurpose.VALIDATION` 经过既有 KSS
runtime、Evidence Admission 和 external model；成功必须为 `ANSWERED_WITH_CITATIONS`，至少一条
accepted citation 非空，并将 trace/receipt 写入 immutable artifact store 后 exact read-back。
输出不含 question、answer、Candidate/Evidence content、credential、raw prompt 或 upstream detail。

[BOUNDARY | HIGH] 本片不伪造 production-local Phase F authorization，也不调用 formal publication
endpoint。它最多允许一条 KSS Query 和两份 validation artifact，不创建或重放 Command、Phase F、
Reference、Grant、Version 或 Active pointer。结果不是 formal online-smoke qualification、
publication approval、release Gate 或 Production GO。

### 54.2 RED → GREEN → 诊断收敛

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | exact Draft identity、固定问题、secret-free success output | verifier 文件不存在，1 failed |
| GREEN-1 | 增加 exact verifier 和成功结果约束 | 聚焦 1 passed |
| RED-2 | Candidate runner 必须执行 governed KSS/model path、只接受 cited evidence 并保留 exact artifacts | runner import 不存在，collection failed |
| GREEN-2 | 增加 Candidate runner、production composition 与 immutable retention | runner 聚焦 1 passed；无 citation 失败关闭 |
| RED-3 | host 只能接受三个 exact Draft 参数；CLI 不回显上游 detail | main/host 不存在，分别按预期失败 |
| GREEN-3 | 增加 bounded CLI 与三参数 host 入口 | 聚焦入口与输出测试转绿 |
| RED-4 | 已知不可 materialize Candidate 必须返回明确且无内容泄露的错误码 | CLI 仅返回 generic failure，1 failed |
| GREEN-4 | materializer error 保持具体类型穿透，CLI 映射固定 error code | 1 passed；错误正文不进入输出 |

### 54.3 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 聚焦/受影响 | 156 passed、1 existing warning | exact verifier、runner、composition、KSS runtime 与 production API |
| 完整默认后端 | 2441 passed、272 dependency-conditioned skips、2 deselected、1 existing warning | 默认不执行外部模型；不是正向 upstream 证据 |
| 静态检查 | Ruff、focused format、Mypy 372 source files、lock、domain-context、Shell 通过 | whole-repository format 仍有既有非本片 drift；未批量重排 |
| production-local build/up + baseline | 退出 0；镜像 `be61c35f3bfe3ddb439f30ffbd96f048c0816129fec315890dabe930d60bda63` | schema `0024`；API/KSS 健康；readiness 仅 `published_agent=not_ready` |
| exact Draft@13 live probe | 退出 1；`formal_candidate_contract_bundle_not_materializable` | secure materializer 在 KSS Query 前拒绝 package-escaping audit paths |
| 副作用边界 | Command 0、Version 0、Active 0、Reference 0、Grant 5、Query 21，前后不变 | 未创建 Query 或 artifact；没有改写 Candidate/Draft/Grant |

[KNOWN | HIGH] 受控结构诊断只投影路径字段，确认 Draft@13 的 immutable Contract Bundle 使用
`../../runs/latest/trace.jsonl` 与 `../../runs/latest/governance_receipt.md`。这些路径逃逸 Candidate
package；既有 secure materializer 按设计拒绝。`./policy.yaml` 解析为 package 内文件，不是本次
阻断原因。不得放宽 traversal 校验、运行时偷偷重写 Candidate，或用独立 deployment manifest
冒充 exact Draft evidence。

### 54.4 状态与下一边界

- [KNOWN | HIGH] TDD-05V 代码能力与 fail-closed 副作用边界为 `LOCAL_VERIFIED`；当前
  Draft@13 live external-dependency probe 为 `BLOCKED`，Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] 当前没有正向外部 KSS/model 证据，也没有 formal publication approval 或
  Production GO。
- [FRAME | HIGH] 下一切片应只处理 exact Draft Contract path normalization：通过既有 Workspace
  complete-Contract validation、revision CAS 和 audit 创建新 revision，将 audit paths 收敛为
  package 内相对路径；不得改变其它 Contract 内容，也不得直接写数据库。随后对新 revision 重跑
  read-only preflight 和本 probe。完整 formal POST、Reference/Grant mutation 与发布 Gate 继续不执行。

## 55. TDD-05W：exact Draft Contract path normalization

### 55.1 冻结边界

[FRAME | HIGH] 本片只修复 TDD-05V 发现的 Draft Contract path blocker。显式
production-local host 入口只接受 exact Agent ID、Draft ID 和 expected revision。调用者不能传入
目标路径、YAML、Release、model 或 credential。checked-in 目标固定为 `./trace.jsonl` 和
`./governance_receipt.md`。完整决策见 ADR-0227。

[FRAME | HIGH] 命令要求 `audit.trace_path` 与 `audit.receipt_path` 唯一、为 scalar 且同时等于
已知 legacy pair。它只替换两个 scalar byte ranges，并以 parsed document equality 证明其它字段
未变。真正写入继续复用 Workspace complete-Contract validation、exact revision CAS、原子 Draft
save 和 configuration audit。missing、duplicate、mixed、unexpected 或 already-normalized 都不写入。

[BOUNDARY | HIGH] 成功最多创建一个新 Draft revision 和一条既有类型的 configuration audit。
不修改 Policy/Tools/extra files，不创建 Command、Phase F、Reference、Grant、Version 或 Active
pointer，也不授权发布。本片不执行 formal publication endpoint。

### 55.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | exact CAS 只修改两个 audit paths，并返回 bounded result | command 文件不存在，1 failed |
| GREEN | 增加 YAML node-range mutation、Workspace CAS、结果重验、bounded CLI 和三参数 host | 聚焦主路径 1 passed；完整聚焦 15 passed |
| REFACTOR | 收敛 known legacy/target constants；补 revision drift、already-normalized、mixed、unknown、duplicate、workspace rejection/result drift | 聚焦 15 passed；受影响回归 123 passed |

### 55.3 production-local 证据

[KNOWN | HIGH] 第一次 build 在 Docker Hub anonymous-token 获取阶段因 EOF 退出，尚未进入产品
构建，也未修改 Draft。重试成功生成镜像
`bf5fb14877db747a4ff9e3a0e0df1d1f36461903ce6e91240c6e68d3d0356998`。baseline 在
schema `0024_formal_candidate_checkpoint` 退出 0；readiness 仍只因
`published_agent=not_ready` 返回预期 HTTP 503。

[KNOWN | HIGH] 写入前 Draft revision 为 13，`agent.draft.contract_updated` audit count 为 7。
exact CAS 退出 0，返回 revision 14、`./trace.jsonl` 与 `./governance_receipt.md`。随后对 revision 14
重放，命令以 `draft_contract_paths_already_normalized` 退出 1。最终 Draft 保持 revision 14，audit
count 为 8；没有 revision 15。

[KNOWN | HIGH] Draft@14 read-only preflight 退出 0。Formal Candidate SHA-256 为
`1e5aee4b24b184333a1d4f4d0a7798716cf8cfe426da4046605c06d3aea063bd`，Knowledge Release
candidate SHA-256 为
`085038769d44ded6f031de42a8eaf3fa4a723d390eb45db9da2b5914bea89299`，exact Release 仍为
`release-a4b70851cb914862000e15c3`，`publication_authorized=false`。

[KNOWN | HIGH] 用户随后明确授权：可把 exact Draft@14 在固定问题下产生的 Candidate Evidence
发送到 configured model，并允许最多新增一条 KSS Query 和两份 immutable validation artifacts。
执行前 Command、Version、Active、Reference 与 artifact 均为 0，Grant 为 5，Query 为 21。

[KNOWN | HIGH] probe 只执行一次，并以 bounded
`formal_candidate_external_smoke_failed` 退出 1。新增 Query
`knowledge-query-f25bebcd4a9946578c46280a68387e32` 在 exact Release
`release-a4b70851cb914862000e15c3` 上为 `succeeded`，`result_availability=available`，
Candidate count 为 3，result digest 已持久化。Query count 变为 22；没有重试。

[KNOWN | HIGH] exact Draft 的 Model Connection ID 为 `model_deepseek`。当前受管记录为 active
revision 1，provider 为 `deepseek`，model 为 `deepseek-v4-flash`，host 为 `api.deepseek.com`，
且存在受管 credential record。由于 CLI 按设计隐藏上游 detail，现有证据不能区分 Evidence
Admission、external model transport/output、citation validation 或 artifact retention 前失败。
ProofAgent artifact count 仍为 0，因此没有 immutable trace/receipt 可用于正向验收。

[KNOWN | HIGH] 执行后 Command、Version、Active 与 Reference 仍为 0，Grant 仍为 5；没有进入
Phase F、formal publication 或 activation。授权上限被遵守：新增一条 KSS Query、零份
ProofAgent validation artifact。

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 聚焦 | 15 passed | exact mutation、CAS、no-op replay、bounded CLI/host |
| 受影响 | 123 passed、1 existing warning | Workspace、Memory repair、preflight、external probe、production migration contracts |
| 完整默认后端 | 2456 passed、272 dependency-conditioned skips、2 deselected、1 existing warning | 不包含 configured-model 外发 |
| 静态检查 | 全仓 Ruff、Mypy 374 sources；focused format、uv lock、domain context、Shell、diff 通过 | 未做无关文件批量格式化 |
| production-local CAS | Draft 13→14；audit 7→8 | replay 不创建 revision 15 |
| read-only preflight | 退出 0 | 新 Candidate 摘要；不授权发布 |
| external-dependency probe | `BLOCKED` | 执行 1 次；KSS Query succeeded/3 candidates，后续 generic failure，artifact 0 |

### 55.4 状态与下一边界

- [KNOWN | HIGH] TDD-05W 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] Draft Contract path blocker 已通过新 revision 修复，没有放宽 materializer 或在
  probe 内改写 Candidate。
- [KNOWN | HIGH] 正向 external KSS/model cited-answer evidence 为 `BLOCKED`。本次一次性授权已消费，
  不能用同一授权重试；当前也没有 Phase F、formal publication、release Gate 或 Production GO。
- [FRAME | HIGH] 下一核心切片应先增加 secret-free external-probe stage classification，使失败能够
  区分 KSS、Evidence Admission、model transport/output、citation validation 与 artifact retention，
  且继续隐藏 question、answer、Candidate/Evidence content、credential、raw prompt 和 provider detail。
  完成诊断能力并通过回归后，新的真实探针仍需另行确认一次 Query/artifact 外发预算。

## 56. TDD-05X：secret-free external probe stage diagnostics

### 56.1 冻结边界

[FRAME | HIGH] 本片只修改 TDD-05V 既有 external probe 的失败诊断。稳定错误码区分 KSS、
Evidence Admission、configured model transport/output、citation validation 和 artifact retention。
结构化事实不足或含义不明确时继续返回 `formal_candidate_external_smoke_failed`。完整决策见
ADR-0228。

[BOUNDARY | HIGH] 分类只读取既有结构化 subsystem code、accepted/citation facts 和 trace-safe
`final_answer_validation_failed`/`model_error` 事件。CLI 不返回 exception message、question、answer、
Candidate/Evidence content、credential、Secret Handle、raw prompt、provider identity/detail、artifact
bytes、local path 或 stack trace。

[BOUNDARY | HIGH] 诊断只在 external probe 调用共享 governed runtime 时开启。正式 online smoke 与
production candidate validation 保持原行为。本片不新增 executor、retry、HTTP/Dashboard surface、
dependency call、Grant mutation、publication side effect 或 migration；所有验证使用本地可控替身。

### 56.2 测试设计

| Given | When | Then |
| --- | --- | --- |
| governed execution 抛出结构化 KSS、Admission 或 model error | exact Candidate runner 执行 probe | 返回对应 stable stage code，异常正文不进入公开结果 |
| run 返回 accepted/citation 与 trace-safe final-answer facts | runner 检查 cited success | 无 accepted 归 Admission，缺 citation 或 citation binding 归 citation，其他 final-answer validation 归 model |
| trace/receipt source 或 immutable exact read-back 失败 | runner 保留 validation artifacts | 返回 artifact-retention code，不返回 bytes 或 path |
| run 失败但 accepted/citation 与 trace facts 无法定位阶段 | runner 执行 fail-closed gate | 保持 generic error，不根据 outcome 或 message 猜测 |
| CLI 捕获 stage diagnostic | verifier 输出失败 JSON | 只返回既有 schema、`status` 和 stable `error_code` |

[FRAME | HIGH] 测试从公开 runner 和 CLI 进入真实分类路径。Mock 只替代 governed external
execution 和 artifact store 边界，使用虚构的错误正文、Evidence metadata 与 artifact bytes。测试不
断言私有 helper、内部调用顺序、provider payload 或真实外部依赖行为。

### 56.3 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED-1 | `PA_KNOWLEDGE_002` 必须成为 bounded KSS stage code | runner 只有无 `code` 的 generic validation error，1 failed |
| GREEN-1 | external probe execution 识别 KSS structured code | KSS tracer 1 passed；其他 runtime caller 未启用分类 |
| RED-2 | Admission、model、citation、artifact 与 CLI public code 均需稳定分类 | 9 failed、2 passed；缺失边界与原 generic 行为一致 |
| GREEN-2 | 增加 structured exception、trace-safe run facts、source/immutable artifact 分类和 CLI 映射 | external-probe behavior 18 passed |
| REFACTOR | 补 source artifact missing 与 ambiguous-stage negative tests；未知失败不猜测根因 | focused files 95 passed；affected set 118 passed |

### 56.4 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| external-probe behavior | 18 passed | 五类稳定码、generic fallback、无 detail 输出 |
| 聚焦文件 | 95 passed | formal Candidate runner 与 production-local CLI |
| 受影响 | 118 passed、1 existing warning | formal chain、production readiness、production roles/composition、external verifier |
| 完整默认后端 | 2467 passed、272 dependency-conditioned skips、2 deselected、1 existing warning | 首轮 8 项仅因 sandbox 禁止 loopback bind 失败；同一命令在允许本机测试端口的环境中通过 |
| 静态检查 | 全仓 Ruff、Mypy 372 sources、focused format、diff 通过 | 无新增 ignore、依赖、schema 或网络入口 |
| external dependency | 未执行 | 没有新增 KSS Query、model request 或 validation artifact |

### 56.5 修改文件、状态与下一边界

| 文件 | 变更 |
| --- | --- |
| `proof_agent/delivery/production_agent_validation.py` | external-only diagnostic type、structured/trace/artifact classification |
| `docker/production-local/verify_formal_candidate_external_smoke.py` | bounded CLI stage-code mapping |
| `tests/test_formal_production_agent_candidate.py` | runner 的五类、source artifact 与 ambiguous fallback 行为测试 |
| `tests/test_production_local_formal_candidate_external_smoke.py` | CLI stable stage code 测试 |
| `docs/adr/0228-classify-formal-candidate-external-probe-failures-without-content.md` | 公开错误契约与内容安全边界 |
| `docs/features/kss-configuration-publication-loop/{scope-plan.md,feature_context.md,tdd-report.md}` | Scope、状态与 TDD 证据 |
| `docs/{PROJ_CONTEXT.md,development-progress.md,operations-deployment-development-guide.zh-CN.md}` | 项目索引、开发状态与运维错误码说明 |

- [KNOWN | HIGH] TDD-05X 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] 这组本地分类测试不能追溯判断 Draft@14 上一次 generic failure。正向 external
  KSS/model cited-answer evidence 继续为 `BLOCKED`，不是 formal online-smoke qualification、
  publication approval、release Gate 或 Production GO。
- [FRAME | HIGH] 下一次真实 probe 必须重新取得 exact Candidate 和 Query/artifact 副作用预算的明确
  授权。若执行失败，只能依据本片新增的 bounded error code 选择下一项安全检查，不得读取或输出
  Candidate Evidence、raw prompt、provider detail 或 credential，也不得用同一授权自动重试。

## 57. TDD-05Y：production validation ArtifactStore cutover 与外部探测前置门

### 57.1 冻结边界与新发现

[FRAME | HIGH] 本片原计划对 exact Agent
`agent_management_insurance_specialist`、Draft
`c8191d9e-ee0a-5324-8c6d-e0b88622ab61` revision 14 执行一次 fixed-question external
probe，预算上限为一条新 KSS Query 和两份 immutable validation artifacts；不进入 Phase F、
formal publication 或 activation。

[KNOWN | HIGH] 在消耗 Query 前的源码检查发现，生产 composition 注入当前
`S3ArtifactStore`，而 shared validation runtime 仍调用只存在于测试 fake 的旧
`key/content/media_type + get_exact` 协议。真实执行即使通过 model/citation，也会在 retention
失败。本片因此先按 ADR-0229 修复同一 production port，不使用外部调用验证已知失败路径。

### 57.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | validation fake 改为当前 `ArtifactStore` port；S3/Filesystem 必须返回 exact URI | 3 failed：旧关键字参数与两个缺失 `exact_uri` |
| GREEN | runtime 写入 typed request，校验 owner/kind/digest/length，exact head/open 后转换既有 public ref | 3 passed |
| REFACTOR | formal Candidate/online smoke fakes 统一到同一端口；删除 validation-only key protocol | 相关完整集合 115 passed |

### 57.3 本地与真实依赖验证

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| Artifact/formal Candidate/readiness 相关集合 | 115 passed | 使用本地可控执行替身，不调用 KSS/model |
| 完整默认后端 | 2467 passed、272 skips、2 deselected、1 existing warning | 首轮 8 项仅因 sandbox 禁止 loopback bind；允许本机端口后同一命令通过 |
| 静态检查 | Mypy 372 sources、全仓 Ruff、8 个变更 Python 文件 format 通过 | 未批量格式化既有 216 个非本片文件 |
| production-local 镜像与 baseline | image `1847e70c79bbaf57b36ce93a4a1eaba3267ad37cf4346aa462ec0b3ef4e1be2d`，baseline 通过 | `/readyz` 仍按预期仅因 `published_agent=not_ready` 返回 503 |
| 真实 MinIO validation pair | trace/receipt write、exact head/open、含 `runs/` 前缀 URI、exact delete 全通过 | 两份非敏感测试对象已删除；不构成 external smoke evidence |
| Draft@14 read-only preflight | Candidate/Release 摘要与 exact Release 通过，`publication_authorized=false` | 无 KSS/ProofAgent 写入 |

### 57.4 外部授权门与副作用

[KNOWN | HIGH] 用户随后明确同意把 exact Draft@14 fixed-question Candidate Evidence 发送给受管
连接 `model_deepseek` revision 1（ACTIVE，DeepSeek `deepseek-v4-flash`，
`https://api.deepseek.com`），允许最多新增一条 KSS Query 和两份 immutable validation
artifacts，并要求只执行一次、失败不重试、不进入 Phase F、formal publication 或 activation。
执行前只读重验 Draft、Candidate/Release 摘要、模型目的地、镜像和副作用基线，全部与授权一致。

[KNOWN | HIGH] 既有三参数入口只执行一次，并返回
`formal_candidate_external_smoke_evidence_admission_failed`。该稳定码只证明执行停在
ProofAgent Evidence Admission 边界，没有 accepted evidence；不证明 Candidate Evidence 质量根因，
也不披露 question、Candidate Evidence、answer、provider response、credential 或日志。按授权立即
停止，没有重试。

[KNOWN | HIGH] Query 总数和 exact Release Query 数量分别保持 22 和 13。本次调用精确重放既有
`knowledge-query-f25bebcd4a9946578c46280a68387e32`；该 Query 仍为 `succeeded`，
`result_availability=available`，Candidate count 为 3，result digest 为
`sha256:c7e91ca01b82e9376e65f4d60491307f99a9f511cfd372cff32c57cf104d29d9`。
没有创建第 23 条 Query。

[KNOWN | HIGH] 执行后 Formal Command、Published Version、Active、KSS Reference 和 ProofAgent
Artifact exact version 仍为 0，Grant 仍为 5；`agent_validation` artifact 为 0。没有 Phase F、
publication 或 activation 副作用。授权预算实际增量为零条 Query、零份 validation artifact。
受治理失败后的 production-local baseline 再次通过；`/readyz` 仍只因
`published_agent=not_ready` 按设计返回 HTTP 503。

- [KNOWN | HIGH] ADR-0229 的 validation ArtifactStore cutover 为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] TDD-05Y external probe 为受治理失败结果，不是正向 cited-answer evidence。
  本次一次性授权已经消费，不得自动重试。
- [BOUNDARY | HIGH] 当前结果不是 formal online-smoke
  qualification、publication approval、release Gate 或 Production GO。

## 58. TDD-05Z：secret-free Evidence Admission reason diagnostics

### 58.1 冻结边界

[FRAME | HIGH] 本片只细化 external probe 已有
`formal_candidate_external_smoke_evidence_admission_failed` 阶段。失败输出继续保留 stage
`error_code`；只有 typed scorer failure 或 trace-safe Evidence Evaluation metadata 能增加一个
allowlist `reason_code`。分类不得读取或返回 exception message、分数、阈值、Candidate/Evidence
标识或内容、question、answer、provider response、credential、raw prompt、artifact bytes/path 或
stack trace。

[BOUNDARY | HIGH] 本片不改变 Evidence Admission 通过/拒绝逻辑，不增加 rank fallback、重试、
network call、持久化、HTTP/Dashboard surface、KSS Query、validation artifact、Grant、Phase F、
formal publication 或 activation。未知结构化事实继续只返回 Admission stage code。

### 58.2 测试设计

| Given | When | Then |
| --- | --- | --- |
| Scorer authorization/transport/response contract 不可用 | scorer port 失败 | 保留 `PA_KNOWLEDGE_001`，并附带 `evidence_admission_scorer_unavailable`；不包含下游正文 |
| Scorer 返回非有限值或超出 0 至 1 | Control Plane 校验分数 | 失败关闭为 `evidence_admission_score_invalid` |
| Candidate 存在且分数均低于 `min_score` | Evidence Evaluation 失败 | metadata 为 `knowledge_candidate_threshold_not_met`，不误报零 Candidate |
| external probe 收到 trace-safe no-evidence reason | runner 分类 | stage code 不变，只投影 allowlist reason |
| 未知 reason 或非 Admission stage 携带 reason | diagnostic/CLI 校验 | 拒绝 reason；不根据正文猜测 |
| 失败 CLI 输出 | v2 envelope 序列化 | 只包含 schema、status、stage error 和可选 allowlist reason |

### 58.3 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | scorer boundary 无 reason；threshold 错标为 `zero_knowledge_candidates`；runner 无 reason；CLI 构造 reason 时退回 generic failure | 4 failed，失败点均为目标行为 |
| GREEN | 新增 typed Admission reason、threshold metadata、runner trace-safe mapping 和 v2 CLI reason projection | 4 passed |
| REFACTOR | scorer reason 贯穿 runner；普通 `PA_KNOWLEDGE_001` 不猜 reason；未知 reason 与跨 stage reason 均拒绝 | 核心集合 11 passed |

### 58.4 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 核心新增行为 | 11 passed | scorer、threshold、runner、CLI 与负向 allowlist |
| 受影响回归 | 146 passed、1 existing warning | KSS retrieval、governed run、formal Candidate、readiness 与 production roles |
| 完整默认后端 | 2474 passed、272 dependency-conditioned skips、2 deselected、1 existing warning | 沙箱首轮仅 8 项 loopback bind 被禁止；同一完整命令在允许本机测试端口的环境中通过 |
| 静态与一致性 | 全仓 Ruff、Mypy 372 sources、domain context、diff、uv lock 通过 | 未执行全仓格式化；没有新增依赖 |
| external dependency | 未执行 | 0 新 Query、0 model/scorer request、0 validation artifact |

### 58.5 状态与下一边界

- [KNOWN | HIGH] ADR-0230 与 TDD-05Z 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] failure envelope 显式升级为
  `production-local-formal-candidate-external-smoke-failure.v2`；success envelope 保持 v1。
- [BOUNDARY | HIGH] 本片不能追溯分类 TDD-05Y 已结束的 live failure，也不是 positive external
  cited-answer evidence、formal online-smoke qualification、publication approval、release Gate 或
  Production GO。
- [FRAME | HIGH] 若后续需要再次验证 exact Draft，必须重新取得 exact Candidate、固定问题、模型
  目的地及 Query/artifact 副作用预算的明确授权。新的调用失败时，只能依据 v2 的 bounded stage/
  reason 选择下一项本地检查，仍不得自动重试。

## 59. TDD-06A：fixed-synthetic production-local Admission Scorer verification

### 59.1 冻结边界

[FRAME | HIGH] 本片只增加一个零参数 production-local Scorer 验证入口。它固定构造一个完全虚构
的问题和一个 relevance Candidate，经既有 production runtime binding 取得部署装配的 Admission
Scorer。调用者不能提供 Draft、Release、问题、Candidate、Model Connection、credential 或预算。

[BOUNDARY | HIGH] verifier 不调用 KSS service/query factory、Draft-selected answer model、artifact
store 或 formal publication service。它不能创建 Query、Grant、Reference、validation artifact、
Formal Command、Version 或 Active pointer，也不能进入 Phase F。

### 59.2 RED → GREEN → REFACTOR

| 阶段 | 行为 | 证据 |
| --- | --- | --- |
| RED | 固定 synthetic scorer verifier 与零参数 host 入口尚不存在 | 聚焦文件 5 failed，均为目标文件缺失 |
| GREEN | 通过 public runtime binding 对一个固定 synthetic Candidate 评分；KSS fake 被设置为调用即失败 | 5 passed |
| REFACTOR | 增加 Scorer identity、Candidate set、NaN/越界/布尔分值、失败脱敏、零参数与 deployment-owned 配置合同 | 最终聚焦 10 passed |

### 59.3 验证结果

| 检查 | 最终结果 | 限定 |
| --- | --- | --- |
| 聚焦行为 | 10 passed | 固定 synthetic 输入、KSS 零调用、identity/response fail-closed 与 secret-free envelope |
| 受影响回归 | 59 passed、1 existing warning | production runtime、KSS client、roles、external probe 与 readiness |
| 完整默认后端 | 2484 passed、272 dependency-conditioned skips、2 deselected、1 existing warning | 没有新增依赖或 migration |
| production-local build/baseline | image `e2bb61b0c78a7e648ccd4d662a4094660327094f49c49ca804f7fb6b79011088`；baseline 通过 | schema `0024`；`/readyz` 仍只因 `published_agent=not_ready` 返回预期 503 |
| fixed synthetic live verifier | 1 Candidate、1 score、固定 Scorer ID/revision，status passed | 仅调用 `models.internal` compatibility Scorer；输出不含输入正文、标识、分数、credential 或 response |
| 副作用只读核对 | KSS Query=22；Formal Command=0 | 与 TDD-05Y 后已记录状态一致；未调用 DeepSeek 或 formal endpoint |

### 59.4 状态

- [KNOWN | HIGH] ADR-0231 与 TDD-06A 建议结论为 `LOCAL_VERIFIED`；Feature 继续为
  `PARTIAL_VERIFICATION`。
- [KNOWN | HIGH] production-local compatibility Scorer 的 identity、versioned Secret Handle、Vault
  resolution、guarded egress 和 strict exact-candidate response contract 已由固定 synthetic live run
  联合覆盖。
- [BOUNDARY | HIGH] 该结果不能判断 Draft@14 的 Candidate 质量、阈值或 policy root cause，不能
  追溯分类 TDD-05Y，也不是 positive external KSS/model cited-answer evidence、formal online-smoke
  qualification、publication approval、release Gate 或 Production GO。
