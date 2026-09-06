# P0-3：结构化证据到答案

[FRAME | HIGH] 用户于 2026-09-06 授权继续 P0-3。依据 ADR-0242，使用外部知识库与 Dify 链路，取代原计划中的 KSS/Release 假设。准入：`TDD_INPUT_READY`。本切片不承担 P0-4 的答案语义正确性判定。

## 接口与行为

- 新增 provider-neutral 的结构化证据记录：版本、记录 ID、有界字段集合；字段明确声明 string/integer/decimal/boolean/date/datetime/null 类型，值不隐式转换，十进制以精确字符串表示，可带单位。
- 外部绑定增加 `content_format`，默认 `text`，显式选择 `structured_json` 才解析完整分段 JSON。它是 ProofAgent 的内容约定，不是 Dify 新增的 API 字段。普通文本不自动抽取数值；混合或损坏的结构化内容拒绝，不降级为文本。
- Candidate 与 Evidence 保留结构化记录，并核对原始内容摘要及记录与内容的一致性。仍须经过原有策略与 Evidence Admission；类型正确不等于事实或答案正确。
- 首次答案和格式修复共用证据投影：每条已准入证据携带自身内容、结构化字段、身份与精确 citation，避免将事实与独立引用列表错误配对。
- 复用同一 Harness、required-query、Observation Truth 与恢复流程；原问题约束与改写查询分别保留，不增加检索执行器或外部权限。

## 验收顺序

1. Dify 精确 decimal、integer、false、null、单位与来源 → 真实适配器 → Candidate，无精度损失。
2. 类型错配、重复字段、非有限值、未知字段/版本、大小边界、JSON 重复键、Q&A 混合内容均失败；默认 text 行为兼容。
3. Candidate → 准入 → 答案输入及格式修复，保持同一来源映射；未准入事实不能出现。
4. 原始问题包含约束、required 改写查询实际执行；多来源同字段不覆盖；快照重建无再检索并保留类型，篡改被拒绝。
5. Dashboard/YAML 配置与冻结一致，类型化基线由实际行为转绿；数值核验与长对话探针保持其真实未完成状态。
6. 相关测试、完整后端/前端回归、静态检查、领域索引和验收文档。保持真实 Dify、生产发布与本地合成验证的区别。

[FRAME | HIGH] 回滚范围是本切片代码与新增配置字段，不修改历史证据文件或生产状态。结构化分段应独立成段且包含完整 JSON；本切片不进行自然语言抽取、聚合计算、单位换算或跨段表格恢复。
