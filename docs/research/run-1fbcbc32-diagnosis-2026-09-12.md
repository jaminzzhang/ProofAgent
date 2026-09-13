# run_1fbcbc32 全流程诊断

日期：2026-09-12。范围：历史 Trace、授权保存的敏感 validation capture、当前工作区代码和离线校验器复放。未重新调用外部模型或知识库，未修改运行逻辑。当前工作区已有大量未提交改动，因此源码解释以当前版本为准；捕获复放结果与历史两次失败一致，不据此声称部署版本相同。

后续状态：用户随后授权修正，实施记录见 `../features/agent-kernel-quality/tdd-run-1fbcbc32.md`。
本文件保留修正前的历史诊断；同目录 offline-probe 已更新为新路径验证，重新生成 ID，
不把旧 capture 中的 ID 用于新版候选目录。历史 RED 结果保留在下文，不代表当前行为。

## 结论

[KNOWN | HIGH] 本 run 的直接失败链为：两轮 Agentset 检索成功 → 原答案通过 schema/safety/citations/adequacy，但未通过 answer_facts → 单次原句选择修复返回 30 个合法且不重复的 ID，超过 1–16 限制 → schema_failed → FAILED_WITH_TRACE。不是连接失败、空检索、超时或无匹配业务流包造成的退出。

[COMPUTED | HIGH] 深层问题是分析型任务和抽取型答案协议不匹配：模型改写空格、前缀、表格事实会被精确匹配拒绝；修复候选过滤表格，又无法表达用户关心的部分负面指标；必查 Query 完成后，控制层禁止继续检索，而答案充分性检查只检查浅层词汇覆盖。

## 原始证据

- `runs/dify-verification/history/run_1fbcbc32/trace.jsonl`，70 个事件，行号与 sequence 相同。
- 同目录 `run_meta.json`：原问题为“平安业绩有什么亮点，哪些业务做的比较好？哪些业务比较差？”，outcome 为 FAILED_WITH_TRACE。
- `runs/dify-verification/config/validation_captures/vcap_e78f9d12a17a/capture.json`：6 次模型交互；`payload.llm_interactions[0]` 意图，`[1:4]` Planner，`[4]` 初次答案，`[5]` 修复。
- Capture 标注敏感保留策略及 2026-09-19 到期时间；本报告和脚本没有复制完整捕获。

## 全流程核查

| 阶段 | 事实与判断 | 证据 |
|---|---|---|
| 意图 | [KNOWN | HIGH] 正确识别业绩亮点、较好与较弱业务；无需强制追问单一指标。模型 confidence=0.71 只是自报分数。 | Trace 10 |
| 业务流 | [KNOWN | HIGH] 推荐 no_pack，未强行进入条款/理赔业务流，随后继续知识问答。领域标签 public_insurance_knowledge_query 偏宽，尚不妨碍本例。 | Trace 8–10 |
| 默认范围 | [KNOWN | HIGH] 当前日期已传入 2026-09-12，模型仍生成“按用户提问年份……2025年最新披露期”。原问题无年份，这是无依据时间限定；服务端合并了六条假设，只做文本去重。 | Capture interaction 0；clarification.py:71 |
| Query 扩展 | [KNOWN | HIGH] 两条 required 分别保留原意、扩展寿险/产险等术语；第三条 optional 强加 2025 年报。扩展缺少明确的下降、亏损、减值、弱项角度。第三条未执行，故错误年份不是本次检索失败原因，但被传给答案。 | Trace 11 |
| Planner | [KNOWN | HIGH] 前两次模型提案均原样查询，并提出 max_results=10。这是系统提示要求原问题，不应简单归因为模型不会改写。控制层随后按 required query 替换执行动作，第二轮对应术语扩展 Query。max_results 不是实际 top_k 权威。 | Capture 1–2；planner.py:335；task_completion.py:206；composition.py:551 |
| 权限与检索 | [KNOWN | HIGH] 两轮 policy allow、低风险 fast path；provider 实际为 agentset，目录名 dify-verification 不能代表 provider。每轮返回并接纳 3 个 chunk，无本次传输失败证据。 | Trace 17–34 |
| 证据内容 | [KNOWN | HIGH] 捕获中确有标为 2026 Q1 的经营亮点、银行、寿险关键指标、集团营运利润内容，包括文字与 Markdown 表格。6 条记录只有 4 个唯一 source/content；不是六份独立来源。 | Capture 5 request.accepted_evidence |
| 证据准入 | [KNOWN | HIGH] native_score 约 0.778–0.844，admission_score 均为 1.0；代码以 available 与分数门槛准入，1.0 不代表事实真实性或权威概率。authority_admitted=false 也不等于本例外部证据被拒绝。 | Trace 22/33；retrieval_service.py:273 |
| 完成判定 | [KNOWN | HIGH] 两条 required Query 各有绑定的 accepted evidence 即判 complete；未证明报告期最新、所有板块覆盖或正负两面充分。完成后 eligible actions 仅剩生成/澄清/拒绝，不能再检索第三条。 | Trace 35–38；task_completion.py:141；orchestrator.py:1583 |
| 初次答案 | [KNOWN | HIGH] 正确引用已接纳的四个 citation，但给出长篇改写、表格转述、重复指标及范围说明。answer_facts 失败，前 32 条诊断截断展示，violation_count=2 指两种错误类别。 | Trace 40–42；Capture 4 |
| 修复 | [KNOWN | HIGH] 66 个候选，要求 1–16 个唯一 ID，模型选择 30 个；全部已知且唯一，明确失败原因是数量越界。 | Trace 44–46；Capture 5 |
| 收尾 | [KNOWN | HIGH] 保存失败元信息并返回 FAILED_WITH_TRACE，未把非法答案输出为成功；这是正确的关闭方式，但用户目标未完成。 | Trace 47–70 |

## 离线复放与最小实验

命令（仓库根目录）：

```bash
.venv/bin/python docs/research/run-1fbcbc32-offline-probe.py
```

[KNOWN | HIGH] 脚本调用真实 validate_model_output、validate_answer_facts、render_selection；使用捕获的模型输出与答案请求中的证据，保留原问题参与 adequacy。它复放校验边界，不模拟一次完整远端 run。

| 实验 | 结果及含义 |
|---|---|
| 原答案原证据 | schema、safety、citations、adequacy 通过；answer_facts 失败，与历史一致 |
| 原修复响应 | source_selection_count_out_of_range，30 个 ID |
| 原句直接校验 | passed |
| 同一句只去空格 | unsupported_numeric_fact；数值没变也会失败，不能把该错误码等同于数据幻觉 |
| 同一句改错数值 | failed；保持此保护必要 |
| 12 句受控选择 | 五项本地检查通过；但未涵盖寿险价值率弱项，不能据此宣称完整回答 |
| 仅假设放宽 30 句限制，原 ID 全部渲染 | answer_facts 通过，adequacy 因 raw_evidence_dump 失败；直接把 16 改成 32 仍不能解决本例 |
| 原答案范围说明 | answer_facts 失败，表明允许披露范围的提示与统一事实匹配存在不协调 |
| 表格弱项候选覆盖 | 23.5、27.8、下降 4.8 个百分点、220.88 在证据中存在，在修复候选中消失 |

[KNOWN | HIGH] `_fact/_parts` 并不是语义蕴含模型；普通中文数值句可能成为整句匹配，空格、加“寿险：”等前缀、跨句合并都会改变匹配结果。answer_facts.py:24 的修复候选过滤又主动排除表格、含 `**`、HTML 等语句。ADR-0250 明确承认表格转述与完整性不在能力范围内。

[KNOWN | HIGH] 12 句实验的 adequacy 仅命中“业务”“平安”两个词就通过，原问题提取了 16 个词项。这说明当前检查能挡明显空答/原文堆砌，但不能证明“亮点与弱项都回答了”。

## 优化顺序与验收

1. **P1：统一答案生成与校验协议。** 对文本抽取可直接请求有界 source IDs，并由服务端按证据组组织，避免先长篇自由生成再修复。为本例提供主体、期间、指标、数值、单位、比较基准、方向及 source locator 的结构化事实；表格必须保留行列头、脚注及单元格绑定，不能只摘一个数字。普通文本不得只改 content_format 就当成 structured_json。
2. **P1：区分事实、范围披露、分析结论。** 范围说明由服务器根据获准默认范围渲染，不依赖模型写自由免责声明，也不能简单豁免整段“假设”。事实逐项校验；分析结论绑定事实与明确比较规则。“价值率下降”不等于“寿险整体做得差”。仅允许经过测试的排版归一化，继续保护数值、符号、单位、否定与条件。
3. **P1：把 Query 完成和问题完成分开。** 为本题记录 entity、actual_period、group_overview、segment_strengths、segment_weaknesses、missing_segments 等需求。两条必查完成后，如存在事实覆盖缺口，在现有检索预算内仍可进行受控补查；Planner 应收到唯一证据摘要及缺口，不仅是 accepted_evidence_count 和 next_action 提示。仍需保留 required Query 与权限校验。
4. **P1：规范时间默认值。** 未指定年份时使用 latest_available 的未解析范围，不凭模型填写 2025。当前日期已存在，不能靠“再加日期 Prompt”声称修好。以检索到的报告期为实际回答范围；没有最新性证明就说“本次查得资料覆盖……”，不能说已确认最新。对假设冲突及年份来源做校验。
5. **P2：精简修复输入与保留弱项。** 本次修复同时传 6 条证据、前一答案和 66 条附长 citation 的选项；候选 JSON 约 25,476 字符。用短 ID 和独立服务器 citation 映射、精简错误提示；候选按业务/正负面覆盖组织，约束输出项数。不得静默截断 30 句以假装模型合规，截断可能删除限制或负面证据。
6. **P2：去重与来源元数据。** 按 binding/chunk/hash 去重生成上下文，保留每条 Query 的 Observation Truth 绑定；分开展示返回数、唯一 chunk 数、有效来源数。本次 Agentset 请求禁用 metadata/relationships，答案记录只带 source/citation/content；官方来源、发布时间和最新性不能由相似度或 hash 推出。补全来源映射后才能据此加强时效/权威检查。
7. **P2：适配业务模板和诊断展示。** 当前 Prompt 偏客服/理赔，给本题增加业绩比较模板，输出期间→核心判断→主要亮点→压力点→未覆盖板块，减少机械的待确认和客户沟通下一步。错误界面展示两次失败、30/16、检索已成功，并区分本阶段 2 次回答调用与全 run 6 次模型调用。

[COMPUTED | HIGH] Trace 模型 token_usage 合计 49,290；最后一次修复 23,635，约占 48%。全 run 首尾约 20.46 秒。此次不是超时失败，优先压缩重复输入与协议冲突比增加 timeout 更对症。Token 为 provider 报告用量，非成本账单。

验收需同时包括：原捕获回归；无年份不造年份；最新性未知可披露；重复命中不增加覆盖；弱项位于表格仍可回答；错数值/单位/主体/期间/否定必失败；只谈亮点不能满足双面问题；限制范围短句不误伤；非法/重复/超量 ID 仍失败。离线通过后，真实模型验证应新建 run 并核对完整答案、来源与期间。任何外部模型重放都需先取得用户对外发输入的同意。

## 本例怎样回答才算正确

[INFERRED | HIGH] 按捕获内容，答案至少应做到：明确只覆盖本次查得的 2026 Q1 材料；从增长、利润、成本率等区分寿险、产险、银行亮点；同时保留寿险新业务价值增长但价值率下降、银行营收利润增长但息差承压的双面解释。医疗养老的覆盖数量属于运营进展，不能单独证明盈利良好；未检索到资管等板块不能评为好或差。

本报告中的财务数字仅用于核对运行快照内的支持关系，未独立核实原始公告真实性或公开最新报告。不把本次 capture 内容作为当前投资研究结论。

## 实现定位

- `proof_agent/control/validators/answer_facts.py`：原句候选、事实匹配及诊断。
- `proof_agent/control/workflow/controlled_react/answer_source_selection.py`：1–16 选择协议与渲染。
- `proof_agent/control/workflow/controlled_react/final_answer_attempt.py:311`：修复后的统一校验。
- `proof_agent/control/workflow/controlled_react/task_completion.py:141`：Query 的绑定证据完成判定。
- `proof_agent/control/workflow/controlled_react/orchestrator.py:1583`：完成后的动作集合。
- `proof_agent/control/workflow/controlled_react/composition.py:1060`：Planner 摘要；`:1158`：答案证据累加。
- `proof_agent/control/workflow/harness_helpers.py:298`：adequacy；`:375`：raw_evidence_dump 启发式。
- `proof_agent/capabilities/react/planner.py:335`：要求原问题逐字提案。
- `proof_agent/control/workflow/clarification.py:71`：默认假设合并。
- `proof_agent/capabilities/knowledge/agentset.py:25` 与 `proof_agent/control/knowledge/retrieval_service.py:273`：调用与准入。

本次产出是诊断报告与离线探针，没有宣称优化已实现或 Agent 已在真实重跑中答对。
