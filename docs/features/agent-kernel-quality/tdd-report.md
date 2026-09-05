# P0-1A 验收记录

[COMPUTED | HIGH] 切片结论：`LOCAL_VERIFIED`，仅指诊断测量器交付。Agent 能力基线：`needs_review`，五项均未满足；整体质量路线仍在开发。分支：`codex/agent-kernel-quality-baseline`。代码摘要与机器可读测量见 [kernel_baseline.json](evidence/p0-1a/kernel_baseline.json)。

## 范围与测试方法

[KNOWN | HIGH] 新增命令复用 `ExploratoryProbeResult`，检索探针使用现有 `compose_harness_invocation` → `build_controlled_react_orchestrator_for_invocation` → `start`。模型及 KSS 使用固定 synthetic 替身；Policy、Evidence Admission、主循环和答案请求组装使用现有实现。数值校验及会话准入调用现有公共函数。不执行真实网络调用、不访问凭证、不读取环境文件、不写生产状态。

| 编号 | Given / When | Then | 结果 |
|---|---|---|---|
| A1 | 五个完整、严格布尔观测；运行聚合 | 仅全部通过才返回成功 | 通过 |
| A2 | 缺失、重复、额外探针，非布尔/未知事实或执行异常 | 无假通过；其余探针继续；异常不暴露原始消息 | 通过 |
| A3 | 每项事实分别置为 true / false | 对应探针正反例正确判定 | 通过 |
| A4 | 较大金额、负号、数值后缀或未准入摘要 | 不误认为目标金额或已保留约束 | 通过 |
| A5 | 结构化来源缺失、Candidate/Rejected 状态或旧答案输入 | 不认作进入最终答案的已准入事实 | 通过 |
| A6 | 原有单源检索和一轮会话正对照 | 事实经 Admission 进入答案输入；近期约束被保留 | 通过 |
| A7 | 命令在另一工作目录启动、写入失败、运行期间源码变化 | 输出与退出码一致；失败不能成为通过 | 通过 |
| A8 | 默认五个真实内核探针 | 五项均实测；无测量异常；能力不足保持失败 | 通过测量验收，能力未通过 |

## RED → GREEN → REFACTOR

| 步骤 | 实际记录 |
|---|---|
| RED-1 | 新增测量契约测试，因 `evaluation.kernel_baseline` 缺失而失败 |
| GREEN-1 | 完整性、严格布尔、异常脱敏和报告聚合：9 passed |
| RED-2 | 默认入口测试因 `demo.kernel_probes` 缺失失败；接入后序列化问题保持失败，修正 synthetic 输出编码后通过 |
| RED-3 | 命令出口测试因 `run_baseline_check` 缺失失败；实现命令与代码摘要后通过 |
| Review RED | 新负对照复现 `912345.67` 子串误报及缺少会话准入判定：2 failed, 17 passed |
| GREEN / REFACTOR | 完整词项匹配、会话准入、Accepted Evidence 身份与末次答案请求来源检查；格式化新增文件；最终 23 passed |

## 实际验证

工作目录为仓库根目录。测试命令均使用 `PYTHONDONTWRITEBYTECODE=1` 和 `-p no:cacheprovider`。

```bash
.venv/bin/python -m pytest -p no:cacheprovider tests/test_agent_kernel_baseline.py -q
# 23 passed

.venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_agent_kernel_baseline.py tests/test_evaluation*.py \
  tests/test_agent_package_execution.py tests/test_react_intent_resolution.py \
  tests/test_react_planner.py tests/test_react_loop_control.py \
  tests/test_controlled_react_orchestrator.py tests/test_knowledge_source_service_client.py \
  tests/test_model_output_validators.py tests/test_context_assembler.py -q
# 280 passed, 1 skipped

.venv/bin/ruff check proof_agent tests scripts/check-agent-kernel-baseline.py
# All checks passed

.venv/bin/mypy proof_agent
# Success: no issues found in 374 source files

.venv/bin/python scripts/check-agent-kernel-baseline.py \
  --output-dir docs/features/agent-kernel-quality/evidence/p0-1a
# exit 1, needs_review; no probe_execution_error
```

[KNOWN | HIGH] 唯一 skip 是 `tests/test_model_output_validators.py` 已有的 embedded Knowledge fixture；本切片未增加 skip/xfail。五个新探针全部执行。未运行前端构建、真实 LLM、KSS、PostgreSQL、S3 或部署验证，因本切片未修改这些边界，也未声称完成相关验收。

## 能力实测与后续归属

| 探针 | 观测 | 归属 |
|---|---|---|
| 数值校验 | 正确 100 被接受；错误 500 也未被拒绝 | P0-4 |
| 复合检索 | A、B 两个必需查询未全部执行；两个事实未共同进入末次答案输入 | P0-2 |
| 意图改写 | 必需的改写查询未到达 KSS 请求 | P0-3 |
| 结构化事实 | 精确金额未作为已准入事实到达末次答案请求 | P0-3 |
| 长会话约束 | 30 轮后的已准入摘要没有第一轮预算和禁止提交约束 | P1-1 |

[COMPUTED | HIGH] 独立 Review 首轮提出两项 P2：金额子串误报、未准入摘要误报；修复并补回归后复核为 `NO_BLOCKING_FINDINGS`。复核另确认既有 composition 正对照可以观测到已准入事实。该结论不关闭上述五项内核能力缺口。

## 交付与限制

- 实现：`evaluation/kernel_baseline.py`、`evaluation/demo/kernel_probes.py`、固定 KSS JSON fixture、独立命令。
- 验收：新增 23 个测试，五个探针的 JSON、Markdown 和既有 exploratory JSONL 格式结果；更新开发指南、开发进度与项目索引。
- 后续：按路线进入 P0-1B，明确正确回答、合理拒答、任务完成与未评估的口径；然后实现 P0-2 的任务完成条件。
- 本基线是固定回归样本；不代表总体正确率、真实任务完成率、30 轮回答质量或生产准入。格式等值/同义答案仍需后续语义与类型化断言。
