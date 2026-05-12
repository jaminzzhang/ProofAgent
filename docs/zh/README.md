# Proof Agent 文档

> **双语约定**: 文档支持中英双语。英文（默认）位于 `docs/`，中文翻译位于 `docs/zh/`，目录结构保持一致。开发过程中仅更新英文文档；中文翻译在发版时同步。

Proof Agent 是一个受控的 Agent 治理框架 (Controlled Agent Harness Framework)。它利用 Harness Engineering 管理 Agent 生命周期，包括工作流、策略、工具、记忆、模型、验证器、Trace、Receipt、部署和可观测性。

该项目并未定位为 local-first 或 CLI-first。它保留了一个确定性的本地演示作为回归基线，并支持 CLI 与 Docker 运行入口。远程模型、LangChain/LangGraph、向量库、真实 MCP 以及 Dashboard 等能力，都是围绕相同 Harness 合约的基于适配器 (adapter) 的集成。

## 事实来源 (Source Of Truth)

1. `prd.md` — 产品定位、范围、非目标和路线图。
2. `technical-design.md` — 权威架构与实现边界。
3. `developer-guide.md` — AI Agent 负责人用于构建、配置、部署和管理受控 Agent 的开发工作流。
4. `development-progress.md` — 当前代码库状态；有用，但始终需要结合代码进行验证。


## 概念合约 (Concept Contracts)

| 文档 | 目的 |
| --- | --- |
| `concepts/control-envelope.md` | 核心 Harness / Control Envelope 心智模型 |
| `concepts/agent-contract.md` | `agent.yaml` 公共合约 |
| `concepts/policy-engine.md` | 策略执行点 (enforcement points) 与决策 |
| `concepts/approval-state-contract.md` | 工具审批状态机 |
| `concepts/trace-event-contract.md` | JSONL trace 事件合约 |
| `concepts/governance-receipt-contract.md` | 人类可读的治理凭证 (receipt) 合约 |
| `concepts/trust-boundaries.md` | 安全范围、假设与不承诺的声明 |

## 开发者指南 (Developer Guide)

| 文档 | 目的 |
| --- | --- |
| `developer-guide.md` | 面向 AI Agent 负责人的快速开始、架构模块概览、配置、开发、部署及管理步骤 |

## 示例 (Examples)

| 文档 | 目的 |
| --- | --- |
| `examples/launch-script.md` | 演示与评估命令 |
| `examples/enterprise-qa.md` | 企服问答模板行为 |
| `examples/governance-receipt.md` | 凭证渲染示例 |

## 活动文档策略 (Active Documentation Policy)

- 保持根级别文档数量少且权威。
- 将可复用的合约放在 `concepts/` 下。
- 将可运行的行为示例放在 `examples/` 下。
- 不要保留重复同一路线图的并行架构草案。
- 当设计决策发生变化时，需同时更新 PRD、技术设计及受影响的概念页面。