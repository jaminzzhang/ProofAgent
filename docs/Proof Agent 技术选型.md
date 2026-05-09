# Proof Agent v1 技术选型

> 基于 PRD、Framework Design、Technical Plan、Engineering Review、可行性分析报告的综合技术选型分析。

## 选型原则

1. **Local-first**：v1 所有核心路径必须可离线运行，deterministic demo 不依赖任何 API key
2. **组合优于自建**：不重复造轮子，在成熟组件之上建立 Control Envelope 控制合约
3. **可控性优先**：选型必须支持 Harness Engineering 的每个策略决策点，不能因为框架限制而绕过控制
4. **最小依赖**：每个依赖必须有不可替代的理由，避免依赖链膨胀
5. **v1 窄范围**：只为一个 Enterprise QA 模板选型，不为假设的未来需求选型

---

## 1. 语言与运行时

### 决策：Python 3.12+

| 项 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12+ | LangGraph、LlamaIndex、MCP SDK、LangChain 生态均为 Python-first；3.12 是 LangGraph 推荐版本，3.9 已 EOL |
| 包管理 | `uv` + `pyproject.toml` | 比 pip 快 10-100x，原生支持 lockfile 和虚拟环境；兼容 `pip install -e .` |

**不选 TypeScript/Go 的理由：** LangGraph、MCP SDK 的 Python API 是最成熟的；Agent 生态的核心库（LlamaIndex、LangChain）均以 Python 为主。v1 不存在性能瓶颈需要编译型语言。

---

## 2. Workflow Runtime（Agent 流程编排）

### 决策：LangGraph 1.1.x

| 项 | 详情 |
|---|---|
| 包 | `langgraph >= 1.1.0` |
| 关键能力 | StateGraph、conditional edges、interrupt()、SQLite checkpointer |
| Python 要求 | >= 3.10（推荐 3.12） |

**选型理由：**

- **interrupt() 实现工具审批**：LangGraph 的 `interrupt()` 函数天然映射 Harness 的 approval state machine。调用 `interrupt()` 暂停工作流，等待人工输入后恢复——无需自建状态持久化
- **Conditional edges 实现策略分支**：`add_conditional_edges()` 直接映射 PolicyEngine 的 `allow/deny/require_approval/escalate` 路由
- **Checkpointer 实现可恢复执行**：SQLite checkpointer 免运维，approval timeout 后可从 checkpoint 恢复
- **确定性 demo 共用同一工作流**：deterministic provider 只替换 LLM 调用节点，不绕过任何控制节点

**不选替代方案的理由：**

| 替代方案 | 不选理由 |
|---|---|
| CrewAI | 角色模型过于高层，无法插入细粒度策略决策点；缺乏 interrupt 和 checkpoint |
| AutoGen | 对话驱动模型不适合显式策略门控；持久化能力弱 |
| 自研状态机 | 重复 LangGraph 已解决的问题（interrupt、checkpoint、conditional routing），浪费 v1 时间 |
| Temporal | 过重，需要独立服务进程；LangGraph 的 SQLite checkpointer 对 v1 本地场景足够 |

**关键约束：** LangGraph 类型不得泄漏到 config、policy、trace、receipt 模型。LangGraph 只在 `runtime/langgraph_runner.py` 中使用。

---

## 3. Knowledge / RAG（知识检索与证据评估）

### 决策：自建轻量 RAG（sentence-transformers + ChromaDB）

| 项 | 详情 |
|---|---|
| Embedding | `sentence-transformers` + `all-MiniLM-L6-v2`（本地，无需 API） |
| 向量存储 | `chromadb`（嵌入式模式，`PersistentClient`，无需服务进程） |
| 文档解析 | 自建 Markdown chunker（按 heading 分块，保留 source/line 元数据） |
| 证据评估 | 自建 `EvidenceEvaluator`（基于 similarity score + policy threshold） |
| 引用追踪 | 自建 citation mapper（chunk metadata → source file + heading） |

**选型理由：**

- **完全可控**：每个环节都经过 Harness 策略门控，无框架黑箱
- **零网络依赖**：embedding 模型本地下载后缓存，ChromaDB 嵌入式运行
- **确定性保证**：similarity score 和 evidence threshold 完全确定性，测试稳定
- **依赖极小**：仅 `sentence-transformers` + `chromadb` 两个核心依赖
- **与 PolicyEngine 天然集成**：evidence score 直接传入 `PolicyEngine.before_answer` 做决策

**不选 LlamaIndex 的理由：**

| 维度 | LlamaIndex | 自建 |
|---|---|---|
| CitationQueryEngine | 开箱即用 | 需自建（~100 行） |
| FaithfulnessEvaluator | 内置 | 不需要——Harness 用策略+证据控制，不依赖 LLM 做评估 |
| 依赖数量 | 50+ 子包，依赖链长 | 2 个核心依赖 |
| 可控性 | 框架黑箱，中间步骤难以插入策略门控 | 每步经过 Harness |
| API 稳定性 | 频繁变更，0.14.x 仍在 break | 零 churn |
| v1 适配度 | 过度设计，大部分功能用不到 | 刚好够用 |

**不选 LangChain RAG 的理由：** 无内置 citation 支持；evaluation 工具（LangSmith）倾向云端；社区反馈 API 不稳定；抽象层过深不适合受控 RAG。

**实现预估：** chunker ~80 行、retriever ~60 行、evidence evaluator ~100 行、citation mapper ~40 行，合计 ~280 行。

---

## 4. MCP Tool（工具调用与审批）

### 决策：`mcp` SDK + stdio transport + `langchain-mcp-adapters`

| 项 | 详情 |
|---|---|
| MCP SDK | `mcp[cli] >= 1.27.0`（Anthropic 官方） |
| Transport | stdio（本地子进程通信，无需 HTTP 服务） |
| LangGraph 集成 | `langchain-mcp-adapters`（MCP tool → LangGraph tool 转换） |
| 审批机制 | LangGraph `interrupt()` + Harness PolicyEngine，不依赖 MCP SDK 的 advisory annotations |

**选型理由：**

- **stdio transport 零运维**：无 HTTP 服务、无端口、无 CORS，适合 v1 本地 mock
- **`langchain-mcp-adapters` 无缝集成 LangGraph**：MCP tool 自动转为 LangGraph callable tool
- **审批由 Harness 控制，不由 MCP 控制**：MCP tool annotations 是 advisory，Harness 的 `before_tool_call` 策略决策才是强制性审批

**mock tool 设计：**

```text
proof-agent run
  → PolicyEngine.before_tool_call → decision: require_approval
  → LangGraph interrupt() → 暂停，CLI 显示审批提示
  → 用户输入 y/n → 恢复工作流
  → MCP mock tool 执行（stdio）或返回安全响应
```

---

## 5. CLI（命令行界面）

### 决策：Typer

| 项 | 详情 |
|---|---|
| 包 | `typer >= 0.12.0` |
| 测试 | `typer.testing.CliRunner` |

**选型理由：** 类型注解驱动的 CLI 框架，自动生成 help 和参数解析，与 Pydantic 模型自然配合。比 click 更现代，比 argparse 更简洁。

**v1 CLI surface：**

```text
proof-agent demo                                    # 确定性演示，无需 LLM key
proof-agent run <agent.yaml>                        # 运行完整企业 QA
proof-agent doctor                                  # 检查本地环境就绪
proof-agent inspect <trace.jsonl|governance_receipt.md>  # 查看审计产物
proof-agent compare <agent.yaml> --question "..."   # Plain RAG vs Harness RAG 对比
```

---

## 6. Data Contracts（数据合约）

### 决策：Pydantic v2

| 项 | 详情 |
|---|---|
| 包 | `pydantic >= 2.7.0` |
| 用途 | AgentManifest、PolicyDecision、TraceEvent、ApprovalState、EvidenceChunk、ReceiptOutcome |

**选型理由：**

- **JSON schema 自动生成**：合约模型可直接导出 schema 用于 YAML 验证
- **field validator 替代手动校验**：`@field_validator` 在模型创建时拒绝非法值（如 unsupported runtime）
- **LangGraph 原生兼容**：LangGraph StateGraph 接受 Pydantic model 作为 state schema
- **不可变模式**：`model_config = ConfigDict(frozen=True)` 强制不可变，符合项目编码规范
- **序列化控制**：`model_dump()` 和 `model_dump_json()` 精确控制 trace 输出

---

## 7. Audit（审计：Trace、Receipt、Redaction）

### 决策：纯标准库 + Pydantic

| 项 | 实现 |
|---|---|
| Trace Writer | `json.dumps()` + 文件追加写入，每行一个 TraceEvent（Pydantic model） |
| Receipt Generator | Jinja2 模板渲染 Markdown（从 trace events 聚合） |
| Redaction | Pydantic model 序列化时 filter sensitive fields |

**不引入额外框架的理由：**

- Trace 是 JSONL 文本文件，标准库足够
- Receipt 是 Markdown 文本，模板渲染足够
- 不依赖 Langfuse / OpenTelemetry / LangSmith——v1 以本地 JSONL 为审计事实源

---

## 8. Testing（测试）

### 决策：pytest + ruff

| 项 | 包 | 用途 |
|---|---|---|
| 测试框架 | `pytest >= 8.0` | 单元/集成/E2E 测试 |
| CLI 测试 | `typer.testing.CliRunner` | CLI 命令集成测试 |
| Lint/Format | `ruff >= 0.4.0` | 替代 flake8 + isort + black，一个工具 |
| 类型检查 | `mypy`（CI 可选） | 合约模型类型安全 |

---

## 9. Distribution（分发）

### 决策：Docker Compose + PyPI

| 项 | 实现 |
|---|---|
| 本地评估 | `docker compose up`（含 ChromaDB volume + proof-agent CLI） |
| PyPI 安装 | `pip install proof-agent-kit` |
| 开发安装 | `uv pip install -e ".[dev]"` |
| CI | GitHub Actions（lint → type check → pytest → CLI smoke → artifact check） |

---

## 完整依赖清单

### 核心依赖（pyproject.toml dependencies）

```toml
dependencies = [
    "langgraph>=1.1.0",
    "langchain-mcp-adapters>=0.1.0",
    "mcp[cli]>=1.27.0",
    "pydantic>=2.7.0",
    "typer>=0.12.0",
    "pyyaml>=6.0.0",
    "chromadb>=1.5.0",
    "sentence-transformers>=3.0.0",
    "jinja2>=3.1.0",
]
```

### 开发依赖（pyproject.toml optional-dependencies.dev）

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]
```

---

## 技术选型总览图

```text
┌─────────────────────────────────────────────────────────────┐
│                    Proof Agent v1 Stack                      │
├──────────┬──────────────────────────────────────────────────┤
│ CLI      │ typer → CliRunner 测试                           │
│ Config   │ pydantic v2 + pyyaml → agent.yaml 合约           │
│ Policy   │ pydantic v2 → PolicyDecision 类型化决策          │
│ Workflow │ langgraph 1.1.x → StateGraph + interrupt()       │
│ Knowledge│ sentence-transformers + chromadb → 本地 RAG      │
│ Evidence │ 自建 EvidenceEvaluator → similarity + threshold  │
│ Tools    │ mcp SDK (stdio) + langchain-mcp-adapters         │
│ Approval │ langgraph interrupt() + PolicyEngine 门控        │
│ Memory   │ 自建 SessionMemory → in-process dict             │
│ Trace    │ pydantic → JSONL (标准库写入)                     │
│ Receipt  │ pydantic + jinja2 → Markdown                     │
│ Redaction│ pydantic 序列化 filter                           │
│ Demo     │ 自建 DeterministicProvider → 替换 LLM 调用       │
│ Test     │ pytest + ruff + typer.testing.CliRunner          │
│ Distrib  │ Docker Compose + pyproject.toml                  │
└──────────┴──────────────────────────────────────────────────┘
```

---

## 与现有设计文档的对比

| 设计文档中的选型 | 本分析结论 | 变化 | 理由 |
|---|---|---|---|
| LangGraph workflow | **保持** LangGraph 1.1.x | 版本明确化 | interrupt() 天然支持 approval state |
| LlamaIndex RAG | **改为** 自建轻量 RAG | **变化** | LlamaIndex 依赖过重，citation/evidence 自建更可控 |
| MCP mock tool | **保持** mcp SDK + stdio | 确认 | stdio transport 零运维，适配器桥接 LangGraph |
| typer CLI | **保持** typer | 确认 | 类型注解驱动，与 Pydantic 配合好 |
| pydantic v2 | **保持** pydantic v2 | 确认 | frozen=True 强制不可变 |
| pytest + ruff | **保持** | 确认 | 成熟稳定 |
| Docker Compose | **保持** | 确认 | 本地评估路径 |

**唯一重要变化：** 知识检索从 LlamaIndex 改为自建轻量 RAG。理由是 LlamaIndex 的 50+ 子包依赖和频繁 API 变更对 v1 的"受控"原则构成风险，而自建 ~280 行即可覆盖 chunking + retrieval + evidence + citation，且每一步都经过 Harness 策略门控。
