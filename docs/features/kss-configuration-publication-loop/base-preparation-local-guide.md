# Base Draft 与 Preparation 本地接口使用说明

## 适用范围

[KNOWN | HIGH] 本说明对应 TDD-02B 至 02G 与 TDD-04C 至 04F：在独立本地 KSS 测试组合中保存 Base Draft、冻结 `queued` Preparation，通过服务端 Interface 领取、构建和提交 `ready/failed` 结果，以一次性核心 CAS 将未到期 ready candidate 发布为 exact Release，并可显式取消 queued/running 或回收一个到期 ready candidate。ProofAgent 已提供 Draft save/exact read、Preparation start/status、controlled publication 和 controlled cancellation 的同源、secret-free BFF；KSS 已提供可选 one-shot execution runtime。它们都不是生产启用步骤，尚未提供 Dashboard 页面、常驻 Preparation 进程或 expiry BFF。

当前提供显式调用的构建执行器、controlled publication/cancellation HTTP/BFF 和 one-shot 主动过期原语，没有常驻 Worker 循环、自动过期调度或 expiry HTTP 路由。`202` 表示准入资源已保存；`running` 只表示已领取；`ready` 表示已生成不可查询的候选；`failed` 只返回稳定错误码；`cancelled`、`expired` 与 `consumed` 是 durable 终态。只有成功 consumed 对应的 exact Release 可进入 KSS Query；Preparation 本身不能作为 Agent Release binding。发布或取消 Preparation 不会修改 Agent Draft 或激活 Agent。

## 前置条件与责任

1. 仅在独立测试 PostgreSQL 上应用 KSS migration runner，包含 `0009_base_preparations`、`0010_preparation_leases`、`0011_preparation_results` 和 `0012_preparation_publications`。`0012` 增加 `expired/consumed`、exact Release 外键和 publication lifecycle audit；不要把本说明用于生产 SQL 执行。
2. 使用已有管理接口创建 Space、Source 和 Base。Base 与成员 Sources 必须位于同一 Space。
3. 通过摄取或同步生成可用的 Source Versions。Draft 可以先保存；开始 Preparation 时每个成员都必须能解析到 ready Version。受管同步步骤见 [Connection Profile 本地说明](connection-profile-local-guide.md)。
4. 在 API 服务端调用 `compose_runtime`，除既有必需依赖外，显式提供 `base_preparation_id_factory` 和 `authenticate_operator`。未提供 factory 时不注册新路由；缺少认证时拒绝启用。需要执行候选时，另行显式提供 `base_preparation_execution`；默认 API runtime 不执行 Preparation。不要将测试内存仓储用作生产 fallback。
5. ProofAgent 同源管理 HTTP 由可信身份映射提供全局 named permissions：读取需要 `knowledge_source.view`，保存、启动、发布或取消需要 `knowledge_source.edit`。身份可以组合这些权限，不新增 Space 级 ACL 或本地授权表。KSS 管理 HTTP 继续要求可信 operator authentication，并在 publication/cancellation 前核对 exact Scope；终端用户不能绕过 BFF 自报权限。TDD-04E/04F 只把既有 one-use publication CAS 和协作取消事务暴露为受控命令；它们不授予 Agent 发布、激活或其他角色权限。

`base_preparation_id_factory` 和 `base_preparation_execution` 是 Python 组合参数，不是现有 CLI 或环境变量开关。`bootstrap/processes.py` 尚未启用 execution 组合。浏览器不得直接持有 KSS operator credential，也不能通过请求体声明角色或操作者。

## 调用顺序

以下均为 KSS 服务端管理 API。路径前缀记为：

```text
/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}
```

所有调用需要服务端认证。保存 Draft、启动 Preparation 和取消 Preparation 还需要 `Idempotency-Key`；不同业务命令使用不同 key，重放原命令保留原 key 和完整原请求。publication 不使用幂等键。说明中不展示凭据值。

### 1. 保存 Draft

调用 `PUT {前缀}/draft`，body 使用完整请求。首次 `expected_revision=0`，后续编辑提交当前 revision；body 中的 Space/Base 必须与路径相同。

以下标识符均为虚构示例，需替换为测试 catalog 中实际存在的对应身份：

```json
{
  "knowledge_space_id": "space-claims",
  "knowledge_base_id": "base-claims",
  "expected_revision": 0,
  "members": [
    {
      "knowledge_source_id": "source-rules",
      "selection": "exact",
      "knowledge_source_version_id": "source-version-rules-v1"
    },
    {
      "knowledge_source_id": "source-limits",
      "selection": "latest_ready_at_preparation"
    }
  ]
}
```

预期返回 `200`，包含新 `revision`、`draft_digest`、成员与更新时间。成员非空且 Source 不重复；`exact` 必须提供 Version ID，`latest_ready_at_preparation` 不能夹带 Version ID。revision 使用 JSON 整数，不接受布尔值或字符串。

### 2. 读取并确认 Draft

调用 `GET {前缀}/draft` 读取当前管理 Draft；需要核对历史时使用 `GET {前缀}/draft?revision=1`。

编辑产生新 revision，旧 revision 保留。此处「当前 Draft」只用于管理，不进入 Query 或 Agent runtime；启动请求不能用 `latest` 替代 exact revision。

### 3. 启动 Preparation

调用 `POST {前缀}/release-preparations`，使用与保存 Draft 不同的 key：

```json
{
  "knowledge_space_id": "space-claims",
  "knowledge_base_id": "base-claims",
  "draft_revision": 1
}
```

预期返回 `202` 和 `Location`。响应包含 `release_preparation_id`、exact Draft revision/digest、`base_version` 的有序 exact Source/Version 成员、`plan_digest`、`submitted_at` 和 `state="queued"`。

KSS 在短事务内锁定当前 Draft，通过一条 catalog 查询读取所有选中 Sources 的 Version。`latest_ready_at_preparation` 按首次可见时间、再按 Version ID 确定性选择；后续 Source 更新不会改变已经冻结的计划。这里不读取原文、不建索引，也不产生可查询 Release。

### 4. 读取资源和审计

调用返回的 `Location` 读取当前 Preparation。该路径的 Space/Base 必须与资源一致。应用和仓储重建后仍可读取，不需要重新启动命令。GET 可返回 `queued/running/ready/failed/cancelled/expired/consumed`；重放原始 start POST 仍返回最初的 `queued` 回执，两者用途不同。

调用 `GET {前缀}/preparation-audit` 查看成功操作及安全拒绝事件；该读取要求对应 Draft 已存在且 Scope 一致。审计只记录安全身份、受限操作/资源标识、稳定错误码和时间，不返回请求 body、headers、key、原文或 secret。

当前没有 expiry HTTP 操作或自动调度。没有显式调用 Worker Interface 时，资源保持 `queued`。`running` 仅表示已被领取，租约过期也保持 `running`，不能据此判断 Worker 健康或构建进度。GET 不推进到期状态；没有 publication 尝试或显式 `expire_next()` 调用时，已过 `expires_at` 的资源仍可能暂时显示 ready。

## ProofAgent 同源管理入口

[KNOWN | HIGH] TDD-04C 为浏览器提供以下同源路径；它们由 ProofAgent 检查权限，再由 guarded management client 使用服务端 KSS credential 调用上述 KSS API。浏览器不得改为直连 KSS。

```text
PUT  /api/config/knowledge-service/spaces/{space}/bases/{base}/draft
GET  /api/config/knowledge-service/spaces/{space}/bases/{base}/draft?revision={n}
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations
GET  /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{preparation_id}
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{preparation_id}:cancel
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{preparation_id}:publish
```

- Draft PUT body 只包含 `expected_revision` 和 `members`；Preparation POST body 只包含 `draft_revision`。Space/Base 由路径持有，ProofAgent client 在调用 KSS 时注入并重验，不接受 body 重复声明 Scope。
- Draft PUT、Preparation start POST 和 cancellation POST 需要 `knowledge_source.edit` 与 `Idempotency-Key`；publication POST 需要 `knowledge_source.edit`，但不接受 body 或 `Idempotency-Key`；两个 GET 需要 `knowledge_source.view`。cancellation 也不接受 body。Draft GET 必须提交 exact `revision`，不提供 mutable latest 读取。
- Preparation 首次启动与相同命令重放都返回 `202`，因为 KSS 的 immutable queued receipt 不区分 HTTP create/replay status。调用方通过同源 `Location` 读取 current state，不得根据 POST 重放结果推断 Worker 当前状态。
- BFF 只投影 Draft/Version/Preparation exact identity、digest、成员、状态、安全终态字段和同源 self link。Worker ID、fencing token、lease deadline、artifact reference、KSS credential 和 raw failure detail 不进入浏览器。
- start/status BFF 不会在请求内运行 Worker 或推进到期；publication/cancellation BFF 只调用既有短事务，也不会执行构建或激活 Agent。只有另行配置的可信 execution runtime 可以把 queued 推进到 running/ready/failed；没有 execution 或 publication 时，资源应保持可见但不可查询。

### 5. 受控发布与不确定结果恢复

只有 current state 为未过期 `ready` 时调用：

```text
POST {前缀}/release-preparations/{preparation_id}:publish
```

请求不带 body，也不带 `Idempotency-Key`。成功返回 `200`、`state="consumed"`，`Location`
指向同一个 Preparation GET 资源；随后 exact Release catalog 中应出现一个
`knowledge_base_release_id` 相同的 queryable Release。路径 Space/Base 与 Preparation 不一致时，
KSS 在消费前拒绝，不能借错误路径发布其他 Scope 的资源。

超时、连接中断或重复调用后，不要生成新的“发布重试 key”，也不要改用旧直接 Release
入口。读取返回的 exact Preparation GET：`consumed` 表示事务已成功，`ready` 表示尚未消费，
`expired` 表示数据库时间已使候选失效；其他状态均不可发布。重复发布 consumed、queued、
failed、cancelled 或 expired 资源返回稳定失败，且不会产生第二个 Release。若业务需要重建，
使用新的 start `Idempotency-Key` 创建新的 Preparation identity。

## 可选的 one-shot execution runtime

TDD-04D 把既有 Worker、candidate builder 和 TTL 隐藏在一个 runtime handle 后。以下代码
只表示本地组合形态；参数值不是生产推荐配置：

```python
from datetime import timedelta
from knowledge_source_service.bootstrap.runtime import (
    BasePreparationExecutionConfiguration,
    compose_runtime,
)

runtime = compose_runtime(
    # 其余 durable PostgreSQL、artifact、catalog/projection 参数由调用方提供。
    base_preparation_execution=BasePreparationExecutionConfiguration(
        worker_id="base-preparation-worker-local-1",
        lease_duration=timedelta(seconds=30),
        candidate_ttl=timedelta(hours=1),
    ),
)
result = runtime.base_preparation_executor.run_once()
```

- 未提供 `base_preparation_execution` 时，`base_preparation_executor` 为 `None`。API runtime
  不会因为注册管理路由而开始处理队列。
- `run_once()` 一次最多处理一个 queued 或可接管 running resource，并返回 ready、failed
  或 `None`。`None` 不证明队列为空；短事务锁竞争也可能导致当前轮次没有领取任务。
- runtime 可以在进程对象重建后继续读取同一 PostgreSQL authority。测试中的重建不等于
  数据库故障恢复、S3 进程重启或生产切换演练。
- 非正 candidate TTL 在 executor 构造阶段拒绝，尚未领取任务。Worker identity 和 lease
  继续使用既有受限格式与一小时上限。
- 本 Interface 没有 CLI、常驻循环、batch、自动重试、健康信号或部署接线。调用方不能
  通过循环测试推断生产运行责任已经建立。

## 仅服务端的构建与结果提交

在已迁移的隔离数据库上构造 `PostgresBasePreparationRepository`，再将 repository 传入 Worker。示例不包含连接参数或凭据：

```python
from datetime import timedelta
from knowledge_source_service.application.base_preparation_builder import KnowledgeReleaseCandidateBuilder
from knowledge_source_service.application.base_preparation_worker import BasePreparationWorker
from knowledge_source_service.application.knowledge_releases import KnowledgeReleaseApplication

worker = BasePreparationWorker(
    repository=repository,  # 调用者已为隔离测试库构造的 PostgreSQL repository
    worker_id="worker-local-test",
    lease_duration=timedelta(seconds=30),
)
builder = KnowledgeReleaseCandidateBuilder(
    releases=KnowledgeReleaseApplication(artifacts=artifacts, catalog=catalog)
)
result = worker.run_next(builder=builder, candidate_ttl=timedelta(hours=1))
```

- `worker_id` 使用 1 至 128 个受限字母、数字、点、下划线或连字符，首字符为字母或数字。它是可信服务端标识，不是浏览器授权参数。
- `lease_duration` 为正值 `timedelta`，上限一小时；示例的 30 秒不是生产推荐或默认配置。租约时间由 PostgreSQL 决定，不接受调用者提供 now。
- `claim_next()` 单次最多领取一个资源，并跳过已锁定行。返回 `None` 可能是暂无可领取工作，也可能是短事务占锁；调用者可在后续调度轮次再次尝试。当前没有自动轮询进程。
- `renew()` 核对持久化 owner、token、截止时间和完整 frozen plan；截止时刻已到、被接管或计划不符返回 `base_preparation_stale_claim`。应停止使用旧 claim，不可自行改 token 或把续租成功当作稍后发布的许可。
- `run_next()` 领取一个资源，在数据库事务外按 frozen Base Version 构建 immutable candidate，再在短事务中核对当前 owner、租约、fencing token 和完整 admission。`candidate_ttl` 必须为正值；示例的一小时不是生产推荐或默认配置。
- 当前 Worker 在候选构建阶段可以写入 immutable artifact 和独立 projection generation，但只有 fenced 结果事务可以把 Preparation 变为 `ready`。`ready` 不写入 Release catalog，因此 Query 和 Agent binding 都不可使用。旧 Worker 产生的孤立 immutable artifact 不构成运行时权威，后续仍需回收策略。
- 到期 `running` 可由新 attempt 接管；Preparation identity 和 plan 不变，fencing token 增加。旧 Worker 随后提交 `ready` 或 `failed` 都会收到 `base_preparation_stale_claim`。Lease 到期与 ready candidate 的主动 `ready → expired` 转换不是同一件事。
- `worker.audit(base_id)` 读取服务端 `claimed/renewed/taken_over/ready/failed` 事件。管理 HTTP 的 `preparation-audit` 仍只提供原有管理成功/拒绝事件，不投影私有 claim。终态、内部候选和对应 Worker 事件原子提交。

该 Interface 没有 Worker HTTP endpoint、CLI 开关或常驻循环。不要把 claim、artifact reference 或 candidate JSON 发送给浏览器。`ready` 只能交给下述可信 application publication CAS，不能直接接入生产 Agent 发布流程。

## 仅服务端的一次性 Release 发布

TDD-02E 提供核心 application Interface，不提供网络入口。调用方必须使用与 Preparation 和 Release catalog 相同 PostgreSQL 权威的 repository：

```python
consumed = application.publish(
    ready.release_preparation_id,
    operator_id="operator-publisher",
)
```

- 调用只接受可信服务端 operator identity；没有请求体角色、自报时间或 publication idempotency key。Preparation identity 本身是一次性 CAS 键。
- PostgreSQL 锁定资源并使用 `clock_timestamp()` 判断到期；边界为 `now >= expires_at`。到期时 transaction 持久化 `expired` 和审计，提交后 application 抛出 `base_preparation_expired`。应随后 GET 确认 durable 终态。
- 未到期时，候选绑定的 Release header、有序成员、retrieval projection、artifact reference、`consumed` 状态、exact Release 外键和生命周期审计在同一事务提交。事务内不访问 S3、OpenSearch 或其他网络依赖。
- 同 identity 重复调用返回 `base_preparation_not_ready`，不会创建第二条 Release 或审计。若调用方没有收到确定响应，应先 GET；GET 为 consumed 表示提交成功，ready 表示仍可按受控恢复策略重试，expired/failed 表示不能复用。
- 相同 content-addressed Release 仅在既有记录仍为 queryable，且 header、manifest artifact、有序成员和 projection 全量一致时复用；KSS 持有对应 Release 行锁直至 consumed 提交，避免退役插入校验与提交之间。retired、部分或冲突记录返回 `base_preparation_release_conflict`，原 ready 保持不变；不会修补或复活旧 Release。
- consumed 记录的是成功发布历史。Release 后续合法 retired 时，Preparation GET 和原始 queued POST receipt 仍可读取；历史校验继续核对 immutable 内容，但不要求 Release 当前仍可查询。新 ready publication 仍不得复用 retired Release。
- `application.publication_audit(base_id)` 可读取 `consumed/expired` 事件及 operator、exact identity、digest 和数据库时间。该 Interface 尚未投影到 management HTTP。

成功 consumed 只建立 KSS query authority，不注册 Agent reference、不修改 Agent Draft、不通过 Phase F，也不激活 Published Agent Version。既有 `KnowledgeReleaseApplication.publish()` 仍是兼容的直接发布路径；当前不能声称 Preparation 是系统级唯一 Release 发布入口。

## 仅服务端的主动过期回收

TDD-02F 复用同一个 application 和 repository，不增加网络入口：

```python
expired = application.expire_next(
    operator_id="system:preparation-expiry",
)
```

- 每次调用最多处理一个到期 ready。PostgreSQL 按 `candidate_expires_at` 和 Preparation ID 排序，并使用数据库时间、`FOR UPDATE SKIP LOCKED LIMIT 1` 和现有 `0012` partial index。
- 返回 expired 表示状态和一条生命周期审计已经在同一事务提交；返回 `None` 可能表示没有到期项，也可能表示候选行正在被其他短事务锁定。后续调度轮次可以重试，但不得将 `None` 当作队列为空或服务健康证明。
- 主动过期重验 frozen plan 和完整 candidate，不创建 Release，也不访问 S3 或 OpenSearch。审计写入或提交失败时，资源保持原 ready。
- 候选完整性校验失败时返回 `base_preparation_integrity_unavailable`，资源保持 ready 且不写事件。该资源可能在后续轮次再次阻塞相同顺序；TDD-02G 的 cancelled 仅适用于 queued/running，不能用来隐藏异常 ready。后续 quarantine 必须独立定义原因、修复与解阻权威，不得绕过校验或伪造 expired。
- 主动过期与 publication 发现到期共用相同终态原语。二者竞争同一资源时只会产生一个 expired 和一条事件，不会发布或复活 Release。
- 当前没有自动循环、轮询间隔、批次上限、健康信号或部署配置。不要在生产进程中自行添加无限循环；这些运行责任需要后续独立设计和批准。

expired 仍保留 candidate 绑定用于完整性审计。本调用不删除 immutable artifact 或 projection generation，也不证明孤立对象已完成物理回收。

## 受控协作取消

TDD-02G 增加 application Interface；TDD-04F 在不改变该事务权威的前提下增加 KSS 与 ProofAgent 同源网络入口：

```text
POST {前缀}/release-preparations/{preparation_id}:cancel
POST /api/config/knowledge-service/spaces/{space}/bases/{base}/release-preparations/{preparation_id}:cancel
```

两个入口都不接受 body，并要求 `Idempotency-Key`。ProofAgent BFF 还要求
`knowledge_source.edit`；KSS 使用可信 operator identity 作为幂等作用域。成功返回 `200`、
`state="cancelled"` 和同一 Preparation GET `Location`。服务端核心等价于：

```python
cancelled = application.cancel(
    queued.release_preparation_id,
    operator_id="operator-canceller",
    idempotency_key="cancel-preparation-1",
)
```

- 仅 queued/running 可取消。数据库锁定 exact Preparation，使用数据库时间生成 `cancelled_at`，并在同一事务提交 cancelled 状态、幂等收据和成功审计。
- running 取消会清除当前 lease owner 和 deadline，但保留已经使用的 fencing token。在途 Builder 不会被进程级强杀；它可以结束外部计算，但旧 claim 的 renew、ready 或 failed 提交都会返回 `base_preparation_stale_claim`。
- 相同 operator、Idempotency-Key 和 Preparation identity 返回原 cancelled 结果且不重复审计。相同 key 改绑另一个请求返回 `base_preparation_idempotency_conflict`；以新 key 再次取消同一终态返回 `base_preparation_not_cancellable`。
- ready、failed、expired、consumed 和 cancelled 都不可取消。失败重试必须用新 Idempotency-Key 启动新的 Preparation identity；取消不会自动重试、发布 Release、删除 artifact 或隔离异常 ready。
- 管理 GET 与 BFF 可以读取 secret-free cancelled 资源；当前仍没有 Dashboard command、CLI、自动取消调度或部署接线。调用方不能根据本地状态伪造 cancelled，也不能在浏览器传 operator identity。
- `0013_preparation_cancellations.sql` 是本地候选 migration；本轮未执行生产 migration。正式启用前仍需单独批准备份、迁移、回滚和运行角色。

取消终止的是 Preparation 的提交权，不等于立即终止外部 I/O 或完成孤立对象回收。物理清理与 ready quarantine 均属于后续独立设计。

## 读取安全审计页

TDD-04G 为 ProofAgent 增加同源只读入口：

```text
GET /api/config/knowledge-service/spaces/{space}/bases/{base}/preparation-audit
    ?offset=0&limit=50
```

- 调用需要 `knowledge_source.view`。`offset` 默认为 0、最大为 20,000；`limit` 默认为 50、范围为 1 至 100。
- KSS 仍是审计事实权威。ProofAgent 只严格校验既有 KSS wire 与 exact Space/Base，并投影为时间有序、secret-free 的 success/rejection 页。
- `actor.identity_kind="kss_service_operator"` 表示 KSS 实际记录的可信服务操作者。它不是浏览器或终端操作者；当前没有把终端身份委托给 KSS，界面不得作此推断。
- 响应不返回 KSS credential、Worker identity、lease、fencing token、artifact reference 或 raw rejection detail。任何额外私有字段、非法 actor 或 Scope 漂移都会失败关闭。
- 当前 Base audit 包含 Draft 保存、Preparation 启动/取消成功及管理拒绝；不合并 Worker audit 或 publication audit。offset 分页基于每次读取的当前快照，并非跨页稳定 cursor；若数据在两次请求间变化，调用方应重新从第一页读取。

该入口只增加观察能力，不创建新的审计账本、不改变 Preparation 状态，也不授予 Release publication 或 Agent activation 权限。

## 幂等与失败处理

| 结果或错误码 | 含义 | 恢复方式 |
| --- | --- | --- |
| `200/202` 后重复原命令 | 同一 operator/key/action/完整请求返回原始结果，成功审计不重复 | 保留 key 和原请求；后续 Draft 变化不影响原回执 |
| `409 base_draft_revision_conflict` | 新命令的 Draft revision 已过期 | 读取当前 Draft、核对差异后再保存或启动；不要自动改用 latest |
| `409 base_preparation_idempotency_conflict` | 成功 key 已绑定另一个 action 或请求 | 重放时恢复原请求；若确为新业务命令，使用新 key |
| `409 base_member_not_ready` | 至少一个成员无法解析到所属 Source 的 ready Version | 检查摄取/同步结果与 exact ID；本次启动未受理，满足条件后可重试 |
| `409 base_scope_mismatch` | 路径、body 或资源的 Space/Base 不一致 | 核对目标身份，不迁移或替换已有资源 |
| `401/403` | 认证未通过或缺少所需 named permission | 修正可信服务端认证/角色映射；不要在 body 中传 operator 或权限 |
| `400 invalid_idempotency_key` | 写操作缺少或提供无效 key | 提供符合接口约束的 key；不把 secret 用作 key |
| `422 invalid_management_request` | 请求结构或字段不符合合同 | 按 schema 修正；服务端不会回显敏感输入 |
| `404` | 对应 Draft 或 Preparation 不存在 | 核对已成功返回的 exact identity；未启用新路由时先检查运行组合 |
| `503 ..._unavailable` | 存储、完整性检查或拒绝审计不可用 | 停止推进；恢复依赖后以原 key/原请求检查结果，不盲目创建重复命令 |
| `failed / base_preparation_build_failed` | 构建器失败；公开资源不包含原始异常 | 检查服务端受控诊断；使用新 key 启动新的 Preparation，不复用 failed identity |
| `failed / base_preparation_invalid_candidate` | 构建结果与 frozen plan、manifest digest 或 content identity 不一致 | 停止使用该构建器结果；修复构建器后以新 Preparation identity 重试 |
| `base_preparation_not_ready` | publish 目标不存在于 ready，包含 queued/running/failed/expired/consumed 或重复消费 | GET exact Preparation；不要把非 ready 状态改回 ready，失败重试创建新 identity |
| `base_preparation_expired` | publication CAS 发现数据库时间已到期，并已持久化 expired | GET 确认终态；以新 key 启动新 Preparation，不复用 candidate |
| `base_preparation_not_cancellable` | 目标不是 queued/running，或已经进入 ready/terminal 状态 | GET exact Preparation；不要回退状态，若需重试则启动新 identity |
| `base_preparation_stale_claim` | running 已取消、lease 已过期/接管或 claim 身份不匹配 | Worker 停止提交；不得修改 fence 或把孤立 artifact 变成 Release |
| `base_preparation_release_conflict` | 相同 Release ID 已存在但不是完整、queryable、exact-equal 记录 | 停止发布并调查 catalog 完整性/生命周期；不会自动修复或复活 |

Draft/Preparation、成功回执与成功审计原子提交。未受理的失败不占用成功 key。`failed/expired/consumed` 均不会再次领取；失败或过期重试时使用新 idempotency key 启动新的 Preparation identity，不修改原终态资源。consumed 是成功终态，不通过新 Preparation 重发同一业务结果。

## 保留与验证边界

- Draft 历史、Base Version、Preparation、receipt 和 audit 当前没有自动 TTL、删除或清理入口。备份恢复、保留期限和审计分页仍待后续实现，不能把回滚二进制当作数据恢复。
- KSS 仍是这些资源的权威。ProofAgent 后续只通过受保护 BFF 管理，并使用已发布的 exact KSS Release；当前不能在 Dashboard 配置使用新 Preparation。
- 本地完整受影响回归为 339 passed、0 skipped，覆盖真实 PostgreSQL/MinIO/OpenSearch。Preparation 的 PostgreSQL 构建 fixture 仍使用内存 artifact store；TDD-02E 证明同一 PostgreSQL 内 Release catalog 与 Preparation 的原子可见性，TDD-02F 证明显式 one-shot 主动过期的选择、并发、完整性失败关闭和回滚合同。两者都不证明常驻 Worker、自动过期调度、孤立 artifact 回收、系统级唯一发布入口、Phase F 或生产恢复已通过。

实现与验证详情见 [TDD 报告](tdd-report.md)第 13 至 17 节。`0012` 的 `expired/consumed` 资源和新列不兼容旧二进制；生产迁移和回滚需要独立授权与验证。
