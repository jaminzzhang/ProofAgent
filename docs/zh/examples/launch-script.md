# Launch Script (发布脚本)

本页面是 Proof Agent 的公共演示和评估合约。如果这些路径不工作，则说明 Harness 框架尚未就绪。

## 目标

在两分钟内，企业 AI Agent 负责人应看到确定性的 Harness 演示：

- 一个可运行的企业级问答 Agent
- 一个有数据引用 (citations) 支撑的答案
- 拒答或升级一个不受支持的提问
- 一个因需要工具而被暂停以等待审批的提问
- JSONL trace 的路径
- 供人类阅读的 Governance Receipt 的路径
- Plain RAG 与 Harness RAG 的直接对比

## 两分钟演示命令

```bash
proof-agent demo
```

该演示不得要求输入 LLM API key。它必须使用捆绑的样本知识并提供确定性的模型输出，同时仍需经过与完整企业级评估相同的策略、证据、审批、追踪和 receipt 代码路径。

## 30 分钟企业级评估

```bash
docker compose up
proof-agent run examples/enterprise_qa/agent.yaml
proof-agent inspect runs/latest/governance_receipt.md
```

CLI 或 Docker 路径必须加载 `examples/enterprise_qa/agent.yaml` 并将产出物写在 `runs/latest/` 下。

可选的 Dashboard API 路径：

```bash
uv run --extra dashboard proof-agent dashboard --host 127.0.0.1 --port 8000
```

Dashboard API 负责读取 run 产出物。它绝不能绕过 workflow、策略、验证器、trace 或 receipt 的生成环节。

在 `agent.yaml` 中配置 `model.provider: openai_compatible` 后，可以进行可选的远程模型评估：

```bash
OPENAI_API_KEY=... proof-agent run examples/enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
```

远程 provider 的配置必须在 `agent.yaml` 中使用环境变量名称；绝不能在其中提交明文 (raw secrets)。

## 演示问题 (Demo Questions)

| 步骤 | 问题 | 预期结果 |
| --- | --- | --- |
| 1 | "What is the reimbursement rule for travel meals?" | Harness RAG 给出带有引用的回答 |
| 2 | "What discount should we give this customer next year?" | Harness RAG 拒答或升级，因为证据缺失 |
| 3 | "Look up customer policy status before answering." | Harness RAG 在运行 MCP mock 工具之前请求审批 |

## 并排对比 (Side-by-Side Comparison)

演示必须包含针对不受支持提问的 Plain RAG 与 Harness RAG 对比：

| 路径 | 预期行为 |
| --- | --- |
| Plain RAG | 可能根据部分或不相关的上下文给出宽泛的回答 |
| Harness RAG | 由于缺乏必要的证据而拒答或进行升级 |

保留这一对比的目的在于证明本项目不仅仅是又一个 RAG 模板。

## 必需的产出物

每一次运行都必须打印这些路径：

```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

该 receipt 必须汇总策略决策、证据状态、工具审批状态、内存写入状态、最终结果以及 trace 的路径。

## 录制脚本建议

1. 展示 README 的标题与 v1 的范畴。
2. 运行 `proof-agent demo`。
3. 问一个受支持的问题，展示带有引用的输出。
4. 问一个不受支持的问题，展示拒答或升级。
5. 问一个需要使用工具的问题，展示审批状态。
6. 打开 `runs/latest/governance_receipt.md`。
7. 展示 Plain RAG 与 Harness RAG 的并排对比。
8. (可选) 运行完整的 Docker + `proof-agent run examples/enterprise_qa/agent.yaml` 评估。
9. (可选) 启动 `proof-agent dashboard`，检查 `/api/health`, `/api/runs`, 与 `/api/stats`。

## 冒烟测试 (Smoke Test)

只有满足以下条件，README 的演示路径才算通过：

- `proof-agent demo` 不需要 LLM API key
- 演示执行了策略、证据、审批、trace 和 receipt 的代码路径
- 演示产生了一个回答或拒答
- 演示输出了 `runs/latest/trace.jsonl`
- 演示输出了 `runs/latest/governance_receipt.md`
- 对于不受支持提问的对比显示了 Plain RAG 与 Harness RAG 发生了分歧

只有满足以下条件，企业评估路径才算通过：

- 命令使用的是 `examples/enterprise_qa/agent.yaml`
- Docker Compose 启动了所需的本地服务
- 运行产出了相同的 trace 与 receipt 工件

只有满足以下条件，Dashboard 路径才算通过：

- 它能读取现有的 run 历史记录
- 它能通过 `/api` 暴露 health、run、trace、receipt 及 stats 数据
- 它不会创建其他不同的执行路径