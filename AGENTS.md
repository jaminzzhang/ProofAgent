# AGENTS.md

This file provides repository guidance for OpenAI Codex and other agents that read `AGENTS.md`.

Read and follow the shared coding-agent guide first:

- `AGENTS-COMMON.md`

The shared guide includes the required expert reasoning, claim-tagging, confidence, uncertainty, anti-sycophancy, and citation rules. Apply those rules before any other repository-specific guidance in this file.

Agent-specific note: keep this file as a thin entry point. When shared project status, architecture rules, commands, testing policy, or security guidance changes, update `AGENTS-COMMON.md` instead of duplicating the same content here.

## hicode

For scoped implementation work, use these repository-local indexes after reading
`AGENTS-COMMON.md`:

- `docs/rules/hicode-coding-rules.md` for incremental delivery constraints;
- `docs/DOMAIN_KNOWLEDGE.md` for domain-document routing;
- `docs/PROJ_CONTEXT.md` for current feature status and evidence paths;
- `docs/features/<feature-id>/` for scope, TDD, and verification evidence.

Do not inspect `.env` files or record secrets in feature evidence. Treat hicode
reports as implementation evidence, never as deployment or release approval.
