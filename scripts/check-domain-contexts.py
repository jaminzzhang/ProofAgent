#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_ROOT = ROOT / "docs/domain"
PRODUCT_CORE_DOMAIN = "product-core"
TERM_RE = re.compile(r"^\*\*([^*]+)\*\*:", re.MULTILINE)
HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def fail(message: str) -> None:
    print(f"domain-context check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def context_files() -> list[Path]:
    domain_contexts = []
    for domain_dir in sorted(path for path in DOMAIN_ROOT.glob("*") if path.is_dir()):
        if domain_dir.name == PRODUCT_CORE_DOMAIN:
            continue
        domain_contexts.append(domain_dir / "CONTEXT.md")
    return [ROOT / "CONTEXT.md", *domain_contexts]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        fail(f"{path.relative_to(ROOT)} is not valid UTF-8")
    raise AssertionError("unreachable")


def main() -> int:
    seen_terms: dict[str, Path] = {}
    for path in context_files():
        if not path.exists():
            fail(f"missing context file: {path.relative_to(ROOT)}")
        text = read_text(path)
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
