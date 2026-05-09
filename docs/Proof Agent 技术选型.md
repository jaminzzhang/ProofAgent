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

### 决策：一期自建轻量 RAG，预留 Agentic / Remote RAG Provider

| 项 | 详情 |
|---|---|
| Provider 抽象 | `KnowledgeProvider` 接口，统一返回 `EvidenceChunk` 和 citation metadata |
| v1 Provider | `LocalKnowledgeProvider`：本地文档 + 本地向量检索 |
| Embedding | `sentence-transformers` + `all-MiniLM-L6-v2`（本地，无需 API） |
| 向量存储 | `chromadb`（嵌入式模式，`PersistentClient`，无需服务进程） |
| 文档解析 | 自建 Markdown chunker（按 heading 分块，保留 source/line 元数据） |
| 证据评估 | 自建 `EvidenceEvaluator`（基于 similarity score + policy threshold） |
| 引用追踪 | 自建 citation mapper（chunk metadata → source file + heading） |
| 后续 Provider | Agentic RAG（如 PageIndex 等）、远程 RAG API、企业知识库检索服务 |

**选型理由：**

- **一期完全可控**：本地 chunk、index、retrieval、evidence evaluation 每个环节都经过 Harness 策略门控，无框架黑箱
- **Provider 边界清晰**：workflow 和 policy 只消费标准化 `EvidenceChunk`，不绑定具体 RAG 实现
- **零网络依赖**：embedding 模型本地下载后缓存，ChromaDB 嵌入式运行
- **确定性保证**：similarity score 和 evidence threshold 完全确定性，测试稳定
- **依赖极小**：一期仅 `sentence-transformers` + `chromadb` 两个 Knowledge 核心依赖
- **与 PolicyEngine 天然集成**：evidence score 直接传入 `PolicyEngine.before_answer` 做决策

**后续扩展原则：**

- Agentic RAG、PageIndex 类 provider、远程 RAG provider 必须实现同一个 `KnowledgeProvider` 接口。
- Provider 可以有自己的检索、重排、查询规划或远程 API 调用逻辑，但输出必须标准化为 `EvidenceChunk`、citation metadata、retrieval trace payload。
- `PolicyEngine.before_retrieval` 和 `PolicyEngine.before_answer` 仍由 Harness 执行；任何 provider 不得绕过 evidence threshold、citation requirement、refusal/escalation policy。
- 远程 RAG 的请求、响应、超时、错误、redaction 必须写入 JSONL trace；provider 返回的来源信息必须能映射到 Governance Receipt。

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

**实现预估：** provider interface ~40 行、chunker ~80 行、retriever ~60 行、evidence evaluator ~100 行、citation mapper ~40 行，合计 ~320 行。

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

## 10. 推荐目录结构

v1 采用 **单 Python package + examples + tests + local runtime assets** 的结构。目录边界围绕 Control Envelope 的核心职责划分，而不是围绕底层框架划分；LangGraph、ChromaDB、MCP 等第三方实现只能出现在各自 adapter/runtime 层，不能污染公共合约模型。

```text
.
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── docs/
│   ├── Proof Agent PRD.md
│   ├── Proof Agent Framework Design.md
│   ├── Proof Agent Technical Plan.md
│   ├── Proof Agent 技术选型.md
│   ├── concepts/
│   │   ├── agent-contract.md
│   │   ├── approval-state-contract.md
│   │   ├── control-envelope.md
│   │   ├── governance-receipt-contract.md
│   │   ├── policy-engine.md
│   │   ├── trace-event-contract.md
│   │   └── trust-boundaries.md
│   └── examples/
│       ├── enterprise-qa.md
│       ├── governance-receipt.md
│       └── launch-script.md
├── proof_agent/
│   ├── __init__.py
│   ├── cli.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── manifest.py
│   │   ├── loader.py
│   │   └── validation.py
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── approval.py
│   │   ├── evidence.py
│   │   ├── policy.py
│   │   ├── receipt.py
│   │   ├── run.py
│   │   ├── tool.py
│   │   └── trace.py
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── orchestrator.py
│   │   ├── nodes.py
│   │   ├── routing.py
│   │   └── state.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   └── langgraph_runner.py
│   ├── policy/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── loader.py
│   │   └── rules.py
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── chunker.py
│   │   ├── citations.py
│   │   ├── evaluator.py
│   │   ├── index.py
│   │   ├── provider.py
│   │   └── local_provider.py
│   ├── memory/
│   │   ├── __init__.py
│   │   └── session.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── approval.py
│   │   ├── gateway.py
│   │   ├── mcp_mock.py
│   │   └── registry.py
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── evidence.py
│   │   ├── quality.py
│   │   ├── safety.py
│   │   ├── schema.py
│   │   └── tool_result.py
│   ├── audit/
│   │   ├── __init__.py
│   │   ├── receipt.py
│   │   ├── redaction.py
│   │   ├── templates/
│   │   │   └── governance_receipt.md.j2
│   │   └── trace.py
│   ├── demo/
│   │   ├── __init__.py
│   │   ├── deterministic_provider.py
│   │   └── scenarios.py
│   └── compare/
│       ├── __init__.py
│       ├── harness_rag.py
│       └── plain_rag.py
├── examples/
│   └── enterprise_qa/
│       ├── agent.yaml
│       ├── policy.yaml
│       ├── tools.yaml
│       ├── questions.yaml
│       ├── knowledge/
│       │   ├── customer-support-policy.md
│       │   └── discount-policy.md
│       ├── expected/
│       │   ├── governance_receipt.md
│       │   └── trace.jsonl
│       └── README.md
├── runs/
│   └── .gitkeep
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── enterprise_qa/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── .github/
    └── workflows/
        └── ci.yml
```

### 目录结构原则

1. **`contracts/` 是稳定边界**：所有外部可理解的 Pydantic 合约放在这里，包括 `PolicyDecision`、`TraceEvent`、`EvidenceChunk`、`ApprovalState`、`RunResult`。其他模块只能依赖 contracts，不能重新定义同义模型。
2. **`runtime/` 隔离 LangGraph**：`workflow/` 表达 Proof Agent 自己的流程语义，`runtime/langgraph_runner.py` 负责把这些语义编译到 LangGraph。这样未来换 runtime 时，不需要改 policy、audit、knowledge、tools。
3. **`knowledge/` 一期自建最小 RAG，接口预留扩展**：`provider.py` 定义统一 `KnowledgeProvider` 边界，`local_provider.py` 实现本地文档 RAG；后续 Agentic RAG、PageIndex 类 provider、远程 RAG 只能作为 provider adapter 接入。
4. **`audit/` 只依赖 trace 合约**：Governance Receipt 必须从 JSONL trace 聚合生成，不能直接读取 workflow 内部状态，避免审计输出和真实执行记录分叉。
5. **`examples/enterprise_qa/` 是验收用例**：这个模板不是演示素材堆放处，而是 v1 的端到端 acceptance fixture。CLI、trace、receipt、policy、knowledge、tool approval 都必须能通过它验证。
6. **`proof_agent/demo/` 只放 demo 命令逻辑**：`proof-agent demo` 的 deterministic provider、固定问题选择、控制台展示逻辑放在 package 内；Enterprise QA 的模板资产仍以 `examples/enterprise_qa/` 为唯一事实源。
7. **`runs/` 是本地运行产物目录**：默认写入 `runs/latest/trace.jsonl` 和 `runs/latest/governance_receipt.md`，除 `.gitkeep` 外不提交运行产物。

---

## 11. 模块职责与依赖边界

| 模块 | 核心职责 | 可依赖 | 不应依赖 |
|---|---|---|---|
| `cli` | Typer 命令入口，参数解析，控制台输出 | `config`、`workflow`、`demo`、`compare`、`audit` | LangGraph 细节、ChromaDB client 细节 |
| `config` | 加载、校验 `agent.yaml` / `policy.yaml` / `tools.yaml` | `contracts`、`pyyaml`、`pydantic` | runtime、knowledge、tools 的具体实现 |
| `contracts` | 公共数据合约和枚举 | `pydantic`、标准库 | LangGraph、Typer、ChromaDB、MCP |
| `workflow` | Control Envelope 流程节点、状态、路由语义 | `contracts`、`policy`、`knowledge`、`memory`、`tools`、`validators`、`audit` | LangGraph 直接 API |
| `runtime` | 将 workflow 编译并运行到 LangGraph | `workflow`、`contracts`、`langgraph` | CLI 输出逻辑、业务模板内容 |
| `policy` | enforcement point 决策：检索、回答、工具、记忆 | `contracts`、`config` | LangGraph、MCP SDK、ChromaDB |
| `knowledge` | KnowledgeProvider 抽象、本地文档索引、检索、证据评分、引用映射 | `contracts`、`sentence-transformers`、`chromadb` | CLI、LangGraph、MCP SDK |
| `memory` | Session Memory 读写与策略前置数据 | `contracts` | 持久化数据库、用户长期画像 |
| `tools` | Tool Gateway、工具注册、MCP mock、审批状态转换 | `contracts`、`policy`、`mcp`、`langchain-mcp-adapters` | knowledge 内部实现 |
| `validators` | schema/evidence/tool/safety/quality 确定性校验 | `contracts` | LLM-as-judge、外部观测平台 |
| `audit` | JSONL Trace、redaction、Governance Receipt 生成 | `contracts`、`jinja2` | workflow 私有状态、未落 trace 的临时数据 |
| `demo` | 无 API key 的 deterministic demo 命令逻辑和打包后 fallback assets | `workflow`、`contracts`、`config` | 外部 LLM provider、examples 的私有文件结构 |
| `compare` | Plain RAG vs Harness RAG 对比 | `knowledge`、`workflow`、`audit` | Tool approval 私有实现 |

### 依赖方向

```text
cli
  ↓
config → contracts
  ↓
workflow → policy / knowledge / memory / tools / validators / audit
  ↓
runtime/langgraph_runner

examples → CLI 输入，不被 framework 反向依赖
runs     → CLI 输出，不被 tests 当作唯一事实源
```

**约束：**

- `contracts` 不能 import Proof Agent 其他业务模块。
- `policy` 只能返回 typed decision，不能直接执行工具、写 memory、写 trace。
- `tools` 必须通过 `ToolGateway` 暴露能力，workflow 不能直接调用 MCP mock tool。
- `audit.receipt` 只能从 trace events 生成 receipt，不能从运行时对象旁路生成。
- `workflow` 和 `policy` 只能依赖 `KnowledgeProvider` 输出的标准 evidence 合约，不能依赖 ChromaDB、PageIndex、远程 RAG API 等具体 provider 细节。
- `examples/enterprise_qa/` 是模板资产唯一事实源；`proof_agent/demo/` 可以按 scenario contract 读取它，或在包发布时使用同步生成的 bundled fallback assets，但不能维护另一套语义不同的 demo 数据。
- `compare.plain_rag` 可以绕过 Control Envelope，但必须只用于对比命令和测试，不能被 `run` 路径引用。

---

## 12. 配置与运行产物布局

### `agent.yaml`

`agent.yaml` 是 v1 的公开入口，负责声明 workflow、knowledge、model、policy、tools、memory 和 audit。推荐字段保持接近概念文档中的 Agent Contract：

```yaml
name: enterprise-qa
purpose: Governed enterprise knowledge Q&A

workflow:
  runtime: langgraph
  template: enterprise_qa

model:
  provider: deterministic
  name: proof-agent-demo

knowledge:
  provider: local
  path: ./knowledge
  index_path: ../../runs/indexes/enterprise_qa

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

### `policy.yaml`

`policy.yaml` 只表达规则，不嵌入 Python 代码。v1 支持的 enforcement points 固定为：

```text
before_retrieval
before_answer
before_tool_call
before_memory_write
```

### `tools.yaml`

`tools.yaml` 声明工具白名单、risk level、approval requirement 和 mock MCP 启动方式。工具是否实际执行由 `ToolGateway` 和 `PolicyEngine.before_tool_call` 共同决定。

### `runs/`

本地运行产物按 run 写入：

```text
runs/
├── latest/
│   ├── trace.jsonl
│   └── governance_receipt.md
├── indexes/
│   └── enterprise_qa/
└── 2026-05-09T120000Z/
    ├── trace.jsonl
    └── governance_receipt.md
```

`runs/latest` 可以是复制目录或软链接；跨平台优先时使用复制目录，避免 Windows symlink 权限问题。

---

## 13. 首批实现顺序

第一批代码应围绕 `proof-agent demo` 和 `proof-agent run examples/enterprise_qa/agent.yaml` 两条路径展开。

| 顺序 | 目录/文件 | 目标 |
|---|---|---|
| 1 | `pyproject.toml`、`proof_agent/cli.py` | 建立 CLI 入口和包安装方式 |
| 2 | `contracts/` | 固化 `AgentManifest`、`PolicyDecision`、`TraceEvent`、`RunResult` 等公共模型 |
| 3 | `config/` | 加载并校验 `agent.yaml`、`policy.yaml`、`tools.yaml` |
| 4 | `audit/trace.py`、`audit/receipt.py` | 先打通 trace JSONL 和 Governance Receipt shell |
| 5 | `demo/` | 实现无 API key deterministic provider 和固定 demo scenarios |
| 6 | `policy/`、`validators/` | 实现 retrieval/answer/tool/memory 的确定性决策和校验 |
| 7 | `knowledge/` | 定义 `KnowledgeProvider` 接口；实现一期 local provider、Markdown chunker、本地索引、检索、evidence evaluator、citation mapper |
| 8 | `workflow/`、`runtime/langgraph_runner.py` | 将 Control Envelope 流程跑在 LangGraph 上 |
| 9 | `tools/` | 接入 MCP mock tool、approval state、timeout/denied/granted trace |
| 10 | `compare/` | 实现 Plain RAG vs Harness RAG 对比命令 |
| 11 | `examples/enterprise_qa/` | 补齐可运行模板、样例知识、预期 trace/receipt |
| 12 | `tests/`、`.github/workflows/ci.yml` | 覆盖 CLI smoke、contracts、policy、evidence、trace、receipt、approval |

**开工验收线：**

- `proof-agent demo` 无 API key 可运行，并生成 trace + receipt。
- `proof-agent run examples/enterprise_qa/agent.yaml` 能走完整 Harness RAG 路径。
- `proof-agent compare` 能展示 Plain RAG 和 Harness RAG 对证据不足问题的行为差异。
- `pytest` 覆盖合约校验、policy decisions、evidence threshold、tool approval state、receipt outcome mapping。
- `ruff check` 通过，CI 至少包含 lint、tests、CLI smoke、artifact existence check。

---

## 与现有设计文档的对比

| 设计文档中的选型 | 本分析结论 | 变化 | 理由 |
|---|---|---|---|
| LangGraph workflow | **保持** LangGraph 1.1.x | 版本明确化 | interrupt() 天然支持 approval state |
| LlamaIndex RAG | **改为** 自建轻量 RAG | **变化** | LlamaIndex 依赖过重，citation/evidence 自建更可控 |
| Agentic / 远程 RAG | **预留** Provider adapter | 明确 deferred | v1 local-first，但 provider 边界必须支持后续接入 PageIndex 类 Agentic RAG 和远程企业知识服务 |
| MCP mock tool | **保持** mcp SDK + stdio | 确认 | stdio transport 零运维，适配器桥接 LangGraph |
| typer CLI | **保持** typer | 确认 | 类型注解驱动，与 Pydantic 配合好 |
| pydantic v2 | **保持** pydantic v2 | 确认 | frozen=True 强制不可变 |
| pytest + ruff | **保持** | 确认 | 成熟稳定 |
| Docker Compose | **保持** | 确认 | 本地评估路径 |

**唯一重要变化：** 知识检索从 LlamaIndex 改为自建轻量 RAG。理由是 LlamaIndex 的 50+ 子包依赖和频繁 API 变更对 v1 的"受控"原则构成风险，而自建 ~280 行即可覆盖 chunking + retrieval + evidence + citation，且每一步都经过 Harness 策略门控。
