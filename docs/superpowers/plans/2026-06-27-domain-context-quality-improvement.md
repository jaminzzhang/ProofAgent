# Domain Context Quality Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the split domain context system easier to maintain by tightening oversized glossaries, curating migrated decision notes, and adding automated checks that prevent regression.

**Architecture:** Product-wide language stays in `CONTEXT.md`; domain-specific glossary terms stay in `docs/domain/*/CONTEXT.md`; relationship and ambiguity history stays in `docs/domain/*/decisions.md`. Add one lightweight repository script to enforce the structural rules that humans and agents should not have to remember manually.

**Tech Stack:** Markdown, Python 3 standard library, shell verification with `rg`, `awk`, and `git diff --check`.

---

### Task 1: Add Domain Context Quality Checker

**Files:**
- Create: `scripts/check-domain-contexts.py`
- Modify: `docs/agents/domain.md`

- [x] **Step 1: Create the checker script**

Create `scripts/check-domain-contexts.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_FILES = [ROOT / "CONTEXT.md", *sorted((ROOT / "docs/domain").glob("*/CONTEXT.md"))]
TERM_RE = re.compile(r"^\*\*([^*]+)\*\*:", re.MULTILINE)
HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def fail(message: str) -> None:
    print(f"domain-context check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    seen_terms: dict[str, Path] = {}
    for path in CONTEXT_FILES:
        if not path.exists():
            fail(f"missing context file: {path.relative_to(ROOT)}")
        text = path.read_text()
        headings = HEADING_RE.findall(text)
        if headings != ["Language"]:
            fail(f"{path.relative_to(ROOT)} must contain exactly one second-level heading: ## Language")
        terms = TERM_RE.findall(text)
        if not terms:
            fail(f"{path.relative_to(ROOT)} has no glossary terms")
        for term in terms:
            if term in seen_terms:
                first = seen_terms[term].relative_to(ROOT)
                second = path.relative_to(ROOT)
                fail(f"duplicate term {term!r} in {first} and {second}")
            seen_terms[term] = path
        if path == ROOT / "CONTEXT.md" and len(terms) > 40:
            fail("root CONTEXT.md should stay product-wide and under 40 terms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: Run checker and verify current pass**

Run:

```bash
python3 scripts/check-domain-contexts.py
```

Expected: exit 0 with no output.

- [x] **Step 3: Document the checker**

In `docs/agents/domain.md`, add a short maintenance rule under `## Consumer Rules`:

```md
- **Quality Check**: After editing `CONTEXT.md`, `CONTEXT-MAP.md`, or `docs/domain/*`, run `python3 scripts/check-domain-contexts.py` and `git diff --check`.
```

- [x] **Step 4: Verify docs and checker**

Run:

```bash
python3 scripts/check-domain-contexts.py
git diff --check
```

Expected: both commands exit 0.

### Task 2: Tighten Oversized Glossaries

**Files:**
- Modify: `docs/domain/workflow-control/CONTEXT.md`
- Modify: `docs/domain/agent-configuration/CONTEXT.md`
- Modify: `docs/domain/knowledge-evidence/CONTEXT.md`
- Modify: `docs/domain/tools-models-memory/CONTEXT.md`

- [x] **Step 1: Identify glossary-only but overly operational terms**

Run:

```bash
awk '/^\*\*[^*]+\*\*:/{print FILENAME ":" FNR ":" $0}' docs/domain/workflow-control/CONTEXT.md docs/domain/knowledge-evidence/CONTEXT.md docs/domain/tools-models-memory/CONTEXT.md
```

Expected: a list of terms from the three largest contexts.

- [x] **Step 2: Move implementation-sequence terms to decisions**

For each term whose name ends with `Implementation Sequence`, `Migration Slice`, `Cutover Scope`, `Acceptance Gate`, or `Test Gate`, remove the glossary entry from the relevant `CONTEXT.md` and add a bullet to that domain's `decisions.md` under `## Relationship And Reference Notes`. Apply the same cleanup to matching operational terms discovered outside the three largest context files.

Use this format:

```md
- **Term Name** is implementation or migration guidance rather than glossary language. Keep its decision/history here unless it later qualifies for an ADR.
```

- [x] **Step 3: Keep canonical domain nouns in glossary**

After removals, run:

```bash
python3 scripts/check-domain-contexts.py
wc -l docs/domain/workflow-control/CONTEXT.md docs/domain/knowledge-evidence/CONTEXT.md docs/domain/tools-models-memory/CONTEXT.md
```

Expected: checker exits 0; each file is shorter than before. Do not force an arbitrary line target if it would lose useful language.

### Task 3: Curate Decision Notes

**Files:**
- Modify: `docs/domain/*/decisions.md`

- [x] **Step 1: Normalize migrated section headings**

In each `docs/domain/*/decisions.md`, keep these headings only when they have content:

```md
## Ambiguity Resolutions
## Relationship And Reference Notes
## Presentation Vocabulary Notes
## Example Dialogue
```

Remove empty headings such as `## Migrated Relationships` when the section only exists as a mechanical migration label.

- [x] **Step 2: Mark ADR candidates**

Search for hard-to-reverse decisions:

```bash
rg -n "ADR|hard to reverse|remove|must not|source of truth|fail closed|direct cutover|publication" docs/domain/*/decisions.md
```

For candidates that look architectural and surprising, add a short marker:

```md
  ADR candidate: hard to reverse, surprising without context, and trade-off based.
```

Do not create ADRs in this task; only tag candidates for review.

- [x] **Step 3: Verify decisions still route cleanly**

Run:

```bash
rg -n "^## " docs/domain/*/decisions.md
git diff --check
```

Expected: headings are intentional; `git diff --check` exits 0.

### Task 4: Update Documentation Routing Summary

**Files:**
- Modify: `CONTEXT-MAP.md`
- Modify: `docs/README.md`
- Modify: `AGENTS-COMMON.md`

- [x] **Step 1: Add quality policy to context map**

In `CONTEXT-MAP.md`, add this short section after `## Relationships`:

```md
## Maintenance Rules

- `CONTEXT.md` and `docs/domain/*/CONTEXT.md` are glossary files and should contain only `## Language`.
- Put relationship notes, ambiguity history, and implementation-order notes in `docs/domain/*/decisions.md`.
- Run `python3 scripts/check-domain-contexts.py` and `git diff --check` after domain documentation edits.
```

- [x] **Step 2: Cross-reference the checker from docs README**

In `docs/README.md`, add this row to the Domain Language table:

```md
| `../scripts/check-domain-contexts.py` | Structural checker for glossary-only context files and duplicate terms. |
```

- [x] **Step 3: Update agent source-of-truth guidance**

In `AGENTS-COMMON.md`, under `## Source Of Truth`, add a sentence after the numbered list:

```md
After editing domain documentation, run `python3 scripts/check-domain-contexts.py` and `git diff --check`.
```

- [x] **Step 4: Verify routing docs**

Run:

```bash
python3 scripts/check-domain-contexts.py
rg -n "check-domain-contexts|Maintenance Rules" CONTEXT-MAP.md docs/README.md docs/agents/domain.md AGENTS-COMMON.md
git diff --check
```

Expected: checker and diff check pass; `rg` shows all intended references.

### Task 5: Final Verification And Review

**Files:**
- Review all changed files from Tasks 1-4.

- [x] **Step 1: Run full documentation verification**

Run:

```bash
python3 scripts/check-domain-contexts.py
awk '/[ \t]$/{print FILENAME ":" FNR ": trailing whitespace"}' CONTEXT.md CONTEXT-MAP.md AGENTS-COMMON.md docs/README.md docs/agents/domain.md docs/domain/*/CONTEXT.md docs/domain/*/decisions.md
git diff --check
```

Expected: checker exits 0; trailing whitespace command prints nothing; `git diff --check` exits 0.

- [x] **Step 2: Review diff scope**

Run:

```bash
git diff --stat
git diff -- CONTEXT.md CONTEXT-MAP.md docs/agents/domain.md docs/README.md AGENTS-COMMON.md scripts/check-domain-contexts.py docs/domain
```

Expected: changes are limited to domain documentation, the domain checker script, and routing instructions.

- [ ] **Step 3: Commit when approved**

Only after review:

```bash
git add CONTEXT.md CONTEXT-MAP.md AGENTS-COMMON.md docs/README.md docs/agents/domain.md docs/domain scripts/check-domain-contexts.py
git commit -m "docs: improve domain context quality gates"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: covers glossary-only enforcement, oversized context cleanup, decision-note curation, routing docs, and final verification.
- Placeholder scan: no TBD/TODO/fill-in steps remain; commands and expected outputs are explicit.
- Type consistency: the checker name is consistently `scripts/check-domain-contexts.py`; context paths consistently use `CONTEXT.md`, `CONTEXT-MAP.md`, and `docs/domain/*`.
