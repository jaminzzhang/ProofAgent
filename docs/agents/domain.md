# Domain Documentation

This repository uses a **single-context** layout for domain knowledge and architectural decisions.

## Consumer Rules

- **Domain Language**: Skills like `diagnose` and `tdd` should read `CONTEXT.md` at the repo root to understand the core concepts (Control Envelope, Harness RAG, etc.).
- **Architectural Decisions**: Skills should look in `docs/adr/` for historical context on design choices.
- **Priority**: If `CONTEXT.md` is missing, skills should fall back to `README.md` and `CLAUDE.md`.
