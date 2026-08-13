# Product Release Authority TDD Report

## 结论

[COMPUTED | HIGH] `initial-private-pilot-v2`、Gate 计算、Manifest 组装、精确
Evidence/attestation 存储、工作负载身份签名校验及四个 Release CLI 动作已通过
本地验证。状态为 `VERIFIED_LOCAL`，不等于生产发布批准。

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

## 验证命令

- `uv run --extra dev python -m pytest tests/test_release_contracts.py tests/test_release_verifier.py tests/test_release_registry.py tests/test_release_bundle_download.py tests/test_product_release_authority.py tests/test_s3_artifact_store.py -q`
- `uv run --extra dev python -m pytest tests/ -q`：3197 passed、134 skipped、13 deselected
- `uv run --extra dev ruff check proof_agent/release proof_agent/delivery/cli.py proof_agent/contracts/artifacts.py proof_agent/contracts/release_registry.py tests/test_product_release_authority.py tests/test_release_contracts.py tests/test_release_verifier.py tests/test_release_registry.py`
- `uv run --extra dev --extra openai mypy proof_agent`

## 未形成的生产证据

[KNOWN | HIGH] 本次没有构建或扫描真实候选镜像，没有运行真实 Blue/Green、容量、
浏览器、故障与恢复演练，也没有把正式 Release Bundle 写入生产 S3/Registry。
因此当前生产结论仍为 `NO-GO`。
