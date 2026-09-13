# 外部知识库配置：Dify 与 Agentset

[KNOWN | HIGH] 本项目已按 ADR-0242 切换到外部知识库绑定。支持 Dify Knowledge API 和 Agentset Search API 的只读检索；服务端配置不会创建、上传、修改或删除 Dify 文档。API 以 Dify [Knowledge 指南](https://docs.dify.ai/en/api-reference/guides/knowledge)和[检索接口](https://docs.dify.ai/en/api-reference/knowledge-bases/retrieve-chunks-from-a-knowledge-base-test-retrieval)为依据。

## 配置流程

1. 在 Dify 的知识库 Service API 页面获取 Service API 地址、Dataset ID 和 Knowledge API Key。API Key 的权限可能涵盖多个知识库；Agent 只能查询自身绑定的 Dataset。
2. 将 Key 交给服务端凭证服务。开发环境通过环境变量解析，生产目标通过现有 Vault Secret Provider 解析。不要把 Key 填入 Agent YAML、Dashboard、聊天消息或 Git。
3. 在 Dashboard → Agent → 草稿 → 知识库中添加 Dify 数据集。填写绑定 ID、Service API URL、Dataset ID、凭证服务、Secret Handle 与版本、检索方式、Top K 和最低相关性分数。Dify 与 Agentset 合计最多 5 个绑定；保存检查草稿 revision，冲突后需重新载入。
4. 开发环境点击“保存并授权连接”：具有 Agent 编辑与出站策略编辑权限的操作者，可在同一草稿 revision 中保存绑定、授权精确 HTTPS origin 并记录审计。普通“保存知识库配置”不增加权限。公网 DNS 地址变化自动复核；每次连接仍检查全部解析地址并固定连接。使用本机代理时，显式勾选“允许内置供应商使用本机代理虚拟地址”；该选项仅对 `api.agentset.ai:443`、`api.dify.ai:443` 的 `198.18.0.0/15` 及映射／转换形式生效，不开放其他内网地址。
5. 授权后自动检查服务端凭证并执行一次固定问题 `connection check` 的只读检索；也可点击“检查已保存连接”重试。界面仅显示该 revision 的连接状态，不返回密钥或检索内容。连接检查不调用模型，不证明回答质量。服务端凭证缺失需在服务启动环境中补齐；凭证不会在浏览器输入。
6. 开发模式下，执行草稿验证，确认实际引用与回答，再发布开发版本。版本固定连接、Dataset、凭证引用与检索设置；不固定 Dify 数据集的全部内容。

## YAML 示例

下面是 `agent.yaml` 中的知识配置片段，其余模型、策略、工作流等配置继续使用现有 Agent：

```yaml
package_knowledge_sources: []
knowledge_bindings:
  - binding_id: policies
    provider: dify
    endpoint: https://api.dify.ai/v1
    dataset_id: c42e2a6e-40b3-4330-96f8-f1e4d768e8c9
    credential_ref:
      protocol_id: local-environment-v1
      handle_id: DIFY_KNOWLEDGE_API_KEY
      purpose: knowledge_credential
      version_id: env
    retrieval:
      search_method: semantic_search
      top_k: 3
      score_threshold: 0.2
    consistency: mutable_remote
    failure_mode: required
    admission_policy: external-relevance-and-provenance.v1
```

Dataset ID 只是示例，必须替换。Service API 地址从 Dify 复制，不填写控制台页面或完整 `/datasets/.../retrieve` 路径。系统会在地址后拼接精确 Dataset 的检索路径。

开发进程需通过自己的环境获得 `DIFY_KNOWLEDGE_API_KEY`。`version_id: env` 表示开发环境变量，不承诺密钥内容不可变。Vault 使用 `protocol_id: hashicorp-vault-2.0-kv-v2`、运维配置的 `handle_id` 和精确 `version_id`；读取到的凭证版本不一致时拒绝检索。

## Agentset 配置

[KNOWN | HIGH] ADR-0249 增加 Agentset 适配器，和 Dify 可在同一 Agent 内混合使用。Dashboard 点击“添加 Agentset Namespace”，填写 Namespace、可选 Tenant、服务端凭证引用及检索设置。切换 Provider 会清空原来源、凭证引用与检索设置，避免配置串用。

```yaml
knowledge_bindings:
  - binding_id: manuals
    provider: agentset
    endpoint: https://api.agentset.ai/v1
    namespace_id: ns_REPLACE_WITH_YOUR_NAMESPACE
    tenant_id: Customer1  # 可选；不使用 Tenant 时省略
    credential_ref:
      protocol_id: local-environment-v1
      handle_id: AGENTSET_KNOWLEDGE_API_KEY
      purpose: knowledge_credential
      version_id: env
    retrieval:
      search_method: semantic
      top_k: 3
      score_threshold: 0.2
      rerank: true
      rerank_model: zeroentropy:zerank-2
    content_format: text
    consistency: mutable_remote
    failure_mode: required
    admission_policy: external-relevance-and-provenance.v1
```

- 地址填写 API 根路径，服务端拼接 `POST /namespace/{namespace_id}/search`；不填写文档网站或完整 Search URL。凭证通过 Bearer Header 注入；可选 Tenant 固定为 `x-tenant-id`，不由问题文本控制。
- Namespace 必须以 `ns_` 开头。Tenant 按官方 API schema 限制为 1–64 个英文字母或数字；指南中的其他格式示例不作为此实现的输入合同。
- 支持 `semantic` 和 `keyword`；Rerank 可关闭，开启时显式固定模型，默认 `zeroentropy:zerank-2`，避免供应商默认值变化。支持的模型列于表单及严格契约；未知模型被拒绝。
- 复用服务端凭证、版本核验、出站许可、超时、响应体与候选数量上限；需为 `api.agentset.ai:443` 配置核准网络范围。关闭 metadata 和 relationships；不开放任意 filter、远端写入、索引管理或供应商托管 Agent 循环。
- Agentset 的 `score` 同样只是相关性输入，必须经过 ProofAgent 准入。Search 成功返回的分段作为可检索候选；不伪造 Dify 的文档启用/索引状态。
- 保留不透明 Chunk ID，不从 `doc_123#4` 等值推导 Document ID。引用来源为 `external://<binding>/namespaces/<namespace>[/tenants/<tenant>]/chunks/<encoded-chunk>`，再附加分段及内容 SHA-256；Tenant 参与来源身份。
- `structured_json` 同样可用，Agentset 每项 `text` 必须完整遵循下述 JSON 记录合同。来源身份与摘要仍由受控链路产生，内容不能覆盖它们。

协议依据：[Search API](https://docs.agentset.ai/api-reference/endpoint/search)、[引用](https://docs.agentset.ai/search-and-retrieval/citations)、[数据隔离](https://docs.agentset.ai/production/data-segregation)。本地证据见 [Agentset 验证记录](agentset-verification.md)。真实 Namespace/Tenant 权限、连通性、模型可用性与召回质量尚未联调。

## 开发出站策略

[KNOWN | HIGH] Dashboard 自动授权按 ADR-0256 保存在现有开发配置存储的服务端字段中，随绑定与审计一起提交；后续请求立即读取，无需设置环境变量、编辑 JSON 或重启。修改／删除绑定会移除相应授权，旧发布版本也不能绕过撤销；仍保留同一 Agent 其他草稿授予的匹配授权。授权仅用于外部 Knowledge，不扩展模型或工具出站权限。草稿中的 YAML 不能自行声明授权。

生产、自部署私网服务或已有独立网络策略继续由服务端管理。开发 CLI 或需要固定 CIDR 的环境可在仓库外保存一份 `EgressPolicyVersion` JSON，并将路径设置到 `PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY`。显式文件与已有服务端 Guarded HTTP 注入具有优先权，Dashboard 不覆盖它们；界面显示“服务端管理策略”。未配置许可时拒绝发起请求。

```json
{
  "version_id": "dify-development-1",
  "revision": 1,
  "created_at": "2026-09-06T00:00:00Z",
  "created_by": "local-operator",
  "rules": [{
    "origin": {"host": "api.dify.ai", "port": 443},
    "allowed_ip_networks": ["203.0.113.10/32"]
  }]
}
```

`203.0.113.10/32` 是文档示例地址，不能访问实际 Dify；请替换为部署方核准的地址范围。客户端每次连接前检查 DNS 返回的全部地址，并将连接固定到核准地址。生产仍使用 PostgreSQL 中的既有活动出站策略；不会读取此开发文件作为降级路径。

## 检索与证据语义

- Dify 检索方式：`semantic_search`、`full_text_search`、`keyword_search`；不开放 hybrid/reranking 或任意 metadata filter。未声明字段会被拒绝。
- 单次查询最多 250 个字符，不静默截断。服务端响应最多 1 MiB，最多解析 100 条候选；单绑定 Top K 为 1–20。实际保留数量还受 Agent `retrieval.top_k` 限制，准入分数门槛取绑定与 Agent `retrieval.min_score` 的较高值。
- 默认单请求超时 10 秒；实际使用 Agent `retrieval.query_timeout_seconds`，上限 60 秒。多绑定顺序查询，每个被选绑定都必须成功，不因接口失败返回部分成功。零命中属于正常检索结果。
- HTTP 401/403/404/429/5xx、超时、出站拒绝、重定向、错误查询、损坏内容与身份不一致均返回稳定脱敏错误。不重定向、不自动重试。
- Dify 的 `score` 仅作为相关性输入。ProofAgent 先检查策略、字段、内容摘要、分段启用与完成状态，再执行显式相关性/来源准入策略。状态缺失的分段不准入。`admission_score=1` 表示通过该门槛，不是独立语义或数值正确率。
- 引用为 `external://<binding>/datasets/<dataset>/documents/<document>#segment=<segment>&sha256=<content>`。真实内容、文档/分段身份、摘要、观测时间与实际 query 进入现有 bound Observation Truth，继续受原有引用检查和 required-query 完成门控约束。
- Dataset 可变化；相同分段的新内容具有新的内容摘要。审批恢复重用已绑定的旧观测。回滚 Agent 版本只恢复连接配置，不回滚 Dify 数据。

## 结构化分段（P0-3）

[KNOWN | HIGH] 普通绑定默认采用 `content_format: text`。若需要保留金额、计数、日期等字段的类型，在 Dashboard 的“分段内容格式”中选择“类型化 JSON 记录”，或在对应 YAML 绑定中设置 `content_format: structured_json`。该设置随配置验证和版本冻结；运行时格式漂移会被拒绝。

这是一项 **ProofAgent 内容约定**，不表示 Dify 原生提供类型化数据库查询。Dify 每个返回分段的 `content` 必须是一条完整记录，例如：

```json
{
  "schema_version": "proofagent-structured-evidence.v1",
  "record_id": "claims-2025",
  "fields": [
    {"field": "claim_total", "value_type": "decimal", "value": "12345.6700", "unit": "CNY"},
    {"field": "year", "value_type": "integer", "value": 2025},
    {"field": "approved", "value_type": "boolean", "value": false},
    {"field": "expiry", "value_type": "null", "value": null}
  ]
}
```

- `schema_version` 必须明确提供，记录与字段不接受未知属性；`record_id`、字段名和可选 `unit` 为非空、有界字符串。字段名区分大小写且不得重复。
- 一条记录包含 1–64 个字段。支持 `string`、`integer`、`decimal`、`boolean`、`date`、`datetime`、`null`；不进行隐式转换。`null` 与未提供的字段不同，不补默认值。
- Decimal 使用最长 128 个字符的普通十进制字符串，不接受 JSON 浮点数、科学计数法、NaN 或 Infinity；保留符号、小数精度和末尾零。Integer 最多 128 位十进制数字。String 最长 4096 个字符。Date 使用 `YYYY-MM-DD`，datetime 必须有时区。
- 每段内容最多 100,000 个字符，仍受既有 1 MiB HTTP 响应限制。不要添加 Markdown 围栏、说明前后缀或将一条 JSON 记录切为多个检索分段。需在 Dify 中确认实际分段内容；此模式不接受非空 Q&A `answer` 混合数据。
- 普通文本不会自动抽取为结构化事实；格式损坏、重复 JSON 键、类型错配和模式不一致均拒绝，不降级为文本。来源、Dataset、文档、分段和内容摘要取自受控检索链路，记录不能自行覆盖这些身份或授予准入。
- 首次答案和格式修复逐条接收同一来源映射。相同字段名在不同记录中独立保留，不覆盖、不做聚合或单位换算；恢复使用原有已绑定观测。类型与引用保真不代表答案的金额、比较或推导已通过语义核验。

本地验收见 [P0-3 记录](../agent-kernel-quality/tdd-p0-3.md)。真实 Dify 分段配置、召回质量和生产发布仍需独立验证。

## KSS 退役与验收边界

[KNOWN | HIGH] 默认 API、Executor、就绪检查与本地部署拓扑不再要求 KSS、KSS_IMAGE、KSS 数据库、OpenSearch 或 KSS 模型服务。旧 KSS 绑定可供历史契约解释，但不能新装配、入队、执行或回滚激活。旧配置不会自动转换为 Dify；需新建外部绑定并重新验证。

[KNOWN | HIGH] KSS 专属 Release、Reference、Grant 和正式发布验证脚本属于历史资料，不能作为此次接入的验收依据。默认正式发布命令未装配，外部知识库生产发布 profile 尚待独立交付。DCM v2 仅移除 KSS 专属基础设施依赖，并保留 v1 历史解析；它不提供外部知识库的生产兼容性或发布证明。

[KNOWN | HIGH] 本切片使用官方协议的合成本地响应验证配置、准入、主循环、冻结与错误行为。未读取真实 Key，未对真实 Dify 进行连通性或数据质量验收，未执行上线。后续真实验收应记录 Dify 版本、Dataset 配置、实际命中/空结果/权限错误、引用准确性和问题集结果。

## Validate 报 PA_CONFIG_002：未装配外部检索组件

如果开发服务器提示未配置 outbound access，进入当前 Agent 的 Knowledge 设置，点击“保存并授权连接”。本机代理解析为虚拟地址时同时启用代理选项。授权即时生效；当前 Agent 的已有绑定也可以直接授权，无需先修改表单。普通保存 URL、Namespace 和 Secret Handle 不会生成许可。若界面显示“服务端管理策略”，则按上文维护已有服务端策略。凭证引用对应的环境变量必须由服务器进程获得，不在浏览器输入 Key。

历史报错 `External Knowledge requires guarded HTTP and a Secret Provider` 可能由缺失出站策略导致；现已将该分支改为明确的缺失配置诊断。测试验证提供策略后两项组件能够装配，但这不证明真实凭证、供应商网络与检索质量已通过验证。
