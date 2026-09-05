# P0-1B 验收记录

[COMPUTED | HIGH] 切片结论：`LOCAL_VERIFIED`。质量评估口径、证据完整性检查和报告投影已完成本地验收；整体 Agent 内核路线仍为 `PARTIAL_VERIFICATION`。新增 49 项测试；受影响回归 329 passed、1 个既有 skip。独立 Review：`NO_BLOCKING_FINDINGS`。本切片未修复五项内核能力缺口，也不构成生产准入。

范围见 [scope-p0-1b.md](scope-p0-1b.md)，公共契约决策见 [ADR-0240](../../adr/0240-separate-verified-quality-from-governed-resolution.md)。分支：`codex/agent-kernel-quality-baseline`；验收日期：2026-09-05。P0-1A 的历史产物保持不变。

## 实现与判定顺序

[KNOWN | HIGH] 复用现有 `analyze_evaluation`、Gate evaluator 和 artifact writer。新增 `contracts/evaluation_quality.py` 与 `evaluation/quality.py`；不新增 Agent 执行器、judge 输入、网络依赖、存储权威或生产配置。`judge_mode=none`，GRR、Gate Profile 和 Release Decision 保留原有治理含义。

1. 从严格标签或一致的旧 expected resolution/outcome 确定质量目标；任务必须显式标注。未分类 required case 单独计数。
2. 验证 subject、同一份原始字节的摘要、最后 `final_output` 的结果及 Trace/Receipt/metadata 一致性。缺失、不可信或不完整记录先判为 `not_evaluated`。
3. 在可信完整记录上，错误 outcome 或必需确定性 Gate 失败为 `failed`。答案语义、任务结果未实施正向验证，因此治理通过仍为 `not_evaluated`。
4. 拒答只可通过「与人工维护的拒答决策标签匹配」这一狭义判定；有待评业务语义时仍未评估。此结果不证明拒答措辞正确或知识库确实不存在答案。
5. 三个 cohort 分别报告总数、通过、失败、未评估及覆盖率。仅 required standalone case 纳入分母；明细显式记录是否纳入统计。

## 逐项验收

行为测试：[test_evaluation_quality.py](../../../tests/test_evaluation_quality.py)。契约测试：[test_evaluation_quality_contracts.py](../../../tests/test_evaluation_quality_contracts.py)。表中每项均已通过。

| 编号 | Given / When | Then / 验收结果 |
|---|---|---|
| B01 分类 | 一致旧标签、显式任务标签、矛盾或拼错标签 | 回答/拒答自动分类；任务显式分类；未知或冲突字段拒绝；无法推断的旧样本保留未分类计数 |
| B02 回答 | 治理、引用、词项检查通过；有或没有语义声明 | GRR 可为 1，答案质量仍未评估；诊断性 PASSED 不升级质量 |
| B03 拒答 | 同一拒答分别对应拒答 gold、应答 gold；拒答 gold 对应实际应答 | 分别为狭义拒答决策通过、应答失败、拒答失败；不混入回答正确率 |
| B04 语义声明 | 拒答声明 required business claims 或 forbidden categories | 语义未评估，不能判为通过；expected 中拼错声明字段被拒绝 |
| B05 任务 | 显式任务返回应答，或已记录成功工具结果 | 均未证明完成，返回 `task_completion_not_evaluated` |
| B06 完整性 | 无摘要、摘要不符、文件/inline response 摘要不符 | 即使 outcome 明确不匹配，也先判未评估，避免用不可信记录证明失败 |
| B07 同一快照 | 文件边界返回的内容与磁盘另一版本不同 | 解析、Gate、结果摘要绑定同一 bytes；不能用另一版本的哈希为内容背书；CRLF 摘要按原始字节正确处理 |
| B08 完成事实 | 缺 final_output、最后 final_output 空结果、Receipt 或 metadata 冲突 | 未评估；旧有效事件或 metadata 不能补足质量完成证明 |
| B09 恢复 | 首个已映射 Trace 缺失或损坏，后一个完整 | 首个治理失败且质量未评估；后一个继续分析；正式治理结果 blocked；不输出原始异常内容 |
| B10 分母 | 拒答 cohort 通过、失败、缺 subject 各 1 个 | total=3；成功比例 1/3、覆盖率 2/3；缺失样本不消失 |
| B11 空与未分类 | 空 cohort、全部未评估、矛盾旧标签 | 空分母为 null；全部未评估时两项比例均为 0；未分类计数补齐 required 总数 |
| B12 重复权重 | optional case、extra subject、scenario 重复引用 | 不扩大分母；optional/scenario 明细明确 `included_in_cohort=false` / outside cohort |
| B13 公共契约 | 负数、布尔计数/比例、NaN/Inf、错误和式/比例、未知字段、矛盾状态/原因 | 严格拒绝；有效结果 JSON 往返一致且不可变 |
| B14 历史兼容 | 旧结果与 summary 无质量字段 | 质量及统计标记保持 null；writer 明确未评估，不推断通过 |
| B15 产物一致 | 同一 summary 写 JSONL、质量 JSON、Markdown、Receipt | 分母、状态、原因一致；包含版本与范围；不复制响应正文 |

## RED → GREEN → REFACTOR 与 Review

| 阶段 | 实际证据 |
|---|---|
| 首轮行为 | 10 项分类、拒答正反例、任务未评估、分母及损坏样本检查通过 |
| Review P1 RED | 两个测试复现「解析/验哈希重读」及「metadata 补足缺失 Trace outcome」：2 failed、10 passed |
| P1 GREEN | 同一 bytes 快照与最后完成事件检查落地：12 passed |
| 报告与严格标签 RED | 缺少质量 JSON、expected 拼错语义字段未拒绝；同轮另有 inline fixture 缺 sensitivity，被既有规则正确拦截：3 failed、26 passed |
| 报告 GREEN | 实现 JSON/Markdown/Receipt 投影，严格 expected；修正 fixture：29 passed |
| 契约 RED → GREEN | 矛盾状态/原因和布尔比例：7 failed、11 passed → 18 passed |
| Review P2 RED → GREEN | optional 明细缺统计排除标记：1 failed、28 deselected → 该测试通过；三种报告均有明确标记 |
| 最终补测与整理 | 工具成功不证明任务完成、历史 writer 不升级质量；行为 31 项 + 契约 18 项；Ruff 格式整理与 Mypy 类型修正 |

[COMPUTED | HIGH] 独立 Review 两项 P1、一项 P2 均已关闭，最终建议为 `NO_BLOCKING_FINDINGS`。复审确认无剩余已发现的质量错误放行问题；该结论仅覆盖本切片和本地证据。没有降低旧断言、删除测试或新增 skip/xfail。

## 实际验证

工作目录为仓库根目录。Python 测试使用 `PYTHONDONTWRITEBYTECODE=1`；没有读取 `.env` 或调用真实模型、KSS、数据库、对象存储。

```bash
.venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_evaluation_quality.py tests/test_evaluation_quality_contracts.py -q
# 49 passed（31 项行为 + 18 项契约；亦包含于下述回归）

.venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_agent_kernel_baseline.py tests/test_evaluation*.py \
  tests/test_agent_package_execution.py tests/test_react_intent_resolution.py \
  tests/test_react_planner.py tests/test_react_loop_control.py \
  tests/test_controlled_react_orchestrator.py tests/test_knowledge_source_service_client.py \
  tests/test_model_output_validators.py tests/test_context_assembler.py -q
# 329 passed, 1 skipped

.venv/bin/ruff check proof_agent tests scripts/check-agent-kernel-baseline.py
# All checks passed

.venv/bin/mypy proof_agent
# Success: no issues found in 376 source files

.venv/bin/python scripts/check-domain-contexts.py
# exit 0

git diff --check
# exit 0

.venv/bin/python scripts/check-agent-kernel-baseline.py \
  --output-dir docs/features/agent-kernel-quality/evidence/p0-1b/kernel-baseline
# exit 1, needs_review；五个探针全部运行，无 probe_execution_error
```

[KNOWN | HIGH] 唯一 skip 是已有 `test_model_output_validators.py` 的 embedded Knowledge fixture。未运行前端构建或真实依赖、部署、发布验证；本切片未修改这些边界。新代码只产生本地评估投影，不能代表答案总体正确率或生产发布证据。

[KNOWN | HIGH] 文档上下文与差异检查均通过。另已核对本记录的相对链接、当前源码与探针摘要一致、固定样例的统计纳入标记与分母一致，以及生成报告没有复制 synthetic 响应正文。

## 可复现产物

- [固定 synthetic Suite](evidence/p0-1b/inputs/suite.yaml) 与 [摘要绑定的 Subjects](evidence/p0-1b/inputs/subjects.yaml)。这组样本用于检验测量口径，不是业务质量样本。
- [质量 JSON](evidence/p0-1b/analysis/p0-1b-synthetic-fixed-artifacts/evaluation_quality.json)、[报告](evidence/p0-1b/analysis/p0-1b-synthetic-fixed-artifacts/evaluation_report.md)、[分析 Receipt](evidence/p0-1b/analysis/p0-1b-synthetic-fixed-artifacts/evaluation_analysis_receipt.md)。required 总计 6、未分类 1；拒答 3 项中通过/失败/未评估各 1；答案和任务各 1 项未评估；另有 1 项 optional 明确排除。治理 Release Decision 为 blocked，符合缺失与错误样本的预期。
- [当前源码内核探针结果](evidence/p0-1b/kernel-baseline/kernel_baseline.json) 与 [可读报告](evidence/p0-1b/kernel-baseline/kernel_baseline.md)。五项仍 `needs_review`，源码摘要记录在 JSON 中。

重新分析固定样本，输出到临时目录：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from pathlib import Path
from proof_agent.evaluation.analyzer import analyze_evaluation
inputs = Path('docs/features/agent-kernel-quality/evidence/p0-1b/inputs')
summary = analyze_evaluation(
    suite_path=inputs / 'suite.yaml', subjects_path=inputs / 'subjects.yaml',
    output_dir=Path('/tmp/proofagent-p0-1b-acceptance'),
)
print(summary.quality_metrics.model_dump_json(indent=2))
print(summary.release_decision.status.value)
PY
```

## 限制与下一切片

[KNOWN | HIGH] 正向答案语义和任务完成核验仍未实现。人工维护的 gold 标签本身需要业务审查；字节摘要只证明本次使用的内容与声明一致。既有 GRR 的 metadata 回退逻辑为兼容而保留，新增质量判定不采纳这种完成推断。未知 case/expected 字段现在显式拒绝，旧套件若含曾被忽略的字段，需要修正拼写或删除不支持的字段。

[FRAME | HIGH] 下一切片为 P0-2：建立任务要求与完成条件，修复复合任务在首个检索结果后过早结束的问题；预算耗尽必须输出明确未完成原因。答案语义与关键数值留在 P0-4，真实服务和生产准入仍需各自证据。
