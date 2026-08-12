---
status: accepted
---

# Build hierarchical independently citable Evidence Units

[FRAME | HIGH] Every unstructured document Source Version produces an immutable provider-neutral Document Structure Graph that preserves applicable document, section, page or slide, heading, paragraph, list item, table region, figure caption, code block, and OCR region hierarchy, order, source coordinates, and native-versus-OCR lineage. An Evidence Unit is the smallest semantically coherent independently citable structural unit. Oversized units split only through deterministic versioned rules at sentence, list, or table boundaries rather than arbitrary fixed-token chunks.

[FRAME | HIGH] Evidence Unit identity combines exact Knowledge Source Version, Citation Locator, and Content Hash; identical normalized content at two locations therefore remains two independently attributable units. The immutable Evidence Unit Manifest enumerates every identity, unit type, relationship, locator, hash, and parser, normalizer, or segmentation lineage. Any parser or segmentation change that alters that manifest creates a new Knowledge Source Version rather than silently mutating published retrieval behavior.

[FRAME | HIGH] Retrieval ranks leaf Evidence Units. After access filtering and ranking, bounded Evidence Unit Context Expansion may attach only necessary heading paths, table headers, adjacent siblings, or referenced definitions. Every attached unit independently passes the effective Knowledge Query Access Scope, consumes the context budget, and retains its own identity, Content Hash, and Citation Locator; it is never concatenated into an anonymous evidence block. Versioned model- or algorithm-generated parent summaries may guide routing, but they are Routing-Only Derived Summaries and cannot be returned as source-backed Candidate Evidence. We accept more structure, identities, and citations to preserve precise attribution while still supplying enough context to interpret a retrieval hit.
