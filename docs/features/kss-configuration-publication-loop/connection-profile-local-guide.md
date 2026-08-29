# Connection Profile 本地接口使用说明

## 适用范围

[KNOWN | HIGH] 本说明对应 TDD-01B 的 KSS PostgreSQL、管理 API 和 Worker 协议接线。它不是生产启用步骤。`bootstrap/processes.py` 仍使用静态 registry；ProofAgent BFF、Dashboard 和三角色包映射尚未接入 Profile 操作。

[FRAME | HIGH] 配置和数据权威保持分离：KSS 保存非敏感 Profile revision 和数据版本，Vault 保存凭据值，部署策略控制 connector、egress、trust root 和硬限制。Knowledge Operator 不因发布 Profile 获得 Agent 发布或激活权限。

## 本地组合的前置条件

1. 在独立测试 PostgreSQL 上显式执行 KSS migrations，包含 `0007_connection_profiles` 和 `0008_profile_synchronizations`。不要把生产 DSN 用于合同测试。
2. 调用 `knowledge_source_service.bootstrap.runtime.compose_runtime`，显式指定 `managed_connection_profiles=True`、Profile ID factory 和 synchronization ID factory。
3. 提供部署侧 `ConnectionProfileDeploymentPolicy`。缺少策略时可以保存 Draft，但校验、发布和同步准入失败关闭；测试中的 `DeploymentPolicy` 不能用于生产。
4. API 组合不提供 `profile_snapshot_readers`，因此不会创建同步执行器或打开上游。Worker 组合必须提供实现 `ConnectionProfileSnapshotReaders` 的适配器；该适配器负责 exact Secret、egress、TLS 和流式大小限制。本轮尚未提供真实上游适配器。
5. 从可信服务端认证获得 operator 和 `knowledge_source.view/edit` 权限。请求头或请求体不能声明角色、权限或操作者。浏览器不得直接使用 KSS operator credential。

受管组合不能同时提供 `snapshot_connections`。`managed_connection_profiles` 是 Python 组合参数，不是已支持的 CLI 或环境变量开关。

## 调用顺序

所有路径均为 KSS 服务端管理接口。变更 Profile 的请求必须携带认证和 `Idempotency-Key`；这里不展示凭据值。

| 顺序 | 方法与路径 | 输入要点 | 成功结果 |
| --- | --- | --- | --- |
| 1 | `POST /v1/knowledge-spaces`，随后 `POST /v1/knowledge-spaces/{space}/knowledge-sources` | 创建目标 Space/Source | Profile 和同步任务通过同 Scope 外键关联 |
| 2 | `POST /v1/connection-profiles` | `knowledge_space_id`、`knowledge_source_id`、服务端 `configuration` | `201`，Draft revision 1；`Location` 给出资源路径 |
| 3 | `POST /v1/connection-profiles/{id}:validate` | `{"expected_revision":1}` | `200`，`validated`；策略不可用返回 `503`，不推进状态 |
| 4 | `POST /v1/connection-profiles/{id}:publish` | exact `expected_revision` | `200`，`published`；重新检查部署策略 revision |
| 5 | `POST /v1/knowledge-source-synchronizations` | exact `connection_profile`，见下例 | `202`，v2 queued resource，包含配置 digest 和轮询链接 |
| 6 | Worker 执行，然后 `GET` 同步资源的 `Location` | API 身份必须与任务 owner 一致 | `succeeded` 和 Source Version ID，或不泄漏上游错误的 `failed` |
| 7 | `GET /v1/connection-profiles/{id}?revision=1`；`GET /v1/connection-profiles/{id}/audit` | 读权限 | 安全 Profile 投影、成功事件和受限拒绝事件 |

同步请求示例（虚构业务字段）：

```json
{
  "knowledge_space_id": "space-claims",
  "knowledge_source_id": "source-claims",
  "connection_profile": {
    "connection_profile_id": "profile-claims",
    "revision": 1
  },
  "display_filename": "claims.json",
  "record_path": ["claims"],
  "field_types": {"claim_id": "string"}
}
```

Profile `configuration` 当前只支持 `http_json`：静态 HTTPS endpoint、可选 exact Secret Handle/version、部署批准的 egress/trust-root 引用和 `max_response_bytes`。不接受 token、password、任意网络白名单、可变 Secret version 或 URL query 凭据。完整配置只用于服务端提交，管理响应不返回 endpoint 或这些引用。

编辑使用 `PUT /v1/connection-profiles/{id}`，请求包含 `expected_revision` 和完整 `draft`。编辑创建新 revision，不改变旧 Published revision，也不移动既有任务。Source/Space 关联不可迁移；revision 冲突返回 `409`，需先读取当前状态再提交新命令。

## 幂等、状态和数据保留

- 同一 operator/key 的相同 Profile 命令返回原始回执，不重复写审计；换 payload 会冲突。后续编辑不会改写旧回执。
- 同步任务持久化 exact Profile ID/revision/digest。Worker 不解析 `latest`；策略失效、scope/digest 不符、上游失败或超限均失败关闭。
- 受管 Source Version 使用 `structured-dataset-revision.v2`，在不可变 artifact 内保存 processing lineage。catalog 校验 lineage digest 后回读 Profile 引用；旧 v1 artifact 仍可读取。
- 当前没有 revision、receipt 或 audit 的自动清理、删除接口或保留期限推断。需要独立的保留/恢复方案后才能清理。
- 本步骤只生成 Source Version，不自动创建 KSS Release、更新 Agent Draft 或激活 Agent。

Source Version 可用于下一步 [Base Draft 与 Preparation 本地接口](base-preparation-local-guide.md)。TDD-02B 至 02D 已有 `queued/running/ready/failed`、租约协调与 fenced candidate 结果；`ready` 仍不可查询，尚不能一次性发布 Release。

## 切换限制

[KNOWN | HIGH] 静态 v1 请求和回执保持原样，不自动导入 Profile。一个运行组合只接受一种连接权威；受管模式不回退到静态 `connection_id`。未来切换需要协调 API/Worker、处理遗留 v1 工作并验证真实上游适配器；不能让旧 Worker 消费 v2 任务，也不能把回滚二进制等同于可安全消费新数据。

[KNOWN | HIGH] PostgreSQL、MinIO 和 OpenSearch 的本地测试不替代真实 Vault/egress/TLS、Worker 发布窗口验证、Phase F、正式发布或恢复演练。详细证据和残余风险见 [TDD 报告](tdd-report.md)。
