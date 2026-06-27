# Domain Documentation

This repository uses a **multi-context** layout for domain knowledge. Start with `CONTEXT-MAP.md` at the repository root, then read the smallest relevant `docs/domain/*/CONTEXT.md` file.

The root `CONTEXT.md` keeps product-wide terms only. Do not add new domain terms there unless the term is truly product-wide and belongs in Product Core.

## Consumer Rules

- **Domain Routing**: Read `CONTEXT-MAP.md` first to identify relevant domain contexts.
- **Product Core**: Read `CONTEXT.md` for cross-cutting terms such as Controlled Agent Harness Framework, Control Envelope, Agent Contract, Harness RAG, Plain RAG, Tool Gateway, Trace & Audit, and Governance Receipt.
- **Domain Language**: Skills like `diagnose` and `tdd` should read only the relevant `docs/domain/*/CONTEXT.md` files after routing. Fall back to the root `CONTEXT.md` when a term has not yet migrated.
- **Tool Proposal Boundary**: For tool proposal eligibility, proposal-safe schemas, binding, approval snapshots, and scope violations, read `docs/domain/tool-proposal-governance/CONTEXT.md`; for Tool Contracts, Tool Sources, MCP, model roles, and memory, read `docs/domain/tools-models-memory/CONTEXT.md`.
- **Architectural Decisions**: Skills should look in `docs/adr/` for historical context on design choices.
- **Decision History**: Use `docs/domain/*/decisions.md` for resolved "could mean / decision" history and relationship notes that are too granular for an ADR but too verbose for a glossary.
- **Quality Check**: After editing `CONTEXT.md`, `CONTEXT-MAP.md`, or `docs/domain/*`, run `python3 scripts/check-domain-contexts.py` and `git diff --check`; the checker enforces glossary-only context files, unique terms, supported decision headings, and no implementation-order or gate terms in glossaries.
- **Priority**: If `CONTEXT-MAP.md` is missing, fall back to `CONTEXT.md`, then `README.md` and `CLAUDE.md`.
