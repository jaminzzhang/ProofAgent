# Proof Agent 新手运维、部署与开发指导书

更新日期：2026-07-27

适用对象：第一次接触本仓库的开发人员、测试人员、平台运维人员和 Agent 负责人。

## 1. 先理解当前边界

[KNOWN | HIGH] 当前活跃产品只有一个工作流 `react_enterprise_qa_v3`、一个公开开发示例 `examples/agent_management_insurance_specialist/`，以及 Dashboard 和 Operator Chat（`/operator`）两个浏览器界面。没有客户 Chat、审批工作流、本地账号密码、用户管理页或任意脚本执行能力。依据：`README.md`、`docs/prd.md`、`docs/technical-design.md`。

[KNOWN | HIGH] 本地离线开发和 Hybrid Knowledge 类生产闭环已经可以执行；正式生产发布仍是 **NO-GO**。S6 已有加固镜像/槽位定义、稳定网关、租约 fencing、显式迁移，以及首个内置 `docker-compose-v1` Blue/Green 操作驱动；真实 Docker/nginx 演练、安全初始化、告警、完整 Runbook 和 13 个候选绑定 Gate 证据仍未闭环。依据：`docs/development-progress.md`。

因此，请先选择正确的工作模式：

| 模式 | 用途 | 是否推荐给新手 | 能否作为生产发布证据 |
| --- | --- | --- | --- |
| 本地离线 | 开发、调试、回归、学习架构 | 是，默认从这里开始 | 否 |
| 本地集成 | 使用一次性 PostgreSQL、MinIO、OpenSearch 验证 Hybrid 数据面 | 熟悉本地流程后使用 | 否 |
| 类生产闭环 | 接入真实私有模型、OIDC、Vault、S3 等部署绑定 | 仅平台与发布负责人 | 只能产生部分候选证据 |
| 正式生产 | 单机加固 Compose、稳定网关、Blue/Green、13 Gate | 当前不可直接执行 | 当前为 NO-GO |

> 不要把“服务能启动”“本地测试全绿”或“类生产闭环成功”解释为正式生产可发布。

## 2. 架构速览

### 2.1 请求执行路径

```mermaid
flowchart TD
    U["Dashboard / Operator Chat / CLI"] --> D["Delivery API 与 CLI"]
    D --> B["Bootstrap / 配置加载 / 依赖组合"]
    B --> C["Controlled ReAct V3 Control Plane"]
    C --> P["Policy：确定性许可或拒绝"]
    C --> K["Knowledge / Model / Memory / Tool Ports"]
    C --> V["Evidence / Citation / Safety Validators"]
    K --> A["Capabilities：具体适配器"]
    P --> O["Observation / Terminal Outcome"]
    V --> O
    A --> O
    O --> T["Trace：执行事实日志"]
    T --> R["Governance Receipt：面向人的投影"]
    T --> S["RunStore / PostgreSQL / S3 读模型"]
```

[KNOWN | HIGH] 模型只能提出动作，不能自行授权或直接调用能力。Control Plane 拥有工作流、策略、证据准入、校验和结果映射；Trace 是执行事实，Governance Receipt 是投影。依据：`AGENTS-COMMON.md`、`docs/technical-design.md`、`proof_agent/control/workflow/controlled_react/`。

一次问答的简化过程是：

1. Delivery 接收请求，Bootstrap 加载 Agent、策略和适配器。
2. Planner 提出澄清、检索、只读工具、回答或拒绝建议。
3. Control Plane 依据策略决定是否允许。
4. Knowledge 或获准的能力产生 Observation。
5. Validators 校验结构、证据、引用、安全和工具结果。
6. 只有通过校验的结果才能成为最终 Outcome。
7. 全过程写入 Trace，并生成 Governance Receipt。

### 2.2 生产目标拓扑

```mermaid
flowchart LR
    Browser["内部操作员浏览器"] --> Gateway["稳定 Gateway"]
    Gateway --> UI1["Dashboard"]
    Gateway --> UI2["Operator Chat"]
    Gateway --> API["Proof Agent API"]
    API --> PG[("PostgreSQL")]
    API --> S3[("S3-compatible artifacts")]
    API --> OIDC["OIDC"]
    API --> Vault["Secret Provider / Vault"]
    API --> OS["OpenSearch"]
    API --> Models["私有模型端点"]
    Executor["Run Executor\n同一产品镜像"] --> PG
    Executor --> S3
    Executor --> OS
    Executor --> Models
    Worker["Knowledge Worker"] --> PG
    Worker --> S3
    Worker --> OS
    Worker --> Parsers["Docling / Paddle / Embedding / Reranker"]
```

[FRAME | HIGH] 正式生产目标是单台加固 Linux 主机上的稳定 Gateway 和 Blue/Green 应用槽位；API 与 Run Executor 使用同一产品镜像，但作为不同进程角色运行。PostgreSQL、S3、OIDC、Secret Provider 和模型服务是外部部署绑定。依据：`docs/technical-design.md` 第 11 节。

[KNOWN | HIGH] `deploy/production/` 现在包含生产镜像定义、稳定 Gateway、Blue/Green 槽位 Compose 和控制器/驱动示例；`proof_agent/deployment/` 包含纯状态机与原子 include 切换，`scripts/deployment/blue_green.py` 包含外部 Docker/nginx 命令边界，`scripts/deployment/compose_driver.py` 提供内置 `docker-compose-v1` 驱动。当前仍没有真实候选镜像、真实环境演练与 Gate 证据。根目录 `Dockerfile`、`docker-compose.yml` 仍只用于开发；`docker-compose.hybrid-test.yml` 使用测试凭据且关闭 OpenSearch 安全插件。三者都不能用于生产。

### 2.3 Knowledge Source 配置目标

[FRAME | HIGH] 已接受的目标不是让 Dashboard 直接配置 PostgreSQL、S3、OpenSearch 或私有模型端点，而是让 Dashboard 只调用统一 Knowledge Source API；该 API 通过 Configuration、Ingestion、Publication、Operations 四个应用服务协调权威与投影。详细设计见 `docs/superpowers/specs/2026-07-27-dashboard-hybrid-knowledge-source-unified-api-design.md`，实施顺序见 `docs/superpowers/plans/2026-07-27-dashboard-hybrid-knowledge-source-unified-api.md`。

```mermaid
flowchart TB
    Dashboard["Dashboard / Knowledge Source API"] --> App["统一 Knowledge application boundary"]
    App --> PG["PostgreSQL authority"]
    App --> S3["S3-compatible artifact authority"]
    App --> OS["OpenSearch derived projection"]
    Worker["Knowledge Worker"] --> App
    Worker --> Plane["Private Knowledge Model Serving Plane"]
    Plane --> Services["Scheduler + Docling + PaddleOCR + Embedding + Reranker"]
```

[FRAME | HIGH] 这里不再使用含义模糊的 “Hybrid private services”。**Private Knowledge Model Serving Plane** 只包含调度器与 Docling、PaddleOCR、Embedding、Reranker；它不包含 PostgreSQL、S3、OpenSearch、Knowledge Worker、Run Executor、OIDC、Secret Provider、Egress Policy 或 Agent answer/planner/reviewer LLM。

[KNOWN | HIGH] Dashboard 的 Hybrid 管理边界已收敛到显式 Source publication，并只提示 Agent binding upgrade opportunity；Phase F 证据、Agent publication 和 Active Agent Version 切换仍属于生产发布流程。该边界已有本地实现与 disposable 数据面测试，但没有候选绑定的生产部署证据，不能据此标记生产就绪。

[KNOWN | HIGH] Dashboard 的 Agent Knowledge 配置会识别已发布的 `hybrid_index` Source，并可选固定 `retrieval_profile_revision_id`；留空时由后端在 Agent validation 中解析部署默认版本。已绑定卡片回显 provider 与固定的 profile，但页面仍不接受 PostgreSQL、S3、OpenSearch、私有模型服务 endpoint 或凭据，也不会因此获得 Agent activation 权限。

### 2.4 目录职责

| 路径 | 主要职责 | 新手常见改动 |
| --- | --- | --- |
| `proof_agent/contracts/` | 严格、供应商中立的 DTO、枚举和端口 | 修改公共契约时同步更新校验和测试 |
| `proof_agent/bootstrap/` | 配置解析、校验、注册表和依赖组合 | 新增适配器组合或生产角色绑定 |
| `proof_agent/control/` | 工作流、策略、知识编排、证据准入和校验 | 修改受控行为的核心位置 |
| `proof_agent/capabilities/` | 模型、知识、存储、Secret、工具等具体适配器 | 接入新的供应商实现 |
| `proof_agent/delivery/` | CLI、API、队列、Executor、Worker | 新增入口或接口，但必须复用同一 Control Plane |
| `proof_agent/observability/` | Trace、Receipt、RunStore、保留和恢复 | 审计、读模型和产物生命周期 |
| `proof_agent/release/` | 候选绑定、Gate、摘要和 fail-closed 验证 | 发布验证规则 |
| `dashboard/` | Agent 配置与观察 UI | Dashboard 前端开发 |
| `chat/` | Operator Chat | 操作员问答界面开发 |
| `packages/ui/` | 两个前端共享的 UI 包 | 通用组件和样式 |
| `examples/agent_management_insurance_specialist/` | 唯一公开、确定性、离线开发示例 | 新手学习和本地回归 |
| `deploy/production/agent_management_insurance_specialist/` | 生产候选 Agent 包 | 仅候选发布流程使用 |
| `deploy/production/Dockerfile`、`gateway/`、`slot/` | 生产镜像与 Blue/Green 拓扑定义 | 由候选构建和发布流程使用，不要手工切流 |
| `proof_agent/deployment/`、`scripts/deployment/blue_green.py` | 纯部署编排、原子 Gateway 切换和外部命令边界 | 仅批准的发布流程与受信操作驱动使用 |
| `tests/` | 后端与契约测试 | 后端行为变更必须同步更新 |

## 3. 第一次在本地运行

### 3.1 环境要求

[KNOWN | HIGH] 基础开发需要 Python 3.12+、`uv`、Node.js 和 npm。运行 Hybrid 集成测试还需要 Docker Engine 与 Docker Compose。依据：`pyproject.toml`、`docs/developer-guide.md` 和 Compose 文件。

在仓库根目录执行：

```bash
uv sync --extra dev --extra dashboard
npm install
uv run --extra dev --extra dashboard proof-agent doctor
```

`doctor` 应至少报告：Python、Proof Agent、`runs/` 可写、规范示例 Agent、示例知识和 deterministic provider 可用。远程模型未配置对离线示例不是错误。

如需环境变量，先阅读 `.env.example`。仅在本地 `.env` 不存在时创建它；不要覆盖已有配置，也不要提交真实 Secret。CLI 会在启动时加载本地 `.env`。

### 3.2 跑通最小烟雾测试

```bash
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "住院理赔需要准备哪些材料？"
```

预期看到：

```text
Outcome: ANSWERED_WITH_CITATIONS
```

查看本次审计产物：

```bash
uv run proof-agent inspect runs/latest/trace.jsonl
uv run proof-agent inspect runs/latest/governance_receipt.md
```

[KNOWN | HIGH] 本地示例使用确定性 planner、reviewer 和 answer provider，不需要 API Key；它证明的是离线受控执行路径，不证明真实模型或生产依赖兼容性。

### 3.3 启动本地服务

只启动后端 API 和本地 Knowledge Worker：

```bash
uv run --extra dev --extra dashboard proof-agent dev
```

需要 Python 热重载时：

```bash
uv run --extra dev --extra dashboard proof-agent dev --reload
```

另开终端启动前端：

```bash
npm run dev -w proof-agent-dashboard
npm run dev -w proof-agent-chat
```

访问地址：

| 服务 | 地址 |
| --- | --- |
| 后端 API 文档 | `http://127.0.0.1:8000/api/docs` |
| Dashboard | `http://127.0.0.1:5173` |
| Operator Chat | `http://127.0.0.1:5174/operator` |

需要一个可重启、单入口的本地验收会话时，使用：

```bash
uv run --extra dev --extra dashboard proof-agent verify-remote
```

然后访问 `http://127.0.0.1:18080`。该命令会构建前端并启动 API、Knowledge Worker、两个前端预览服务和本地 Gateway。

[KNOWN | HIGH] `verify-remote` 只监听本机，不创建公网隧道。停止本地服务使用前台终端的 `Ctrl-C`；不要用它承载正式生产流量。

### 3.4 本地健康检查

服务启动后执行：

```bash
curl -fsS http://127.0.0.1:8000/livez
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8000/api/health
```

含义：

| 端点 | 用途 |
| --- | --- |
| `/livez` | 进程仍在响应 |
| `/readyz` | 当前模式的就绪结果；生产模式失败返回 HTTP 503 |
| `/api/health` | 开发态 RunStore 摘要和版本信息 |

[KNOWN | HIGH] 当前生产 `/readyz` 会报告 release ID、镜像 digest、槽位、角色、激活状态、Schema 当前/兼容区间和 DCM digest，并检查 PostgreSQL、运行队列、运行产物 S3、Hybrid 产物 S3、active Egress Policy、唯一 Published Agent 和 Secret Provider。API 还校验 OIDC discovery/JWKS 与 60 秒内 S3 精确写后读；Worker 校验其 PostgreSQL 角色租约。响应只返回经过净化的组件状态，不返回 owner ID、Secret 或内部异常。

## 4. 日常本地运维

### 4.1 本地状态在哪里

| 路径 | 内容 | 是否可直接删除 |
| --- | --- | --- |
| `runs/latest/` | 最近一次 CLI 执行的 Trace 与 Receipt | 仅确认不需要后可清理 |
| `runs/history/` | API 历史运行产物 | 仅本地开发；清理会丢历史 |
| `runs/config/` | 本地 Agent 配置与发布状态 | 不要手工删，使用 `config-reset` |
| `runs/conversations/` | 本地会话时间线 | 清理会丢本地会话 |
| `runs/evaluations/` | 本地评估产物 | 清理前先确认是否需要比较 |

[KNOWN | HIGH] 这些文件系统存储是开发适配器，不是生产 authority。生产可变状态以 PostgreSQL 为准，受治理产物以 S3 精确版本为准。

重置本地配置前先停止服务并确认目标目录：

```bash
uv run proof-agent config-reset \
  --scope local-store \
  --config-dir runs/config \
  --yes
```

这是破坏性操作，会清除生成的本地 Configuration Store；它不能用于生产 PostgreSQL。

### 4.2 最小观测顺序

发生异常时按以下顺序查看：

1. 启动终端中的首个错误，而不是最后一串级联错误。
2. `/livez` 和 `/readyz`。
3. `runs/latest/trace.jsonl` 的最后一个事件。
4. `runs/latest/governance_receipt.md` 的最终 Outcome 和拒绝原因。
5. 对应 API、Executor 或 Knowledge Worker 进程日志。
6. 若为生产组合，再检查 PostgreSQL、S3、OpenSearch、OIDC、Vault 和模型服务。

不要在日志中增加原始 chain-of-thought、凭据、完整受限文档或未脱敏的供应商 payload。新增 Trace 字段必须先做脱敏和受众审查。

## 5. 开发工作流

### 5.1 推荐的改动顺序

1. 先从活跃文档确认边界：`README.md` → `docs/prd.md` → `docs/technical-design.md` → `docs/developer-guide.md` → `docs/development-progress.md`。
2. 为行为变更先写一个最小失败测试。
3. 在拥有该职责的模块修改，不要从 API、前端或评估代码创建旁路。
4. 先运行最小相关测试，再运行受影响套件。
5. 修改行为时同步更新活跃文档。
6. 提交前执行完整本地验证。

常见改动与测试入口：

| 改动 | 首选代码位置 | 最小测试方向 |
| --- | --- | --- |
| Agent 契约或字段 | `proof_agent/contracts/`、`proof_agent/bootstrap/loader.py` | `tests/test_contracts.py`、`tests/test_config_loader.py` |
| V3 工作流 | `proof_agent/control/workflow/controlled_react/` | `tests/test_controlled_react_*.py` |
| 策略或校验器 | `proof_agent/control/policy/`、`control/validators/` | 对应 `test_*validator.py`、`test_policy*.py` |
| API | `proof_agent/delivery/` | `tests/test_*_api.py` |
| PostgreSQL | `proof_agent/capabilities/persistence/postgres/` | 标记为 `postgres_integration` 的测试 |
| Hybrid Knowledge | `proof_agent/control/knowledge/`、`capabilities/knowledge/` | `test_hybrid_*.py` 与 `tests/integration/` |
| Dashboard | `dashboard/`、`packages/ui/` | `npm run test -w proof-agent-dashboard` |
| Operator Chat | `chat/`、`packages/ui/` | `npm run test -w proof-agent-chat` |

### 5.2 Agent 包开发规则

[KNOWN | HIGH] 新手只应修改唯一公开示例：`examples/agent_management_insurance_specialist/`。生产候选位于 `deploy/production/...`，二者不能混用。

[FRAME | HIGH] 首发私有试点不启用运行时 Case Memory。生产候选必须保持 `capabilities.memory.enabled: false`；PostgreSQL conversation context 只用于受控连续对话，不能作为证据或引用依据。未来启用 Case Memory 需要独立完成写入准入、事实 Schema、删除/过期、审计、敏感数据与真实模型评估。

开发示例的关键文件：

```text
agent.yaml          Agent Contract
policy.yaml         确定性策略
knowledge/          本地 Markdown 开发知识
skills/             Business Flow Skill Packs
```

必须保持：

```yaml
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
```

不要添加：

- `workflow.runtime`、`workflow.checkpointer` 或 `react.max_steps`；
- 旧模板 ID 或 `proof_agent/runtime/` 兼容层；
- 包内 Python handler、MCP stdio 或任意脚本执行；
- 初始生产中的状态变更工具；
- 将 Memory 当作 Accepted Evidence 的逻辑。

生产候选还要求：共享 Hybrid binding、真实模型 Secret Handle、无包内 Knowledge、无本地工具、无非权威运行时 Memory。依据：`deploy/production/agent_management_insurance_specialist/agent.yaml`。

### 5.3 前端开发

```bash
npm run dev -w proof-agent-dashboard
npm run dev -w proof-agent-chat
```

只改共享组件时，先验证共享包和受影响应用：

```bash
npm run typecheck --workspaces --if-present
npm run test -w proof-agent-dashboard
npm run test -w proof-agent-chat
npm run build
```

不要恢复已经移除的 customer、handoff 或 approval 页面；活跃浏览器范围只有 Dashboard 与 `/operator`。

### 5.4 提交前完整验证

```bash
uv lock --check
uv run --extra dev python -m pytest tests/ -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
npm run typecheck
npm test
npm run build
python3 scripts/check-domain-contexts.py
git diff --check
```

[KNOWN | HIGH] 一些 HTTP 和 Gateway 测试需要绑定 loopback socket；受限沙箱可能因 `PermissionError` 失败。正式签署 Gate 前必须在允许本地 socket 的 CI 或主机环境重跑，不能把这类跳过当作通过。

## 6. 本地 Hybrid 集成部署

### 6.1 适用范围

[KNOWN | HIGH] `docker-compose.hybrid-test.yml` 只启动一次性的 PostgreSQL、MinIO 和 OpenSearch。它不提供真实 Docling、Paddle、Embedding、Reranker、模型调度器、回答模型或独立 evaluator。

安装额外依赖并启动数据面：

```bash
uv sync \
  --extra dashboard \
  --extra ingestion \
  --extra hybrid \
  --extra production \
  --extra openai
docker compose -f docker-compose.hybrid-test.yml up -d --wait
```

只运行应用 PostgreSQL 集成测试时，在 Git 忽略的 `.env.test.local` 中保存本机测试配置：

```dotenv
PROOF_AGENT_TEST_POSTGRES_DSN=postgresql+psycopg://proof:proof-test-only@127.0.0.1:55432/proof
PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1
```

`PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1` 会让缺失或不可用的 DSN 直接导致测试失败，避免测试被静默跳过。该地址和凭据只对应 `docker-compose.hybrid-test.yml` 中绑定 loopback 的一次性数据库，不能用于共享或生产环境。

按照 `docs/deployment/hybrid-knowledge-closed-loop.md` 第 1 节配置本地测试 DSN、S3 和 OpenSearch 环境变量，然后执行：

```bash
uv run proof-agent database upgrade
uv run proof-agent hybrid-migrate
uv run proof-agent database check
```

[KNOWN | HIGH] `database upgrade` 显式安装应用 Alembic schema；`hybrid-migrate` 安装或验证幂等 Hybrid DDL；服务启动本身不会静默迁移数据库。`PROOF_AGENT_POSTGRES_DSN` 与 `HYBRID_POSTGRES_DSN` 必须指向同一 PostgreSQL authority。

运行一次性集成测试：

```bash
uv run --env-file .env.test.local --extra dev --extra production \
  pytest -m 'postgres_integration and not hybrid_integration' tests -q
uv run pytest -m hybrid_integration tests/integration -q
```

这些测试还需要文档部署指南中列出的 `HYBRID_TEST_*`、`PROOF_AGENT_TEST_*` 和 AWS 测试变量。

停止测试数据面：

```bash
docker compose -f docker-compose.hybrid-test.yml down
```

不要把测试密码、测试 bucket、`HYBRID_S3_ALLOW_INSECURE_ENDPOINT=1` 或禁用安全插件的 OpenSearch 复制到生产。

### 6.2 Hybrid 知识发布路径

```mermaid
flowchart LR
    PDF["隔离 PDF 上传"] --> Parse["私有 Docling / Paddle"]
    Parse --> Canonical["Canonical JSON + Preview"]
    Canonical --> Review["业务元数据审批"]
    Review --> Candidate["候选快照"]
    Candidate --> S3["精确版本 S3 Manifest"]
    Candidate --> Embed["Embedding"]
    Embed --> OS["OpenSearch"]
    OS --> Smoke["受治理 Smoke Retrieval"]
    Smoke --> Publish["PostgreSQL CAS 发布指针"]
    Publish --> PhaseF["Shadow / Capacity / Acceptance / Recovery"]
    PhaseF --> Agent["Published Agent Version"]
```

[KNOWN | HIGH] `/api/config/knowledge-sources` 是 Development 与 Production 的唯一 V1 资源根。PDF 与工作簿只通过 multipart admission 进入 durable operation；Dashboard 不发送 Base64、不持有 S3 authority，也不配置 Private Knowledge Model Serving Plane。未注入统一 application services 的 Development API 会返回安全 503，而不会退回文件型 Knowledge Hub。

[KNOWN | HIGH] 异步 publication preparation 在 authority commit 前完成候选防漂移、fencing、精确 S3 manifest、真实 embedding、OpenSearch 写后读、受治理 smoke retrieval 和投影 attestation。最终 Source publish 只执行幂等性、权限、新鲜度和短 PostgreSQL CAS，不调用私有模型、S3 或 OpenSearch。任一步失败都会失败关闭。完整 multipart/API 与 Phase F 命令见 `docs/deployment/hybrid-knowledge-closed-loop.md`。

### 6.3 一次性迁移旧 Development Knowledge Hub

[KNOWN | HIGH] 旧文件型 Development Knowledge Hub 只能通过显式一次性命令迁移；应用启动不会自动迁移，也不存在运行时双读、fallback 或兼容适配器。一次性 disposable 环境应直接初始化新的 PostgreSQL、S3-compatible 和 OpenSearch 依赖，无需迁移。

先使用组织认可的备份工具，为旧 `runs/config` 创建位于不同且非嵌套目录的精确备份。迁移器会对源目录和备份目录的相对路径、文件大小和内容 SHA-256 做完整比对；不一致、符号链接或缺失原件都会在写入目标前失败。

先执行 dry-run：

```bash
uv run proof-agent knowledge migrate-development-hub \
  --source-dir /srv/proof-agent/runs/config \
  --backup-dir /srv/proof-agent/backups/config-before-knowledge-v1 \
  --manifest /srv/proof-agent/migration/knowledge-hub-dry-run.json \
  --actor operator-subject
```

检查同目录生成的 `.json` 机器清单和 `.txt` 操作员报告。所有 Source 都必须明确为 `planned` 或可接受的 `skipped`；`source_id_conflict` 不会覆盖 PostgreSQL authority，必须先由操作员解决。确认目标环境已配置同一 PostgreSQL authority、启用版本控制的 S3 bucket，以及与 Knowledge Worker 一致的 parser revision、model digests 和 parser configuration SHA-256 后，再显式应用：

```bash
uv run proof-agent knowledge migrate-development-hub \
  --source-dir /srv/proof-agent/runs/config \
  --backup-dir /srv/proof-agent/backups/config-before-knowledge-v1 \
  --manifest /srv/proof-agent/migration/knowledge-hub-applied.json \
  --actor operator-subject \
  --apply
```

[KNOWN | HIGH] `local_index` 只迁移经过文件身份校验的 PDF 原件和已验证路由元数据；原件通过统一 multipart/V1 intake 重新入队，旧缓存索引和 `artifact_path` 从不导入。`http_json` 只复制非秘密配置与 `*_env`/引用字段，并保持 unpublished、verification-required；部署必须先提供相应 adapter capability，再做 fresh verification 和 Source publication。静态 Authorization/API Key、Bearer 值、URL userinfo、私钥和类似凭据会按 item 拒绝，且不会写入迁移清单。

[KNOWN | HIGH] 包内 Markdown 继续属于 Agent Package，不进入共享 Knowledge Hub。`hybrid_index` 等生产 authority 也不经过这个迁移器；它们只使用 expand-only PostgreSQL schema migration。若应用结果为 `partial_failure`，已经入队的 item 不会回滚；先核对 PostgreSQL/S3 审计和 operation，再处理失败项，禁止启动旧/新 authority 双读来掩盖失败。

[COMPUTED | HIGH] 2026-07-27 的仓库验证使用全新 disposable PostgreSQL/S3/OpenSearch authority，因此没有旧 Development Knowledge Hub 可迁移，实际 operator dry-run 按适用范围明确跳过；迁移器的 backup-tree 校验、dry-run 零目标写入、Source ID 冲突、缺失原件、静态秘密拒绝、逐项失败与 JSON/TXT manifest 行为由 7 个 focused tests 覆盖。真实存量环境仍必须按上面的 backup + dry-run + 人工清单确认流程执行，不能把 disposable skip 当成生产迁移证据。

## 7. 类生产角色如何启动

以下命令是当前代码中可执行的角色入口，不是完整的正式生产部署方案。只有在 PostgreSQL、S3、OpenSearch、OIDC、Vault、Egress Policy、私有模型和已发布 Agent 全部正确配置后才使用。

先设置生产模式并完成显式迁移：

```bash
export PROOF_AGENT_MODE=production
export PROOF_AGENT_RELEASE_SCHEMA=0021_metadata_workbook_v2
uv run proof-agent database upgrade \
  --locked \
  --expand-only \
  --target "$PROOF_AGENT_RELEASE_SCHEMA"
uv run proof-agent hybrid-migrate
uv run proof-agent database check
```

分别启动三个进程角色：

```bash
uv run proof-agent server \
  --host 127.0.0.1 \
  --port 8000 \
  --no-seed-example-agent
```

```bash
export PROOF_AGENT_KNOWLEDGE_WORKER_ID=knowledge-worker-1
uv run proof-agent knowledge-worker --slot 1 --poll-interval 1
```

```bash
export PROOF_AGENT_EXECUTOR_ID=executor-1
uv run proof-agent run-executor --slot 1 --concurrency 5
```

在对应容器内验证 Worker 健康端点：

```bash
curl -fsS http://127.0.0.1:8001/livez
curl -fsS http://127.0.0.1:8001/readyz
curl -fsS http://127.0.0.1:8002/livez
curl -fsS http://127.0.0.1:8002/readyz
```

[KNOWN | HIGH] 生产组合没有自动回退到本地文件存储或本地身份。缺少依赖、active Egress Policy、Published Agent 或 Secret 时应启动失败或 `/readyz` 返回 503；不要通过 allow-all、跳过 OIDC 或环境变量明文 Secret 绕过失败。API readiness 会校验精确 PostgreSQL schema、OIDC discovery/JWKS、专用 Secret Provider probe handle、版本化 S3 与 60 秒内的后台精确写读、Egress Policy、唯一 Published Agent 和队列。

[KNOWN | HIGH] `PROOF_AGENT_ACTIVATION_STATE=standby|draining` 时，Run Executor 和 Knowledge Worker 不会领取新任务；只有 `active` 且持有精确 PostgreSQL 角色租约时可以领取。每个角色只有一个权威槽位，激活 epoch 单调递增，后台 heartbeat 续租；续租失败会使 `/readyz` 返回 503，并阻止新领取及旧 owner 的最终提交。Run Executor 在 drain 时继续维护在途 Attempt，完成后释放角色；Knowledge Worker 在角色 fencing 时取消在途模型构建。

[KNOWN | HIGH] Worker 健康端点仅绑定容器 loopback：Run Executor 使用 `127.0.0.1:8001/livez|readyz`，Knowledge Worker 使用 `127.0.0.1:8002/livez|readyz`。`/livez` 只表示进程存活；`/readyz` 才表示依赖与角色状态可用于当前部署阶段。不要把 Worker 健康端口暴露到槽位网络或公网。

生产变量完整模板见 `.env.example`，按责任可分为：

| 变量组 | 示例前缀 | 负责人 |
| --- | --- | --- |
| 应用与角色 | `PROOF_AGENT_MODE`、`PROOF_AGENT_RELEASE_ID` | 平台发布 |
| PostgreSQL | `PROOF_AGENT_POSTGRES_DSN`、`HYBRID_POSTGRES_DSN` | DBA / 平台 |
| S3 | `PROOF_AGENT_ARTIFACT_S3_*`、`HYBRID_S3_*` | 存储平台 |
| OIDC 与 Session | `PROOF_AGENT_OIDC_*`、`PROOF_AGENT_SESSION_*` | 身份平台 |
| Vault / Secret Handle | `PROOF_AGENT_SECRET_*`、`*_SECRET_HANDLE` | 安全平台 |
| Hybrid 模型 | `PA_KNOWLEDGE_*`、`HYBRID_EMBEDDING_*` | 模型平台 |
| OpenSearch | `HYBRID_OPENSEARCH_*` | 搜索平台 |
| Phase F | `PA_KNOWLEDGE_*DRIVER`、evaluator/verifier | 评估与发布负责人 |
| Release Bundle | `PROOF_AGENT_RELEASE_BUNDLE_CACHE_DIR`、`PROOF_AGENT_RELEASE_TRUSTED_ED25519_KEYS_JSON` | 发布与安全负责人 |

配置只应保存 Secret Handle、变量名或无凭据 origin；真实 Secret 留在 Vault、workload identity 或部署 Secret 注入机制内。

## 8. 正式生产部署前置条件

[KNOWN | HIGH] 当前不能仅凭仓库中的生产 Dockerfile 和 Compose 定义上线。先复制 DCM 示例为候选本地文件，替换全部示例产品版本、origin、不可变 revision 和 Evidence digest，然后在显式时间校验：

```bash
uv run proof-agent deployment validate-compatibility \
  --manifest deploy/production/deployment-compatibility-manifest.json \
  --at 2026-07-25T12:00:00Z
```

`deployment-compatibility-manifest.example.json` 只说明结构，其占位 digest 绝不能作为发布证据。生产定义和操作说明见 `deploy/production/README.md`。

尚需完成或用真实候选证明：

- 使用 digest 固定的三个基础镜像构建、扫描并登记不可变产品镜像；
- 把 Gateway 的 `proof-agent.invalid` 安全占位符渲染为 DCM 绑定域名，并执行容器内 `nginx -t`；
- 原子安全 bootstrap 和 active Permission Mapping / Egress Policy；
- Worker 租约丢失、heartbeat 失败和 `/readyz` 503 的告警与日志投递；
- 审查内置 `docker-compose-v1` 驱动，并在一次性真实依赖环境完成 standby、N/N-1、admission pause、drain、稳定源 smoke、30 分钟 soak 与两类回滚演练；
- PostgreSQL PITR 与精确版本 S3 联合恢复演练；
- 用真实候选完成 Release Registry 定稿、认证下载与审计 Evidence，并补齐运维 Runbook；
- 同一候选绑定的 13 个 Gate 全部 `passed`。

13 个正式 Gate 为：

1. backend/frontend quality；
2. distribution/image；
3. supply-chain/runtime security；
4. identity/authorization；
5. secrets/egress；
6. deterministic evaluation；
7. real-LLM evaluation；
8. dependency compatibility；
9. capacity/responsiveness；
10. queue/progress；
11. resilience/recovery；
12. deployment；
13. browser/operations。

离线核验一个已经生成的候选 Manifest：

```bash
uv run proof-agent release verify \
  --manifest /path/to/release-gate-manifest.json \
  --evidence-root /path/to/immutable/evidence \
  --at 2026-07-18T10:00:00Z
```

退出码：`0` 为 GO，`1` 为有效的 NO-GO，`2` 为输入无效。不要手工把结果改成 GO；修复问题后，为同一精确候选重新生成证据。

[KNOWN | HIGH] Blue/Green 纯编排已经固定顺序：候选绑定预检 → 显式 expand migration → 启动 standby → `/readyz` 与隔离 smoke → 双向 N/N-1 队列契约 → 旧 Worker `DRAINING` 并最多等待 150 秒 → 原子切换全部浏览器/API/OIDC callback/SSE 路由 → 更高 activation epoch → 稳定源 OIDC/提交/SSE/terminal/S3 smoke → 30 分钟 soak → 停旧计算。排空超时会在切流前以旧 epoch 恢复旧 Worker并保持候选 standby；切流后的失败会先路由回旧 API，再排空或 fence 候选、以更高 epoch 激活旧 Worker并显式失败丢失 Attempt。依据：`proof_agent/deployment/choreography.py` 与对应测试。

[KNOWN | HIGH] nginx 原子切换和 `docker-compose-v1` 驱动已在本地 fake 命令边界验证：驱动覆盖双镜像/环境绑定、Compose 生命周期、双队列计数、原子 admission pause、同 epoch 排空恢复、认证稳定源 smoke、固定 soak 与回滚 fencing。实际 Gateway 候选 include 仍会先执行容器内 `nginx -t`，再原子替换、reload，并从五个入口核对相同 generation；混代会恢复旧 include。当前不可直接上线的剩余点是没有运行中 Docker/nginx、真实 OIDC cookie、真实候选镜像和一次性完整依赖环境的演练证据，不能把“驱动代码存在”解释为“已经可发布”。

### 8.1 Release Registry 与精确下载

[KNOWN | HIGH] schema `0013_release_registry` 提供 `PREPARING → FINALIZED` 单向状态机。`PREPARING` 只绑定候选摘要和精确 Release Gate Manifest，不能下载；一次条件事务会写入精确 Bundle Index、分离 attestation、信任身份和定稿时间。重复定稿，或 candidate、Manifest、owner、Index、attestation 任一不匹配都会失败关闭。

API 容器必须配置 tmpfs 内的只读校验缓存和部署拥有的 Ed25519 公钥映射：

```dotenv
PROOF_AGENT_RELEASE_BUNDLE_CACHE_DIR=/var/lib/proofagent/release-bundle-cache
PROOF_AGENT_RELEASE_TRUSTED_ED25519_KEYS_JSON={"release-key-2026-07":"BASE64_OF_32_RAW_PUBLIC_KEY_BYTES"}
```

使用拥有 `audit.export` 权限的 OIDC 会话访问 Dashboard `/releases`。下载固定为：

```text
GET /api/releases/{release_id}/bundle/{artifact_name}
```

[KNOWN | HIGH] 服务先从 PostgreSQL 解析精确 S3 object version，完整物化并校验 Bundle Index 和分离 attestation，再由已验证 Index 授权 Manifest、HTML、Closure Audit、Evidence、SBOM 或 Provenance 的精确成员。响应来自只读缓存，支持单段 byte range，并带 attachment、`private, no-store` 和 `nosniff`；每次允许、拒绝或失败都会留下 operator/release/object/outcome 审计元数据。它不会读取仓库 `reports/`，HTML 也不是 GO/NO-GO authority。

[KNOWN | HIGH] 当前只完成代码与本地测试前置条件，没有真实候选 Registry 行、S3 Bundle 或下载 Gate Evidence。不得手工伪造 `FINALIZED`，实际定稿只能在 S7B 得到同一候选 `GO` 后由已冻结的 S8B 工具执行。

## 9. 运维巡检与故障排查

### 9.1 建议巡检表

| 层级 | 检查 | 正常信号 | 异常时先看 |
| --- | --- | --- | --- |
| 进程 | `/livez` | HTTP 200，`alive` | 进程退出、端口、启动日志 |
| 依赖 | `/readyz` | HTTP 200，所有组件 `ready` | 返回的首个 `not_ready`/`unavailable` 组件 |
| 数据库 | `proof-agent database check` | 退出码 0 | DSN、schema revision、迁移锁 |
| 队列 | API stats / runs | 无长期无主 lease，未超过容量 | Executor、claim token、attempt、fencing |
| Knowledge | ingestion job | `ready` | Worker、scheduler、parser、S3 exact ref |
| Agent | 在线 smoke | `ANSWERED_WITH_CITATIONS` | frozen binding、ACL、证据与引用 Gate |
| 产物 | `artifacts verify-references` | `valid` | S3 version、SHA-256、PG reference |
| 恢复 | `recovery verify` | 联合 authority 有效 | 保留策略、缺失对象、损坏引用 |
| 发布 | `release verify` | 同一候选 13 Gate GO | blocker code、freshness、binding digest |

### 9.2 常见故障树

#### 服务无法启动

1. 运行 `uv run proof-agent doctor`。
2. 检查 Python 是否为 3.12+，依赖 extra 是否安装。
3. 检查 `PROOF_AGENT_MODE`；误设为 `production` 会强制要求完整生产组合。
4. 生产模式下先检查两个 PostgreSQL DSN 是否指向同一 authority。
5. 查找启动日志中的首个 `is required`、schema mismatch 或 Secret validation 错误。

#### `/readyz` 返回 503

[KNOWN | HIGH] 当前响应会把失败归类到 `artifact_store`、`hybrid_artifact_store`、`egress_policy`、`postgresql`、`published_agent`、`release_registry`、`run_queue` 或 `secret_provider`。

- `postgresql`：检查网络、凭据和 `database check`；
- `artifact_store`：检查 bucket、endpoint、版本能力和工作负载身份；
- `hybrid_artifact_store`：检查 Hybrid bucket、prefix 和 endpoint；
- `egress_policy`：确认 active policy 已由受控 bootstrap 激活；
- `published_agent`：确认只有目标 Agent 处于 active 且其 Secret Handle 可解析；
- `run_queue`：检查队列表和数据库事务；
- `release_registry`：检查 `0013_release_registry`、Registry 查询和 PostgreSQL 权限；
- `secret_provider`：检查 Vault Agent token、handle locator 与 CSRF key。

不要把 readiness 改成固定 200 来掩盖依赖故障。

#### 请求一直排队

1. 确认 Run Executor 进程存在且 ID 唯一。
2. 检查 `PROOF_AGENT_RELEASE_ID` 和 `PROOF_AGENT_IMAGE_DIGEST` 是否与候选绑定一致。
3. 检查 lease、attempt、claim token 与 fencing 错误。
4. 检查容量是否达到 5 个 active / 50 个 queued 的目标包络。
5. 浏览器断开不会取消 Run；重连 SSE 应恢复持久化当前状态。

#### Knowledge job 未进入 `ready`

按边界定位：

1. admission / PDF 类型和大小；
2. Knowledge Worker 是否领取 job；
3. scheduler、Docling、Paddle 是否可达；
4. 原始文件和 vendor 输出是否写入精确版本 S3；
5. metadata review 是否全部由正确 authority 批准；
6. validation 是否因候选漂移或 fencing 失效；
7. embedding、OpenSearch bulk/read-back 和 smoke retrieval。

#### 有检索结果但没有最终回答

[INFERRED | HIGH] 优先检查 citation、evidence adequacy、institution authorization、applicability filter、frozen publication/manifest/attestation，以及回答模型是否输出了可被 schema 接纳的引用。不要降低 deterministic Gate 来迁就模型输出。

#### Artifact 或恢复校验失败

先做只读校验：

```bash
uv run proof-agent artifacts verify-references \
  --dsn "$PROOF_AGENT_POSTGRES_DSN" \
  --at 2026-07-18T10:00:00Z

uv run proof-agent recovery verify \
  --dsn "$PROOF_AGENT_POSTGRES_DSN" \
  --at 2026-07-18T10:00:00Z
```

这些命令验证 PostgreSQL 引用、S3 精确版本和 SHA-256；它们不替代外部 PostgreSQL PITR 或 S3 恢复。没有变更单和备份证据时不要添加 `--apply`。

## 10. 高风险操作清单

| 操作 | 默认行为 | 风险 | 新手要求 |
| --- | --- | --- | --- |
| `config-reset --yes` | 删除本地配置目录 | 丢失本地草稿和发布状态 | 停服务、核对 `--config-dir` |
| `database upgrade` | 修改 PostgreSQL schema | 迁移失败或版本不兼容 | 先备份、确认候选和回滚窗口 |
| `artifacts expire --apply` | 应用逻辑过期 | 普通读路径立即不可见 | 先不带 `--apply` 预览 |
| `artifacts gc --apply` | 删除宽限期外未引用精确版本 | 物理对象不可恢复 | 先预览并保留输出证据 |
| `artifacts verify-references --apply` | 校验并应用保留处理 | 会改变保留状态 | 先只读执行 |
| `recovery verify --apply` | 重应用保留并联合验证 | 会改变保留状态 | 仅恢复演练或批准窗口 |
| `production-publish-agent` | 原子激活新 Published Agent | 改变线上 active pointer | 仅 Phase F 四门和发布授权齐全时 |
| `scripts/deployment/blue_green.py` | 真实驱动存在时修改槽位、Worker authority 与 Gateway 路由 | 错误切流、流量中断、错误 fencing | 仅批准窗口、双人复核、先在一次性环境演练 |

[COMMON | HIGH] 对数据库、对象存储、active pointer 或 Gateway routing generation 的变更应在批准的变更窗口执行，保留命令输出、操作者、候选摘要、每步结果、开始/结束时间与回滚判断。仓库已有编排与内置驱动，但尚无真实演练证据和完整告警，因此这些外部控制不能省略。

## 11. 新手第一周建议

1. 第一天：读本指导书和五个活跃事实源，跑通离线 smoke。
2. 第二天：启动 `dev` 与两个前端，观察一次请求的 API、Trace 和 Receipt。
3. 第三天：修改一个本地 Knowledge 文档，先写/改测试，再观察引用变化。
4. 第四天：阅读 `controlled_react/`、policy 和 validators，画出一次请求的状态迁移。
5. 第五天：启动 disposable Hybrid 数据面并跑集成测试；不要接触正式凭据。
6. 完成上述步骤后，再在资深发布负责人陪同下阅读类生产闭环和 Phase F。

## 12. 权威资料索引

按以下顺序判断“当前真实状态”：

1. `README.md`：产品边界和常用命令；
2. `docs/prd.md`：初始发布需求与非目标；
3. `docs/technical-design.md`：活跃架构；
4. `docs/developer-guide.md`：开发约束；
5. `docs/development-progress.md`：已实现、缺口和正式 NO-GO 状态；
6. `docs/deployment/hybrid-knowledge-closed-loop.md`：Hybrid 类生产闭环与 Phase F；
7. `.env.example`：变量名与部署绑定模板；
8. `CONTEXT-MAP.md`：领域上下文路由。

`docs/adr/` 和 `docs/superpowers/` 下的材料用于解释历史决策和批准目标，但可能包含已删除或延期的能力。若它们与上述活跃事实源冲突，以活跃事实源为准。
