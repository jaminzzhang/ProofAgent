# Product Release Authority TDD Report

## 结论

[COMPUTED | HIGH] `initial-private-pilot-v2`、Candidate Binding v2、Gate 计算、Manifest 组装、精确 Evidence/attestation 存储、工作负载身份签名校验及四个 Release CLI 动作已通过本地验证。Candidate Binding v2 已纳入独立 KSS artifact 和 contract identity。状态为 `VERIFIED_LOCAL`，不等于生产发布批准。

## RED → GREEN 证据

| 行为 | RED | GREEN |
| --- | --- | --- |
| 五个风险 Gate 与完整策略归一 | v2 Profile 不存在 | Profile 契约、规范化摘要与五 Gate 固定顺序通过 |
| 流水线只给质量事实 | 缺少 Gate 计算模块 | `candidate_integrity=failed`，缺失镜像和供应链项均为 blocker |
| 部分结果组装 | 缺少 Manifest assembler | 未上报 Gate 显式补为 `not_run` |
| 正式 Evidence 落账 | 缺少精确版本适配 | 文件系统测试与 S3 生产端口共用 `ArtifactStore` 精确读写语义 |
| Evidence 签名 | 缺少可用 attestation verifier | Ed25519 信封绑定 workload identity、artifact、candidate 和 Gate Result |
| CLI 复用现有流水线 | 仅有 `verify` 且 verifier 不可用 | `bind-candidate`、`evaluate-gate`、`assemble-manifest`、可信 `verify` 通过 |
| Release Bundle 归档 | Bundle Index 拒绝新 Evidence 类型和 owner | exact Evidence/attestation 可由 Release owner 纳入 Bundle Index |
| 独立 KSS 候选身份 | Candidate Binding 只绑定 ProofAgent 主镜像 | Candidate Binding v2 同时绑定 KSS OCI、wheel、OpenAPI、migration set；DCM 增加 KSS、OpenSearch 和私有知识模型平面 |
| KSS 契约产物 | 流水线只能人工填写 KSS contract digest | `openapi-contract` 和 `migration-contract` 输出确定性规范字节，并由 golden digest 回归保护 |
| Metadata V2 迁移安全 | `0020`、`0021` 被误列为 expand-only | Blue/Green 失败关闭；显式 maintenance cutover 命令要求停写、停 Worker 和精确备份 Evidence |
| KSS 正式部署边界 | 只有 production-local Compose | 正式 Compose 使用同一不可变 KSS image 启动五角色，并通过外部 mode-`0400` Secret 文件注入凭据 |
| ProofAgent 正式镜像构建 | `deploy/production/Dockerfile` 未复制根目录 `tsconfig.base.json`，`npm run build` 因共享 TypeScript 配置缺失而失败 | 增加构建上下文回归测试和最小 `COPY`；使用三个固定基础镜像摘要完成正式 Dockerfile 构建 |
| ProofAgent Python 依赖冻结 | 正式 Dockerfile 虽复制 `uv.lock`，但 `uv pip install` 重新解析 production extra；同一提交的两次构建得到不同 boto3、botocore 和 pypdf 版本 | 改用 `uv sync --frozen --no-dev --no-editable --extra production`；镜像和 SBOM 中的 boto3、botocore、pypdf 分别固定为 `1.43.47`、`1.43.47`、`6.12.2` |
| 前端 High 漏洞 | 正式 `npm ci` 报告 4 个 High；构建日志定位到 react-router `7.18.0`、postcss `8.5.15` 和 nanoid `3.3.12` | 提升直接依赖安全下限，为传递依赖增加 override，并增加锁文件回归测试；全新正式 `npm ci` 审计 360 个包，结果为 0 个漏洞 |
| CI Python 依赖完整性 | `python` job 在 Linux 缺少 `boto3`，`postgres-integration` job 在测试收集阶段缺少 `openpyxl` 和 `authlib` | 两个 Python job 统一执行 `uv sync --frozen --all-extras`；工作流契约测试、隔离 mypy 和 PostgreSQL 测试收集通过 |
| GitHub Actions 彩色 CLI help | Rich ANSI 样式将 `--option` 拆成多个终端片段，两个 help 测试只在 runner 失败 | help 断言先使用 Click `unstyle` 还原可见文本；模拟 GitHub Actions 环境后测试通过 |
| 历史数据库升级预期 | `0011 → head` 测试仍要求全路径 expand-only，与 Metadata V2 maintenance cutover 决策冲突 | 测试先断言 expand-only 失败关闭，再以专用 `metadata_v2_cutover` 模式完成真实 PostgreSQL 升级 |

## 验证命令

- `.venv/bin/python -m pytest tests/test_release_contracts.py tests/test_release_verifier.py tests/test_release_registry.py tests/test_release_bundle_download.py tests/test_product_release_authority.py tests/test_s3_artifact_store.py -q`：227 passed、1 skipped
- `.venv/bin/python -m pytest tests/ -q`：3224 passed、135 skipped、13 deselected；8 项 loopback 测试在文件沙箱内因禁止绑定本机端口而失败，按相同命令仅放开本机 `127.0.0.1` 后全部通过
- `npm --workspace dashboard test -- --run`：229 passed
- `npm --workspace chat test -- --run`：35 passed
- `npm run typecheck`：passed
- `npm --workspace dashboard run build`：passed
- `docker compose -f deploy/production/knowledge/compose.yaml config --quiet`：passed（使用非 Secret 占位配置完成静态展开）
- `uv lock --check --project services/knowledge-source-service`：34 packages，lock 与项目配置一致
- `uv run --extra dev ruff check proof_agent/release proof_agent/delivery/cli.py proof_agent/contracts/artifacts.py proof_agent/contracts/release_registry.py tests/test_product_release_authority.py tests/test_release_contracts.py tests/test_release_verifier.py tests/test_release_registry.py`
- `uv run --extra dev --extra openai mypy proof_agent`：438 source files passed
- `uv run --extra dev --extra openai mypy --strict services/knowledge-source-service/knowledge_source_service`：77 source files passed
- `docker build --file deploy/production/Dockerfile ...`：passed；本地产物摘要为 `ee6efc7476fd8831be9767c16a3243d2bb220f96548be3df052c9c1b95ee78f2`
- `docker run --rm --entrypoint proof-agent proof-agent:production-candidate-local --help`：passed；Dashboard 与 Operator Chat 静态入口文件存在
- `docker run --rm --entrypoint id <image>`：ProofAgent 与 KSS 均以 `uid=10001`、`gid=10001` 运行
- `.venv/bin/python -m pytest tests/test_production_image_layout.py tests/test_production_compose.py -q`：14 passed
- `npm ci --ignore-scripts --audit=false`：本地冻结安装通过；随后 Dashboard 229 项、Operator Chat 35 项测试、typecheck 和两个 production build 均通过
- `docker buildx build --sbom=true --provenance=mode=max --output type=oci ...`：全新容器内 `npm ci` 审计 360 个包，0 个漏洞；OCI image manifest 为 `sha256:b78778edc39aa4f59a2b1f2f23cfb582fca7c168595c5742a6b0dba2d130966a`
- ProofAgent OCI attestation manifest 为 `sha256:0535024304968b824bcf29e0d48472dac4196e2c8432d50959c3b1ee11a0b20f`，其 subject 绑定上述 image manifest；SPDX SBOM 为 `sha256:46ecac34491741c9d6895c1fd1c56281ca5554c1cefaf8110d9b72be6fe9a7c7`，SLSA v1 Provenance 为 `sha256:7a7a226daf75edaf7630f5e74f4ca9bef375c29b63a87e6d1991636801251084`
- KSS OCI image manifest 为 `sha256:caa5d26c4ae9ba12bc64ad08d8f25f0f733b2c3fcaf430de537738de890e3b28`；attestation manifest 为 `sha256:843e2fb6fe18190f303e18c982609f88f59d9b9edab6a74c46345234fb9e58af`
- 本地 wheel：ProofAgent `sha256:8f55dad68f6053553da72c7552c978b68302bd3500a38215e5312cccb480ebbd`；KSS `sha256:c00161ded217da3725fb7f7451ee16fe381c0aede9e16f399d635b60c4847c1d`
- `docker run --rm proofagent-knowledge-source-service:production-local openapi-contract | shasum -a 256`：`5101269935f2aecaf985f673641a593db58c3afe98f5d6bf38acb33a995b2a7a`
- `docker run --rm proofagent-knowledge-source-service:production-local migration-contract | shasum -a 256`：`707106a66e820852debf617f93ec3086f1e47241e07e9896afb749288bdc8101`
- `docker compose -f deploy/production/slot/compose.yaml config --quiet`：passed（使用绝对配置路径和非 Secret 占位绑定）
- `uv run pytest tests/test_ci_workflow.py -q`：修复前稳定失败；修复后 1 passed
- `uv run --isolated --all-extras mypy proof_agent`：438 source files passed
- `uv run --isolated --all-extras pytest tests/test_postgres_configuration_uow.py tests/test_application_composition.py -m postgres_integration --collect-only -q`：3 tests collected、4 deselected；不再出现依赖导入错误
- `CI=true GITHUB_ACTIONS=true TERM=xterm-256color uv run pytest tests/test_production_migration_job.py::test_production_upgrade_cli_requires_explicit_safety_contract tests/test_release_verifier.py::test_release_verify_cli_help -q`：修复前 2 failed；修复后 2 passed
- `PROOF_AGENT_TEST_POSTGRES_DSN=<disposable-local-postgres> PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1 uv run --all-extras pytest tests/test_postgres_migrations.py::test_upgrade_adopts_released_model_credential_revision -q`：1 passed；一次性 PostgreSQL 16.9 容器已删除

## 未形成的生产证据

[KNOWN | HIGH] 本地 ProofAgent 与 KSS OCI 绑定干净提交 `cc322f9bd2d8a820ee0667e51b99a7da152d1783`，但本次 CI 修复会形成新的候选提交，正式流水线必须从新提交重新生成 Provenance。当前本地 builder identity 为空，SBOM 和 Provenance 未由流水线工作负载身份签名，OCI 也未推送为 registry digest。前端 `npm ci` 已报告 0 个漏洞，但最终镜像漏洞扫描、Secret scan 和 SAST 仍须由正式流水线生成候选绑定 Evidence。企业 OIDC、真实模型评估、容量、队列浸泡、多人浏览器试点、故障恢复、Blue/Green 浸泡、Phase F 四门和正式 Release Bundle 也尚未形成候选绑定 Evidence。当前生产结论仍为 `NO-GO`。
