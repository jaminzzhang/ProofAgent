# KSS 独立项目隔离 Feature Context

## 1. 需求基本信息

| 字段 | 内容 |
| --- | --- |
| 需求名称 | 将 KSS 抽取为与 ProofAgent 隔离的独立项目 |
| Feature ID | `kss-project-isolation` |
| 需求来源 | 2026-09-03 用户明确要求“那 KSS 拆到单独的项目中，跟 ProofAgent 隔离” |
| 目标项目 | `/Users/jamin/Dev/mz-projects/KSS`（请求时不存在，本轮已创建本地独立 Git 工作区） |
| 当前状态 | `PARTIAL_VERIFICATION` |
| 负责人 | 未指定；本地实现不替代代码、发布或数据迁移负责人确认 |

## 2. 需求目标与范围

| 目标 | 说明 | 验收口径 |
| --- | --- | --- |
| 项目所有权隔离 | KSS 独占源码、依赖锁、容器构建、迁移和内部契约测试 | ProofAgent 仓库不再包含 KSS 实现包或 distribution 目录 |
| 发布工件隔离 | ProofAgent 只能消费外部 KSS OCI/wheel/OpenAPI/migration identity | ProofAgent 的本地集成 Compose 不再从本仓库构建 KSS |
| 运行时权威不漂移 | KSS 继续返回 Candidate Evidence；ProofAgent 继续负责 Evidence Admission 和最终回答 | 既有 HTTP 客户端、exact Release 与 fail-closed 测试保持通过 |
| 独立可验证 | KSS 新项目可独立锁依赖、运行测试和构建镜像 | 新项目自己的测试、Ruff、Mypy、lock check 通过或明确记录限制 |

### 范围内

| 范围项 | 说明 | 依据 |
| --- | --- | --- |
| KSS 源码与迁移 | 移动 `knowledge_source_service/` | 当前仓库事实；ADR-0192、ADR-0210 |
| KSS distribution | 把 service 子目录元数据收敛到新项目根目录 | 当前 `services/knowledge-source-service/` |
| KSS 内部测试 | 移动纯 KSS contract、fixture 和真实依赖测试 | `tests/contract/knowledge_service/` |
| ProofAgent 集成边界 | 保留 HTTP client、BFF、Admission、Candidate Binding 和外部服务契约 | `proof_agent/capabilities/knowledge/` 与 active docs |
| 本地集成编排 | KSS 可以作为外部镜像依赖被 ProofAgent 集成栈启动，但不能从 ProofAgent 源码构建 | 项目隔离不等于取消跨服务验证 |
| 文档与 CI | 两个项目分别声明所有权、命令和证据边界 | `AGENTS-COMMON.md` 与 hicode 规则 |

### 范围外

| 范围项 | 排除原因 | 影响 |
| --- | --- | --- |
| 生产数据迁移 | 需要精确备份、停写、恢复和负责人授权 | 本轮不改变任何 PostgreSQL、S3 或 OpenSearch 数据 |
| 生产部署或切流 | 需要独立 Candidate、Gate 和发布批准 | 本地验证不能解释为 Production GO |
| Git 远端、推送或历史重写 | 用户未授权远端变更；历史拆分策略未指定 | 新项目保留来源 commit 记录，但本轮不发布 |
| KSS 领域模型重构 | 与物理项目拆分正交 | 保持 exact Release、Space、Grant、Candidate Evidence 契约不变 |
| ProofAgent Dashboard 产品范围变化 | Dashboard 仍通过 BFF 管理 KSS | 不新增浏览器直连 KSS |

## 3. 设计树

| 节点 | 类型 | 触发条件/输入 | 处理方案 | 输出/状态变化 | 验证点 | 风险等级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | 用户要求 KSS 与 ProofAgent 项目隔离 | 建立独立源码和发布所有权，只保留网络契约 | 两个独立项目 | 双仓边界测试 | P1 | 已关闭 |
| MAIN-1 | 新项目骨架 | 当前 KSS package、service metadata 和 tests | 在同级 `KSS` 项目建立根 pyproject、lock、Dockerfile、tests、docs | KSS 可独立安装和测试 | distribution / import / lock tests | P1 | 已关闭 |
| MAIN-2 | ProofAgent 瘦身 | KSS 源码和内部测试仍在 ProofAgent | 删除嵌入实现并清理 KSS-only 依赖 | ProofAgent 不可直接 import KSS | repository-boundary test | P1 | 已关闭 |
| MAIN-3 | 集成工件 | Compose 当前从 ProofAgent context 构建 KSS | 要求调用方传入外部 `KSS_IMAGE`，保留黑盒 HTTP 集成 | 构建所有权移出 ProofAgent | Compose contract test | P1 | 已关闭 |
| MAIN-4 | 契约与文档 | active docs 仍声明根级 KSS package | 更新为独立项目与外部工件边界 | current-source 文档一致 | domain-context / doc grep | P2 | 已关闭 |
| BRANCH-1 | 跨仓测试耦合 | 两个 KSS contract 文件 import ProofAgent | KSS 项目只保留纯 KSS 场景；ProofAgent 保留/补充黑盒边界测试 | 无反向 Python dependency | import scan | P1 | 已关闭 |
| BRANCH-2 | 工件缺失 | 未提供 KSS image 或 identity | 配置/构建失败关闭，不回退到本地源码 | 稳定阻断 | negative compose test | P1 | 已关闭 |
| BRANCH-3 | 数据和部署 | 代码迁移可能被误解为数据迁移 | 明确不触碰运行数据、容器和发布 Gate | 无运行态变更 | git/status 与未执行记录 | P1 | 已关闭 |
| BRANCH-4 | 回滚 | 双项目变更需要独立回退 | ProofAgent 与 KSS 各自保留可审查 diff，不自动提交 | 可按项目回退 | 两个 git status/diff | P2 | 已关闭 |

## 4. 核心规则

| 规则编号 | 规则说明 | 边界 |
| --- | --- | --- |
| KSS-ISO-1 | KSS 不得 import `proof_agent`，ProofAgent 不得 import `knowledge_source_service` | Python 源码和测试辅助代码都检查 |
| KSS-ISO-2 | ProofAgent 不得拥有 KSS Docker build context、wheel metadata 或 migrations | 可保留外部工件 identity schema |
| KSS-ISO-3 | 跨项目调用只通过版本化 HTTPS API 与受控 credential/egress boundary | 浏览器不得直接取得 KSS token |
| KSS-ISO-4 | KSS 仍只返回 Candidate Evidence | Evidence Admission、冲突治理和答案仍归 ProofAgent |
| KSS-ISO-5 | 缺少精确 KSS 工件或服务时失败关闭 | 不允许嵌入式或本地 provider fallback |

## 5. 高严谨风险基线

| 维度 | 是否涉及 | 已知规则/证据 | 待确认问题 | 风险等级 |
| --- | --- | --- | --- | --- |
| 领域业务逻辑 | 是 | ADR-0192、ADR-0210；语义保持不变 | 无 | P1 |
| 数据一致性 | 是 | PostgreSQL/S3/OpenSearch 权威不在本轮迁移 | 后续生产数据迁移需单独 Scope | P1 |
| 状态、幂等、并发 | 是 | 现有 KSS tests 随实现迁移 | 不改变状态机 | P1 |
| 权限与审计 | 是 | HTTP Grant、operator secret、egress fail closed | 不改变权限模型 | P1 |
| 隐私与凭证 | 是 | 不读取 `.env`，不复制 runtime secrets/data | 无 | P1 |
| 生产变更与回滚 | 是 | 本轮不部署、不切流、不推送 | 远端与正式 cutover 后续确认 | P1 |
| 金额与关键数值 | 否 | 无金额逻辑变更 | 无 | NONE |

## 6. 影响范围

| 类型 | 对象 | 影响说明 | 风险等级 |
| --- | --- | --- | --- |
| 新项目 | `/Users/jamin/Dev/mz-projects/KSS` | 新建独立 Git 项目与验证入口 | P1 |
| 删除/迁移 | `knowledge_source_service/`、`services/knowledge-source-service/`、KSS 内部 tests | 从 ProofAgent 所有权移出 | P1 |
| 构建 | `docker-compose.production-local.yml`、production docs/tests | 改为外部 KSS image | P1 |
| 依赖 | 两个 `pyproject.toml` 与 lock | 按项目归属拆分 | P1 |
| 文档 | active docs、domain indexes、feature evidence、ADR | 更新当前事实，不改写历史证据 | P2 |

## 7. 测试与发布关注点

| 关注项 | 类型 | 优先级 | 证据或说明 |
| --- | --- | --- | --- |
| 双向 import 禁止 | architecture | P1 | AST/文本边界测试 |
| 外部镜像必填且不可本仓构建 | deployment contract | P1 | Compose 解析测试 |
| KSS 全部内部 contract | regression | P1 | 在新项目执行 |
| ProofAgent KSS clients/BFF/Admission | regression | P1 | 在 ProofAgent 执行 |
| lock、Ruff、Mypy、domain docs | static | P2 | 两项目分别执行 |

## 8. 待确认问题

| 问题 | 风险等级 | 影响 | 建议确认人 | 处理 |
| --- | --- | --- | --- | --- |
| 新项目远端地址和可见性 | P2 | 后续 push/release | 用户/仓库负责人 | 本轮不创建远端、不推送 |
| 是否保留完整 Git 历史 | P2 | blame 与审计便利性 | 用户/仓库负责人 | 本轮记录来源 commit，后续可做 filter-repo 历史迁移 |
| 生产数据与运行栈何时独立迁移 | P1 | 正式 cutover | 数据/发布/安全负责人 | 单独 Scope 与 Gate，当前不执行 |
