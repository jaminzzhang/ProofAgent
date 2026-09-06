# P0-4：事实一致性与有界修复验收

[COMPUTED | HIGH] 2026-09-06，本切片的有界事实一致性与修复范围为 `LOCAL_VERIFIED`。65 项新增事实专项通过，完整后端 2564 项通过；独立 Review 为 `NO_BLOCKING_FINDINGS`。内核整体保持 `PARTIAL_VERIFICATION`，通用语义、真实模型/Dify 与生产验证未完成。

- 起点：`main` 的 `1bdd92a`；工作分支：`codex/p0-4-answer-fact-validation`。
- 设计版本：[scope-p0-4.md](scope-p0-4.md) v1；主计划：[scope-plan.md](scope-plan.md) 当前交付树；决策：[ADR-0244](../../adr/0244-validate-bounded-answer-facts-before-admission.md)。
- 使用合成模型、合成 Dify HTTP 响应与临时本地存储。未读取真实凭证、环境文件或用户验证数据；未重启本地服务，未提交、合并或推送。

## 设计树执行快照

```text
P0-2 必需检索完成 → P0-3 Accepted Evidence + 最终答案
  P0-4 / FACT_CHECK [已验证：A1/A2]
    通过 → P0-4 / ADMIT [已验证：A3/A4]
    失败 → P0-4 / REPAIR [已验证：A3]
      一次逻辑修复 → 全部校验 → 交付或安全拒绝
      策略/预算拒绝 → POLICY_DENIED
P1-1 长对话任务状态 [待执行]
```

| 验收 | 开始 → 结束 | 实际行为与证据 |
|---|---|---|
| A1 / FACT_CHECK | 执行中 → 已验证 | 固定 100/500 对照；精确小数、大整数、单位/主体/字段互换、未引用/未准入来源拒绝；`test_answer_fact_validation.py` |
| A2 / FACT_CHECK | 待验证 → 已验证 | 肯定/否定、条件删除、枚举、false/null、字符串与数字、大小写单位、数学符号、typed 字段名分隔冲突、完整性和输入上限；诊断只有代码/计数；同文件 |
| A3 / REPAIR → ADMIT | 待验证 → 已验证 | 真实 FinalAnswerAttemptRunner 和 PolicyEngine：错误 500 修复为 100；仍错则拒绝；token 估算超策略上限则拒绝调用；混合 schema/safety 不修复；修复答案仍须通过 safety |
| A4 / 集成 | 待验证 → 已验证 | Dify 配置验证与开发发布、P0-2 检索与恢复、P0-3 typed 输入回归、完整后端与独立基线；见下表 |

## TDD 与独立复核

[COMPUTED | HIGH] 第一轮先运行 20 个正反例，得到 **14 failed、6 passed**：合法引用下的错误数值、单位、主体、条件和极性未被拦截。新增 Control Plane validator 并接入原答案链路后通过。

[COMPUTED | HIGH] 后续每组已确认反例均先复现，再修复：比较/币种符号丢失；NFKC 压平指数；单位大小写被折叠；主体/枚举中的数字被归一化；`1+2` 被拼接为 `12`；typed string 被视为数字；字段名中的英文/中文分隔符绕过字面值比较。最终采用精确主体、独立数量 token、非数值 typed 字面值和已知字段前缀优先解析。没有增加计算器或自由语义判定。

[KNOWN | HIGH] 一次测试夹具将 `record_id=is` 的 qualified `approved` 与 unqualified `is approved` 构造成同一主体。该输入有冲突；保留拒绝用例，并使用无冲突的记录名验证正常解析，没有放宽实现。

[COMPUTED | HIGH] 独立 Review 还发现去列表前缀的跨行空白可能重复回溯；改为行内空白后，独立公开入口对 99,000 个换行的测量为约 0.003 秒。这是单次本地诊断，不是延迟 SLA。独立复验事实及模型输出测试 **75 passed、1 skipped**，最终 `NO_BLOCKING_FINDINGS`；未发现新的修复、策略、准入或诊断泄漏问题。

## 检查结果

| 命令 | 实际结果 |
|---|---|
| `.venv/bin/python -m pytest tests/test_answer_fact_validation.py -q` | **65 passed**，含最后补充的混合 schema/safety 和修复后 safety 分支 |
| `.venv/bin/python -m pytest tests/ -q` | **2564 passed、108 skipped、2 deselected**，33.84 秒；1 项既有 Authlib 弃用警告 |
| `.venv/bin/ruff check proof_agent tests` | 通过 |
| `.venv/bin/mypy proof_agent` | 通过，385 个源文件 |
| `uv lock --check --offline` | 通过，114 个包；无依赖变更 |
| `python3 scripts/check-domain-contexts.py` | 通过 |
| `git diff --check` | 通过 |

[KNOWN | HIGH] 首次完整回归的 12 项失败中，8 项来自沙箱禁止回环端口绑定，3 项来自确定性模型旧模板，1 项为旧验证器集合断言。模型适配器现在保留数值来源措辞并读取 typed/repair records；原引用测试新增事实校验失败预期，保留其余断言。完整后端随后在允许回环绑定的环境中通过。`uv` 在沙箱内先遇缓存权限及 macOS 系统配置错误，授权环境的只读锁文件核对通过。所有 skip/deselect 均保留且未计为通过。

[KNOWN | HIGH] 本次未改前端、公开输出 schema、存储或部署配置，因此未重复 P0-3 的前端构建与浏览器验证；当前报告只主张本次后端范围。

## 基线与剩余边界

```bash
.venv/bin/python scripts/check-agent-kernel-baseline.py \
  --output-dir docs/features/agent-kernel-quality/evidence/p0-4/kernel-baseline
```

[COMPUTED | HIGH] [报告](evidence/p0-4/kernel-baseline/kernel_baseline.md)与[结构化结果](evidence/p0-4/kernel-baseline/kernel_baseline.json)绑定实际源码指纹。数值校验、复合检索、必需改写、typed 事实四项通过；30 轮后的预算/禁止提交约束未保留，整体仍退出 **1 / needs_review**。历史指标 `intent_rewrite_reaches_kss` 实际执行 Dify，不表示恢复 KSS 关联。

[KNOWN | HIGH] 有界事实校验不是通用语义 judge。未识别的语句计入 `unassessed_statement_count`；即使 validator 为 passed，也不说明这些语句已证明。正确的自由改写、隐含推理、复杂字段表述或计算结果可能被保守拒绝。数值等值只处理受支持的写法，不做聚合、单位数量级换算或汇率换算；一条合法引用不能直接证明总体答案正确率。真实模型/Dify 的召回、分段、延迟与质量尚未验证。P1-1 是下一待执行节点；正式外部知识库生产发布仍另行关闭。

## 主要实现

- `control/validators/answer_facts.py`：有界一致性、typed 字面值、引用范围与安全诊断。
- `control/workflow/harness_helpers.py`：原校验入口和模型事实表述要求。
- `control/workflow/controlled_react/final_answer_attempt.py`：事实失败状态接入一次修复，混合 safety 失败不可修复。
- `capabilities/models/deterministic.py`：离线模板保持数值、读取 typed 和修复请求。
- `tests/test_answer_fact_validation.py`、`tests/test_model_output_validators.py`：行为验收与旧引用断言的新增 validator 适配。
