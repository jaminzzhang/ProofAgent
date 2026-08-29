# KSS Release Reference 与 Release lifecycle 本地调用指南

[KNOWN | HIGH] TDD-03A 至 03E 仅提供可信 application Interface。它们用于在外部 Published Agent Version 可执行前持久化 exact KSS Release 引用，在可信 verifier 证明该 immutable external resource 永久失去执行与回滚资格后注销引用，把不再允许新采用的 Release 标记为 `deprecated`，在零 active Reference 且满足服务端 retention policy 后执行普通退役，或因安全/严重数据完整性事件紧急撤销；没有 HTTP/BFF/Dashboard 命令，也不会激活、替换或通知 Agent。

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

## 稳定错误

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

[FRAME | HIGH] 注册成功不代表 Agent 已发布或激活。跨服务顺序仍应是“先注册 KSS Reference，后尝试 ProofAgent publication/activation”；后续失败保留引用是安全孤儿。弃用有意保留既有查询与引用，普通退役只能处理零 active Reference；紧急撤销只提供 KSS 本地 query denial 和受影响数量。当前尚未实现 ProofAgent publication/activation 接线、真实注销 verifier、后台认证对账、lifecycle 网络权限、affected-reference 明细/通知、ProofAgent runtime/rollback 失败关闭接线、删除资格、生产 retention 配置或部署，因此 application-only 核心不能外推为生产退役或完整紧急止损授权。
