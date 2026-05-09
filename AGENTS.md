# Repository Guidelines

## Project Structure & Module Organization

This repository is currently documentation-first. Product planning and technical analysis live in `docs/`:

- `docs/Proof Agent PRD.md` defines MVP scope, modules, architecture, and delivery milestones.
- `docs/Proof Agent 可行性分析报告.md` captures feasibility, audience, stack options, and risks.
- `docs/concepts/` explains framework concepts such as Control Envelope, Agent Contract, and Policy Engine.
- `docs/examples/` documents the enterprise Q&A demo, launch script, and Governance Receipt.

When implementation starts, keep source code in a dedicated package directory such as `src/` or `proof_agent/`, tests in `tests/`, runnable examples in `examples/`, and operational assets such as Docker or deployment files at the repository root.

## Build, Test, and Development Commands

No build or test tooling is committed yet. Until implementation exists, validate documentation changes manually:

- `ls docs` checks the expected documentation set.
- `sed -n '1,120p' "docs/Proof Agent PRD.md"` previews the PRD without opening an editor.

When code is added, document the exact local workflow here, for example `python -m pytest`, `docker compose up`, or `make lint`.

## Coding Style & Naming Conventions

Use clear Markdown headings, short paragraphs, and tables only when they improve scanability. Keep project terminology consistent: `Enterprise Agent Delivery Kit`, `Control Envelope`, `Agent Contract`, `PolicyEngine`, `MCP mock tool approval`, `Trace & Audit`, `Governance Receipt`, and `Enterprise QA Template`.

For future Python code, prefer 4-space indentation, snake_case modules and functions, PascalCase classes, and explicit type hints on public APIs. Keep configuration examples in YAML or JSON with descriptive file names, such as `examples/knowledge_qa.yaml`.

## Testing Guidelines

There is no test suite yet. For documentation edits, verify links, headings, tables, and code blocks render correctly. For future implementation, place tests under `tests/` and name files `test_<module>.py`. Cover workflow routing, memory read/write behavior, knowledge retrieval, MCP tool registration, and trace/audit output.

## Commit & Pull Request Guidelines

Use concise, imperative commit subjects such as `Add MVP architecture notes` or `Document receipt contract`.

Pull requests should include a short summary, changed files or sections, validation performed, and any unresolved product or architecture questions. For UI or diagram changes, attach screenshots or rendered previews when available.

## Security & Configuration Tips

Do not commit API keys, model provider credentials, vector database secrets, or production connection strings. Use `.env.example` for required variables once runtime code is introduced, and keep real secrets in local environment files excluded by `.gitignore`.
