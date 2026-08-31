# KSS Release Reference 与 Release lifecycle 本地调用指南

[KNOWN | HIGH] TDD-03A 至 03F 提供可信 application Interface，用于注册和可信注销 exact KSS Release 引用、执行 Release deprecation/ordinary retirement/emergency revocation，以及只读评估删除资格。TDD-04A 只把删除资格评估接入受 `knowledge_source.view` 保护的 KSS 管理 GET 和同源 ProofAgent BFF GET；TDD-05D 另行公开 Bearer client-authenticated Reference registration，并在 ProofAgent 增加独立 guarded registrar。注销和 lifecycle 仍无网络命令或 Dashboard 页面，也不会删除 artifact、发布、激活、替换或通知 Agent。

## 注册

```python
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.contracts.release_references import (
    RegisterKnowledgeBaseReleaseReferenceRequest,
)

reference = application.register(
    RegisterKnowledgeBaseReleaseReferenceRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-exact",
        external_resource_kind="published_agent_version",
        external_resource_id="agent-version-001",
        purpose="execution_or_rollback",
    ),
    authenticated_client_id="proof-agent",
    idempotency_key="publish-agent-version-001",
)
```

- `authenticated_client_id` 必须来自可信服务端身份，不接受浏览器自报值。
- `idempotency_key` 只在该客户端内生效；相同 key 必须保持相同请求指纹。
- 仅 exact `queryable` Release 可注册。Space、Base 和 Release tuple 必须全部匹配。
- 同一客户端的 immutable external resource 只能绑定一个 Release；需要变更知识时必须创建新的 Published Agent Version identity。
- 返回值和审计均为 secret-free identity/lifecycle facts，不包含 Agent configuration、用户内容或凭据。

### 通过公共客户端 API 注册

ProofAgent 或其他已注册服务客户端调用：

```http
POST /v1/knowledge-base-release-references
Authorization: Bearer <service-client-credential>
Idempotency-Key: formal-agent-reference:<provisional-version-id>
Content-Type: application/json
```

Body 只包含上例 `RegisterKnowledgeBaseReleaseReferenceRequest` 的六个字段，不包含
`authenticated_client_id`。KSS 只从 Bearer authentication 结果取得客户端身份；首次命令和
exact replay 都返回 `200` 与同一 `knowledge-base-release-reference.v1` active resource。
ProofAgent 的 concrete registrar 只接受 HTTPS origin，经 `GuardedHttpClient` 发出请求，使用
专用 client authorization factory，并拒绝 redirect、非 `200`、过大或非法响应、unknown field
和任一 Scope/Release/external-resource/kind/purpose/state 漂移。它不复用管理端 Knowledge
Operator credential，也不使 Reference staging 成为 Published 或 Active Agent Version。

### production-local 专用客户端

[KNOWN | HIGH] TDD-05J 的 checked-in production-local 配置使用
`knowledge/source-service/reference-client` Secret Handle。一次性
`kss-reference-client-bootstrap` 在 KSS migration 后、KSS API 启动前注册
`proof-agent-formal-publication-reference` client identity。Vault fixture、Reference Handle、
runtime Query Handle 和 Operator Handle 相互独立；production composition 检测到 Handle 复用时
立即失败。

该 bootstrap 只调用 `register_client`，不调用 `grant_release_query`。原因是当前
`knowledge_client_grants` 只授权 exact-Release Knowledge Query；它不是 Reference registration
Grant。没有 Query Grant 时，专用 Reference client 可以按公共客户端合同注册 Reference，但调用
Knowledge Query 会返回 `403 knowledge_query_access_denied`。这项本地 fixture 不能替代生产 Secret、
runtime Query client Grant、部署验证或 Production GO。

## 注销

```python
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.contracts.release_references import (
    DeregisterKnowledgeBaseReleaseReferenceRequest,
)

reference_application = KnowledgeBaseReleaseReferenceApplication(
    repository=release_reference_repository,
    deregistration_verifier=trusted_external_resource_retirement_verifier,
)
deregistered = reference_application.deregister(
    DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id=reference.release_reference_id,
    ),
    authenticated_client_id="proof-agent",
    idempotency_key="deregister-agent-version-001",
)
```

- 请求只包含 exact `release_reference_id`。调用者不能提交“已不可执行”、回滚资格、验证时间、Reference 数量或 TTL。
- `authenticated_client_id` 必须是 Reference owner。KSS 在验证前拒绝其他客户端，避免跨客户端探测或注销。
- `ReleaseReferenceDeregistrationVerifier` 由可信服务端组合注入。它必须独立确认 immutable external resource 已永久失去执行资格且不再保留为回滚目标；无法确认时返回无证明并失败关闭。
- 外部验证在 PostgreSQL 事务外执行。KSS 随后在事务内重新检查永久 receipt、锁定 exact active Reference，并复核 verification 所指 Reference 未漂移。
- 成功后 current state 为 `deregistered`；verifier ID、verification ID、数据库 `deregistered_at`、永久 receipt 和成功审计在一个事务提交。验证详情、Agent configuration、用户内容和凭据不进入 Ledger。
- 相同 client/key/fingerprint 精确重放原注销结果，不再次依赖 verifier；不同 key 的重复注销稳定拒绝。注册历史 receipt 仍返回原 active 注册事实，同一 immutable external resource 也不能重新绑定。
- 当前仓库没有 ProofAgent verifier adapter、证明签发或后台 reconciler。本 Interface 不能与测试 verifier 一起被解释为可用的生产对账流程。

## 弃用

```python
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
)
from knowledge_source_service.contracts.release_references import (
    DeprecateKnowledgeBaseReleaseRequest,
)

deprecated = lifecycle_application.deprecate(
    DeprecateKnowledgeBaseReleaseRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-exact",
    ),
    operator_id="knowledge-operator",
    idempotency_key="deprecate-release-exact",
)
```

- `operator_id` 必须来自可信服务端授权结果；当前没有可供浏览器调用的 delivery。
- 仅 `queryable` Release 可弃用。相同 operator/key/fingerprint 返回原结果；其他状态或不同请求稳定拒绝。
- 状态、`deprecated_at`、永久 receipt 和成功审计在同一个 PostgreSQL 事务提交。
- `deprecated` 仍可服务既有 Reference 与既有 Query Grant，并继续参与完整性扫描；它拒绝新 Reference 和新 Query Grant。
- 弃用不会修改、迁移或自动升级任何 Agent Version，也不授权普通退役或物理删除。

## 普通退役

```python
from datetime import timedelta

from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
)
from knowledge_source_service.contracts.release_references import (
    RetireKnowledgeBaseReleaseRequest,
)
from knowledge_source_service.domain.release_references import (
    ReleaseRetentionPolicy,
)

lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
    repository=release_lifecycle_repository,
    retention_policy=ReleaseRetentionPolicy(
        policy_id="release-retention-30d",
        minimum_age=timedelta(days=30),
    ),
)
retired = lifecycle_application.retire(
    RetireKnowledgeBaseReleaseRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-exact",
    ),
    operator_id="knowledge-operator",
    idempotency_key="retire-release-exact",
)
```

- `ReleaseRetentionPolicy` 必须由可信服务端组合注入且在 Application 生命周期内不可变。调用者不能提交当前时间、Reference 数量、保留截止时间或 eligibility 结论。
- 仅 `deprecated` Release 可普通退役。KSS 在持有 Release 行锁时检查自己的 active Reference Ledger，并使用数据库时间判断 `deprecated_at + minimum_age`。
- 任一 active Reference 都会阻断退役。只有通过上述可信注销准入后，该 Reference 才不再计入普通退役阻塞；无法验证的孤儿引用继续保守保留。
- 状态、policy ID、`deprecated_at`、`retention_eligible_at`、数据库 `retired_at`、永久 receipt 与成功审计在一个 PostgreSQL 事务提交。
- 相同 operator/key/fingerprint 返回原结果；并发调用不会产生重复状态转换或成功审计。
- `retired` 不执行物理删除，但不再出现在 Catalog query、完整性扫描或既有 Query Grant authorization 中。

## 紧急撤销

```python
from knowledge_source_service.contracts.release_references import (
    RevokeKnowledgeBaseReleaseRequest,
)

revoked = lifecycle_application.revoke(
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

- Delivery 必须先认证并授权 exact operator；application 只接受格式有效的可信身份。当前没有 lifecycle 网络入口或角色映射接线。
- `reason_code` 仅允许 `security_incident` 或 `severe_data_integrity_failure`；availability、普通清理和自由文本不是合法紧急原因。
- `confirmation` 必须精确为 `fail_closed_without_fallback`。成功结果与审计保留该确认事实，不允许调用者选择 fallback 或替代 Release。
- 仅 `queryable` 或 `deprecated` Release 可撤销。KSS 在 Release 锁内锁定并统计 active References，再以数据库时间原子提交 `revoked`、原因、确认、受影响数量、永久 receipt 与成功审计。
- 撤销不注销、不删除也不改写任何 Reference。提交后 Release 不再进入 Catalog query、完整性扫描或既有 Query Grant authorization；新 Reference registration 同样失败关闭。
- 撤销与 registration、deregistration、deprecation、ordinary retirement 竞争时由 Release/Reference 锁收敛。`retired` 与 `revoked` 是不同终态，不能相互覆盖。
- 当前 `affected_active_reference_count` 是 KSS 事务内的精确汇总，不是 affected-reference 明细、通知完成证明或 ProofAgent Run/rollback 隔离证明。

## 删除资格评估

```python
from knowledge_source_service.contracts.release_references import (
    AssessKnowledgeBaseReleaseDeletionEligibilityRequest,
)

lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
    repository=release_lifecycle_repository,
    artifact_retention_authority=artifact_retention_authority,
)
assessment = lifecycle_application.assess_deletion_eligibility(
    AssessKnowledgeBaseReleaseDeletionEligibilityRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-exact",
    )
)
```

- 该 Interface 是只读评估，不是物理删除命令。请求只含 exact Space/Base/Release identity，不接受 operator、idempotency key、调用者时间、Reference 数、retention 结论或删除原因。
- 只有普通 `retired`、具有完整 `retired_at`、零 active Reference，且服务端注入的 artifact-retention authority 对 exact Release 明确返回 `clear` 时，`eligible` 才为 `true`。
- `deregistered_reference_count` 是保留的历史事实，不阻断资格；active Reference 产生独立 blocker。旧版无完整 retirement history 的 retired Release 失败关闭。
- `queryable`/`deprecated` 返回 ordinary-lifecycle blocker；`revoked` 返回 incident-response retention blocker，并且不会调用 artifact-retention authority。缺少 authority、authority 返回 `None` 或明确 `blocked` 都失败关闭。
- 结果中的 `assessed_at` 来自 PostgreSQL 数据库时间。评估不写 state、receipt 或 audit，也不存在 command replay 语义；未来物理删除命令不得信任历史评估，必须在删除事务中重验引用、lifecycle、artifact retention 并单独记录可存续审计。

## 通过 KSS 与 ProofAgent BFF 读取

前置条件：KSS 管理端和 ProofAgent Operator Session 都必须为认证身份授予
`knowledge_source.view`。浏览器只访问同源 BFF，不持有 KSS operator token。

1. KSS 管理客户端读取：
   `GET /v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility`。
2. Dashboard 或其他同源浏览器调用方读取：
   `GET /api/config/knowledge-service/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility`。
3. 调用方只把结果作为当前观察事实。结果不得缓存为删除权限；后续状态或
   Reference 变化会使旧结果失效。

KSS 资源保留 trace-safe artifact authority/assessment identity。BFF 投影删除这两个
identity，并且不返回 KSS endpoint、operator credential、外部 Published Agent Version
identity 或 raw upstream problem。生产组合尚未配置 artifact-retention authority；普通
retired Release 因此返回 `artifact_retention_unverified`，不会被推断为可删除。

## 稳定错误

公共 HTTP 把内部错误收敛为不回显输入的 problem code：认证失败为
`invalid_client_credential`；缺失或空白 HTTP key 为 `invalid_idempotency_key`；请求 contract
非法为 `invalid_knowledge_service_request`；application key 非法为
`invalid_release_reference_request`；幂等或 external-resource 冲突为
`release_reference_conflict`；Release 不可采用或 Scope 不匹配为
`release_reference_not_admissible`；存储或完整性不可确认统一为可重试的
`release_reference_unavailable`。下表是 application/repository 内部诊断 code，不应原样回显
私有输入或数据库 detail。

| code | 含义 |
| --- | --- |
| `release_reference_invalid_client` | 可信客户端身份格式无效 |
| `release_reference_invalid_idempotency_key` | 幂等键格式无效 |
| `release_reference_idempotency_conflict` | 相同 client/key 被不同请求复用 |
| `release_reference_release_not_admissible` | Release 缺失或当前不可注册 |
| `release_reference_release_scope_mismatch` | exact Space/Base/Release tuple 不匹配 |
| `release_reference_external_resource_conflict` | immutable external resource 已有引用 |
| `release_reference_not_found` | exact Reference 不存在 |
| `release_reference_not_owned` | 认证客户端不是 Reference owner |
| `release_reference_not_deregisterable` | Reference 当前不是可注销的 active 状态 |
| `release_reference_deregistration_verifier_unavailable` | 服务端未注入可信注销 verifier |
| `release_reference_deregistration_unverified` | verifier 未提供与 exact Reference 匹配的永久失效证明 |
| `release_reference_integrity_unavailable` | durable row、receipt 或安全投影不一致 |
| `release_reference_storage_unavailable` | PostgreSQL 事务无法可靠完成 |

| lifecycle code | 含义 |
| --- | --- |
| `release_lifecycle_invalid_operator` | 可信操作员身份格式无效 |
| `release_lifecycle_invalid_idempotency_key` | 幂等键格式无效 |
| `release_lifecycle_idempotency_conflict` | 相同 operator/key 被不同请求复用 |
| `release_lifecycle_release_not_found` | Release 不存在 |
| `release_lifecycle_release_scope_mismatch` | exact Space/Base/Release tuple 不匹配 |
| `release_lifecycle_not_deprecatable` | Release 当前不是 `queryable` |
| `release_lifecycle_not_retirable` | Release 当前不是具有有效弃用时间的 `deprecated` |
| `release_lifecycle_not_revocable` | Release 当前不是可紧急撤销的 `queryable` 或 `deprecated` |
| `release_lifecycle_references_present` | KSS Reference Ledger 中仍有 active Reference |
| `release_lifecycle_retention_policy_unavailable` | 服务端未注入 retention policy |
| `release_lifecycle_invalid_retention_policy` | policy ID 或最短保留时长无效 |
| `release_lifecycle_retention_pending` | 数据库时间尚未到达保留截止时间 |
| `release_lifecycle_integrity_unavailable` | lifecycle receipt 或持久化事实不一致 |
| `release_lifecycle_storage_unavailable` | PostgreSQL 事务无法可靠完成 |

## 当前边界

[FRAME | HIGH] 注册成功本身不代表 Agent 已发布或激活。跨服务顺序仍是“先注册 KSS
Reference，后尝试 ProofAgent smoke/publication/activation”；后续失败保留引用是安全孤儿。
TDD-05F 的 application-only formal publisher core 已消费 TDD-05E qualification，并以最终一个
Configuration UoW 原子提交 Published Version、Active pointer CAS 与 publication audit。TDD-05G 已
提供 concrete governed online smoke runner：从 exact staging 安全物化临时只读 package，以
validation purpose 运行并 exact-read-back 保留 Trace/Receipt。TDD-05H/05I 已增加持久化幂等正式
发布命令并完成 production composition cutover；TDD-05O 进一步增加显式 exact Query authority
verifier。三个历史 queryable Release 都已有不同历史 Grant，所以首次 live verifier 在 Query 前
冲突失败关闭。操作者随后在 verifier 外部通过既有 KSS 管理发布 API 准备一个新的 exact Release；
两次 verifier 运行精确重放同一 Grant，并完成两个独立的 bounded Query。该结果仍无真实外部
KSS/model 上游联机证据。弃用有意保留既有查询与引用，普通退役只能处理零 active Reference；紧急撤销
只提供 KSS 本地 query denial 和受影响数量；删除资格 GET 只是只读 blocker projection。当前尚未
实现真实上游 smoke、真实注销 verifier、后台认证对账、deregistration/lifecycle 网络命令、
生产 client Secret/egress 接线、生产 artifact-retention adapter、物理删除、affected-reference
明细/通知、Dashboard lifecycle 页面、ProofAgent runtime/rollback 失败关闭接线、生产 retention
配置或部署，因此该本地投影不能外推为生产发布、退役、删除授权或完整紧急止损授权。
