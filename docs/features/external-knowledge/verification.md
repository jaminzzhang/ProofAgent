# 外部知识库切片验收记录

[COMPUTED | HIGH] 2026-09-06，本切片达到 `LOCAL_VERIFIED`：Dify 配置、开发验证/发布、既有 Harness 检索执行和默认 KSS 依赖退役的本地验收通过。该状态不代表真实 Dify 联调、总体回答准确率或 Production GO。

- 分支：`codex/agent-kernel-quality-baseline`；实现起点：`9c29c68`。
- 范围与决策：[scope-plan.md](scope-plan.md)、[ADR-0242](../../adr/0242-replace-kss-runtime-coupling-with-external-knowledge.md)。
- 使用说明：[configuration.md](configuration.md)。所有请求、凭证和响应测试均使用合成数据。

## 验收矩阵

| 能力与边界 | 已验证行为 | 主要证据 |
|---|---|---|
| 外部绑定契约 | Dify、HTTPS endpoint、精确 Dataset、版本化 Secret Handle、检索参数严格校验；最多 5 个绑定；拒绝未知字段、原始 Key 和范围越界 | `tests/test_dify_knowledge.py`；`tests/test_config_loader.py` |
| 只读 Dify 适配器 | 精确 Dataset POST；原样 query；保留文本及 Q&A 答案、文档和分段身份；校验内容摘要 | `test_dify_query_uses_exact_configured_dataset_and_returns_candidate_facts`；Q&A、query、document、duplicate、empty-content 用例 |
| 凭证与出站 | 控制字符凭证不进入 HTTP；使用既有 Guarded HTTP/Secret Provider；拒绝未授权 origin；不重定向、不自动重试 | 适配器和 `test_guarded_adapter_never_follows_redirect_or_retries`；完整 guarded transport 回归 |
| 外部失败 | 401/403/404/429/5xx、损坏/过大/深层 JSON、错查询、身份冲突、非法分数返回稳定错误，不回显原始内容 | 参数化 HTTP、body、score、provenance 用例 |
| 控制面准入 | 策略拒绝时不查询；低分、禁用、缺少可用状态和空结果不能满足 required retrieval；高相关性分数不绕过门控 | `test_unadmitted_dify_results_cannot_complete_required_retrieval` 的 5 类场景 |
| 同一内核执行 | Dify 经过现有 Controlled ReAct/Harness；两个 required 查询均执行，改写后的 query 到达实际适配器，Accepted Evidence 进入答案及 bound truth | `test_external_binding_loads_and_answers_through_existing_harness`；[内核基线](baseline/kernel_baseline.md) |
| 配置冻结 | GET/PATCH → revision CAS → 草稿验证 → 开发发布；运行时 endpoint、Dataset、threshold、凭证引用或绑定缺失的漂移均在 HTTP 前拒绝 | `test_external_configuration_round_trip_validation_and_publication`；`test_published_binding_drift_fails_before_http` |
| 可变 Dataset | 同一分段的新内容产生新摘要；记录观测时间和 `mutable_remote`，不伪造 KSS Release 或全库快照 | `test_mutable_dataset_keeps_distinct_observed_content_digests`；既有 Observation Truth/恢复回归 |
| Dashboard | 保存、删除绑定、空状态、读取失败、校验错误、409 冲突、草稿重载和跨草稿切换；相同 revision 的不同草稿不复用旧绑定；无 Key 输入框、无默认 KSS workspace 请求 | `AgentDetailPage.test.tsx`、`KnowledgePage.test.tsx`、`client.test.ts` |
| 配置错误与权限 | 无编辑权限不可写入；深层 JSON 拒绝且 revision 不变；非法 YAML 错误不回显粘贴 Key | `test_knowledge_config_requires_edit_permission`、`test_deeply_nested_configuration_is_rejected_without_draft_change`、`test_invalid_yaml_does_not_echo_a_pasted_api_key` |
| 历史 KSS 退役 | 旧绑定仍可解析为历史对象，但不能新装配、入队、执行或回滚激活；这些失败不触发旧 catalog 或 executor | `test_production_agent_readiness.py`、`test_run_execution_service.py`、`test_agent_configuration_workspace.py` |
| 默认启动与部署 | API/Executor 不默认装配 KSS；Compose、网关、DCM v2 移除 KSS 专属角色；核心身份、持久化及出站控制保留 | `test_production_roles.py`、`test_production_migration_job.py`、`test_kss_project_isolation.py`；Compose 静态校验 |
| 发布与回滚 | 保留版本不可变、指针并发检查和审计事务断言；外部正式生产发布 profile 未完成时入口明确关闭 | Workspace、publication、readiness 全量回归；生产边界见下文 |

## TDD 与独立复核

[COMPUTED | HIGH] 按外部绑定/适配器、控制面执行、配置接口、Dashboard、默认启动的顺序补充可观察行为测试，再完成实现。旧 KSS“必须可执行”的断言按用户新决定替换为“历史可读、执行退役”的断言；外部运行正向行为由真实适配器与 Harness、草稿验证/发布测试覆盖。回滚并发、不可变版本、审计和错误原子性断言保留。本次没有新增 skip、xfail 或 deselect 来规避失败。

[COMPUTED | HIGH] 复核发现并关闭了以下问题：缺失分段状态的默认放行、非法 Q&A answer 类型被静默忽略、深层 JSON 异常、历史 KSS 版本就绪与入队不一致、跨草稿配置缓存复用及配置请求错误脱敏。独立复核结论为 `NO_BLOCKING_FINDINGS`。之后另以 RED 用例复现了非法 YAML 错误包含原始片段的问题，移除异常正文插值后完成针对性及全量后端回归。

## 最终检查

| 命令 | 实际结果 |
|---|---|
| `.venv/bin/pytest -q tests/` | **2447 passed, 108 skipped, 2 deselected**；1 项既有 Authlib 弃用警告；33.49 秒 |
| `.venv/bin/pytest -q tests/test_dify_knowledge.py tests/test_config_loader.py tests/test_agent_configuration_api.py` | **192 passed, 4 skipped**；覆盖最后一次 YAML 脱敏变更 |
| `npm run test:dashboard` | **225 passed，32 个文件** |
| `npm run test:chat` | **35 passed，14 个文件** |
| `.venv/bin/ruff check proof_agent tests` | 通过 |
| `.venv/bin/mypy proof_agent` | 通过，382 个源文件 |
| `npm run typecheck` | 通过；应用 TypeScript 检查同时由 build 的 `tsc -b` 覆盖 |
| `npm run build` | UI、Dashboard、Chat 构建通过 |
| `uv lock --check --offline` | 通过，114 个包；未变更依赖锁文件 |
| `.venv/bin/python scripts/check-domain-contexts.py` | 通过 |
| `sh -n scripts/production-local-up.sh scripts/production-local-prepare.sh scripts/production-local-verify.sh` | 通过 |
| `docker compose --env-file /dev/null -f docker-compose.production-local.yml config --no-interpolate --quiet` | 通过；仅检查拓扑语法，不读取 `.env`，不启动服务 |
| `git diff --check` | 通过 |

完整后端检查在允许 loopback 绑定的环境中执行。108 项 skip 和 2 项 deselect 未计入通过项；它们不提供本切片的真实依赖或上线证据。检查过程中发现旧 KSS 镜像测试会进入已变更的启动脚本，已替换为静态拓扑断言；该次调用在 Compose 校验阶段失败，未到服务启动。随后修正空 environment 映射，并使用上述静态命令复验。

## 内核质量基线与剩余工作

[COMPUTED | HIGH] 执行 `.venv/bin/python scripts/check-agent-kernel-baseline.py --output-dir docs/features/external-knowledge/baseline`，得到 `needs_review`（退出码 1，符合未完成质量项的含义）。[报告](baseline/kernel_baseline.md)、[结构化结果](baseline/kernel_baseline.json)与当前内核源代码指纹一致。

- 多查询完成、问题改写两项为 `passed_with_diagnostics`。为保留历史指标对照，`intent_rewrite_reaches_kss` 指标 ID 暂未改名；本次实际调用已迁移到合成 HTTP 支撑的 Dify 适配器，没有执行 KSS 请求。
- 数值回答核验、结构化事实进入答案、长对话约束保留三项仍为 `needs_review`。不因接入新知识库而标为解决，也不将固定问题集的通过率当作总体解答率。

[KNOWN | HIGH] 以下工作尚未验收：

1. **真实 Dify 联调**：实际部署版本、Dataset 索引设置、命中/空结果/权限失败、引用准确性、时延与代表性问题集。需要部署方配置服务端凭证及网络许可；本次未读取真实 Key、未查询真实 Dataset。
2. **外部知识库正式生产发布 profile**：需为外部绑定建立独立的正式发布和生产就绪证据。现有 KSS Release/Grant/Reference 证据不再适用，当前正式发布保持关闭。
3. **更多 provider 与高级检索**：本次只实现 Dify 只读适配器；其他知识库、hybrid/reranking、metadata filter、远端写操作尚未实现。
4. **既有生产环境迁移**：本次只变更默认代码和拓扑，未修改既有生产数据库、活动出站策略或密钥，也未执行部署。DCM v2 和新 egress fixture 不会自动迁移原有活动记录。

[FRAME | HIGH] 下一知识库切片先完成 provider-neutral 的正式发布与就绪路径，再使用真实 Dify 配置进行独立验收；Agent 内核原有三项质量缺口继续按既定优先级交付。

## 主要变更路径

- 外部接口与适配器：`proof_agent/contracts/external_knowledge.py`、`contracts/ports/external_knowledge.py`、`capabilities/knowledge/dify.py`、`bootstrap/external_knowledge.py`。
- 内核接入：`bootstrap/composition.py`、`control/knowledge/retrieval_service.py`、`control/workflow/controlled_react/`、`evaluation/demo/kernel_probes.py`。
- 配置与发布边界：`delivery/external_knowledge_configuration.py`、`delivery/agent_configuration_validation.py`、`configuration/local_store.py`、`control/agent_configuration_workspace.py`、`delivery/run_submission_service.py`、`delivery/run_execution_service.py`。
- UI 与部署：`dashboard/src/components/agent/KnowledgeModuleEditor.tsx`、`dashboard/src/pages/AgentDetailPage.tsx`、`dashboard/src/pages/KnowledgePage.tsx`、`docker-compose.production-local.yml`、`docker/production-local/`、`scripts/production-local-*.sh`。
