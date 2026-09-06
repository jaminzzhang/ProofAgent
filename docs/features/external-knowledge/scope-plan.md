# 外部知识库：Dify 首接与 KSS 运行关联退役

[FRAME | HIGH] 用户于 2026-09-06 明确要求切断本项目知识库与 KSS 的关联，改为支持外部知识库，首接 Dify。该决定覆盖历史 KSS-only 规则；ProofAgent 仍负责 Evidence Admission、策略、引用核验和最终答案。设计决策见 ADR-0242。

## 交付范围

1. 外部绑定契约：provider、binding ID、Service API 地址、服务端凭证引用、精确 Dataset ID、检索设置和 `mutable_remote` 一致性声明。模型不能改写这些执行参数。
2. Dify 只读适配器：`POST /datasets/{dataset_id}/retrieve`，Bearer Knowledge API Key；有界查询、响应、结果数量和超时；稳定脱敏错误。首期不管理远端文档、索引或知识库写操作。
3. 复用既有检索与主循环：外部结果先转为 Candidate；ProofAgent 检查来源、内容摘要与明确的准入策略，之后才成为 Accepted Evidence。Dify score 是相关性输入，不是答案正确性证明。
4. 配置、验证、开发发布与运行使用同一个绑定；Dashboard 知识模块配置外部 Dataset，不再要求 KSS Release。凭证仅保存 Secret Handle，禁止原始 API Key。
5. 默认生产启动和就绪检查不再创建或调用 KSS；旧 KSS 配置不能自动转成 Dify。旧专属正式发布、Grant、Release 入口停止作为默认能力，既有生产发布门禁保持关闭，直到外部知识库正式发布切片获得自身验证证据。
6. 默认部署拓扑解除 KSS 服务及镜像的必填依赖。保留本项目自己的身份、数据库、对象存储和 egress 控制；不执行真实部署或变更外部 Dify 数据。

## 验收行为

| 场景 | 必须结果 |
|---|---|
| 有效 Dify 配置 | 严格校验并冻结；无 KSS 环境配置即可装配 |
| 原始 Key、未知 provider、非法 endpoint、非法 Dataset、参数越界 | 拒绝，不回显凭证或响应正文 |
| 检索 | 精确请求配置中的 Dataset；250 字符上限显式检查，不截断问题 |
| 结果 | 保留文本及 Q&A 的答案内容、文档/分段身份和内容摘要；无伪造 Release 或行号 |
| 准入 | 高 Dify score 不能绕过 Policy、引用/状态/内容验证；未准入内容不参与完成门控 |
| 错误 | 401/403/404/429/5xx、超时、重定向、过大/损坏响应、错查询、错文档身份均 fail closed |
| 范围 | Key 可访问更多 Dataset，Agent/Skill/模型仍只能使用配置绑定；metadata filter 不是 ACL |
| 主循环 | 两个 required 查询均执行；原始证据进入 bound truth；继续覆盖预算、审批恢复和拒答 |
| 可变数据 | 相同 Dataset 更新后不同观测各自保存实际内容摘要；不宣称远端全库快照一致 |
| 配置界面 | 保存、重新载入、冲突、校验失败、未配置状态清晰；不再请求 KSS workspace |
| 历史 | 旧 KSS 数据可解释但不可作为新的外部绑定执行或重新激活；旧摘要不重写 |

[FRAME | HIGH] 按测试先行的纵向切片交付：绑定与适配器 → 控制面与运行 → 配置界面 → 默认启动/部署解耦 → 回归与独立 Review。真实 Dify 联调需要部署方提供服务端凭证；本次不读取 `.env` 或索取 Key 内容。发布治理与数据读取验证分开记录，不能把本地测试升级为 Production GO。
