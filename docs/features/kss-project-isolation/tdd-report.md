# KSS 独立项目隔离 TDD 报告

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `PARTIAL_VERIFICATION` |
| 最高风险等级 | P1 |
| 日期 | 2026-09-03 |
| 本地实现结论 | KSS 源码、迁移、依赖锁、容器构建、正式五角色 Compose、内部测试、文档和 CI 已移入独立兄弟项目 `/Users/jamin/Dev/mz-projects/KSS` |
| ProofAgent 边界 | ProofAgent 只保留受控 HTTP 客户端、Candidate Binding、BFF、Evidence Admission 和最终答案治理；本地集成栈只消费外部固定摘要 `KSS_IMAGE` |

[COMPUTED | HIGH] 双项目本地代码拆分和各自的默认测试、静态检查、锁文件检查已通过。KSS 还能独立构建 sdist、wheel，并用固定摘要基础镜像完成 cache-only Dockerfile 构建。该结果证明本地源码与构建边界，不证明生产数据迁移、候选容器发布、外部依赖 readiness、跨产品完整黑盒链路或 Production GO。

## 2. 本轮边界

### 范围内

- 创建独立 KSS Git 工作区，并迁移仅属于 KSS 的已跟踪源码和证据。
- 删除 ProofAgent 内嵌 KSS 实现、distribution、迁移、正式部署定义和内部测试。
- 拆分 Python 依赖与锁文件。
- 将 ProofAgent 类生产 Compose 改为消费外部 KSS OCI 工件。
- 更新当前上下文、ADR、开发和运维文档。

### 范围外

- 生产 PostgreSQL、S3、OpenSearch 数据迁移或修改。
- KSS 或 ProofAgent 生产部署、切流、发布 Gate、回滚演练。
- 新 KSS 远端创建、Git 历史重写、commit、push 或 merge。
- KSS 领域语义、公共 HTTP 契约、ProofAgent Evidence Admission 语义变更。

## 3. RED → GREEN → REFACTOR

| 轮次 | 实际 RED | GREEN 结果 | 说明 |
| --- | --- | --- | --- |
| TDD-01 ProofAgent repository boundary | `tests/test_kss_project_isolation.py` 初次执行 4 failed：旧实现目录存在、46 个测试文件直接导入 KSS、Compose 仍构建 KSS、生产镜像仍请求已不存在的 `hybrid` extra | 删除嵌入实现与内部测试；保留 HTTP/工件边界；最终 7 passed | 没有以复制两份实现换取通过 |
| TDD-01 KSS project boundary | 空目标项目的骨架测试初次执行 2 failed、1 passed | 新项目拥有根级 package、distribution、Dockerfile、lock 和项目隔离测试 | KSS AST 扫描禁止 `proof_agent` import |
| TDD-02 external artifact | ProofAgent Compose 测试确认 `kss-api.build` 仍存在；启动脚本没有 immutable image 准入 | 所有 KSS 角色使用同一必填外部 `KSS_IMAGE`；脚本拒绝缺名、可变 tag、非 64 位或非小写十六进制摘要 | 负向测试未启动 Compose，也未拉取 KSS 候选 |
| TDD-03 dependency ownership | ProofAgent 的 `production` extra 仍声明 `openpyxl`、`Pillow`、`pyarrow`；新 KSS 自有虚拟环境首次收集测试时缺少 `PyYAML` | KSS 专属解析依赖归入 KSS；ProofAgent lock 移除不再需要的直接依赖；KSS dev extra 增加 `PyYAML` | 缺依赖是独立项目元数据缺口，不伪称领域行为 RED |
| TDD-03 CI lifecycle | 新 CI 对包含一次性 `minio-init` 的依赖栈直接执行 `up -d --wait`，且没有验证独立 distribution/container 构建 | 先等待三个长驻依赖，再单独 `run --rm minio-init`；默认 job 构建 sdist/wheel 和 cache-only container | 合同测试对两项缺口分别经历 1 failed、3 passed，修复后均为 4 passed |
| TDD-04 active truth | 当前文档和部署说明仍指向 ProofAgent 内部 KSS build/Compose | ADR-0239、两个项目的 current context、开发/部署说明和迁移 provenance 已更新 | 历史 ADR、设计和 TDD 证据保留原路径语境 |
| REFACTOR | Ruff 0.16 的默认规则集合较原项目基线扩张，产生 175 个与抽取无关的历史风格问题 | KSS 明确固定原基线规则 `E4/E7/E9/F`，防止工具版本改变默认检查语义 | 未批量重写迁移源码 |

## 4. 实现结果

| 所有者 | 结果 | 关键路径 |
| --- | --- | --- |
| KSS | 独占实现、18 个 migration、独立 `pyproject.toml`/`uv.lock`、Dockerfile、内部/真实依赖测试、正式五角色 Compose 和 CI | `/Users/jamin/Dev/mz-projects/KSS` |
| ProofAgent | 不再包含 `knowledge_source_service/`、`services/knowledge-source-service/`、`deploy/production/knowledge/` 或 KSS 内部 contract tests | `tests/test_kss_project_isolation.py` |
| 集成 | 类生产栈保留 KSS API、Query Executor、Worker、Scheduler、Migration 和 bootstrap 组合，但只消费外部 OCI 摘要 | `docker-compose.production-local.yml`、`scripts/production-local-up.sh` |
| 权威 | KSS 仍返回 Candidate Evidence；ProofAgent 仍执行 Evidence Admission、冲突治理和答案控制 | ADR-0239 和既有 ADR-0192/0210 |
| 追溯 | KSS 记录抽取来源 ProofAgent commit `b80ca47`；请求时该分支相对 `origin/main` ahead 11 | KSS `MIGRATION.md` |

## 5. 验证记录

### 独立 KSS 项目

| 检查 | 结果 | 限定 |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests -q -p no:cacheprovider` | 274 passed、164 skipped、1 个依赖库 deprecation warning | 164 个 PostgreSQL、S3-compatible 或 OpenSearch 门禁用例未配置真实依赖，不计为通过 |
| `.venv/bin/ruff check knowledge_source_service tests` | All checks passed | 使用项目显式 lint 基线 |
| `.venv/bin/mypy ... knowledge_source_service` | 101 source files，无错误 | 静态类型证据，不是运行时 readiness |
| `uv lock --check --offline` | 通过，解析 46 packages | 独立锁文件一致 |
| `uv build --offline` + wheel 内容检查 | 成功构建 `.tar.gz` 和 `py3-none-any.whl`；wheel 包含全部 18 个有序 SQL migration | 证明 Python distribution 独立构建；未生成或发布 OCI 候选 |
| `docker buildx build ... --output type=cacheonly` | 使用固定摘要的 UV/Python 基础镜像完成全部构建阶段 | 没有生成候选 tag、发布摘要、签名或扫描证据 |
| `docker compose ... config --quiet` | 使用虚构、无 Secret 值的绑定成功渲染正式五角色 Compose | 只读配置验证；未启动 Migration 或在线角色 |

### ProofAgent 项目

| 检查 | 结果 | 限定 |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests -q` | 2264 passed、108 skipped、2 deselected、1 个既有 Authlib deprecation warning | 在允许绑定本地 `127.0.0.1` 临时端口的环境运行；显式跳过和 opt-in 用例未计为通过 |
| `.venv/bin/ruff check proof_agent tests` | All checks passed | 覆盖产品代码和测试 |
| `.venv/bin/mypy proof_agent` | 372 source files，无错误 | 静态类型证据 |
| `.venv/bin/python scripts/check-domain-contexts.py` | 通过 | 当前领域上下文结构检查 |
| `uv lock --check --offline` | 通过，解析 114 packages | KSS 专属直接依赖已移出 ProofAgent |
| `npm run typecheck` | 通过 | 前端类型检查 |
| `npm test` | Dashboard 32 files/225 tests；Chat 14 files/35 tests，全部通过 | 前端本地回归 |
| `npm run build` | UI、Dashboard、Chat 均构建成功 | Chat 保留既有大 chunk warning；不是本轮回归失败 |
| `git diff --check` | 通过 | whitespace 检查 |

## 6. 安全与运行态记录

[KNOWN | HIGH] 抽取只复制 Git 已跟踪的 KSS 文件。没有读取或复制 `.env`、Secret、数据库、对象工件、索引、日志、运行目录或容器数据。

[KNOWN | HIGH] 本轮没有启动、停止或删除 production-local 容器和 volume；没有执行 SQL、发布、生产迁移、远端创建、commit、push、merge 或 Gate 激活。

[KNOWN | HIGH] ProofAgent 原仓库和新 KSS 仓库均未留下 staged changes。新 KSS 仓库当前没有 commit 或 remote；全部交付文件保持为可审查的未跟踪工作区内容。

## 7. 残余风险与下一步

| 风险 | 等级 | 当前证据边界 | 后续动作 |
| --- | --- | --- | --- |
| KSS 真实依赖回归未刷新 | P1 | 164 个门禁用例保持 skipped | 在隔离、可清理的 PostgreSQL、S3-compatible、OpenSearch 环境运行 `KSS_REQUIRE_*_TESTS=1` 套件 |
| 五个跨产品 in-process 场景未迁移 | P1 | 为避免 KSS 反向依赖 ProofAgent，已从 KSS 内部套件移除 | 用两个独立构建的版本化服务，通过 HTTPS 重建黑盒合同场景 |
| OCI 候选尚未形成 | P1 | Dockerfile cache-only 构建已通过；没有候选 tag、发布摘要、签名、扫描或推送 | KSS 独立 CI 生成固定摘要候选，再由 ProofAgent 集成栈消费 |
| 生产数据和部署仍是原运行态 | P1 | 本轮没有触碰运行数据或部署 | 另立 Scope，准备备份、停写、恢复、兼容性和正式 Gate 证据后再 cutover |
| Git 远端与历史策略未定 | P2 | 本地独立 repo 无 commit/remote | 仓库负责人决定 snapshot 初始提交或经审阅的历史提取；随后分别 review 两个项目 |

## 8. 状态结论

[COMPUTED | HIGH] 本地 repository/build ownership 隔离已完成并通过默认回归。由于真实依赖、跨产品黑盒集成、OCI 候选和生产 cutover 证据仍缺失，Feature 保持 `PARTIAL_VERIFICATION`，不得表述为生产完成或发布批准。
