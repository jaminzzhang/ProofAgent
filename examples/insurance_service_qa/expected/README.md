# Expected Artifacts

This directory documents the expected artifact shape for the Insurance Service QA Reference Agent.

Each governed run writes:

- `runs/latest/trace.jsonl`
- `runs/latest/governance_receipt.md`
- `runs/history/{run_id}/trace.jsonl` when RunStore is enabled
- `runs/history/{run_id}/governance_receipt.md` when RunStore is enabled

Run ids and timestamps are generated at runtime, so committed golden artifacts are intentionally omitted for this first business-shaped package.
