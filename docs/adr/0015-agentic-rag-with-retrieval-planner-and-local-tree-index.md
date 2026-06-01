# ADR-0015: Agentic RAG with RetrievalPlanner and Local Tree Index

## Status

Accepted

## Context

Proof Agent 当前依赖外部 PageIndex 服务进行文档检索，存在以下问题：

1. **检索策略灵活性不足**：单次 `retrieve()` 调用无法支持多轮迭代检索
2. **Agentic RAG 集成深度有限**：`_run_agentic_retrieval()` 本质仍是单次 provider 调用
3. **部署复杂度高**：需要独立部署和维护 PageIndex 服务
4. **延迟问题**：每次检索都需要 HTTP roundtrip

同时，真正的 Agentic RAG 需要一个闭环机制：分析问题 → 规划检索 → 执行检索 → 评估证据 → 判断是否充分 → 不够则改写 query 或换角度再检索。

## Decision

### 核心架构

采用**混合架构**：保留 PageIndex 的树形索引概念（通过 LlamaIndex TreeIndex 实现），用 LLM 做检索规划（路由），用 TreeIndex 引擎做结构化执行。

**新增 RetrievalPlanner 组件**：
- 位于 orchestrator 和 provider 之间
- 拥有独立 LLM 配置（planner_model + evaluator_model）
- 驱动多轮检索循环，直到证据充分或达到 max_rounds
- 仅在 `retrieval.strategy: agentic` 时激活，`single_step` 路径不变

**新增 `local_index` Knowledge Provider**（替代 `pageindex` 和 `local_pageindex`）：
- 底层引擎：LlamaIndex TreeIndex
- 支持结构化接口：`list_structure()`、`retrieve_at_scope()`
- 通过 `RetrievalCapabilities` 声明能力
- 作为可插拔可选依赖（`tree` 组）

**废弃远程 `pageindex` provider**：
- 删除 `pageindex.py` 和 `pageindex_ingestion.py`
- 现有 `pageindex` source 配置需迁移到 `local_index`，提供迁移脚本
- 现有引用 `pageindex` source 的 Published Agent Version 需强制重新发布
- 理由：简化架构，单一索引引擎

### 组件设计

#### RetrievalPlanner

**职责**：
1. 分析问题，规划检索策略
2. 调用 provider 执行检索
3. 用 evaluator_model 评估证据是否充分
4. 输出结构化 Action Plan 决定下一步

**Action Plan（V1）**：
```python
@dataclass(frozen=True)
class RetrievalAction:
    action: Literal["rewrite", "sufficient", "abort"]
    reason: str
    new_query: str | None = None  # for rewrite
```

每轮执行流程：`retrieve(query)` → `evaluate(evidence)` → 输出 Action。trace 中的 `action` 字段记录评估决策（`rewrite`/`sufficient`/`abort`），`retrieve` 本身是每轮的默认检索行为，不是 action 值。

**终止条件**：
- LLM 软判断：evaluator_model 输出 `sufficient` 或 `abort`
- 硬上限：`max_rounds`（默认 3）兜底

**错误处理（fail-closed）**：
- Planner LLM 调用失败 → 返回前一轮已累积的证据，终止循环
- Evaluator LLM 调用失败 → 视为 `abort`，返回已累积证据
- Action Plan 解析失败 → 视为 `abort`，返回已累积证据
- Provider 检索超时/失败 → 返回前一轮已累积的证据
- 所有失败记录到 trace，带 stable error code

**与 BlendedKnowledgeProvider 的关系**：
- V1：Planner 在 BlendedProvider 之上，每轮查询所有绑定 source。Planner 只看到合并后的证据，只做 query rewrite + sufficient/abort
- V2：演进到 per-source awareness，可以做 `narrow_scope` 和 `try_different_source`。**V2 需要重构 Planner-Provider 边界**（Planner 需要访问 per-source 结果而非 BlendedProvider 合并结果），接受返工成本
- 对于不支持结构化接口的 provider，Planner 只做 query rewrite + 普通 `retrieve()`，不调用结构化接口

**治理**：
- 外层一次 `before_retrieval` policy gate
- 内层每轮只做 trace 审计，不做 policy gate
- 最终证据评估和 model call 做 policy gate

#### Local Index Provider

**底层引擎**：LlamaIndex TreeIndex

**索引构建**（worker 阶段）：
1. 文档解析（PDF/Markdown）→ LlamaIndex Document
2. `TreeIndex.from_documents()` → 用 ProofAgentLLM(ingestion_model) 生成节点摘要
3. 持久化：LlamaIndex 原生格式 + Proof Agent 元数据 sidecar（`artifact_meta.json`）
4. Sidecar 包含：revision_id、content_hash、ingestion_config_fingerprint、engine_version、engine_name
5. Sidecar 是 provider-agnostic 的 artifact 元数据契约，未来其他本地索引引擎也应复用同一套格式；Knowledge Hub V1 不包含 `local_vector`

**检索时**：
- 单文档内：LlamaIndex `TreeSelectLeafRetriever` 做树遍历（用 ProofAgentLLM(routing_model)）
- 跨文档：Planner 做路由选择
- 支持结构化接口：
  - `list_structure()` → `tuple[DocumentNode, ...]`
  - `retrieve_at_scope(scope_id, top_k)` → `tuple[EvidenceChunk, ...]`

**DocumentNode 契约**：
```python
@dataclass(frozen=True)
class DocumentNode:
    node_id: str
    title: str
    summary: str | None
    depth: int
    child_ids: tuple[str, ...]
    metadata: Mapping[str, Any]  # tags, document_type, business_category
```

#### ProofAgentLLM 桥接

**目的**：让 LlamaIndex 的 LLM 调用走 Proof Agent 的 ModelProvider 协议

**实现**：最小同步接口，显式禁用异步

```python
class ProofAgentLLM(CustomLLM):  # extends llama_index.core.llms.CustomLLM
    def __init__(self, model_provider: ModelProvider, role: ModelCallRole):
        self._provider = model_provider
        self._role = role
    
    def complete(self, prompt, **kwargs) -> CompletionResponse:
        # 转发到 ModelProvider.generate()
        # 复用 Proof Agent 的 trace、token 估算
    
    def chat(self, messages, **kwargs) -> ChatResponse:
        # 转发到 ModelProvider.generate()，转换消息格式
    
    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name=self._provider.model_name, is_chat_model=True)
    
    # 显式禁用异步接口
    async def acomplete(self, *args, **kwargs) -> CompletionResponse:
        raise NotImplementedError("ProofAgentLLM does not support async. Use sync interface.")
    
    async def achat(self, *args, **kwargs) -> ChatResponse:
        raise NotImplementedError("ProofAgentLLM does not support async. Use sync interface.")
```

**LlamaIndex 同步模式配置**：TreeIndex 构建和检索时，需确保 LlamaIndex 使用同步 LLM 调用路径。在 `Settings` 或 `ServiceContext` 中配置 `ProofAgentLLM` 实例作为 LLM，并验证 TreeSelectLeafRetriever 的实际调用链路。

**好处**：
- 统一 LLM 调用链路
- 所有 LLM 调用都有 trace identity（`ModelCallRole.RETRIEVAL_PLANNER` / `RETRIEVAL_EVALUATOR` / `INGESTION` / `ROUTING`）
- 复用现有的 model registry 和 telemetry

#### 分层协议

**KnowledgeProvider（基础）**：
```python
class KnowledgeProvider(Protocol):
    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self: ...
    def retrieve(self, query, *, top_k=None) -> tuple[EvidenceChunk, ...]: ...
    @property
    def capabilities(self) -> RetrievalCapabilities: ...
    @property
    def provider_name(self) -> str: ...
```

**StructuredKnowledgeProvider（扩展）**：
```python
class StructuredKnowledgeProvider(KnowledgeProvider, Protocol):
    def list_structure(self) -> tuple[DocumentNode, ...]: ...
    def retrieve_at_scope(self, scope_id, *, top_k=None) -> tuple[EvidenceChunk, ...]: ...
```

**RetrievalCapabilities**：
```python
@dataclass(frozen=True)
class RetrievalCapabilities:
    supports_structure_listing: bool = False
    supports_scoped_retrieval: bool = False
```

- `local_index` 实现 `StructuredKnowledgeProvider`，`capabilities` 返回两个 `True`
- 其他 provider 只实现 `KnowledgeProvider`，`capabilities` 返回两个 `False`
- Planner 通过 `capabilities` 标志位探测（不用 `isinstance`）：
  ```python
  if provider.capabilities.supports_structure_listing:
      nodes = cast(StructuredKnowledgeProvider, provider).list_structure()
  ```

### 配置模型

#### RetrievalConfig 扩展

```python
class RetrievalConfig(FrozenModel):
    strategy: str  # "single_step" | "agentic"
    top_k: int = 3
    min_score: float = 0.2
    max_steps: int | None = None       # 管外层 ReAct 循环（现有，不变）
    max_rounds: int = 3                # 新增：管内层 Planner 循环
    planner_model: ModelConfig | None = None       # 已有字段，现赋予 RetrievalPlanner 消费
    evaluator_model: ModelConfig | None = None     # 新增：评估用模型（默认继承 planner_model）
    allow_query_rewrite: bool = False  # 保持现有默认值，agentic strategy 时需显式启用
    allow_rerank: bool = False
    allow_single_step_fallback: bool = False
```

**`max_steps` vs `max_rounds` 语义**：
- `max_steps`：控制外层 ReAct 工作流循环（tool calling 步数），仅在 `workflow.template` 为 ReAct 类型时生效
- `max_rounds`：控制内层 RetrievalPlanner 检索循环（query rewrite 轮数），仅在 `retrieval.strategy: agentic` 时生效
- 两者独立，互不影响。一个 ReAct agent 可以在每个 step 中触发一次 agentic 检索，此时 `max_steps` 限制 tool calling 步数，`max_rounds` 限制每步内的检索轮数

#### Knowledge Source 配置（local_index）

```yaml
knowledge_sources:
  - source_id: docs
    provider: local_index
    params:
      index_path: ./data/index
      ingestion_model:
        provider: openai
        name: gpt-4o-mini
        params:
          api_key_env: OPENAI_API_KEY
      routing_model:  # 继承 ingestion_model，可覆盖
        provider: openai
        name: gpt-4o-mini
        params:
          api_key_env: OPENAI_API_KEY
```

**配置验证**：`KnowledgeConfig.params` 仍为 `Mapping[str, Any]`（不变），嵌套的 `ingestion_model`/`routing_model` 在 `LocalIndexProvider.from_config()` 内部从 params dict 提取并手动构建 `ModelConfig` + `ModelProvider`。验证逻辑：
- 缺少 `ingestion_model` → 抛 `ProofAgentError("PA_KNOWLEDGE_003", ...)`
- `routing_model` 缺失 → 继承 `ingestion_model` 配置
- 凭证环境变量未设置 → 在 ModelProvider 构建时 fail-closed（复用现有行为）

### 依赖管理

**新增可选依赖组 `tree`**：

```toml
[project.optional-dependencies]
tree = ["llama-index-core>=0.12.0"]
all = ["proof-agent[openai,vector,tree]"]
```

- `llama-index-core` 是最小核心包，不含 `llama-index-openai` 等 LLM 集成包
- 通过 `ProofAgentLLM` 桥接，不需要 `llama-index-openai`
- 注意：`llama-index-core` 会引入传递依赖（tiktoken、numpy、dataclasses-json、typing-inspect 等），估计额外 ~15-20 个包
- 不安装时 `local_index` provider 不可用，`from_config()` 报 `ProofAgentError`（与其他缺失可选依赖的 provider 行为一致）

### Trace 审计

**复用现有 trace event 类型**：
- 每轮：`retrieval_step`、`model_request`、`model_response`（带 `round_id` 字段）
- 结束：`agentic_retrieval_completed` 汇总 event

**round_id 关联**：同一轮的 retrieval_step、model_request、model_response 共享 `round_id`

**model_request 区分**：现有 `model_request` payload 中已有 `role` 字段（`ModelCallRole.FINAL_ANSWER`）。新增的 `RETRIEVAL_PLANNER`/`RETRIEVAL_EVALUATOR` 角色自动通过 `role` 字段区分，下游 Dashboard Run Detail 按 `role` 过滤分组。

**汇总 event**：
```python
trace.emit("agentic_retrieval_completed", {
    "total_rounds": 3,
    "total_candidates": 8,
    "total_accepted": 5,
    "final_action": "sufficient",
    "rounds": [
        {"round_id": "r1", "action": "rewrite", "query": "...", "new_query": "...", "candidate_count": 3},
        {"round_id": "r2", "action": "rewrite", "query": "...", "new_query": "...", "candidate_count": 3},
        {"round_id": "r3", "action": "sufficient", "query": "...", "candidate_count": 2},
    ]
})
```

### LLM 角色扩展（ADR-0005 Amendment）

新增四个正式 LLM 角色：

- `ModelCallRole.RETRIEVAL_PLANNER`：RetrievalPlanner 的规划 LLM（用 planner_model）
- `ModelCallRole.RETRIEVAL_EVALUATOR`：RetrievalPlanner 的评估 LLM（用 evaluator_model）
- `ModelCallRole.INGESTION`：索引构建时生成节点摘要（用 ingestion_model）
- `ModelCallRole.ROUTING`：检索时树遍历节点选择（用 routing_model）

每个角色独立 trace identity，输出必须归一化为 Proof Agent 契约（structured output → Action Plan）。

### 与 ADR-0014 的关系

**复用 ADR-0014 的上层设计**：
- Dashboard 管理的文档上传（PDF + Markdown）
- Revision 状态机：`PENDING → READY / FAILED`
- Worker 进程 + 文件队列
- Snapshot 发布流程
- 增量重索引（基于配置指纹 + 内容哈希）
- Knowledge Source 级别的 ingestion/routing model 配置

**替换底层引擎**：
- 从"调用外部 PageIndex ingestion API"变为"本地 LlamaIndex TreeIndex 构建"
- Provider 名称从 `local_pageindex` 改为 `local_index`

**更新不兼容条款**：
- "PageIndex tree indexes" → LlamaIndex TreeIndex
- ingestion HTTP API → 本地引擎
- `endpoint_env`、`api_key_env` → 不再需要，改为本地引擎配置
- "路由模型使用 PageIndex tree summaries" → LlamaIndex 节点摘要
- artifact 指纹兼容性 → LlamaIndex 持久化格式

### 测试要求

所有新增和修改代码需达到 **80% 最低测试覆盖率**，重点覆盖：

- **RetrievalPlanner 主循环**：单轮 sufficient、多轮 rewrite + sufficient、max_rounds 硬上限、LLM 失败 fail-closed、Action Plan 解析失败、证据累积
- **ProofAgentLLM 桥接**：`complete()` 和 `chat()` 转发正确性、`metadata` 属性、异步禁用抛异常
- **LocalIndexProvider**：索引构建 + 持久化 + 加载、`retrieve()` 基础检索、`list_structure()` 和 `retrieve_at_scope()` 结构化接口、`capabilities` 返回正确值
- **RetrievalConfig**：`max_rounds` 默认值、`evaluator_model` 继承 `planner_model`、`allow_query_rewrite` 默认保持 `False`
- **集成测试**：完整 agentic 检索流程（deterministic model provider 驱动）

## Consequences

### 正面影响

1. **检索质量提升**：多轮迭代 + query rewrite 显著提升复杂问题的检索质量
2. **部署简化**：去掉外部 PageIndex 服务依赖，单一进程运行
3. **延迟降低**：本地索引查询无 HTTP roundtrip
4. **架构灵活性**：Planner 与 Provider 解耦，未来可以接入其他索引引擎
5. **治理一致性**：所有 LLM 调用走 ModelProvider 协议，统一 trace 和 policy gate
6. **可插拔设计**：`local_index` 作为可选依赖，不影响确定性 demo 和 CI

### 负面影响

1. **依赖增加**：引入 LlamaIndex（可选的），`llama-index-core` 约引入 15-20 个传递依赖（tiktoken、numpy 等）
2. **LLM 开销增加**：多轮检索 + 证据评估消耗额外 tokens
3. **配置复杂度**：新增 evaluator_model、max_rounds 等配置项
4. **迁移成本**：现有 `pageindex` source 需要迁移到 `local_index`，Published Agent Version 需强制重新发布
5. **代码复杂度**：新增 RetrievalPlanner、ProofAgentLLM、StructuredKnowledgeProvider 等组件
6. **ProofAgentLLM 桥接维护**：需跟踪 LlamaIndex `CustomLLM` 接口变化，pin 版本号

### 风险与缓解

**风险 1：LLM 成本失控**
- 缓解：`max_rounds` 硬上限兜底，evaluator_model 可以用便宜模型

**风险 2：LlamaIndex 版本锁定**
- 缓解：元数据 sidecar 与 LlamaIndex 格式解耦，未来可以换引擎

**风险 3：Planner 判断不准**
- 缓解：结构化 Action Plan 可审计，错误判断会记录在 trace 中

**风险 4：索引构建失败**
- 缓解：复用 ADR-0014 的 revision 状态机和重试机制

**风险 5：V1→V2 Planner 架构重构**
- 缓解：V1 明确标注边界重构成本，V2 action plan 扩展自然引入 per-source awareness

## Implementation Sequence

1. **Contracts & Protocols**：
   - 新增 `RetrievalCapabilities`、`DocumentNode`、`RetrievalAction` 数据契约
   - 扩展 `KnowledgeProvider` 协议（新增 `capabilities` 属性，保留 `from_config`）
   - 新增 `StructuredKnowledgeProvider` 协议
   - 扩展 `ModelCallRole` 枚举（新增四个角色）
   - 扩展 `RetrievalConfig`（新增 `max_rounds`、`evaluator_model`；赋予 `planner_model` 实际消费者）
   - 单元测试：数据契约序列化/反序列化

2. **ProofAgentLLM 桥接**：
   - 实现 `ProofAgentLLM extends CustomLLM`（`complete` + `chat` + `metadata` + `model_name`，禁用异步）
   - 单元测试：验证 `ModelProvider` 协议桥接正确性

3. **Local Index Provider**：
   - 实现 `LocalIndexProvider`（基础 `retrieve()`）
   - 实现结构化接口（`list_structure()`、`retrieve_at_scope()`）
   - 实现 `from_config()` 内部解析 `ingestion_model`/`routing_model`
   - 实现索引构建逻辑（`TreeIndex.from_documents()`）
   - 实现持久化逻辑（LlamaIndex 原生 + provider-agnostic sidecar）
   - 注册到 `PROVIDER_MAP`（`"local_index": LocalIndexProvider`）
   - 单元测试：索引构建、持久化、检索、结构化接口、配置验证

4. **RetrievalPlanner**：
   - 实现 Planner 主循环（分析问题 → 检索 → 评估 → action）
   - 实现 Action Plan 解析（structured output）
   - 实现 query rewrite 逻辑
   - 实现终止条件判断（LLM 软判断 + max_rounds 硬兜底）
   - 实现错误处理（fail-closed，返回累积证据）
   - 实现 trace 审计（复用现有 event 类型 + round_id）
   - 单元测试：单轮、多轮、终止条件、LLM 失败、Action Plan 解析失败、trace 输出

5. **Orchestrator 集成**：
   - 修改 `_run_agentic_retrieval()` 调用 RetrievalPlanner
   - 修改 composition root 构建 Planner（注入 planner_model、evaluator_model）
   - 集成测试：完整 agentic 检索流程
   - **集成验证 gate**：用 deterministic model provider 驱动所有现有场景，确认 `local_index` provider 在 agentic 策略下行为正确

6. **废弃 PageIndex**（仅在步骤 5 集成验证通过后执行）：
   - 删除 `pageindex.py` 和 `pageindex_ingestion.py`
   - 从 `registry.py` 删除 `"pageindex"` 条目
   - 提供迁移脚本：`pageindex` source → `local_index` source
   - 现有 Published Agent Version 引用 `pageindex` 的需强制重新发布
   - 更新示例 `agent.yaml`（`pageindex` → `local_index`）
   - 更新测试 fixtures

7. **Documentation**：
   - 更新 CONTEXT.md（废弃 PageIndex Provider，新增 Local Index Provider、RetrievalPlanner 等词条）
   - 创建 ADR-0015（本文档）
   - Amendment ADR-0005（新增 LLM 角色）
   - Amendment ADR-0014（引擎替换，provider 改名）
   - Amendment ADR-0001（删除 pageindex provider）

## Related ADRs

- ADR-0001: Knowledge Provider Contract and Retrieval Strategy（需 amendment）
- ADR-0005: LLM Role Boundaries and Harness-Normalized Output（需 amendment）
- ADR-0014: Local PageIndex Knowledge Source Ingestion（需 major update）

## References

- LlamaIndex TreeIndex: https://docs.llamaindex.ai/en/stable/module_guides/indexing/tree_index/
- LlamaIndex CustomLLM: https://docs.llamaindex.ai/en/stable/module_guides/models/llms/usage_custom/
