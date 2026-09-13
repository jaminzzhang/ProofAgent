# Codex 与 DeepSeek Harness：ProofAgent Workflow 优化的一手来源研究

研究日期：2026-09-12。状态：研究与设计输入，未实现、未运行外部模型、未形成部署或发布证据。

## 结论与证据范围

[INFERRED | HIGH] 建议借鉴两个项目的分层方法：把持久目标、单轮执行、问询、工具授权、模型 effort 和上下文管理分别建模；ProofAgent 应继续由 Control Plane 编译并执行业务流程、证据准入与最终结果映射。需要新增的是 `GoalContract / InteractionPolicy / AssurancePolicy / ComplexityProfile → ResolvedExecutionPlan`，不是照搬一个允许模型任意改写的执行循环。这是结合外部实现与本项目不变量提出的方案，不是上游已有接口。[O1]、[D1]、[P1]

[KNOWN | HIGH] 用户所指的 DeepSeek 官方项目已确认是 `deepseek-ai/deepseek-harness`：DeepSeek 官网直接链接此仓库，并标注 developer preview。第三方同名仓库、桌面封装、fork 和模型评测框架未用于论证。[D0]

| 对象 | 本次固定版本与范围 |
|---|---|
| OpenAI Codex | `openai/codex@c4017a87aacc7558002b7cb510025e967c1d765e`，commit 时间 2026-09-12 05:04:11 UTC。读取 Rust turn loop、goal extension、goal state、question handlers、effort normalization。 |
| DeepSeek Harness | `deepseek-ai/deepseek-harness@c291e7961a515f6d7af9304e7fd1d257929aef26`，commit 时间 2026-09-10 14:17:09 UTC。读取 architecture、goal、approval、workflow、agent-loop、ask-user、plan-mode、LLM adapter、compaction 文档及相关源码。 |
| OpenAI 官方文档 | 2026-09-12 实际打开 App Server、Configuration Reference 页面；旧 `developers.openai.com/codex/` 地址当日重定向至 `learn.chatgpt.com/docs/`。页面没有固定 commit；字段行为以对应固定源码为主要依据。 |
| 本地事实范围 | 仅读取本项目 `AGENTS-COMMON.md` 的有效边界；本报告不替代对 ProofAgent runtime、contract、API、UI 的代码审计。 |

[KNOWN | HIGH] 下文 `KNOWN` 的上游结论均来自实际获取的一手文档或源码，固定 commit 链接列于文末；`INFERRED` 是迁移建议。未实跑两套 harness、未验证模型回答质量、未复现 benchmark。因此没有延迟、成本下降比例或事实正确率数据。

## 外部实现事实表

| 主题 | OpenAI Codex 的直接证据 | DeepSeek Harness 的直接证据 | 对 ProofAgent 的启示 |
|---|---|---|---|
| 单轮循环 | [KNOWN \| HIGH] `run_turn` 在模型提出工具调用后执行工具并继续 sampling；工具后续需求或新增 input 都可触发下一步；停止前还有 stop hooks。[O1] | [KNOWN \| HIGH] step 是一次模型请求及其工具调用，turn 可含多个 step。工具结果和用户 steering 都进入同一 inbox / log 路径；pre-step、request、tool pipeline、turn-stopping 是扩展点。[D1]、[D2] | [INFERRED \| HIGH] 共用一个执行内核；自动与 HIL 不应各维护一套 workflow。 |
| 目标与完成状态 | [KNOWN \| HIGH] goal 独立持久化，含 objective、token budget、tokens used、time used；状态区分 active、paused、blocked、usage_limited、budget_limited、complete。[O2] | [KNOWN \| HIGH] goal 使用 id + revision；状态含 active、paused、blocked、complete，另存 maxGoalRounds。durable phase 与 process-local activation 分离。[D3] | [INFERRED \| HIGH] “生成了 final answer”与“完成业务目标”须分开；预算耗尽不应记为完成。 |
| 并发与旧目标 | [KNOWN \| HIGH] goal runtime 在读取目标与启动 idle continuation 的窗口持有 semaphore，外部目标变更与启动不能任意交错；continuation 经 start-if-idle 提交。[O3] | [KNOWN \| HIGH] goal fold 要求 revision 恰好递增；round driver 在 admission 前后检查目标版本，durability flush 后重新检查目标与 competing input。[D4]、[D5] | [INFERRED \| HIGH] 问询回复、续跑、目标编辑都绑定 revision；旧回复不能使新目标继续。 |
| 持续工作与预算 | [KNOWN \| HIGH] goal tool 的预算与 complete / blocked / paused 操作分开，不能因接近预算而声称 complete；runtime 按 usage 与错误停止。[O3]、[O4] | [KNOWN \| HIGH] driver 只在 idle、active、armed 且轮数有余量时续跑；重启或 fork 后默认不自动 arm，轮数耗尽记 round-limit。[D5] | [INFERRED \| HIGH] 需要独立配置 model calls、tool calls、tokens、deadline 和重试限额，不能只配“最大轮数”。 |
| 用户澄清 | [KNOWN \| HIGH] 同步 question handler 校验 root 身份与 available modes；Plan 模式设置 blocking。异步 handler 发出问题后立即返回，答案作为新用户消息进入；预选项不会自动提交。[O5]、[O6] | [KNOWN \| HIGH] ask_user_question 调 userQuestions seam，等待结构化回答，再以普通 tool result 回到 loop；stable question id 对应 selected/custom 答案。[D6]、[D7] | [INFERRED \| HIGH] 每条问询需标明阻塞程度、等待对象、目标版本和恢复点，不能只拼一个问句。 |
| 子任务的问询 | [KNOWN \| HIGH] 同步 request_user_input 只允许 root thread。[O5] | [KNOWN \| HIGH] 非 live caller 与被另一 live agent 拥有的 child 不能直接问人；child 应把未解决问题返回给 root。[D7] | [INFERRED \| HIGH] 问询应由主任务汇总、去重和编排，避免多个分支重复打断用户。 |
| 澄清与权限审批 | [KNOWN \| HIGH] App Server 区分 tool/requestUserInput 与 permissions/requestApproval，后者只授予请求权限的子集，并可限定 turn/session。某些 connector 审批可以复用问询 UI，但审批语义仍独立。[O7] | [KNOWN \| HIGH] user-approval 独立于 userQuestions；结果仅 allowed-once / rejected / cancelled / unavailable，只有 allowed-once 放行，缺失 answerer 等情况 fail closed。[D8] | [INFERRED \| HIGH] HIL 补充信息不能当工具权限、证据准入或最终发布批准；先遵守本项目当前没有 approval workflow 的范围。[P1] |
| Plan 模式 | [KNOWN \| HIGH] 模式可影响问题是否 blocking，不能由此推导业务验收已通过。[O5] | [KNOWN \| HIGH] plan-mode 的限制通过 guidance 实现，every tool remains available；review 让人查看具体 plan，硬限制仍需 sandbox / approval。[D9] | [INFERRED \| HIGH] 简化和跳过流程必须由受控执行计划决定，不能依靠“请简化回答”prompt。 |
| 模型推理力度 | [KNOWN \| HIGH] reasoning effort 根据具体 ModelInfo 解析，别名和 fallback 由模型能力映射处理；可信 harness metadata 才能形成保留的 effort override。[O8]、[O9] | [KNOWN \| HIGH] LlmCallConfig 将 provider、model、reasoningEffort、maxTokens、stop 作为请求头状态；DeepSeek adapter 解析 off / low / high / max，off 映射 thinking.disabled，其他值启用 thinking；不支持值请求前失败。[D10]、[D11]、[D12] | [INFERRED \| HIGH] 将抽象复杂度映射到 provider 支持值；模型内部思考预算与 workflow 步骤数量是两个配置维度。 |
| Workflow 含义 | [KNOWN \| HIGH] turn loop 是执行控制代码，question / goal 等能力通过协议与 handler 接入。[O1]、[O4]、[O5] | [KNOWN \| HIGH] workflow seam 是可选的模型脚本编排能力；meta.phases 仅用于展示分组，不规定执行结构；host 提供的 agent ceiling 不能被脚本改写。[D13]、[D14] | [INFERRED \| HIGH] UI 展示节点与执行拓扑须有明确映射；ProofAgent 不应引入任意脚本绕过 Control Plane。[P1] |
| 上下文与可追溯 | [KNOWN \| HIGH] turn loop 有 pre-sampling compaction，新增输入在失败路径仍被保留；effort override 与 compaction 有单独状态处理。[O1]、[O9] | [KNOWN \| HIGH] model input 从 append-only session log 派生，request 配置有日志；compaction 保持 tool call/result 配对并记录替换范围，失败与取消有独立处理。[D1]、[D15] | [INFERRED \| HIGH] 保存用户目标、已确认约束、pending question、证据 ID、验证结论和策略版本；不得将摘要升级为 Accepted Evidence。 |
| 验收与置信 | [KNOWN \| HIGH] 已读 goal tool 对 complete 的文字要求，不等于存在业务验收 evaluator 或已校准事实概率。[O4] | [KNOWN \| HIGH] goal-round-driver 明确将 independent evaluator 列为 deferred，完成充分性仍由模型策略决定。[D5] | [INFERRED \| HIGH] ProofAgent 的可信度与目标验收层必须自行定义，不能宣称“上游已验证 90% 可信门禁”。 |

## 三项需求应如何落地

### 1. 明确目标、任务可控

[INFERRED | HIGH] `GoalContract` 至少应包含：目标与输出边界、必答问题、必要上下文、约束、验收标准、每项标准需要的证据类型、资源预算、目标版本。目标来源可由模型提取候选，但由 Control Plane 校验后冻结；用户补充信息只修订相关字段，记录来源与版本。DSH 的 CAS 与 Codex 的独立 goal lifecycle 是可借鉴机制，业务验收条目则是 ProofAgent 新增设计。[D3]、[D4]、[O2]、[P1]

[INFERRED | HIGH] 状态建议区分 `running / waiting_for_input / verifying / completed / insufficient_evidence / budget_exhausted / failed / cancelled`；最终命名应与本项目现有结果契约协调。继续运行必须同时满足目标仍有效、依赖满足、预算有余量、没有取消/阻塞问询、lease 与版本匹配。资源耗尽可以输出已证实部分及缺口，但不能映射为目标完成。

[INFERRED | HIGH] 不应直接复制上游“同一 blocker 连续三轮才停止”的模型指令。对缺少必要投保条件、关键资格信息、身份权限或不可获得证据，首次确认缺口后即可 wait / abstain；只有可恢复检索失败或策略允许的替代证据路径才消耗有限重试。三轮重复本身不创造信息，也不是可信度证明。[O4]、[D5]、[P1]

### 2. 自动回答与全流程 HIL

[INFERRED | HIGH] `InteractionPolicy` 负责“什么时候问、问多少、阻塞什么、无人应答怎么办”，`AssurancePolicy` 负责“什么结论在什么证据条件下允许输出”。二者独立；用户偏好少问，不允许跳过缺失的必要证据。

建议的交互策略维度：

| 维度 | 建议语义 |
|---|---|
| interaction mode | auto：不发可选问询；adaptive：问影响结果的关键缺口；guided：在约定节点询问用户选择。必要条件缺失仍保持阻塞或明确不足。 |
| checkpoints | 目标明确、任务拆分、证据冲突、结论边界、最终输出前；使用同一个策略判定器，避免节点各自解释配置。 |
| question budget | 最大问询轮次、单轮问题数、总等待时长、重复问题指纹；达到上限后按明示 fallback 处理。 |
| blocking | required：依赖分支暂停；optional：独立工作继续；全局目标变更则使旧计划失效并重新解析。 |
| no-answer policy | 返回不足、限定条件回答、使用预先允许的假设；超时与空答案不可等价为确认。 |
| response contract | question_id、goal_revision、expected_fields、answer_source、answer_time、expiry、resume_checkpoint。 |

[INFERRED | HIGH] “可信度要求”优先用可审计的要求向量，而不是模型自评概率：必答项覆盖率、关键断言证据覆盖、来源准入级别、证据时效、引用可解析性、冲突状态、确定性校验结果。阈值可配置，但引用真实性、身份/租户、工具权限、证据准入等硬约束不能调低。若未来引入 `confidence >= 0.9`，应先给出任务分布、独立 holdout、校准方法和误差，否则只能称“配置等级”，不能称“90% 正确率”。

[INFERRED | HIGH] 用户回答可确认个人目标、偏好和由用户声明的情境；用户声称某保险条款、理赔结论或金额正确，并不会自动证明外部事实。数据来源需带 provenance，进入 Answer 前仍按对应证据规则校验。本项目明确 memory / conversation 不等于 Accepted Evidence，问询设计应延续这一边界。[P1]

### 3. 推理复杂度与流程裁剪

[INFERRED | HIGH] `ComplexityProfile` 同时给出可选推理能力与资源上限，但不修改 `AssurancePolicy` 的硬约束；`model_reasoning_effort` 作为独立执行参数，经 provider capability 校验后传入。上游只证明 effort 与能力组合可配置，没有证明降低 effort 自动等价于跳过业务 workflow。[O8]、[D10]、[D11]

| 示例档位 | 可裁剪内容 | 必须保留的内容 |
|---|---|---|
| lite | 可省显式多步计划、检索扩展、多候选草稿、可选反思；已充分限定的问题走最短证据路径。 | 目标有效性、必要上下文、授权工具、Evidence Admission、必答项与引用校验、结果映射、trace。 |
| standard | 按需拆解问题与补充检索，一次可选复核；达到门槛即停止。 | 同上；必要 HIL 与冲突处理不受档位关闭。 |
| deep | 有界分解、来源交叉验证、冲突消解和额外候选比较。 | 同上；更多推理仍不得自动提升证据等级。 |

[INFERRED | HIGH] `ResolvedExecutionPlan` 应是执行前或受控修订点生成的版本化数据：记录实际启用节点、跳过节点及理由、必经 gate、依赖、预算、模型配置、问询策略和输出要求。配置若要求跳过某业务目标不可缺少的证据或校验节点，解析器应拒绝或显式提升执行档位；不能静默执行一个无法满足验收的计划。

[INFERRED | HIGH] Dashboard 应展示完整流程及本次选中的路线，区分 `not_applicable / skipped_by_profile / awaiting_input / blocked / passed / failed`。被裁剪的节点不应从产品认知中消失，更不能显示为通过。HIL 回复只恢复受其影响的后续步骤；重新执行时保留旧证据与旧结论的版本关联，防止重复工具调用和预算重复计费。

## 不宜照搬的部分

1. [KNOWN | HIGH] DSH 的 goal round cap 不是 token / 费用 / 时间预算；默认 agent-loop 明确没有内建 turn budget。若一个 turn 不断发工具调用，单靠 round cap 仍不足以控制运行。[D2]、[D5]
2. [KNOWN | HIGH] DSH 的 plan-mode 不是硬工具限制，workflow phases 不是执行 DAG；把这些直接当作 ProofAgent 的可信工作流会混淆展示与执行约束。[D9]、[D14]
3. [KNOWN | HIGH] DeepSeek 官网描述 session log 可包含 reasoning；ProofAgent 明确禁止存储或返回 raw chain-of-thought。可借鉴事件可回放与摘要，不得复制原始思维链日志策略。[D0]、[P1]
4. [INFERRED | HIGH] 不在本次迁移“任意模型编排脚本”“shell/代码运行”“插件任意替换核心 policy”等能力；它们与本项目受控、只读工具及未来隔离 sandbox 边界不同。[D1]、[D13]、[P1]
5. [KNOWN | HIGH] 上游源码与网站会漂移。特别是官方通用 config 文档枚举并非所有模型/源码版本的完整能力集；应以所选 provider/model 的 capability contract 校验，不对所有模型硬套一组 effort。[O8]、[O10]、[D11]

## 可验证的交付与评估建议

[INFERRED | HIGH] 实现应先验证确定性控制，再验证回答收益。最低验收场景应包括：

- 简单且证据充分的问题：lite 跳过可选推理，保留所有必要 gates，给出可追溯原因。
- 必要信息缺失：auto 模式给出不足或允许范围内的条件回答；adaptive / guided 进入可恢复问询。
- 用户在检索后修改目标：旧 goal revision 和 pending answer 不得继续提交最终结论。
- 用户未应答或选择空值：不推定同意；独立步骤可继续，依赖步骤保持等待。
- 证据冲突或覆盖不足：deep 可增加受限工作，预算耗尽后保持不足，禁止“多思考一次就通过”。
- HIL 含错误外部事实：仅记录为用户陈述，不能冒充已接纳来源。
- 节点被配置跳过：必经节点拒绝跳过；可选节点在 trace 与 UI 清楚标为 skip，不计为 pass。
- provider 不支持 effort、stream max-tokens、tool timeout、lease 丢失、durability flush 失败：各自返回稳定失败/停止状态。
- 进程恢复、重复 HIL 回调与重复续跑：幂等、版本栅栏、预算计数一致。
- 多配置比较：使用同一输入集与相同 evidence snapshot，记录模型调用数、工具调用数、tokens、时延、必要问询次数、漏问/多问、证据覆盖及结果等级；本报告不预设收益百分比。

[INFERRED | HIGH] 若需要模型质量验证，应先固定匿名化样例、期望答案/不足条件和预算，再取得外部模型调用授权。单元测试或模型 judge 分数不替代业务证据准入与发布门禁。[P1]

## 一手来源

以下代码链接全部固定至上述 commit；官方网页按本次读取日期理解。

### OpenAI

[O1]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/core/src/session/turn.rs
[O2]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/state/src/model/thread_goal.rs
[O3]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/ext/goal/src/runtime.rs
[O4]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/ext/goal/src/spec.rs
[O5]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/core/src/tools/handlers/request_user_input.rs
[O6]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/core/src/tools/handlers/request_user_input_async.rs
[O7]: https://learn.chatgpt.com/docs/app-server
[O8]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/protocol/src/openai_models/reasoning_effort.rs
[O9]: https://github.com/openai/codex/blob/c4017a87aacc7558002b7cb510025e967c1d765e/codex-rs/core/src/session/reasoning_effort.rs
[O10]: https://learn.chatgpt.com/docs/config-file/config-reference

- [O1 — turn loop][O1]：`run_turn`、follow-up 判定、stop hooks、compaction 与 cancel。
- [O2 — ThreadGoal 数据][O2]；[O3 — 目标 runtime][O3]；[O4 — goal 工具契约][O4]。
- [O5 — 同步问询 handler][O5]；[O6 — 异步问询 handler][O6]；[O7 — App Server 协议][O7]。
- [O8 — 模型 effort 解析][O8]；[O9 — effort 与保留上下文][O9]；[O10 — 官方配置参考][O10]。

### DeepSeek

[D0]: https://deepseek.com/harness/en/
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/architecture.md
[D2]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/core/agent-loop/README.md
[D3]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/subsystems/goal.md
[D4]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/goal/goal/src/fold.ts
[D5]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/goal/goal-round-driver/README.md
[D6]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/interaction/tool-ask-user/src/index.ts
[D7]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/interaction/user-questions/src/index.ts
[D8]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/subsystems/approval.md
[D9]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/plan/plan-mode/README.md
[D10]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/llm/llm/src/call-config.ts
[D11]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/llm/llm-deepseek/README.md
[D12]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/llm/llm-deepseek/src/index.ts
[D13]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/subsystems/workflow.md
[D14]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/packages/workflow/workflow/src/types.ts
[D15]: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/subsystems/compaction.md

- [D0 — 官方 Harness 页面][D0]；[D1 — 架构][D1]；[D2 — agent-loop 与已知限制][D2]。
- [D3 — goal 契约][D3]；[D4 — goal replay 校验][D4]；[D5 — 自动续跑 driver 及评估/预算限制][D5]。
- [D6 — ask_user_question][D6]；[D7 — root 问询服务][D7]；[D8 — 审批边界][D8]；[D9 — plan-mode 软约束][D9]。
- [D10 — 请求配置][D10]；[D11 — DeepSeek adapter 行为][D11]；[D12 — 配置源码][D12]。
- [D13 — workflow seam][D13]；[D14 — phases 仅用于展示][D14]；[D15 — compaction 契约][D15]。

### 本项目有效边界

[P1]: ../../AGENTS-COMMON.md

- [P1 — ProofAgent Coding-Agent Guide][P1]：Control Plane 权威、候选与 Accepted Evidence 的区别、只读工具、禁止 raw chain-of-thought、生产存储与发布门禁。
