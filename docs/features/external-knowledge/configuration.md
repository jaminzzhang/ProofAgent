# Dify 外部知识库配置

[KNOWN | HIGH] 本项目已按 ADR-0242 切换到外部知识库绑定。首期支持 Dify Knowledge API 的只读检索；服务端配置不会创建、上传、修改或删除 Dify 文档。API 以 Dify [Knowledge 指南](https://docs.dify.ai/en/api-reference/guides/knowledge)和[检索接口](https://docs.dify.ai/en/api-reference/knowledge-bases/retrieve-chunks-from-a-knowledge-base-test-retrieval)为依据。

## 配置流程

1. 在 Dify 的知识库 Service API 页面获取 Service API 地址、Dataset ID 和 Knowledge API Key。API Key 的权限可能涵盖多个知识库；Agent 只能查询自身绑定的 Dataset。
2. 将 Key 交给服务端凭证服务。开发环境通过环境变量解析，生产目标通过现有 Vault Secret Provider 解析。不要把 Key 填入 Agent YAML、Dashboard、聊天消息或 Git。
3. 在 Dashboard → Agent → 草稿 → 知识库中添加 Dify 数据集。填写绑定 ID、Service API URL、Dataset ID、凭证服务、Secret Handle 与版本、检索方式、Top K 和最低相关性分数。最多 5 个绑定；保存检查草稿 revision，冲突后需重新载入。
4. 配置独立的出站许可：明确 Service API 的 HTTPS origin 和允许连接的 IP/CIDR。更改 Agent 地址不会自动获得网络许可。自部署 Dify 需通过 TLS 暴露 Service API。
5. 开发模式下，执行草稿验证，确认实际引用与回答，再发布开发版本。版本固定连接、Dataset、凭证引用与检索设置；不固定 Dify 数据集的全部内容。

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

## 开发出站策略

在仓库外保存一份 `EgressPolicyVersion` JSON，并将路径设置到 `PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY`。已有服务端 Guarded HTTP 注入时继续使用该实例，不创建第二套网络权限。未配置许可时拒绝发起请求。

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

- 首期检索方式：`semantic_search`、`full_text_search`、`keyword_search`；不开放 hybrid/reranking 或任意 metadata filter。未声明字段会被拒绝。
- 单次查询最多 250 个字符，不静默截断。服务端响应最多 1 MiB，最多解析 100 条候选；单绑定 Top K 为 1–20。实际保留数量还受 Agent `retrieval.top_k` 限制，准入分数门槛取绑定与 Agent `retrieval.min_score` 的较高值。
- 默认单请求超时 10 秒；实际使用 Agent `retrieval.query_timeout_seconds`，上限 60 秒。多绑定顺序查询，每个被选绑定都必须成功，不因接口失败返回部分成功。零命中属于正常检索结果。
- HTTP 401/403/404/429/5xx、超时、出站拒绝、重定向、错误查询、损坏内容与身份不一致均返回稳定脱敏错误。不重定向、不自动重试。
- Dify 的 `score` 仅作为相关性输入。ProofAgent 先检查策略、字段、内容摘要、分段启用与完成状态，再执行显式相关性/来源准入策略。状态缺失的分段不准入。`admission_score=1` 表示通过该门槛，不是独立语义或数值正确率。
- 引用为 `external://<binding>/datasets/<dataset>/documents/<document>#segment=<segment>&sha256=<content>`。真实内容、文档/分段身份、摘要、观测时间与实际 query 进入现有 bound Observation Truth，继续受原有引用检查和 required-query 完成门控约束。
- Dataset 可变化；相同分段的新内容具有新的内容摘要。审批恢复重用已绑定的旧观测。回滚 Agent 版本只恢复连接配置，不回滚 Dify 数据。

## KSS 退役与验收边界

[KNOWN | HIGH] 默认 API、Executor、就绪检查与本地部署拓扑不再要求 KSS、KSS_IMAGE、KSS 数据库、OpenSearch 或 KSS 模型服务。旧 KSS 绑定可供历史契约解释，但不能新装配、入队、执行或回滚激活。旧配置不会自动转换为 Dify；需新建外部绑定并重新验证。

[KNOWN | HIGH] KSS 专属 Release、Reference、Grant 和正式发布验证脚本属于历史资料，不能作为此次接入的验收依据。默认正式发布命令未装配，外部知识库生产发布 profile 尚待独立交付。DCM v2 仅移除 KSS 专属基础设施依赖，并保留 v1 历史解析；它不提供外部知识库的生产兼容性或发布证明。

[KNOWN | HIGH] 本切片使用官方协议的合成本地响应验证配置、准入、主循环、冻结与错误行为。未读取真实 Key，未对真实 Dify 进行连通性或数据质量验收，未执行上线。后续真实验收应记录 Dify 版本、Dataset 配置、实际命中/空结果/权限错误、引用准确性和问题集结果。
