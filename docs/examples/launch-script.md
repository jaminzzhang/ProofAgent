# Local Demonstration Script

## Purpose

Show the sole V3 Agent answering supported internal insurance questions with evidence, refusing unsupported claims, and producing trace plus Governance Receipt without credentials.

## Commands

```bash
uv sync --extra dev

uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "住院理赔需要准备哪些材料？"

uv run --extra dev proof-agent inspect runs/latest/trace.jsonl
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
```

Then ask an unsupported question and show that the Harness refuses to invent an answer:

```bash
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "请承诺下一年度一定给予客户五折优惠。"
```

Do not demonstrate customer Chat, approval actions, local handlers or command execution; they are not in the active product baseline.
