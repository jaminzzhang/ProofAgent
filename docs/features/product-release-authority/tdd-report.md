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

## 验证命令

- `uv run --extra dev python -m pytest tests/test_release_contracts.py tests/test_release_verifier.py tests/test_release_registry.py tests/test_release_bundle_download.py tests/test_product_release_authority.py tests/test_s3_artifact_store.py -q`
- `uv run --extra dev python -m pytest tests/ -q`：3221 passed、135 skipped、13 deselected
- `npm --workspace dashboard test -- --run`：229 passed
- `npm --workspace dashboard run build`：passed
- `docker compose -f deploy/production/knowledge/compose.yaml config --quiet`：passed（使用非 Secret 占位配置完成静态展开）
- `uv lock --check --project services/knowledge-source-service`：34 packages，lock 与项目配置一致
- `uv run --extra dev ruff check proof_agent/release proof_agent/delivery/cli.py proof_agent/contracts/artifacts.py proof_agent/contracts/release_registry.py tests/test_product_release_authority.py tests/test_release_contracts.py tests/test_release_verifier.py tests/test_release_registry.py`
- `uv run --extra dev --extra openai mypy proof_agent`：438 source files passed
- `uv run --extra dev --extra openai mypy --strict services/knowledge-source-service/knowledge_source_service`：77 source files passed

## 未形成的生产证据

[KNOWN | HIGH] 本次没有构建或扫描真实候选镜像，没有运行企业 OIDC、真实容量、浏览器、故障与恢复演练，也没有执行 Metadata V2 维护窗切换或把正式 Release Bundle 写入生产 S3/Registry。当前分支的精确提交也尚无远端 CI 和独立评审 Evidence。因此当前生产结论仍为 `NO-GO`。
