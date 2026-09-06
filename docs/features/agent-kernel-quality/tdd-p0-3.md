# P0-3：结构化证据到答案验收

[COMPUTED | HIGH] 2026-09-06，本切片本地验收通过：`LOCAL_VERIFIED`。结构化证据已通过真实 Dify 适配器和既有 Harness 到达首次答案及格式修复输入，保留类型、精确值、单位与来源。Agent 内核整体仍为 `PARTIAL_VERIFICATION`，不代表答案语义正确率、真实 Dify 验收或 Production GO。

- 起点：`main` 的 `7ac84c7`；开发分支：`codex/kernel-p0-3-structured-evidence`。
- 范围：[scope-p0-3.md](scope-p0-3.md)；接口决策：[ADR-0243](../../adr/0243-preserve-typed-external-evidence-through-answer-input.md)。
- 配置：[Dify 结构化分段说明](../external-knowledge/configuration.md#结构化分段p0-3)。
- 使用合成模型响应、合成 Dify HTTP 响应及测试私有文件存储；没有查询真实 Dataset、读取真实 Key 或执行生产状态变更。

## 验收矩阵

| 场景 | 验证结果 | 主要证据 |
|---|---|---|
| 精确数值与类型 | `12345.6700` 保留小数末尾零与 CNY；大于 JavaScript 安全整数范围的整数无浮点转换；false 与 null 保持类型；序列化往返一致 | `test_dify_structured_record_preserves_exact_values_without_admitting_them` |
| 非法字段与边界 | 拒绝 decimal 浮点数、NaN/Infinity、指数/空白表示和长度越界；拒绝整数/布尔/字符串/null 错配、非法日期和无时区时间 | 参数化 `test_mistyped_or_unbounded_fields_fail_without_text_fallback` |
| 结构契约 | 重复字段、重复 JSON 键、未知属性/版本、缺失版本、空字段集、字段超限及混合 Q&A 均拒绝 | 参数化 `test_ambiguous_structured_content_fails_closed` |
| 显式模式 | 普通文本即使包含合法 JSON 也不自动生成 typed facts；控制面拒绝 Provider 与冻结 content_format 的双向漂移 | `test_text_mode_never_promotes_json_into_structured_evidence`；`test_control_plane_rejects_provider_format_drift` |
| 原始约束与改写 | 原问题的年份、币种和禁止转换约束进入答案请求；必需改写 query 实际到达 Dify | `test_real_harness_preserves_typed_facts_original_constraints_and_required_rewrite` |
| 初次与修复输入 | 上述真实 Harness 用例确实产生 2 次答案请求，第二次为 repair_attempt=1；两次的 typed record、来源、内容摘要及 citation 对应同一 Accepted Evidence | 同上；共用 `answer_evidence_records` |
| 准入与冲突 | 低分、空结果、禁用、未知可用状态和策略拒绝在 text/structured_json 两种模式下都不能完成 required retrieval；不同来源的同名字段保留为独立记录；候选和拒绝内容不进入答案 | `test_dify_knowledge.py` 的 10 个不准入场景；`test_answer_input_keeps_conflicting_records_separate_and_excludes_unadmitted_data` |
| 答案准备边界 | 首次与后续修复仅携带已准入记录和引用集合，不能因调用方混入 Candidate 而泄漏其身份 | `test_answer_attempt_prepares_only_accepted_records_for_later_repair` |
| 篡改 | 内容、typed record、单位、引用、版本摘要、document、binding、Dataset、segment 任一不一致均在答案输入前拒绝 | 参数化 `test_tampered_typed_evidence_is_rejected_before_answer_input` |
| 持久化与恢复 | 新建文件适配器重载后金额类型与单位不变；内部一致的替换内容仍不能复用旧 Truth reference；恢复执行不重查已完成来源，不重做 Intent | `test_stored_truth_reconstruction_preserves_types_and_rejects_rebound_content`；`test_file_snapshot_resume_preserves_original_requirements_and_truth[True]` |
| 历史兼容 | 可选 typed 字段为 None、模式为 text 时不改变旧序列化；旧文本 Truth reference 可往返验证；独立比较旧/新 Evidence、Candidate、Binding 规范字节一致 | `test_legacy_text_serialization_does_not_change_existing_bound_truth`；独立复核 |
| 配置与冻结 | text 和 structured_json 均完成 GET/PATCH → revision CAS → 验证 → 开发发布；content_format 漂移在 HTTP 前拒绝 | `test_external_configuration_round_trip_validation_and_publication`；`test_published_binding_drift_fails_before_http[content_format]` |
| Dashboard | 默认文本，明确选择类型化 JSON，展示完整分段约束，按当前 revision 保存；旧配置保存及跨草稿隔离回归通过 | `AgentDetailPage.test.tsx` 的格式选择用例及完整 Dashboard 测试 |

## TDD 与复核过程

[COMPUTED | HIGH] 首个适配器用例在新增 content_format 前失败，接口与基础传递实现后转绿。第二轮类型/边界组实际出现 19 个行为失败，关闭类型转换、重复键、缺失版本和 Q&A 混合路径后通过。真实 Harness 用例随后复现 EvidenceChunk 丢失 typed 数据，完成准入至答案投影后通过。Dashboard 新用例先因不存在格式选项失败，实现后通过。

[COMPUTED | HIGH] 篡改用例与独立 Review 确认 source URI 和 document 身份未一致校验；补齐 binding、Dataset、document、segment 对应关系后关闭。复核还通过公开 SourceSet 端口复现 Provider 格式漂移可进入准入；现在控制面显式拒绝两种方向的漂移。格式修复前的混合输入另以 RED 用例暴露，prepare 统一收敛到 Accepted tuple 后通过。

[KNOWN | HIGH] 开发期间两处测试构造失败（既有 FrozenDict 不能直接 model_dump_json、Truth fixture 缺 `/truth`）已改用正式 artifact 投影和合法 reference。Provider 漂移测试的一次错误调用签名也已修正；这些错误未计为产品缺陷或有效 RED 证据。

[COMPUTED | HIGH] hicode 独立复核最终结论：`NO_BLOCKING_FINDINGS`。其独立执行结果为结构化专项 44 项、恢复相关 4 项、配置发布与冻结 8 项通过；并比较了 `git show 7ac84c7` 中旧模型与当前模型的合成对象规范序列化。没有删除测试、降低断言或新增 skip/xfail 来获得通过。

## 最终检查

| 检查 | 实际结果 |
|---|---|
| `.venv/bin/pytest -q tests/test_structured_evidence.py tests/test_dify_knowledge.py tests/test_retrieval_task_completion.py` | **163 passed** |
| `.venv/bin/pytest -q tests/` | **2499 passed, 108 skipped, 2 deselected**；34.07 秒；1 项既有 Authlib 弃用警告 |
| `npm run test:dashboard` | **226 passed，32 个文件** |
| `npm run test:chat` | **35 passed，14 个文件** |
| `.venv/bin/ruff check proof_agent tests` | 通过 |
| `.venv/bin/mypy proof_agent` | 通过，384 个源文件 |
| `npm run typecheck`；`npm run build -w @proofagent/ui` | 通过 |
| `npm run build -w proof-agent-dashboard -- --outDir /tmp/proofagent-p0-3-build/dashboard` | TypeScript 与 Vite 构建通过 |
| `npm run build -w proof-agent-chat -- --outDir /tmp/proofagent-p0-3-build/chat` | TypeScript 与 Vite 构建通过；保留既有 chunk 大小提示 |
| `uv lock --check --offline` | 通过，114 个包；无依赖变更 |
| `.venv/bin/python scripts/check-domain-contexts.py` | 通过 |
| `git diff --check` | 通过 |

完整后端测试在允许 loopback 的本地环境中执行；108 项跳过与 2 项排除未计为通过。本次比 `7ac84c7` 增加 52 个后端执行用例和 1 个 Dashboard 用例。前端构建输出到临时目录，未替换用户正在使用的验证页面；既有本地验证服务未重启。

## 内核基线与边界

[COMPUTED | HIGH] 执行：

```bash
.venv/bin/python scripts/check-agent-kernel-baseline.py \
  --output-dir docs/features/agent-kernel-quality/evidence/p0-3/kernel-baseline
```

[报告](evidence/p0-3/kernel-baseline/kernel_baseline.md)与[结构化结果](evidence/p0-3/kernel-baseline/kernel_baseline.json)绑定当前源码指纹。实际结果：

- 多查询完成、必需改写到达提供者、结构化事实进入答案三项为 `passed_with_diagnostics`。
- 数值答案核验和长对话约束两项仍为 `needs_review`；整体命令退出 1，无测量基础设施错误。
- 原改写指标 ID `intent_rewrite_reaches_kss` 为历史对照保留，实际执行使用 Dify。结构化来源身份按 ADR-0242 使用实际 Dataset/文档/分段与内容摘要；不伪造旧 KSS source/Release。

[KNOWN | HIGH] 尚未验证真实 Dify 的分段配置、索引、召回或时延；没有启用外部知识库正式生产发布。结构化内容必须由来源显式提供完整记录，本切片不从自然语言推断类型、不跨段拼表、不计算聚合或转换单位。字段来源保真不能证明模型最终数值或推导正确；P0-4 继续承担这一缺口，P1-1 承担长对话状态。

## 主要实现路径

- `proof_agent/contracts/structured_evidence.py`：类型化记录及严格内容解析。
- `proof_agent/contracts/external_knowledge.py`、`evidence.py`：冻结内容模式、结构化字段和来源一致性。
- `proof_agent/capabilities/knowledge/dify.py`、`control/knowledge/retrieval_service.py`：显式解析、模式校验与既有准入路径。
- `proof_agent/control/knowledge/answer_evidence.py`、`control/workflow/harness_helpers.py`、`control/workflow/controlled_react/final_answer_attempt.py`：首次与修复共享投影。
- `proof_agent/capabilities/models/deterministic.py`：读取新的证据记录格式，保持离线演示行为。
- `dashboard/src/components/agent/KnowledgeModuleEditor.tsx`：格式配置及说明。
- `proof_agent/evaluation/demo/kernel_probes.py` 与新 fixture：通过真实适配器测量 typed 事实传递。
